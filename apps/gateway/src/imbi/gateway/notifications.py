import hashlib
import hmac
import http
import json
import logging
import re
import time
import typing

import celpy
import fastapi
import jsonpointer
import pydantic

from imbi.common import clickhouse, graph, models
from imbi.common.auth.encryption import TokenEncryption
from imbi.common.plugins import base as plugin_base
from imbi.common.plugins import registry as plugin_registry
from imbi.common.plugins.credentials import decrypt_integration_credentials
from imbi.common.plugins.errors import PluginNotFoundError
from imbi.gateway import actions

if typing.TYPE_CHECKING:
    from collections import abc

LOGGER = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix='/notifications')

#: Capability kind that gates and supplies gateway-dispatched webhook
#: actions on an :class:`imbi.common.models.Integration`.
_WEBHOOK_ACTIONS = 'webhook-actions'

#: Headers that may carry credentials or webhook signatures. These are
#: replaced with ``'[redacted]'`` before persisting ``metadata.headers``
#: so the activity-feed event row never stores secrets in ClickHouse.
_SENSITIVE_HEADERS = frozenset(
    {
        'authorization',
        'cookie',
        'set-cookie',
        'proxy-authorization',
        'x-hub-signature',
        'x-hub-signature-256',
        'x-gitlab-token',
        'x-pagerduty-signature',
        'x-sonar-webhook-hmac-sha256',
    }
)

#: ``WebhookRule.handler`` is ``"<plugin_slug>#<action_name>"``. The ``#``
#: separator is invalid Python import syntax so a stored value can never
#: be confused with the previous ``pydantic.ImportString`` form.
_HANDLER_PATTERN = re.compile(r'^[a-z][a-z0-9-]*#[a-z][a-z0-9_]*$')


def _safe_headers(headers: 'abc.Mapping[str, str]') -> dict[str, str]:
    """Return a redacted copy of ``headers`` for persisted metadata.

    Sensitive header values (authorization, cookies, webhook signatures)
    are replaced with ``'[redacted]'`` so secrets never reach ClickHouse.
    """
    return {
        key: ('[redacted]' if key.lower() in _SENSITIVE_HEADERS else value)
        for key, value in headers.items()
    }


def _json_dict(raw: object) -> dict[str, typing.Any]:
    """Decode an AGE map property to a dict.

    The graph client serializes dict node properties (``options``,
    ``capabilities``, ``encrypted_credentials``) via ``json.dumps``, so
    they come back as a ``str`` that must be parsed. Tolerates an
    already-decoded dict and treats anything else (``None``, malformed
    JSON, non-object JSON) as an empty mapping rather than failing the
    dispatch.
    """
    if isinstance(raw, dict):
        return typing.cast('dict[str, typing.Any]', raw)
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return typing.cast('dict[str, typing.Any]', parsed)
    return {}


#: Identifier of a ``Project`` node — the value of ``project.id`` in
#: the graph and of ``project_id`` on activity-feed event rows. Any
#: string passed around under this alias must originate there.
type ProjectId = str


class HandlerOutcome(pydantic.BaseModel):
    """Disposition of one webhook-rule handler for one project.

    Serialized with ``exclude_none`` into ``metadata.handlers`` on the
    phase-2 activity-feed row by :class:`DeliveryRecorder`, so skipped
    handlers carry no ``duration_ms`` and successes carry no ``error``.
    """

    handler: str
    status: typing.Literal['succeeded', 'failed', 'skipped']
    error: str | None = None
    duration_ms: int | None = None


class WebhookRule(pydantic.BaseModel):
    """A single ``WebhookRule`` row pulled from the graph.

    ``handler`` is a ``"<plugin_slug>#<action_name>"`` string where the
    slug is the installed package's plugin slug (e.g. ``github``,
    ``sonarqube``, ``gateway-actions``). The field validator only
    enforces shape -- plugin/action resolution happens at dispatch time
    so a stale rule does not stop the gateway from accepting deliveries
    (the dispatcher logs and skips instead).
    """

    handler: str
    ordinal: int
    handler_config: str
    filter_expression: str

    @pydantic.field_validator('handler')
    @classmethod
    def _handler_shape(cls, value: str) -> str:
        if not _HANDLER_PATTERN.match(value):
            raise ValueError(
                f"handler {value!r} must be '<plugin_slug>#<action_name>'"
            )
        return value

    @property
    def plugin_slug(self) -> str:
        return self.handler.split('#', 1)[0]

    @property
    def action_name(self) -> str:
        return self.handler.split('#', 1)[1]

    def evaluate_condition(
        self, context: object, *, webhook_id: str | None = None
    ) -> bool | None:
        """Evaluate ``filter_expression`` against the event ``context``.

        ``context`` is the activation built by
        :func:`_record_and_build_filter_context` -- the same shape the
        activity-feed :class:`imbi.common.models.Event` row is
        materialized into, so a rule filters on ``type``,
        ``integration``, ``attributed_to``, ``metadata.headers``, and
        ``payload`` (the webhook body).
        """
        log_extra: dict[str, typing.Any] = {
            'webhook_id': webhook_id,
            'rule_handler': self.handler,
            'rule_ordinal': self.ordinal,
            'filter_expression': self.filter_expression,
        }
        try:
            env = celpy.Environment()
            ast = env.compile(self.filter_expression)
            prg = env.program(ast)
            result = prg.evaluate(celpy.json_to_cel(context))
            return bool(result)
        except celpy.CELEvalError as e:
            LOGGER.warning(
                'CEL evaluation error for webhook_id=%r rule=%r'
                ' (ordinal=%s) expression=%r: %s',
                webhook_id,
                self.handler,
                self.ordinal,
                self.filter_expression,
                e,
                extra=log_extra,
            )
        except Exception as e:  # noqa: BLE001
            LOGGER.warning(
                'Unexpected error evaluating webhook_id=%r rule=%r'
                ' (ordinal=%s) expression=%r: %s',
                webhook_id,
                self.handler,
                self.ordinal,
                self.filter_expression,
                e,
                extra=log_extra,
            )
        return None


