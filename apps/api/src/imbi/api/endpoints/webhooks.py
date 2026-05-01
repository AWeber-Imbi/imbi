"""Webhook management endpoints."""

import json
import logging
import re
import typing

import fastapi
import nanoid
import psycopg
import pydantic
from imbi_common import graph
from imbi_common.auth import encryption

from imbi_api import patch as json_patch
from imbi_api.auth import permissions
from imbi_api.domain import models
from imbi_api.graph_sql import props_template, set_clause

LOGGER = logging.getLogger(__name__)

_READ_ONLY_PATHS = frozenset({'/notification_path', '/id'})


def _slugify(value: str) -> str:
    """Convert a string to a valid webhook slug fragment."""
    value = value.lower()
    value = re.sub(r'[^a-z0-9]+', '-', value)
    value = value.strip('-')
    if not value:
        return 'hook'
    if len(value) < 2:
        return value + '0'
    return value


def _generate_id() -> str:
    """Generate a nanoid surrogate key for a webhook."""
    return str(nanoid.generate())


def _compute_webhook_slug(
    service_slug: str | None,
    name: str,
) -> str:
    """Compute the system-generated slug from service slug and name."""
    name_part = _slugify(name)
    if service_slug:
        combined = f'{service_slug}-{name_part}'
        return combined[:64]
    return name_part[:64]


async def _check_identifier_collision(
    db: graph.Graph,
    org_slug: str,
    *,
    slug: str,
    webhook_id: str | None = None,
    exclude_id: str | None = None,
) -> None:
    """Raise 409 if slug or id would collide with the other identifier type.

    Checks that no webhook in the org has ``id = slug`` (a slug that
    matches an existing surrogate key) or ``slug = webhook_id`` (an id
    that matches an existing human-readable slug).  ``exclude_id`` skips
    the webhook with that id so a PATCH on the current webhook doesn't
    flag itself.
    """
    conditions: list[str] = ['w.id = {chk_slug}']
    params: dict[str, str] = {'org_slug': org_slug, 'chk_slug': slug}
    if webhook_id is not None:
        conditions.append('w.slug = {chk_id}')
        params['chk_id'] = webhook_id
    condition_expr = ' OR '.join(conditions)

    exclude_clause = ''
    if exclude_id is not None:
        exclude_clause = ' AND w.id <> {exclude_id}'
        params['exclude_id'] = exclude_id

    query = (
        'MATCH (w:Webhook)-[:BELONGS_TO]->'
        '(o:Organization {{slug: {org_slug}}})'
        f' WHERE ({condition_expr}){exclude_clause}'
        ' RETURN count(w) AS n'
    )
    rows = await db.execute(query, params, ['n'])
    count = graph.parse_agtype(rows[0].get('n', 0)) if rows else 0
    if count:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                'The webhook slug and id must not collide with any existing '
                "webhook's id or slug in this organization."
            ),
        )


def _rules_create_clauses(
    rules: list[dict[str, str | int]],
) -> tuple[str, dict[str, typing.Any]]:
    """Build CREATE clauses for webhook rules.

    Returns (cypher_fragment, params_dict). The fragment
    contains one CREATE pair per rule using unique variable
    names (rule_0, rule_1, …) so AGE never sees UNWIND-
    driven row multiplication or WITH DISTINCT after CREATE.
    """
    if not rules:
        return '', {}
    clauses: list[str] = []
    params: dict[str, typing.Any] = {}
    for i, rule in enumerate(rules):
        n = str(i)
        clauses.append(
            ' CREATE (rule_' + n + ':WebhookRule'
            ' {{filter_expression: {rule_' + n + '_fe},'
            ' handler: {rule_' + n + '_handler},'
            ' handler_config: {rule_' + n + '_hc},'
            ' ordinal: {rule_' + n + '_ord}}})'
            ' CREATE (rule_' + n + ')-[:ACTIONS]->(w)'
        )
        params['rule_' + n + '_fe'] = rule['filter_expression']
        params['rule_' + n + '_handler'] = rule['handler']
        params['rule_' + n + '_hc'] = rule['handler_config']
        params['rule_' + n + '_ord'] = rule['ordinal']
    return ''.join(clauses), params


