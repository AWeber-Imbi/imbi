import http
import json
import logging
import re
import typing

import celpy
import fastapi
import jsonpointer
import pydantic
from imbi_common import clickhouse, graph, models
from imbi_common.auth.encryption import TokenEncryption
from imbi_common.plugins import base as plugin_base
from imbi_common.plugins import registry as plugin_registry
from imbi_common.plugins.errors import PluginNotFoundError

from imbi_gateway import actions

if typing.TYPE_CHECKING:
    from collections import abc

LOGGER = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix='/notifications')

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


class WebhookRule(pydantic.BaseModel):
    """A single ``WebhookRule`` row pulled from the graph.

    ``handler`` is a ``"<plugin_slug>#<action_name>"`` string. The
    field validator only enforces shape -- plugin/action resolution
    happens at dispatch time so a stale rule does not stop the gateway
    from accepting deliveries (the dispatcher logs and skips instead).
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
        self, body: object, *, webhook_id: str | None = None
    ) -> bool | None:
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
            result = prg.evaluate(celpy.json_to_cel(body))
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
async def process_notification(
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
        ' OPTIONAL MATCH (w)-[i:IMPLEMENTED_BY]->(tps:ThirdPartyService)'
        ' OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)'
        ' WITH w, o, tps, i, r ORDER BY r.ordinal'
        ' WITH w, o, tps, i, collect(r{{.*}}) AS rules'
        ' OPTIONAL MATCH (tps)-[:HAS_PLUGIN]->(plg:Plugin)'
        ' WITH w, o, tps, i, rules,'
        '      collect(DISTINCT plg.plugin_slug) AS plugin_slugs,'
        '      collect(DISTINCT plg{{.id, .plugin_slug,'
        '        .plugin_configuration}}) AS plugins'
        ' RETURN w{{.*}} AS webhook, o{{.*}} AS org, tps{{.*}} AS service,'
        '        i{{.*}} AS sel, rules, plugin_slugs, plugins',
        {'webhook_id': webhook_id},
        [
            'webhook',
            'org',
            'service',
            'sel',
            'rules',
            'plugin_slugs',
            'plugins',
        ],
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
    service = graph.parse_agtype(record['service'])  # maybe None
    sel = graph.parse_agtype(record['sel'])  # maybe None
    raw_rules = record['rules']
    plugin_slugs_raw: list[typing.Any] = (
        graph.parse_agtype(record['plugin_slugs']) or []
    )
    plugin_slugs: list[str] = [str(s) for s in plugin_slugs_raw if s]
    plugins_raw: list[typing.Any] = graph.parse_agtype(record['plugins']) or []
    plugins_by_slug = _index_plugins(plugins_raw)

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
    LOGGER.debug('third_party_service: %r', service)
    LOGGER.debug('third_party_sel: %r', sel)
    LOGGER.debug('%s rules: %r', len(rules), rules)

    if sel is None or service is None:
        LOGGER.warning(
            'Global webhooks are not yet implemented (webhook_id=%r)',
            webhook_id,
            extra={'webhook_id': webhook_id},
        )
        return

    tps_slug = str(service['slug'])
    body = await _extract_json_body(request)
    try:
        ptr = jsonpointer.JsonPointer(sel['identifier_selector'])
        resolved = ptr.resolve(body)
    except jsonpointer.JsonPointerException:
        LOGGER.exception(
            'failed to select project identifier %r for webhook_id=%r tps=%r',
            sel['identifier_selector'],
            webhook_id,
            tps_slug,
            extra={
                'webhook_id': webhook_id,
                'tps_slug': tps_slug,
                'identifier_selector': sel['identifier_selector'],
            },
        )
        return

    project_records = await db.execute(
        'MATCH (p:Project)'
        '      -[:EXISTS_IN {{identifier: {external_id}}}]'
        '      ->(tps:ThirdPartyService {{slug: {tps_slug}}}) '
        'OPTIONAL MATCH (p)-[:OWNED_BY]->(t:Team)'
        ' RETURN p.id AS project_id, p.slug AS project_slug,'
        '        t.slug AS team_slug',
        {'external_id': str(resolved), 'tps_slug': tps_slug},
        ['project_id', 'project_slug', 'team_slug'],
    )
    if not project_records:
        LOGGER.warning(
            'Ignoring notification: no project found for external_id=%r'
            ' (webhook_id=%r tps=%r)',
            str(resolved),
            webhook_id,
            tps_slug,
            extra={
                'webhook_id': webhook_id,
                'tps_slug': tps_slug,
                'external_identifier': str(resolved),
            },
        )
        return

    user_id = await _resolve_user_id(
        body=body,
        user_subject_selector=sel.get('user_subject_selector'),
        edge_plugin_slug=sel.get('identity_plugin_slug'),
        candidate_plugin_slugs=plugin_slugs,
        webhook_id=webhook_id,
    )
    event_type = _resolve_event_type(
        sel.get('event_type_selector'),
        body,
        request.headers,
        webhook_id=webhook_id,
    )
    _set_access_log_context(request, user_id=user_id, event=event_type)
    await _record_events(
        project_records,
        webhook_id=webhook_id,
        service_slug=tps_slug,
        user_id=user_id,
        event_type=event_type,
        headers=request.headers,
        body=body,
    )

    filter_results = [
        rule.evaluate_condition(body, webhook_id=webhook_id) for rule in rules
    ]
    if not any(filter_results):
        LOGGER.debug(
            'Ignoring notification: no filter matches (webhook_id=%r tps=%r)',
            webhook_id,
            tps_slug,
            extra={'webhook_id': webhook_id, 'tps_slug': tps_slug},
        )
        return

    matched_rules = [
        rule
        for rule, enabled in zip(rules, filter_results, strict=True)
        if enabled
    ]
    for proj_record in project_records:
        await _run_handlers(
            org_slug=str(org['slug']),
            project_id=str(graph.parse_agtype(proj_record['project_id'])),
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
            service_slug=tps_slug,
            service_endpoint=(
                str(service['api_endpoint'])
                if service.get('api_endpoint') is not None
                else None
            ),
            external_identifier=str(resolved),
            payload=body,
            user_id=user_id,
            rules=matched_rules,
            plugins_by_slug=plugins_by_slug,
            webhook_id=webhook_id,
        )

    # indicates that we actually did something
    response.status_code = http.HTTPStatus.ACCEPTED


def _index_plugins(
    plugins_raw: 'abc.Iterable[typing.Any]',
) -> dict[str, dict[str, str]]:
    """Build ``{plugin_slug: {id, plugin_configuration}}`` from raw rows."""
    indexed: dict[str, dict[str, str]] = {}
    for row in plugins_raw:
        if not isinstance(row, dict):
            continue
        row_dict = typing.cast('dict[str, typing.Any]', row)
        slug_raw: object = row_dict.get('plugin_slug')
        if not slug_raw:
            continue
        slug = str(slug_raw)
        plugin_id: object = row_dict.get('id')
        configuration: object = row_dict.get('plugin_configuration')
        indexed[slug] = {
            'id': str(plugin_id) if plugin_id is not None else '',
            'plugin_configuration': (
                str(configuration) if configuration is not None else ''
            ),
        }
    return indexed


def _decrypt_plugin_credentials(
    plugin_record: dict[str, str],
) -> dict[str, str]:
    """Decrypt the ``plugin_configuration`` blob into a credential dict.

    Returns ``{}`` for plugins that store no configuration. Decryption
    or JSON parse failures are logged and treated as missing creds so
    a bad row does not 5xx the webhook.
    """
    encrypted = plugin_record.get('plugin_configuration')
    if not encrypted:
        return {}
    try:
        plaintext = TokenEncryption.get_instance().decrypt(encrypted)
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Plugin credentials decrypt failed for plugin_id=%s',
            plugin_record.get('id'),
        )
        return {}
    if not plaintext:
        return {}
    try:
        data = json.loads(plaintext)
    except json.JSONDecodeError:
        LOGGER.warning(
            'Plugin credentials JSON parse failed for plugin_id=%s',
            plugin_record.get('id'),
        )
        return {}
    if not isinstance(data, dict):
        return {}
    creds = typing.cast('dict[str, typing.Any]', data)
    return {k: str(v) for k, v in creds.items() if v is not None}


def _resolve_rule_handler(
    rule: WebhookRule, *, webhook_id: str | None = None
) -> tuple[plugin_registry.RegistryEntry, plugin_base.ActionDescriptor] | None:
    """Look the rule's plugin / action up in the registry.

    Returns ``None`` (after logging) when the plugin or action cannot
    be resolved -- the dispatcher continues with the next rule rather
    than failing the whole delivery.
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
    if not issubclass(entry.handler_cls, plugin_base.WebhookActionPlugin):
        LOGGER.error(
            'Plugin %r is not a WebhookActionPlugin; cannot dispatch %r'
            ' (webhook_id=%r)',
            rule.plugin_slug,
            rule.handler,
            webhook_id,
            extra=log_extra,
        )
        return None
    try:
        descriptors = [
            d
            for d in entry.handler_cls.actions()
            if d.name == rule.action_name
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
    project_id: str,
    project_slug: str,
    team_slug: str | None,
    service_slug: str,
    service_endpoint: str | None,
    external_identifier: str,
    payload: object,
    user_id: str | None,
    rules: 'abc.Iterable[WebhookRule]',
    plugins_by_slug: dict[str, dict[str, str]],
    webhook_id: str | None = None,
) -> None:
    LOGGER.debug(
        'Running handlers for %s/%s (webhook_id=%r tps=%r)',
        org_slug,
        project_id,
        webhook_id,
        service_slug,
    )
    assignment_options: dict[str, typing.Any] = {'service_slug': service_slug}
    if service_endpoint is not None:
        assignment_options['service_endpoint'] = service_endpoint
    ctx = plugin_base.PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        actor_user_id=user_id,
        assignment_options=assignment_options,
    )
    for rule in rules:
        resolved = _resolve_rule_handler(rule, webhook_id=webhook_id)
        if resolved is None:
            continue
        entry, descriptor = resolved
        credentials = _credentials_for_plugin(
            entry,
            plugins_by_slug,
            webhook_id=webhook_id,
            rule_handler=rule.handler,
        )
        if credentials is None:
            continue
        try:
            config = descriptor.config_model.model_validate_json(
                rule.handler_config
            )
        except pydantic.ValidationError:
            LOGGER.exception(
                'Invalid handler_config for rule %r (webhook_id=%r tps=%r);'
                ' skipping rule',
                rule.handler,
                webhook_id,
                service_slug,
                extra={
                    'webhook_id': webhook_id,
                    'tps_slug': service_slug,
                    'rule_handler': rule.handler,
                    'rule_ordinal': rule.ordinal,
                },
            )
            continue
        try:
            await descriptor.callable(
                ctx=ctx,
                credentials=credentials,
                external_identifier=external_identifier,
                action_config=config,
                payload=payload,
            )
        except Exception:
            LOGGER.exception(
                'Failure executing rule %r (webhook_id=%r tps=%r'
                ' project=%s/%s)',
                rule.handler,
                webhook_id,
                service_slug,
                org_slug,
                project_id,
                extra={
                    'webhook_id': webhook_id,
                    'tps_slug': service_slug,
                    'rule_handler': rule.handler,
                    'rule_ordinal': rule.ordinal,
                    'org_slug': org_slug,
                    'project_id': project_id,
                    'rule': rule,
                },
            )