@router.post('/{webhook_id}', include_in_schema=False)
async def process_notification(  # noqa: PLR0911, PLR0915 - linear webhook pipeline reads top-down
    webhook_id: str,
    *,
    db: graph.Pool,
    request: fastapi.Request,
    response: fastapi.Response,
) -> None:
    # default to 204 ==> nothing to do
    response.status_code = http.HTTPStatus.NO_CONTENT
    records = await db.execute(
        'MATCH (w:Webhook {{ id: {webhook_id} }})'
        ' -[:BELONGS_TO]->(o:Organization)'
        ' OPTIONAL MATCH (w)-[i:IMPLEMENTED_BY]->(intg:Integration)'
        ' OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)'
        ' WITH w, o, intg, i, r ORDER BY r.ordinal'
        ' WITH w, o, intg, i, collect(r{{.*}}) AS rules'
        ' RETURN w{{.*}} AS webhook, o{{.*}} AS org,'
        '        intg{{.*}} AS integration, i{{.*}} AS sel, rules',
        {'webhook_id': webhook_id},
        ['webhook', 'org', 'integration', 'sel', 'rules'],
    )
    if not records:
        LOGGER.warning(
            'No records found for webhook_id=%r',
            webhook_id,
            extra={'webhook_id': webhook_id},
        )
        return
    if len(records) != 1:
        LOGGER.error(
            'Webhook %r is connected to %s Organizations',
            webhook_id,
            len(records),
            extra={'webhook_id': webhook_id},
        )
        raise fastapi.HTTPException(http.HTTPStatus.INTERNAL_SERVER_ERROR)

    record = records[0]
    webhook = graph.parse_agtype(record['webhook'])
    org = graph.parse_agtype(record['org'])
    integration = graph.parse_agtype(record['integration'])  # maybe None
    sel = graph.parse_agtype(record['sel'])  # maybe None
    raw_rules = record['rules']

    parsed_rules: list[typing.Any] = graph.parse_agtype(raw_rules) or []
    try:
        rules = [WebhookRule.model_validate(row) for row in parsed_rules]
    except pydantic.ValidationError as e:
        LOGGER.error(
            'failed to deserialize rules for webhook_id=%r: %s',
            webhook_id,
            e,
            extra={'webhook_id': webhook_id, 'rules_count': len(parsed_rules)},
        )
        return

    LOGGER.debug('webhook: %r', webhook)
    LOGGER.debug('org: %r', org)
    LOGGER.debug('integration: %r', integration)
    LOGGER.debug('sel: %r', sel)
    LOGGER.debug('%s rules: %r', len(rules), rules)

    if sel is None or integration is None:
        LOGGER.warning(
            'Global webhooks are not yet implemented (webhook_id=%r)',
            webhook_id,
            extra={'webhook_id': webhook_id},
        )
        return

    integration_slug = str(integration['slug'])
    integration_plugin = str(integration.get('plugin') or '')
    integration_options = _json_dict(integration.get('options'))
    integration_capabilities = _json_dict(integration.get('capabilities'))
    integration_credentials = decrypt_integration_credentials(
        _json_dict(integration.get('encrypted_credentials'))
    )
    webhook_capability = _json_dict(
        integration_capabilities.get(_WEBHOOK_ACTIONS)
    )
    capability_options = _json_dict(webhook_capability.get('options'))
    webhook_actions_enabled = bool(webhook_capability.get('enabled'))

    body = await _extract_json_body(request)
    try:
        ptr = jsonpointer.JsonPointer(sel['identifier_selector'])
        resolved = ptr.resolve(body)
    except jsonpointer.JsonPointerException:
        LOGGER.exception(
            'failed to select project identifier %r for webhook_id=%r'
            ' integration=%r',
            sel['identifier_selector'],
            webhook_id,
            integration_slug,
            extra={
                'webhook_id': webhook_id,
                'integration_slug': integration_slug,
                'identifier_selector': sel['identifier_selector'],
            },
        )
        return

    project_records = await _resolve_project_and_verify(
        db,
        request,
        external_id=str(resolved),
        integration_slug=integration_slug,
        webhook_id=webhook_id,
    )
    if project_records is None:
        return

    identity_candidates = _identity_candidate_slugs(
        integration_slug=integration_slug,
        integration_plugin=integration_plugin,
        capabilities=integration_capabilities,
        edge_identity_slug=sel.get('identity_plugin_slug'),
    )
    user_id = await _resolve_user_id(
        body=body,
        user_subject_selector=sel.get('user_subject_selector'),
        user_type_selector=sel.get('user_type_selector'),
        candidate_identity_slugs=identity_candidates,
        webhook_id=webhook_id,
    )
    event_type = _resolve_event_type(
        sel.get('event_type_selector'),
        body,
        request.headers,
        webhook_id=webhook_id,
    )
    _set_access_log_context(request, user_id=user_id, event=event_type)
    recorder = DeliveryRecorder()
    context = await _record_and_build_filter_context(
        project_records,
        recorder=recorder,
        headers=request.headers,
        webhook_id=webhook_id,
        integration_slug=integration_slug,
        user_id=user_id,
        event_type=event_type,
        body=body,
    )
    if not webhook_actions_enabled:
        LOGGER.debug(
            'webhook-actions capability disabled for integration %r;'
            ' recorded delivery but dispatching no handlers'
            ' (webhook_id=%r)',
            integration_slug,
            webhook_id,
            extra={
                'webhook_id': webhook_id,
                'integration_slug': integration_slug,
            },
        )
        return
    filter_results = [
        rule.evaluate_condition(context, webhook_id=webhook_id)
        for rule in rules
    ]
    if not any(filter_results):
        LOGGER.debug(
            'Ignoring notification: no filter matches'
            ' (webhook_id=%r integration=%r)',
            webhook_id,
            integration_slug,
            extra={
                'webhook_id': webhook_id,
                'integration_slug': integration_slug,
            },
        )
        return

    matched_rules = [
        rule
        for rule, enabled in zip(rules, filter_results, strict=True)
        if enabled
    ]
    resolver = _make_user_resolver(identity_candidates)
    try:
        for proj_record in project_records:
            project_id: ProjectId = str(
                graph.parse_agtype(proj_record['project_id'])
            )
            await _run_handlers(
                org_slug=str(org['slug']),
                project_id=project_id,
                project_slug=str(
                    graph.parse_agtype(proj_record['project_slug'])
                    if proj_record.get('project_slug') is not None
                    else ''
                ),
                team_slug=(
                    str(graph.parse_agtype(proj_record['team_slug']))
                    if proj_record.get('team_slug') is not None
                    else None
                ),
                integration_slug=integration_slug,
                integration_options=integration_options,
                capability_options=capability_options,
                integration_credentials=integration_credentials,
                external_identifier=str(resolved),
                event=context,
                user_id=user_id,
                rules=matched_rules,
                resolver=resolver,
                webhook_id=webhook_id,
                outcomes=recorder.outcomes_for(project_id),
            )
    finally:
        await recorder.record_dispositions()

    # indicates that we actually did something
    response.status_code = http.HTTPStatus.ACCEPTED


