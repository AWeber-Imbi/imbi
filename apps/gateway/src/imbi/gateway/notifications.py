import http
import inspect
import logging
import typing
from collections import abc

import celpy
import fastapi
import jsonpointer
import pydantic
from imbi_common import graph

LOGGER = logging.getLogger(__name__)

router = fastapi.APIRouter(prefix='/notifications')

ActionFunction = typing.Callable[
    [str, str, typing.Any, str], abc.Awaitable[None]
]


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
    webhook_id: str, *, db: graph.Pool, request: fastapi.Request
) -> None:
    records = await db.execute(
        'MATCH (w:Webhook {{ id: {webhook_id} }})'
        ' -[:BELONGS_TO]->(o:Organization)'
        ' OPTIONAL MATCH (w)-[i:IMPLEMENTED_BY]->(tps:ThirdPartyService)'
        ' OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)'
        ' WITH w, o, tps, i, r ORDER BY r.ordinal'
        ' WITH w, o, tps, i, collect(r{{.*}}) AS rules'
        ' RETURN w{{.*}} AS webhook, o{{.*}} AS org, tps{{.*}} AS service,'
        '        i{{.*}} AS sel, rules',
        {'webhook_id': webhook_id},
        ['webhook', 'org', 'service', 'sel', 'rules'],
    )
    if not records:
        LOGGER.warning('No records found for %r', webhook_id)
    else:
        if len(records) != 1:
            LOGGER.warning(
                'Found multiple records (%s) for %r', len(records), webhook_id
            )

        record = records[0]
        webhook = graph.parse_agtype(record['webhook'])
        org = graph.parse_agtype(record['org'])
        service = graph.parse_agtype(record['service'])  # maybe None
        sel = graph.parse_agtype(record['sel'])  # maybe None
        raw_rules = record['rules']

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
                LOGGER.info('Ignoring notification: no filter matches')
                return

            # 3. execute each enabled handler for each matching project
            # TODO(daves) - this should probably be an imbi-api request
            records = await db.execute(
                'MATCH (p:Project)'
                '      -[:EXISTS_IN {{identifier: {external_id}}}]'
                '      ->(tps:ThirdPartyService {{id: {tps_id}}}) '
                'RETURN p.id AS project_id',
                {'external_id': str(resolved), 'tps_id': str(service['id'])},
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
            for record in records:
                await _run_handlers(
                    org['slug'],
                    graph.parse_agtype(record['project_id']),
                    body,
                    handlers,
                )


async def _run_handlers(
    org_slug: str,
    project_id: str,
    body: object,
    handlers: abc.Iterable[WebhookRule],
) -> None:
    LOGGER.debug('Running handlers for %s/%s', org_slug, project_id)
    for rule in handlers:
        try:
            await rule.handler(org_slug, project_id, body, rule.handler_config)
        except Exception:
            LOGGER.exception(
                'Failure in %s', rule.handler, extra={'rule': rule}
            )


async def _extract_json_body(request: fastapi.Request) -> object:
    try:
        return await request.json()
    except ValueError:
        raise fastapi.HTTPException(
            http.HTTPStatus.UNPROCESSABLE_CONTENT
        ) from None