def _credentials_for_plugin(
    entry: plugin_registry.RegistryEntry,
    plugins_by_slug: dict[str, dict[str, str]],
    *,
    webhook_id: str | None = None,
    rule_handler: str | None = None,
) -> dict[str, str] | None:
    """Return decrypted credentials for ``entry`` or ``None`` to skip.

    Plugins that declare no credentials always get ``{}``. Plugins
    with declared credentials but no attached ``Plugin`` node are
    skipped with a warning -- they require operator configuration the
    TPS does not have.
    """
    if not entry.manifest.credentials:
        return {}
    log_extra: dict[str, typing.Any] = {
        'webhook_id': webhook_id,
        'rule_handler': rule_handler,
        'plugin_slug': entry.manifest.slug,
    }
    record = plugins_by_slug.get(entry.manifest.slug)
    if record is None:
        LOGGER.warning(
            'Plugin %r requires credentials but is not attached to the TPS;'
            ' skipping rule %r (webhook_id=%r)',
            entry.manifest.slug,
            rule_handler,
            webhook_id,
            extra=log_extra,
        )
        return None
    credentials = _decrypt_plugin_credentials(record)
    if not credentials:
        LOGGER.warning(
            'Plugin %r requires credentials but none could be loaded;'
            ' skipping rule %r (webhook_id=%r)',
            entry.manifest.slug,
            rule_handler,
            webhook_id,
            extra=log_extra,
        )
        return None
    return credentials


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
    edge_plugin_slug: str | None,
    candidate_plugin_slugs: list[str],
    webhook_id: str | None = None,
) -> str | None:
    """Resolve the Imbi ``user_id`` for a webhook delivery.

    Returns ``None`` when the IMPLEMENTED_BY edge does not declare a
    ``user_subject_selector``, the selector does not resolve to a value,
    no identity plugin yields a match, or two or more plugins yield
    *different* user ids (logged as an error — handler still runs
    without attribution).
    """
    subject = _extract_subject(
        body, user_subject_selector, webhook_id=webhook_id
    )
    if subject is None:
        return None
    slugs: list[str] = (
        [edge_plugin_slug] if edge_plugin_slug else candidate_plugin_slugs
    )
    if not slugs:
        return None

    matches: set[str] = set()
    async with actions.ImbiClient() as client:
        for slug in slugs:
            user_id = await client.find_user_by_identity(slug, subject)
            if user_id is not None:
                matches.add(user_id)

    if len(matches) > 1:
        LOGGER.error(
            'Identity subject %r resolved to multiple Imbi users via '
            'plugins %r: %r — passing user_id=None (webhook_id=%r)',
            subject,
            slugs,
            sorted(matches),
            webhook_id,
            extra={
                'webhook_id': webhook_id,
                'identity_subject': subject,
                'identity_plugins': slugs,
                'identity_matches': sorted(matches),
            },
        )
        return None
    return next(iter(matches), None)


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