_FETCH_WEBHOOK_QUERY: typing.LiteralString = """
MATCH (w:Webhook)-[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
WHERE w.slug = {identifier} OR w.id = {identifier}
OPTIONAL MATCH (w)-[impl:IMPLEMENTED_BY]->(tps:ThirdPartyService)
OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
WITH w, tps, impl, r
ORDER BY r.ordinal
WITH w, tps, impl,
     collect(CASE WHEN r IS NOT NULL
             THEN r{{.filter_expression, .handler,
                    .handler_config, .ordinal}}
             END)
        AS all_rules
RETURN w{{.*}} AS webhook,
       tps{{.*}} AS tps,
       impl.identifier_selector AS identifier_selector,
       [x IN all_rules
        | x {{.filter_expression, .handler,
              .handler_config}}]
           AS rules
"""


_UPDATE_RETURN_TAIL_WITH_TPS: typing.LiteralString = (
    ' WITH w, tps, impl'
    ' OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)'
    ' WITH w, tps, impl, r ORDER BY r.ordinal'
    ' WITH w, tps, impl,'
    ' collect(CASE WHEN r IS NOT NULL'
    ' THEN r{{.filter_expression, .handler,'
    ' .handler_config, .ordinal}} END) AS all_rules'
    ' RETURN w{{.*}} AS webhook, tps{{.*}} AS tps,'
    ' impl.identifier_selector AS identifier_selector,'
    ' [x IN all_rules'
    ' | x {{.filter_expression, .handler,'
    ' .handler_config}}] AS rules'
)


_UPDATE_RETURN_TAIL_NO_TPS: typing.LiteralString = (
    ' WITH w'
    ' OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)'
    ' WITH w, r ORDER BY r.ordinal'
    ' WITH w,'
    ' collect(CASE WHEN r IS NOT NULL'
    ' THEN r{{.filter_expression, .handler,'
    ' .handler_config, .ordinal}} END) AS all_rules'
    ' RETURN w{{.*}} AS webhook, null AS tps,'
    ' null AS identifier_selector,'
    ' [x IN all_rules'
    ' | x {{.filter_expression, .handler,'
    ' .handler_config}}] AS rules'
)