def _identity_candidate_slugs(
    *,
    integration_slug: str,
    integration_plugin: str,
    capabilities: dict[str, typing.Any],
    edge_identity_slug: object,
) -> list[str]:
    """Resolve the identity Integration slug(s) for actor attribution.

    An ``IdentityConnection`` is keyed by Integration in v3, so the
    delivery's own Integration is the identity source when its plugin
    declares an ``identity`` capability and that capability is enabled on
    the Integration. An operator may override this by pinning an explicit
    identity Integration slug on the ``IMPLEMENTED_BY`` edge
    (``identity_plugin_slug``); the pin is trusted as-is. Returns an
    empty list when neither applies, so the caller skips the
    ``/users/by-identity`` lookups entirely.
    """
    if edge_identity_slug:
        return [str(edge_identity_slug)]
    identity_capability = _json_dict(capabilities.get('identity'))
    if not identity_capability.get('enabled'):
        return []
    try:
        entry = plugin_registry.get_plugin(integration_plugin)
    except PluginNotFoundError:
        LOGGER.debug(
            'Integration plugin %r not loaded; cannot resolve identities',
            integration_plugin,
        )
        return []
    if entry.manifest.get_capability('identity') is None:
        return []
    return [integration_slug]


def _verify_webhook_signature(
    *,
    secret_enc: str,
    raw_body: bytes,
    signature_header: str | None,
    webhook_id: str | None,
    integration_slug: str,
) -> bool:
    """Verify an HMAC-signed inbound delivery; fail closed.

    The matched ``EXISTS_IN`` edge carries an encrypted per-Integration
    signing secret (e.g. a PagerDuty V3 webhook-subscription secret).
    The signature header is one or more comma-separated ``v1=<hex>``
    tokens, each an HMAC-SHA256 of the raw request body keyed by the
    decrypted secret; the delivery is accepted if any token matches
    (constant-time, so a secret rotation that briefly emits two
    signatures still verifies). Returns ``False`` -- meaning drop the
    delivery -- on a missing header, decrypt failure, or no match.

    Note: the header name is PagerDuty's; PagerDuty is the only producer
    of edge signing secrets today. A second signed integration would add
    a per-Integration scheme selector rather than another hard-coded
    header.
    """
    if not signature_header:
        LOGGER.warning(
            'Signature required but header missing; dropping delivery '
            '(webhook_id=%r integration=%r)',
            webhook_id,
            integration_slug,
            extra={
                'webhook_id': webhook_id,
                'integration_slug': integration_slug,
            },
        )
        return False
    try:
        secret = TokenEncryption.get_instance().decrypt(secret_enc)
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Webhook signing secret decrypt failed; dropping delivery '
            '(webhook_id=%r integration=%r)',
            webhook_id,
            integration_slug,
            extra={
                'webhook_id': webhook_id,
                'integration_slug': integration_slug,
            },
        )
        return False
    if not secret:
        return False
    expected = (
        'v1=' + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    )
    for token in signature_header.split(','):
        if hmac.compare_digest(token.strip(), expected):
            return True
    LOGGER.warning(
        'Webhook signature verification failed; dropping delivery '
        '(webhook_id=%r integration=%r)',
        webhook_id,
        integration_slug,
        extra={'webhook_id': webhook_id, 'integration_slug': integration_slug},
    )
    return False


