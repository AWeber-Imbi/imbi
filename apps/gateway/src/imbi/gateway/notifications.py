import http
import inspect
import logging
import typing
from collections import abc

import celpy
import fastapi
import jsonpointer
import pydantic
from imbi_common import clickhouse, graph, models

from imbi_gateway import actions

LOGGER = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix='/notifications')

ActionFunction = typing.Callable[
    [str, str, typing.Any, str | None, str], abc.Awaitable[None]
]

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


def _safe_headers(headers: abc.Mapping[str, str]) -> dict[str, str]:
    """Return a redacted copy of ``headers`` for persisted metadata.

    Sensitive header values (authorization, cookies, webhook signatures)
    are replaced with ``'[redacted]'`` so secrets never reach ClickHouse.
    """
    return {
        key: ('[redacted]' if key.lower() in _SENSITIVE_HEADERS else value)
        for key, value in headers.items()
    }


class WebhookRule(pydantic.BaseModel):
    handler: pydantic.ImportString[ActionFunction]
    ordinal: int
    handler_config: str
    filter_expression: str

    @pydantic.field_validator('handler')
    @classmethod
    def _handler_must_by_async(cls, v: ActionFunction) -> ActionFunction:
        if not inspect.iscoroutinefunction(v):
            raise ValueError(f'{v!r} must be an async function')
        return v

    def evaluate_condition(self, body: object) -> bool | None:
        try:
            env = celpy.Environment()
            ast = env.compile(self.filter_expression)
            prg = env.program(ast)
            result = prg.evaluate(celpy.json_to_cel(body))
            return bool(result)
        except celpy.CELEvalError as e:
            LOGGER.warning(
                'CEL evaluation error in expression %r: %s',
                self.filter_expression,
                e,
            )
        except Exception as e:  # noqa: BLE001
            LOGGER.warning(
                'Unexpected error in expression %r: %s',
                self.filter_expression,
                e,
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
        '      collect(DISTINCT plg.plugin_slug) AS plugin_slugs'
        ' RETURN w{{.*}} AS webhook, o{{.*}} AS org, tps{{.*}} AS service,'
        '        i{{.*}} AS sel, rules, plugin_slugs',
        {'webhook_id': webhook_id},
        ['webhook', 'org', 'service', 'sel', 'rules', 'plugin_slugs'],
    )
    if not records:
        LOGGER.warning('No records found for %r', webhook_id)
    else:
        if len(records) != 1:
            LOGGER.error(
                'Webhook %r is connected to %s Organizations',
                webhook_id,
                len(records),
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

        try:
            rules = [
                WebhookRule.model_validate(row)
                for row in graph.parse_agtype(raw_rules)
            ]
        except pydantic.ValidationError as e:
            LOGGER.error(
                'failed to deserialize rules: %s',
                e,
                extra={'rules': raw_rules},
            )
            return

        LOGGER.debug('webhook: %r', webhook)
        LOGGER.debug('org: %r', org)
        LOGGER.debug('third_party_service: %r', service)
        LOGGER.debug('third_party_sel: %r', sel)
        LOGGER.debug('%s rules: %r', len(rules), rules)

        if sel is None or service is None:
            LOGGER.warning('Global webhooks are not yet implemented')
        else:
            body = await _extract_json_body(request)
            try:
                ptr = jsonpointer.JsonPointer(sel['identifier_selector'])
                resolved = ptr.resolve(body)
            except jsonpointer.JsonPointerException:
                LOGGER.exception(
                    'failed to select project identifier %r',
                    sel['identifier_selector'],
                )
                return

            # 2. validate each filter
            filter_results = [rule.evaluate_condition(body) for rule in rules]
            if not any(filter_results):
                LOGGER.debug('Ignoring notification: no filter matches')
                return

            # 3. execute each enabled handler for each matching project
            # TODO(daves) - this should probably be an imbi-api request
            records = await db.execute(
                'MATCH (p:Project)'
                '      -[:EXISTS_IN {{identifier: {external_id}}}]'
                '      ->(tps:ThirdPartyService {{slug: {tps_slug}}}) '
                'RETURN p.id AS project_id',
                {
                    'external_id': str(resolved),
                    'tps_slug': str(service['slug']),
                },
                ['project_id'],
            )
            if not records:
                LOGGER.warning(
                    'Ignoring notification: no project found for %r',
                    str(resolved),
                )
                return

            handlers = [
                rule
                for rule, enabled in zip(rules, filter_results, strict=True)
                if enabled
            ]
            user_id = await _resolve_user_id(
                body=body,
                user_subject_selector=sel.get('user_subject_selector'),
                edge_plugin_slug=sel.get('identity_plugin_slug'),
                candidate_plugin_slugs=plugin_slugs,
            )
            event_type = _resolve_event_type(
                sel.get('event_type_selector'), body, request.headers
            )
            metadata: dict[str, typing.Any] = {
                'webhook_id': webhook_id,
                'headers': _safe_headers(request.headers),
            }
            payload = _payload_dict(body)
            events = [
                models.Event(
                    project_id=graph.parse_agtype(record['project_id']),
                    type=event_type,
                    third_party_service=service['slug'],
                    attributed_to=user_id or '',
                    metadata=metadata,
                    payload=payload,
                )
                for record in records
            ]
            await _record_events(events)
            for record in records:
                await _run_handlers(
                    org['slug'],
                    graph.parse_agtype(record['project_id']),
                    body,
                    user_id,
                    handlers,
                )

            # indicates that we actually did something
            response.status_code = http.HTTPStatus.ACCEPTED


async def _run_handlers(
    org_slug: str,
    project_id: str,
    body: object,
    user_id: str | None,
    handlers: abc.Iterable[WebhookRule],
) -> None:
    LOGGER.debug('Running handlers for %s/%s', org_slug, project_id)
    for rule in handlers:
        try:
            await rule.handler(
                org_slug, project_id, body, user_id, rule.handler_config
            )
        except Exception:
            LOGGER.exception(
                'Failure in %s', rule.handler, extra={'rule': rule}
            )


def _extract_subject(
    body: object, user_subject_selector: str | None
) -> str | None:
    if not user_subject_selector:
        return None
    try:
        subject = jsonpointer.JsonPointer(user_subject_selector).resolve(body)
    except jsonpointer.JsonPointerException:
        LOGGER.warning(
            'user_subject_selector %r did not resolve in payload',
            user_subject_selector,
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
) -> str | None:
    """Resolve the Imbi ``user_id`` for a webhook delivery.

    Returns ``None`` when the IMPLEMENTED_BY edge does not declare a
    ``user_subject_selector``, the selector does not resolve to a value,
    no identity plugin yields a match, or two or more plugins yield
    *different* user ids (logged as an error — handler still runs
    without attribution).
    """
    subject = _extract_subject(body, user_subject_selector)
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
            'plugins %r: %r — passing user_id=None',
            subject,
            slugs,
            sorted(matches),
        )
        return None
    return next(iter(matches), None)


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
    selector: str | None, body: object, headers: abc.Mapping[str, str]
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
                'event_type_selector %r failed to resolve', selector
            )
            return ''
        return '' if resolved is None else str(resolved)
    header_value = headers.get(selector)
    if header_value:
        return header_value
    return selector


async def _record_events(events: list[models.Event]) -> None:
    """Insert one ``events`` row per matched project into ClickHouse.

    Best-effort — failures are logged and swallowed so handlers run
    regardless of analytics insert health.
    """
    if not events:
        return
    try:
        await clickhouse.insert(
            'events', typing.cast('list[pydantic.BaseModel]', events)
        )
    except Exception:
        LOGGER.exception('Failed to record webhook events in ClickHouse')