async def _extract_json_body(request: fastapi.Request) -> object:
    try:
        return await request.json()
    except ValueError:
        raise fastapi.HTTPException(
            http.HTTPStatus.UNPROCESSABLE_CONTENT
        ) from None


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


async def _record_events(  # noqa: PLR0913 - all inputs are required event fields
    records: 'abc.Sequence[abc.Mapping[str, typing.Any]]',
    *,
    webhook_id: str,
    service_slug: str,
    user_id: str | None,
    event_type: str,
    headers: 'abc.Mapping[str, str]',
    body: object,
) -> None:
    """Insert one ``events`` row per matched project into ClickHouse.

    Best-effort — failures are logged and swallowed so handlers run
    regardless of analytics insert health.
    """
    if not records:
        return
    metadata: dict[str, typing.Any] = {
        'webhook_id': webhook_id,
        'headers': _safe_headers(headers),
    }
    payload = _payload_dict(body)
    events = [
        models.Event(
            project_id=graph.parse_agtype(record['project_id']),
            type=event_type,
            third_party_service=service_slug,
            attributed_to=user_id or '',
            metadata=metadata,
            payload=payload,
        )
        for record in records
    ]
    try:
        await clickhouse.insert(
            'events', typing.cast('list[pydantic.BaseModel]', events)
        )
    except Exception:
        LOGGER.exception('Failed to record webhook events in ClickHouse')