async def _resolve_project_and_verify(
    db: graph.Pool,
    request: fastapi.Request,
    *,
    external_id: str,
    integration_slug: str,
    webhook_id: str | None,
) -> list[dict[str, typing.Any]] | None:
    """Resolve the project(s) for an inbound delivery and verify it.

    Matches ``(:Project)-[:EXISTS_IN {identifier}]->(:Integration)`` and
    returns the rows. Returns ``None`` -- meaning the caller should drop
    the delivery -- when no project matches, or when any matched edge
    carries a webhook signing secret and the request's signature does not
    verify against it (parse-then-verify, fail closed). When
    ``external_id`` fans out to multiple projects, every secret-bearing
    edge must verify against the same request body, so acceptance is not
    row-order dependent. Integrations that don't sign deliveries store no
    secret and pass straight through.
    """
    project_records: list[dict[str, typing.Any]] = await db.execute(
        'MATCH (p:Project)'
        '      -[ei:EXISTS_IN {{identifier: {external_id}}}]'
        '      ->(intg:Integration {{slug: {integration_slug}}}) '
        'OPTIONAL MATCH (p)-[:OWNED_BY]->(t:Team)'
        ' RETURN p.id AS project_id, p.slug AS project_slug,'
        '        t.slug AS team_slug,'
        '        ei.webhook_secret_enc AS webhook_secret_enc',
        {'external_id': external_id, 'integration_slug': integration_slug},
        ['project_id', 'project_slug', 'team_slug', 'webhook_secret_enc'],
    )
    if not project_records:
        LOGGER.warning(
            'Ignoring notification: no project found for external_id=%r'
            ' (webhook_id=%r integration=%r)',
            external_id,
            webhook_id,
            integration_slug,
            extra={
                'webhook_id': webhook_id,
                'integration_slug': integration_slug,
                'external_identifier': external_id,
            },
        )
        return None
    raw_body = await request.body()
    signature_header = request.headers.get('x-pagerduty-signature')
    for record in project_records:
        secret_enc = graph.parse_agtype(record.get('webhook_secret_enc'))
        if secret_enc and not _verify_webhook_signature(
            secret_enc=str(secret_enc),
            raw_body=raw_body,
            signature_header=signature_header,
            webhook_id=webhook_id,
            integration_slug=integration_slug,
        ):
            return None
    return project_records


def _resolve_rule_handler(
    rule: WebhookRule, *, webhook_id: str | None = None
) -> tuple[plugin_registry.RegistryEntry, plugin_base.ActionDescriptor] | None:
    """Look the rule's plugin / webhook action up in the registry.

    Resolves the rule's ``<plugin_slug>#<action_name>`` handler to the
    plugin's ``webhook-actions`` capability and the matching
    :class:`ActionDescriptor`. Returns ``None`` (after logging) when the
    plugin is unknown, exposes no ``webhook-actions`` capability, raises
    while enumerating actions, or does not expose the named action -- the
    dispatcher continues with the next rule rather than failing the whole
    delivery.
    """
    log_extra: dict[str, typing.Any] = {
        'webhook_id': webhook_id,
        'rule_handler': rule.handler,
        'rule_ordinal': rule.ordinal,
        'plugin_slug': rule.plugin_slug,
        'action_name': rule.action_name,
    }
    try:
        entry = plugin_registry.get_plugin(rule.plugin_slug)
    except PluginNotFoundError:
        LOGGER.error(
            'Unknown plugin %r referenced by rule handler %r (webhook_id=%r)',
            rule.plugin_slug,
            rule.handler,
            webhook_id,
            extra=log_extra,
        )
        return None
    capability = entry.manifest.get_capability(_WEBHOOK_ACTIONS)
    if capability is None:
        LOGGER.error(
            'Plugin %r exposes no webhook-actions capability; cannot'
            ' dispatch %r (webhook_id=%r)',
            rule.plugin_slug,
            rule.handler,
            webhook_id,
            extra=log_extra,
        )
        return None
    handler_cls = typing.cast(
        'type[plugin_base.WebhookActionsCapability]', capability.handler
    )
    try:
        descriptors = [
            d for d in handler_cls.actions() if d.name == rule.action_name
        ]
    except Exception:
        LOGGER.exception(
            'Plugin %r raised while enumerating actions; skipping rule %r'
            ' (webhook_id=%r)',
            rule.plugin_slug,
            rule.handler,
            webhook_id,
            extra=log_extra,
        )
        return None
    if not descriptors:
        LOGGER.error(
            'Plugin %r does not expose action %r (webhook_id=%r rule=%r)',
            rule.plugin_slug,
            rule.action_name,
            webhook_id,
            rule.handler,
            extra=log_extra,
        )
        return None
    return entry, descriptors[0]