def _parse_json_rules(raw: typing.Any) -> list[typing.Any]:
    """Parse rules from a graph record; handles str (JSON) or list."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, TypeError):
            return []
    return list(raw) if raw else []


webhooks_router = fastapi.APIRouter(tags=['Webhooks'])


@webhooks_router.post('/', status_code=201)
async def create_webhook(
    org_slug: str,
    data: models.WebhookCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('webhook:create'),
        ),
    ],
) -> models.WebhookResponse:
    """Create a new webhook linked to an organization.

    The slug, id, and notification_path are system-generated:
    - slug: ``{service_slug}-{slugified_name}`` or just the slugified name
    - id: nanoid (21-char URL-safe string, stable surrogate key)
    - notification_path: ``/{id}``
    """
    encryptor = encryption.TokenEncryption.get_instance()

    webhook_id = _generate_id()
    slug = _compute_webhook_slug(data.third_party_service_slug, data.name)
    await _check_identifier_collision(
        db, org_slug, slug=slug, webhook_id=webhook_id
    )
    notification_path = f'/{webhook_id}'

    props: dict[str, typing.Any] = {
        'id': webhook_id,
        'name': data.name,
        'slug': slug,
        'description': data.description,
        'icon': data.icon,
        'notification_path': notification_path,
        'secret': (
            encryptor.encrypt(data.secret) if data.secret is not None else None
        ),
    }
    create_tpl = props_template(props)

    rule_dicts: list[dict[str, str | int]] = []
    for idx, rule in enumerate(data.rules):
        rule_dicts.append(
            {
                'filter_expression': rule.filter_expression,
                'handler': rule.handler,
                'handler_config': json.dumps(
                    rule.handler_config,
                ),
                'ordinal': idx,
            }
        )
    rule_clauses, rules_params = _rules_create_clauses(rule_dicts)

    base_params: dict[str, typing.Any] = {
        'org_slug': org_slug,
        **props,
        **rules_params,
    }
    if data.third_party_service_slug is not None:
        write_query: str = (
            'MATCH (o:Organization {{slug: {org_slug}}})'
            ' MATCH (tps:ThirdPartyService {{slug: {tps_slug}}})'
            ' -[:BELONGS_TO]->(o)'
            f' CREATE (w:Webhook {create_tpl})'
            ' CREATE (w)-[:BELONGS_TO]->(o)'
            ' CREATE (w)-[:IMPLEMENTED_BY'
            ' {{identifier_selector: {identifier_selector}}}]->(tps)'
            + rule_clauses
            + ' RETURN w.id AS id'
        )
        write_params: dict[str, typing.Any] = {
            **base_params,
            'tps_slug': data.third_party_service_slug,
            'identifier_selector': data.identifier_selector,
        }
    else:
        write_query = (
            'MATCH (o:Organization {{slug: {org_slug}}})'
            f' CREATE (w:Webhook {create_tpl})'
            ' CREATE (w)-[:BELONGS_TO]->(o)'
            + rule_clauses
            + ' RETURN w.id AS id'
        )
        write_params = base_params

    try:
        write_records = await db.execute(
            write_query,
            write_params,
            ['id'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'A webhook with slug {slug!r} already exists. '
                f'Choose a different name or rename the existing webhook.'
            ),
        ) from e

    if not write_records:
        if data.third_party_service_slug:
            raise fastapi.HTTPException(
                status_code=404,
                detail=(
                    f'Organization {org_slug!r} or third-party service '
                    f'{data.third_party_service_slug!r} not found'
                ),
            )
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization {org_slug!r} not found',
        )

    records = await db.execute(
        _FETCH_WEBHOOK_QUERY,
        {'identifier': webhook_id, 'org_slug': org_slug},
        ['webhook', 'tps', 'identifier_selector', 'rules'],
    )
    return models.WebhookResponse.from_graph_record(records[0])


@webhooks_router.get('/')
async def list_webhooks(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('webhook:read'),
        ),
    ],
) -> list[models.WebhookResponse]:
    """List webhooks for an organization."""
    query: typing.LiteralString = """
    MATCH (w:Webhook)-[:BELONGS_TO]->
          (o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (w)-[impl:IMPLEMENTED_BY]->
                   (tps:ThirdPartyService)
    OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
    WITH w, tps, impl, r
    ORDER BY r.ordinal
    WITH w, tps, impl,
         collect(CASE WHEN r IS NOT NULL
                 THEN r{{.filter_expression, .handler,
                        .handler_config, .ordinal}}
                 END)
            AS all_rules
    RETURN w{{.*}} AS webhook,
           tps{{.*}} AS tps,
           impl.identifier_selector AS identifier_selector,
           [x IN all_rules
            | x {{.filter_expression, .handler,
                  .handler_config}}]
               AS rules
    ORDER BY w.name
    """
    records = await db.execute(
        query,
        {'org_slug': org_slug},
        ['webhook', 'tps', 'identifier_selector', 'rules'],
    )
    return [models.WebhookResponse.from_graph_record(r) for r in records]


@webhooks_router.get('/{webhook}')
async def get_webhook(
    org_slug: str,
    webhook: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('webhook:read'),
        ),
    ],
) -> models.WebhookResponse:
    """Get a webhook by slug or id."""
    records = await db.execute(
        _FETCH_WEBHOOK_QUERY,
        {'identifier': webhook, 'org_slug': org_slug},
        ['webhook', 'tps', 'identifier_selector', 'rules'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Webhook {webhook!r} not found',
        )
    return models.WebhookResponse.from_graph_record(records[0])


@webhooks_router.patch('/{webhook}')
async def patch_webhook(
    org_slug: str,
    webhook: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('webhook:update'),
        ),
    ],
) -> models.WebhookResponse:
    """Partially update a webhook using JSON Patch (RFC 6902).

    The ``id`` and ``notification_path`` fields are read-only;
    patch operations targeting them are rejected with 400.

    When ``third_party_service_slug`` is changed and ``slug`` is not
    explicitly set in the same patch, the slug is auto-regenerated
    from the new service slug and webhook name.
    """
    for op in operations:
        if op.path in _READ_ONLY_PATHS:
            raise fastapi.HTTPException(
                status_code=400,
                detail=f'{op.path!r} is read-only and cannot be modified',
            )

    existing = await db.execute(
        _FETCH_WEBHOOK_QUERY,
        {'identifier': webhook, 'org_slug': org_slug},
        ['webhook', 'tps', 'identifier_selector', 'rules'],
    )

    if not existing:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Webhook {webhook!r} not found',
        )

    existing_webhook = graph.parse_agtype(existing[0]['webhook'])

    raw_rules = _parse_json_rules(existing[0].get('rules'))

    existing_tps = existing[0].get('tps')
    if existing_tps:
        existing_tps = graph.parse_agtype(existing_tps)

    patchable: dict[str, typing.Any] = {
        'name': existing_webhook.get('name'),
        'slug': existing_webhook.get('slug'),
        'description': existing_webhook.get('description'),
        'icon': existing_webhook.get('icon'),
        'secret': None,
        'third_party_service_slug': (
            existing_tps.get('slug') if existing_tps else None
        ),
        'identifier_selector': graph.parse_agtype(
            existing[0].get('identifier_selector')
        ),
        'rules': [
            {
                'filter_expression': r['filter_expression'],
                'handler': r['handler'],
                'handler_config': (
                    json.loads(r['handler_config'])
                    if isinstance(r.get('handler_config'), str)
                    else r.get('handler_config', {})
                ),
            }
            for r in raw_rules
            if r is not None
        ],
    }

    op_paths = {op.path for op in operations}
    service_changed = '/third_party_service_slug' in op_paths
    slug_explicitly_set = '/slug' in op_paths

    patched = json_patch.apply_patch(patchable, operations)

    if service_changed and not slug_explicitly_set:
        patched['slug'] = _compute_webhook_slug(
            patched.get('third_party_service_slug'),
            patched['name'],
        )

    new_slug: str = patched['slug']
    if new_slug != existing_webhook.get('slug'):
        await _check_identifier_collision(
            db,
            org_slug,
            slug=new_slug,
            exclude_id=existing_webhook.get('id', ''),
        )

    encryptor = encryption.TokenEncryption.get_instance()
    if '/secret' not in op_paths:
        encrypted_secret: str | None = existing_webhook.get('secret')
    elif patched.get('secret') is None:
        encrypted_secret = None
    else:
        encrypted_secret = encryptor.encrypt(patched['secret'])

    try:
        data = models.WebhookUpdate.model_validate(patched)
    except pydantic.ValidationError as exc:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {exc.errors()}',
        ) from exc

    props: dict[str, typing.Any] = {
        'name': data.name,
        'slug': data.slug,
        'description': data.description,
        'icon': data.icon,
        'secret': encrypted_secret,
    }
    set_stmt = set_clause('w', props)

    rule_dicts: list[dict[str, str | int]] = []
    for idx, rule in enumerate(data.rules):
        rule_dicts.append(
            {
                'filter_expression': rule.filter_expression,
                'handler': rule.handler,
                'handler_config': json.dumps(
                    rule.handler_config,
                ),
                'ordinal': idx,
            }
        )
    rule_clauses, rules_params = _rules_create_clauses(rule_dicts)

    # Use id as the stable lookup key for the write query
    existing_webhook_id: str = existing_webhook.get('id', '')

    if data.third_party_service_slug:
        write_query: str = (
            'MATCH (w:Webhook {{id: {webhook_id}}})'
            ' -[:BELONGS_TO]->(o:Organization'
            ' {{slug: {org_slug}}})'
            ' MATCH (tps:ThirdPartyService'
            ' {{slug: {tps_slug}}})-[:BELONGS_TO]->(o)'
            ' OPTIONAL MATCH'
            ' (old_r:WebhookRule)-[:ACTIONS]->(w)'
            ' DETACH DELETE old_r'
            ' WITH DISTINCT w, o, tps'
            ' OPTIONAL MATCH'
            ' (w)-[old_impl:IMPLEMENTED_BY]->()'
            ' DELETE old_impl'
            ' WITH DISTINCT w, o, tps'
            f' {set_stmt}'
            ' CREATE (w)-[impl:IMPLEMENTED_BY]->(tps)'
            ' SET impl.identifier_selector'
            ' = {identifier_selector}' + rule_clauses + ' RETURN w.id AS id'
        )
        params: dict[str, typing.Any] = {
            'webhook_id': existing_webhook_id,
            'org_slug': org_slug,
            'tps_slug': data.third_party_service_slug,
            **props,
            'identifier_selector': data.identifier_selector,
            **rules_params,
        }
    else:
        write_query = (
            'MATCH (w:Webhook {{id: {webhook_id}}})'
            ' -[:BELONGS_TO]->(o:Organization'
            ' {{slug: {org_slug}}})'
            ' OPTIONAL MATCH'
            ' (old_r:WebhookRule)-[:ACTIONS]->(w)'
            ' DETACH DELETE old_r'
            ' WITH DISTINCT w, o'
            ' OPTIONAL MATCH'
            ' (w)-[old_impl:IMPLEMENTED_BY]->()'
            ' DELETE old_impl'
            ' WITH DISTINCT w'
            f' {set_stmt}' + rule_clauses + ' RETURN w.id AS id'
        )
        params = {
            'webhook_id': existing_webhook_id,
            'org_slug': org_slug,
            **props,
            **rules_params,
        }

    try:
        write_records = await db.execute(
            write_query,
            params,
            ['id'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'A webhook with slug {data.slug!r} already exists.'),
        ) from e

    if not write_records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Webhook {webhook!r} not found',
        )

    records = await db.execute(
        _FETCH_WEBHOOK_QUERY,
        {'identifier': existing_webhook_id, 'org_slug': org_slug},
        ['webhook', 'tps', 'identifier_selector', 'rules'],
    )
    return models.WebhookResponse.from_graph_record(records[0])


@webhooks_router.delete('/{webhook}', status_code=204)
async def delete_webhook(
    org_slug: str,
    webhook: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('webhook:delete'),
        ),
    ],
) -> None:
    """Delete a webhook and its rules."""
    query: typing.LiteralString = """
    MATCH (w:Webhook)-[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    WHERE w.slug = {identifier} OR w.id = {identifier}
    OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
    DETACH DELETE r, w
    RETURN count(w) AS deleted
    """
    records = await db.execute(
        query,
        {'identifier': webhook, 'org_slug': org_slug},
        ['deleted'],
    )

    deleted = graph.parse_agtype(records[0]['deleted']) if records else 0
    if not records or deleted == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Webhook {webhook!r} not found',
        )


# -- Project EXISTS_IN endpoints ----------------------------------------


project_services_router = fastapi.APIRouter(
    tags=['Project Services'],
)


@project_services_router.get('/')
async def list_project_services(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> list[models.ExistsInResponse]:
    """List third-party services this project exists in."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    MATCH (p)-[ei:EXISTS_IN]->(tps:ThirdPartyService)
    RETURN tps.slug AS service_slug,
           tps.name AS service_name,
           ei.identifier AS identifier,
           ei.canonical_link AS canonical_link
    ORDER BY tps.name
    """
    records = await db.execute(
        query,
        {'org_slug': org_slug, 'project_id': project_id},
        [
            'service_slug',
            'service_name',
            'identifier',
            'canonical_link',
        ],
    )

    return [
        models.ExistsInResponse(
            third_party_service_slug=graph.parse_agtype(
                r['service_slug'],
            ),
            third_party_service_name=graph.parse_agtype(
                r['service_name'],
            ),
            identifier=graph.parse_agtype(r['identifier']),
            canonical_link=graph.parse_agtype(
                r.get('canonical_link'),
            ),
        )
        for r in records
    ]


@project_services_router.post('/', status_code=201)
async def create_project_service(
    org_slug: str,
    project_id: str,
    data: models.ExistsInCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> models.ExistsInResponse:
    """Add an EXISTS_IN link between a project and a service."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    MATCH (tps:ThirdPartyService {{slug: {tps_slug}}})
          -[:BELONGS_TO]->(o)
    MERGE (p)-[ei:EXISTS_IN]->(tps)
    SET ei.identifier = {identifier},
        ei.canonical_link = {canonical_link}
    RETURN tps.slug AS service_slug,
           tps.name AS service_name,
           ei.identifier AS identifier,
           ei.canonical_link AS canonical_link
    """
    records = await db.execute(
        query,
        {
            'org_slug': org_slug,
            'project_id': project_id,
            'tps_slug': data.third_party_service_slug,
            'identifier': data.identifier,
            'canonical_link': data.canonical_link,
        },
        [
            'service_slug',
            'service_name',
            'identifier',
            'canonical_link',
        ],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Project {project_id!r} or '
                f'service {data.third_party_service_slug!r} '
                f'not found'
            ),
        )

    r = records[0]
    return models.ExistsInResponse(
        third_party_service_slug=graph.parse_agtype(
            r['service_slug'],
        ),
        third_party_service_name=graph.parse_agtype(
            r['service_name'],
        ),
        identifier=graph.parse_agtype(r['identifier']),
        canonical_link=graph.parse_agtype(
            r.get('canonical_link'),
        ),
    )


@project_services_router.delete(
    '/{service_slug}',
    status_code=204,
)
async def delete_project_service(
    org_slug: str,
    project_id: str,
    service_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> None:
    """Remove an EXISTS_IN link."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    MATCH (p)-[ei:EXISTS_IN]->
          (tps:ThirdPartyService {{slug: {tps_slug}}})
    DELETE ei
    RETURN count(ei) AS deleted
    """
    records = await db.execute(
        query,
        {
            'org_slug': org_slug,
            'project_id': project_id,
            'tps_slug': service_slug,
        },
        ['deleted'],
    )

    deleted = graph.parse_agtype(records[0]['deleted']) if records else 0
    if not records or deleted == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'EXISTS_IN link between project '
                f'{project_id!r} and service '
                f'{service_slug!r} not found'
            ),
        )