async def _run_handlers(  # noqa: PLR0913
    *,
    org_slug: str,
    project_id: ProjectId,
    project_slug: str,
    team_slug: str | None,
    integration_slug: str,
    integration_options: dict[str, typing.Any],
    capability_options: dict[str, typing.Any],
    integration_credentials: dict[str, str],
    external_identifier: str,
    event: dict[str, typing.Any],
    user_id: str | None,
    rules: 'abc.Iterable[WebhookRule]',
    outcomes: list[HandlerOutcome],
    resolver: 'abc.Callable[[str], abc.Awaitable[str | None]] | None' = None,
    webhook_id: str | None = None,
) -> None:
    LOGGER.debug(
        'Running handlers for %s/%s (webhook_id=%r integration=%r)',
        org_slug,
        project_id,
        webhook_id,
        integration_slug,
    )
    ctx = plugin_base.PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        actor_user_id=user_id,
        integration_slug=integration_slug,
        integration_options=integration_options,
        capability_options=capability_options,
        resolve_user_by_identity=resolver,
    )
    for rule in rules:
        resolved = _resolve_rule_handler(rule, webhook_id=webhook_id)
        if resolved is None:
            outcomes.append(
                HandlerOutcome(
                    handler=rule.handler,
                    status='skipped',
                    error='handler not resolvable',
                )
            )
            continue
        entry, descriptor = resolved
        credentials = _credentials_for_plugin(
            entry,
            integration_credentials,
            webhook_id=webhook_id,
            rule_handler=rule.handler,
        )
        if credentials is None:
            outcomes.append(
                HandlerOutcome(
                    handler=rule.handler,
                    status='skipped',
                    error='missing credentials',
                )
            )
            continue
        try:
            config = descriptor.config_model.model_validate_json(
                rule.handler_config
            )
        except pydantic.ValidationError as err:
            LOGGER.exception(
                'Invalid handler_config for rule %r (webhook_id=%r'
                ' integration=%r); skipping rule',
                rule.handler,
                webhook_id,
                integration_slug,
                extra={
                    'webhook_id': webhook_id,
                    'integration_slug': integration_slug,
                    'rule_handler': rule.handler,
                    'rule_ordinal': rule.ordinal,
                },
            )
            outcomes.append(
                HandlerOutcome(
                    handler=rule.handler,
                    status='skipped',
                    error=f'invalid handler_config: {err}',
                )
            )
            continue
        started = time.monotonic()
        try:
            await descriptor.callable(
                ctx=ctx,
                credentials=credentials,
                external_identifier=external_identifier,
                action_config=config,
                event=event,
            )
        except Exception as err:
            LOGGER.exception(
                'Failure executing rule %r (webhook_id=%r integration=%r'
                ' project=%s/%s)',
                rule.handler,
                webhook_id,
                integration_slug,
                org_slug,
                project_id,
                extra={
                    'webhook_id': webhook_id,
                    'integration_slug': integration_slug,
                    'rule_handler': rule.handler,
                    'rule_ordinal': rule.ordinal,
                    'org_slug': org_slug,
                    'project_id': project_id,
                    'rule': rule,
                },
            )
            outcomes.append(
                HandlerOutcome(
                    handler=rule.handler,
                    status='failed',
                    error=f'{type(err).__name__}: {err}',
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            )
        else:
            outcomes.append(
                HandlerOutcome(
                    handler=rule.handler,
                    status='succeeded',
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            )


def _credentials_for_plugin(
    entry: plugin_registry.RegistryEntry,
    integration_credentials: dict[str, str],
    *,
    webhook_id: str | None = None,
    rule_handler: str | None = None,
) -> dict[str, str] | None:
    """Return the credentials for ``entry`` or ``None`` to skip the rule.

    Plugins that declare no credentials always get ``{}`` (e.g. the
    built-in gateway actions). Plugins that declare credentials receive
    the delivery Integration's decrypted blob; the rule is skipped with a
    warning when the Integration carries no credentials, since the action
    would fail without operator configuration.
    """
    if not entry.manifest.credentials:
        return {}
    if not integration_credentials:
        LOGGER.warning(
            'Plugin %r requires credentials but the Integration has none;'
            ' skipping rule %r (webhook_id=%r)',
            entry.manifest.slug,
            rule_handler,
            webhook_id,
            extra={
                'webhook_id': webhook_id,
                'rule_handler': rule_handler,
                'plugin_slug': entry.manifest.slug,
            },
        )
        return None
    return integration_credentials


async def _resolve_identity(
    subject: str,
    identity_slugs: 'abc.Sequence[str]',
    *,
    webhook_id: str | None = None,
) -> str | None:
    """Map an identity ``subject`` to an Imbi user via ``identity_slugs``.

    Queries ``/users/by-identity`` for each candidate identity
    Integration slug and returns the single matching user's email.
    Returns ``None`` when nothing matches, or -- defensively -- when two
    or more candidates resolve to *different* users (logged as an error;
    the actor is left unattributed rather than mis-attributed).
    """
    matches: set[str] = set()
    async with actions.ImbiClient() as client:
        for slug in identity_slugs:
            user_id = await client.find_user_by_identity(slug, subject)
            if user_id is not None:
                matches.add(user_id)
    if len(matches) > 1:
        LOGGER.error(
            'Identity subject %r resolved to multiple Imbi users via '
            'integrations %r: %r — leaving unattributed (webhook_id=%r)',
            subject,
            list(identity_slugs),
            sorted(matches),
            webhook_id,
        )
        return None
    return next(iter(matches), None)


def _make_user_resolver(
    identity_slugs: 'abc.Sequence[str]',
) -> 'abc.Callable[[str], abc.Awaitable[str | None]] | None':
    """Build the ``PluginContext.resolve_user_by_identity`` resolver.

    Returns a coroutine mapping an external identity *subject* (e.g. a
    GitHub numeric user id) to the matching Imbi user's email, so an
    action (e.g. commit-sync author attribution) can resolve external
    actors via ``/users/by-identity`` without itself talking to the API.
    Returns ``None`` when there are no identity Integration candidates,
    so the action skips the lookups entirely.
    """
    if not identity_slugs:
        return None
    candidates = list(identity_slugs)

    async def _resolve(subject: str) -> str | None:
        return await _resolve_identity(subject, candidates)

    return _resolve


def _actor_is_bot(
    body: object,
    user_type_selector: str | None,
    *,
    webhook_id: str | None = None,
) -> bool:
    """Return ``True`` when the delivery's actor is a bot account.

    ``user_type_selector`` is an optional JSON pointer on the
    ``IMPLEMENTED_BY`` edge that resolves to the sender's account type
    (e.g. GitHub's ``/sender/type``, which is ``"Bot"`` for app/bot
    actors). When it resolves to ``"Bot"`` (case-insensitive) the caller
    skips the ``/users/by-identity`` lookup: bots are never Imbi users,
    so the lookup only ever 404s. A missing selector, an unresolvable
    pointer, or any non-bot value returns ``False`` so attribution
    proceeds normally.
    """
    if not user_type_selector:
        return False
    try:
        value = jsonpointer.JsonPointer(user_type_selector).resolve(body)
    except jsonpointer.JsonPointerException:
        LOGGER.debug(
            'user_type_selector %r did not resolve in payload'
            ' for webhook_id=%r',
            user_type_selector,
            webhook_id,
            extra={
                'webhook_id': webhook_id,
                'user_type_selector': user_type_selector,
            },
        )
        return False
    return isinstance(value, str) and value.casefold() == 'bot'


def _extract_subject(
    body: object,
    user_subject_selector: str | None,
    *,
    webhook_id: str | None = None,
) -> str | None:
    if not user_subject_selector:
        return None
    try:
        subject = jsonpointer.JsonPointer(user_subject_selector).resolve(body)
    except jsonpointer.JsonPointerException:
        LOGGER.warning(
            'user_subject_selector %r did not resolve in payload'
            ' for webhook_id=%r',
            user_subject_selector,
            webhook_id,
            extra={
                'webhook_id': webhook_id,
                'user_subject_selector': user_subject_selector,
            },
        )
        return None
    if subject in (None, ''):
        return None
    return str(subject)


async def _resolve_user_id(
    *,
    body: object,
    user_subject_selector: str | None,
    user_type_selector: str | None,
    candidate_identity_slugs: 'abc.Sequence[str]',
    webhook_id: str | None = None,
) -> str | None:
    """Resolve the Imbi ``user_id`` for a webhook delivery.

    Returns ``None`` when the delivery's actor is a bot (per
    ``user_type_selector`` -- see :func:`_actor_is_bot`), the
    ``IMPLEMENTED_BY`` edge does not declare a ``user_subject_selector``,
    the selector does not resolve to a value, there is no identity
    Integration candidate, or no candidate yields a match.
    ``candidate_identity_slugs`` is resolved by the caller (see
    :func:`_identity_candidate_slugs`) so this function performs no
    registry filtering of its own.
    """
    if _actor_is_bot(body, user_type_selector, webhook_id=webhook_id):
        LOGGER.debug(
            'Skipping identity lookup for bot actor (webhook_id=%r)',
            webhook_id,
            extra={'webhook_id': webhook_id},
        )
        return None
    subject = _extract_subject(
        body, user_subject_selector, webhook_id=webhook_id
    )
    if subject is None:
        return None
    if not candidate_identity_slugs:
        return None
    return await _resolve_identity(
        subject, candidate_identity_slugs, webhook_id=webhook_id
    )


def _set_access_log_context(
    request: fastapi.Request, *, user_id: str | None, event: str
) -> None:
    updates: dict[str, str] = {}
    if user_id:
        updates['user_id'] = user_id
    if event:
        updates['event'] = event
    if not updates:
        return
    existing: object = getattr(request.state, 'imbi_common_access_log', None)
    if isinstance(existing, dict):
        context = typing.cast('dict[str, str]', existing)
        context.update(updates)
    else:
        request.state.imbi_common_access_log = updates


def _sanitize_utf8(value: object) -> object:
    """Recursively coerce a parsed JSON body to storable UTF-8.

    GitHub (and other senders) occasionally deliver payloads whose JSON
    strings carry characters that don't round-trip through UTF-8 — most
    commonly lone surrogates from ``\\uXXXX`` escapes (e.g. a half of an
    emoji pair in a commit message), or bytes that decoded leniently
    above. Such ``str`` values are valid in Python but raise when
    re-encoded to UTF-8, so they break CEL evaluation and the ClickHouse
    ``payload`` insert downstream. Replace the offending characters here
    — once, at ingestion — so every consumer sees clean UTF-8.

    Dict keys are sanitized alongside values; non-string scalars
    (numbers, bools, ``None``) pass through untouched.
    """
    if isinstance(value, str):
        return value.encode('utf-8', 'replace').decode('utf-8')
    if isinstance(value, dict):
        items = typing.cast('typing.Any', value).items()
        return {_sanitize_utf8(k): _sanitize_utf8(v) for k, v in items}
    if isinstance(value, list):
        return [
            _sanitize_utf8(item) for item in typing.cast('typing.Any', value)
        ]
    return value


async def _extract_json_body(request: fastapi.Request) -> object:
    # Decode the raw body leniently rather than via ``request.json()``
    # (which decodes UTF-8 strictly and 422s on a single bad byte) so a
    # mis-encoded payload is accepted and cleaned instead of rejected;
    # ``_sanitize_utf8`` then repairs any lone surrogates the JSON parse
    # produced from ``\\uXXXX`` escapes.
    raw = await request.body()
    try:
        body = json.loads(raw.decode('utf-8', 'replace'))
    except ValueError:
        raise fastapi.HTTPException(
            http.HTTPStatus.UNPROCESSABLE_CONTENT
        ) from None
    return _sanitize_utf8(body)


def _payload_dict(body: object) -> dict[str, typing.Any]:
    """Coerce a webhook body into a dict for the ``payload`` column.

    Non-dict bodies map to ``{}`` so the typed ClickHouse insert never
    sees ``None`` or scalar JSON for the ``payload`` JSON column.
    """
    if isinstance(body, dict):
        return typing.cast('dict[str, typing.Any]', body)
    return {}


def _resolve_event_type(
    selector: str | None,
    body: object,
    headers: 'abc.Mapping[str, str]',
    *,
    webhook_id: str | None = None,
) -> str:
    """Resolve the event-type label per the configured selector.

    - ``None`` / empty selector -> ``''``.
    - Selector starting with ``/`` -> JSON pointer against ``body``;
      on miss, log a warning and return ``''``.
    - Otherwise -> case-insensitive HTTP header lookup. If the header
      is absent, return the selector itself as a literal label so
      sources without a useful event-type field (e.g. SonarQube)
      still get a stable string.
    """
    if not selector:
        return ''
    if selector.startswith('/'):
        try:
            resolved = jsonpointer.JsonPointer(selector).resolve(body)
        except jsonpointer.JsonPointerException:
            LOGGER.warning(
                'event_type_selector %r failed to resolve for webhook_id=%r',
                selector,
                webhook_id,
                extra={
                    'webhook_id': webhook_id,
                    'event_type_selector': selector,
                },
            )
            return ''
        return '' if resolved is None else str(resolved)
    header_value = headers.get(selector)
    if header_value:
        return header_value
    return selector


class DeliveryRecorder:
    """Two-phase activity-feed recording for one webhook delivery.

    :meth:`record_received` inserts one phase-1 ``events`` row per
    matched project before any handler runs. Handler outcomes are then
    appended to the per-project lists handed out by
    :meth:`outcomes_for`, and :meth:`record_dispositions` re-inserts
    each row with its outcomes under the same ``id`` and
    ``recorded_at`` with ``version = 1`` so the ``events_latest`` view
    collapses the pair into the latest disposition.

    Both inserts are best-effort — failures are logged and swallowed
    so handlers run (and the delivery is accepted) regardless of
    analytics insert health. If the phase-2 insert fails, the phase-1
    row remains the source of truth.
    """

    def __init__(self) -> None:
        self._events: dict[ProjectId, models.Event] = {}
        self._outcomes: dict[ProjectId, list[HandlerOutcome]] = {}

    async def record_received(  # noqa: PLR0913 - all inputs are required event fields
        self,
        records: 'abc.Sequence[abc.Mapping[str, typing.Any]]',
        *,
        integration_slug: str,
        user_id: str | None,
        event_type: str,
        metadata: dict[str, typing.Any],
        payload: dict[str, typing.Any],
    ) -> None:
        """Insert one phase-1 ``events`` row per matched project.

        ``metadata`` and ``payload`` are the materialized values
        shared with the rule filter context (see
        :func:`_record_and_build_filter_context`) so the recorded row
        and the filtered-on data never diverge; each row extends the
        shared metadata with ``event_type`` and an empty ``handlers``
        list.
        """
        if not records:
            return
        # ``version`` distinguishes the phase-1 row (0) from the phase-2
        # reinsert (1) so events_latest collapses to the populated
        # disposition. The field ships in the imbi-common revision this
        # repo pins for the webhook-history feature.
        events = [
            models.Event(
                project_id=str(graph.parse_agtype(record['project_id'])),
                # Category: every gateway-recorded row is an inbound
                # webhook delivery. The per-source resolved event-type
                # (e.g. 'pull_request', 'push', the SonarQube selector
                # literal) lives in ``metadata.event_type`` so the
                # events table can host non-webhook rows later without
                # overloading this column.
                type='webhook',
                integration=integration_slug,
                attributed_to=user_id or '',
                metadata={
                    **metadata,
                    'event_type': event_type,
                    'handlers': [],
                },
                payload=payload,
                version=0,
            )
            for record in records
        ]
        try:
            await clickhouse.insert(
                'events', typing.cast('list[pydantic.BaseModel]', events)
            )
        except Exception:
            LOGGER.exception('Failed to record webhook events in ClickHouse')
        self._events = {event.project_id: event for event in events}

    def outcomes_for(self, project_id: ProjectId) -> list[HandlerOutcome]:
        """Return the outcome list to append to for ``project_id``."""
        return self._outcomes.setdefault(project_id, [])

    async def record_dispositions(self) -> None:
        """Insert phase-2 rows that backfill handler outcomes."""
        if not self._events:
            return
        # ``version=1`` marks the phase-2 reinsert; see ``record_received``.
        phase2 = [
            models.Event(
                id=event.id,
                project_id=event.project_id,
                recorded_at=event.recorded_at,
                type=event.type,
                integration=event.integration,
                attributed_to=event.attributed_to,
                metadata={
                    **event.metadata,
                    'handlers': [
                        outcome.model_dump(exclude_none=True)
                        for outcome in self._outcomes.get(project_id, [])
                    ],
                },
                payload=event.payload,
                version=1,
            )
            for project_id, event in self._events.items()
        ]
        try:
            await clickhouse.insert(
                'events', typing.cast('list[pydantic.BaseModel]', phase2)
            )
        except Exception:
            LOGGER.exception(
                'Failed to record webhook event dispositions in ClickHouse'
            )


async def _record_and_build_filter_context(  # noqa: PLR0913 - required event fields
    records: 'abc.Sequence[abc.Mapping[str, typing.Any]]',
    *,
    recorder: DeliveryRecorder,
    headers: 'abc.Mapping[str, str]',
    webhook_id: str,
    integration_slug: str,
    user_id: str | None,
    event_type: str,
    body: object,
) -> dict[str, typing.Any]:
    """Record the activity-feed events and return the CEL filter context.

    ``metadata`` and ``payload`` are materialized once here so the
    ClickHouse ``events`` rows recorded through ``recorder`` and the
    rule filter context never diverge. The returned activation mirrors
    the project-independent fields of the
    :class:`imbi.common.models.Event` row, so a ``filter_expression``
    matches on exactly what the activity feed records:

    - ``type`` — resolved event type (e.g. the ``X-GitHub-Event`` value)
    - ``integration`` — Integration slug
    - ``attributed_to`` — resolved Imbi user (``''`` when unattributed)
    - ``metadata.headers`` — request headers, keys lower-cased and
      sensitive values redacted
    - ``payload`` — the webhook body

    Per-row identity (``id``, ``project_id``, ``recorded_at``) is omitted:
    the filter runs once per delivery, not per matched project.
    """
    metadata: dict[str, typing.Any] = {
        'webhook_id': webhook_id,
        'headers': _safe_headers(headers),
    }
    payload = _payload_dict(body)
    await recorder.record_received(
        records,
        integration_slug=integration_slug,
        user_id=user_id,
        event_type=event_type,
        metadata=metadata,
        payload=payload,
    )
    return {
        'type': event_type,
        'integration': integration_slug,
        'attributed_to': user_id or '',
        'metadata': metadata,
        'payload': payload,
    }
