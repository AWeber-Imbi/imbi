"""Webhook management endpoints."""

import json
import logging
import typing

import fastapi
import psycopg
import pydantic
from imbi_common import graph
from imbi_common.auth import encryption

from imbi_api import patch as json_patch
from imbi_api.auth import permissions
from imbi_api.domain import models

LOGGER = logging.getLogger(__name__)


def _props_template(props: dict[str, typing.Any]) -> str:
    """Build a Cypher property-map template with double-escaped braces.

    Each key becomes ``key: {key}`` inside doubled braces so that
    ``psycopg.sql.SQL.format()`` resolves them correctly::

        >>> _props_template({'name': 'x', 'slug': 'y'})
        '{{name: {name}, slug: {slug}}}'

    """
    if not props:
        return ''
    pairs = [f'{k}: {{{k}}}' for k in props]
    return '{{' + ', '.join(pairs) + '}}'


def _set_clause(
    alias: str,
    props: dict[str, typing.Any],
) -> str:
    """Build a Cypher SET clause from a property dict.

    Returns a string like ``SET w.name = {name}, w.slug = {slug}``.

    """
    if not props:
        return ''
    assignments = ', '.join(f'{alias}.{k} = {{{k}}}' for k in props)
    return f'SET {assignments}'


def _rules_template(
    rules: list[dict[str, str | int]],
) -> tuple[str, dict[str, typing.Any]]:
    """Build an inline Cypher list of maps for webhook rules.

    Returns a tuple of (template_fragment, params_dict) where
    the template uses indexed placeholders and the params dict
    maps those keys to scalar values.

    """
    if not rules:
        return '[]', {}
    maps: list[str] = []
    params: dict[str, typing.Any] = {}
    for i, rule in enumerate(rules):
        maps.append(
            f'{{{{filter_expression: {{rule_{i}_fe}},'
            f' handler: {{rule_{i}_handler}},'
            f' handler_config: {{rule_{i}_hc}},'
            f' ordinal: {{rule_{i}_ord}}}}}}'
        )
        params[f'rule_{i}_fe'] = rule['filter_expression']
        params[f'rule_{i}_handler'] = rule['handler']
        params[f'rule_{i}_hc'] = rule['handler_config']
        params[f'rule_{i}_ord'] = rule['ordinal']
    return '[' + ', '.join(maps) + ']', params


def _rule_unwind(rules_tpl: str) -> str:
    """Build the UNWIND + FOREACH clause for rule creation."""
    return (
        f' UNWIND CASE WHEN size({rules_tpl}) = 0'
        f' THEN [null] ELSE {rules_tpl}'
        ' END AS rule_data'
        ' FOREACH (_ IN CASE WHEN rule_data IS NOT NULL'
        ' THEN [1] ELSE [] END |'
        ' CREATE (r:WebhookRule'
        ' {{{{filter_expression:'
        ' rule_data.filter_expression,'
        ' handler: rule_data.handler,'
        ' handler_config: rule_data.handler_config,'
        ' ordinal: rule_data.ordinal}}}})'
        ' CREATE (r)-[:ACTIONS]->(w))'
    )


_RULE_RETURN_TPS: typing.LiteralString = (
    ' WITH DISTINCT w, tps, impl'
    ' OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)'
    ' WITH w, tps, impl, r'
    ' ORDER BY r.ordinal'
    ' WITH w, tps, impl,'
    ' collect(r{{.filter_expression, .handler,'
    ' .handler_config, .ordinal}}) AS rules'
    ' RETURN w{{.*}} AS webhook,'
    ' tps{{.*}} AS tps,'
    ' impl.identifier_selector AS identifier_selector,'
    ' [x IN rules | x {{.filter_expression,'
    ' .handler, .handler_config}}] AS rules'
)

_RULE_RETURN_NO_TPS: typing.LiteralString = (
    ' WITH DISTINCT w'
    ' OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)'
    ' WITH w, r'
    ' ORDER BY r.ordinal'
    ' WITH w,'
    ' collect(r{{.filter_expression, .handler,'
    ' .handler_config, .ordinal}}) AS rules'
    ' RETURN w{{.*}} AS webhook,'
    ' null AS tps,'
    ' null AS identifier_selector,'
    ' [x IN rules | x {{.filter_expression,'
    ' .handler, .handler_config}}] AS rules'
)


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
    """Create a new webhook linked to an organization."""
    encryptor = encryption.TokenEncryption.get_instance()

    props: dict[str, typing.Any] = {
        'name': data.name,
        'slug': data.slug,
        'description': data.description,
        'icon': data.icon,
        'notification_path': data.notification_path,
        'secret': (
            encryptor.encrypt(data.secret) if data.secret is not None else None
        ),
    }
    create_tpl = _props_template(props)

    # Build rule creation params as scalars
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
    rules_tpl, rules_params = _rules_template(rule_dicts)
    unwind = _rule_unwind(rules_tpl)

    if data.third_party_service_slug:
        query: str = (
            'MATCH (o:Organization {{slug: {org_slug}}})'
            ' MATCH (tps:ThirdPartyService'
            ' {{slug: {tps_slug}}})-[:BELONGS_TO]->(o)'
            f' CREATE (w:Webhook {create_tpl})'
            ' CREATE (w)-[:BELONGS_TO]->(o)'
            ' CREATE (w)-[impl:IMPLEMENTED_BY]->(tps)'
            ' SET impl.identifier_selector'
            ' = {identifier_selector}'
            ' WITH w, tps, o, impl' + unwind + _RULE_RETURN_TPS
        )
        params: dict[str, typing.Any] = {
            'org_slug': org_slug,
            'tps_slug': data.third_party_service_slug,
            **props,
            'identifier_selector': data.identifier_selector,
            **rules_params,
        }
    else:
        query = (
            'MATCH (o:Organization {{slug: {org_slug}}})'
            f' CREATE (w:Webhook {create_tpl})'
            ' CREATE (w)-[:BELONGS_TO]->(o)'
            ' WITH w, o' + unwind + _RULE_RETURN_NO_TPS
        )
        params = {
            'org_slug': org_slug,
            **props,
            **rules_params,
        }

    try:
        records = await db.execute(
            query,
            params,
            ['webhook', 'tps', 'identifier_selector', 'rules'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Webhook with slug {data.slug!r} '
                f'or notification_path '
                f'{data.notification_path!r} already exists'
            ),
        ) from e

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization {org_slug!r} not found',
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
         collect(r{{
                .filter_expression, .handler,
                .handler_config, .ordinal}})
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


@webhooks_router.get('/{slug}')
async def get_webhook(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('webhook:read'),
        ),
    ],
) -> models.WebhookResponse:
    """Get a webhook by slug."""
    query: typing.LiteralString = """
    MATCH (w:Webhook {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (w)-[impl:IMPLEMENTED_BY]->
                   (tps:ThirdPartyService)
    OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
    WITH w, tps, impl, r
    ORDER BY r.ordinal
    WITH w, tps, impl,
         collect(r{{
                .filter_expression, .handler,
                .handler_config, .ordinal}})
            AS all_rules
    RETURN w{{.*}} AS webhook,
           tps{{.*}} AS tps,
           impl.identifier_selector AS identifier_selector,
           [x IN all_rules
            | x {{.filter_expression, .handler,
                  .handler_config}}]
               AS rules
    """
    records = await db.execute(
        query,
        {'slug': slug, 'org_slug': org_slug},
        ['webhook', 'tps', 'identifier_selector', 'rules'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Webhook with slug {slug!r} not found',
        )
    return models.WebhookResponse.from_graph_record(records[0])


@webhooks_router.put('/{slug}')
async def update_webhook(
    org_slug: str,
    slug: str,
    data: models.WebhookUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('webhook:update'),
        ),
    ],
) -> models.WebhookResponse:
    """Update a webhook (full replacement including rules)."""
    # Verify exists
    check_query: typing.LiteralString = """
    MATCH (w:Webhook {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN w{{.*}} AS webhook
    """
    existing = await db.execute(
        check_query,
        {'slug': slug, 'org_slug': org_slug},
        ['webhook'],
    )

    if not existing:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Webhook with slug {slug!r} not found',
        )

    encryptor = encryption.TokenEncryption.get_instance()

    # Distinguish omitted secret (preserve existing) from explicit
    # null (clear) or a new value (encrypt and store).
    existing_webhook = graph.parse_agtype(
        existing[0]['webhook'],
    )
    if 'secret' not in data.model_fields_set:
        encrypted_secret = existing_webhook.get('secret')
    elif data.secret is None:
        encrypted_secret = None
    else:
        encrypted_secret = encryptor.encrypt(data.secret)

    props: dict[str, typing.Any] = {
        'name': data.name,
        'slug': data.slug,
        'description': data.description,
        'icon': data.icon,
        'notification_path': data.notification_path,
        'secret': encrypted_secret,
    }
    set_clause = _set_clause('w', props)

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
    rules_tpl, rules_params = _rules_template(rule_dicts)
    unwind = _rule_unwind(rules_tpl)

    # Delete old rules and IMPLEMENTED_BY, then recreate
    if data.third_party_service_slug:
        query: str = (
            'MATCH (w:Webhook {{slug: {old_slug}}})'
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
            f' {set_clause}'
            ' CREATE (w)-[impl:IMPLEMENTED_BY]->(tps)'
            ' SET impl.identifier_selector'
            ' = {identifier_selector}'
            ' WITH w, tps, impl' + unwind + _RULE_RETURN_TPS
        )
        params: dict[str, typing.Any] = {
            'old_slug': slug,
            'org_slug': org_slug,
            'tps_slug': data.third_party_service_slug,
            **props,
            'identifier_selector': data.identifier_selector,
            **rules_params,
        }
    else:
        query = (
            'MATCH (w:Webhook {{slug: {old_slug}}})'
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
            f' {set_clause}'
            ' WITH w' + unwind + _RULE_RETURN_NO_TPS
        )
        params = {
            'old_slug': slug,
            'org_slug': org_slug,
            **props,
            **rules_params,
        }

    try:
        records = await db.execute(
            query,
            params,
            ['webhook', 'tps', 'identifier_selector', 'rules'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Webhook with slug {data.slug!r} '
                f'or notification_path '
                f'{data.notification_path!r} already exists'
            ),
        ) from e

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Webhook with slug {slug!r} not found',
        )

    return models.WebhookResponse.from_graph_record(records[0])


@webhooks_router.patch('/{slug}')
async def patch_webhook(
    org_slug: str,
    slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('webhook:update'),
        ),
    ],
) -> models.WebhookResponse:
    """Partially update a webhook using JSON Patch (RFC 6902)."""
    check_query: typing.LiteralString = """
    MATCH (w:Webhook {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (w)-[impl:IMPLEMENTED_BY]->
                   (tps:ThirdPartyService)
    OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
    WITH w, tps, impl, r
    ORDER BY r.ordinal
    WITH w, tps, impl,
         collect(r{{
                .filter_expression, .handler,
                .handler_config, .ordinal}})
            AS all_rules
    RETURN w{{.*}} AS webhook,
           tps{{.*}} AS tps,
           impl.identifier_selector AS identifier_selector,
           [x IN all_rules
            | x {{.filter_expression, .handler,
                  .handler_config}}]
               AS rules
    """
    existing = await db.execute(
        check_query,
        {'slug': slug, 'org_slug': org_slug},
        ['webhook', 'tps', 'identifier_selector', 'rules'],
    )

    if not existing:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Webhook with slug {slug!r} not found',
        )

    existing_webhook = graph.parse_agtype(existing[0]['webhook'])

    # Build the patchable document (never expose encrypted secret)
    raw_rules: list[typing.Any] = existing[0].get('rules') or []
    if isinstance(raw_rules, str):
        try:
            raw_rules = json.loads(raw_rules)
        except (json.JSONDecodeError, TypeError):
            raw_rules = []

    existing_tps = existing[0].get('tps')
    if existing_tps:
        existing_tps = graph.parse_agtype(existing_tps)

    patchable: dict[str, typing.Any] = {
        'name': existing_webhook.get('name'),
        'slug': existing_webhook.get('slug'),
        'description': existing_webhook.get('description'),
        'icon': existing_webhook.get('icon'),
        'notification_path': existing_webhook.get('notification_path'),
        'secret': None,
        'third_party_service_slug': (
            existing_tps.get('slug') if existing_tps else None
        ),
        'identifier_selector': existing[0].get('identifier_selector'),
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

    patched = json_patch.apply_patch(patchable, operations)

    # Secret handling: preserve encrypted secret if not in patch
    encryptor = encryption.TokenEncryption.get_instance()
    secret_paths = {op.path for op in operations}
    if '/secret' not in secret_paths:
        encrypted_secret: str | None = existing_webhook.get('secret')
    elif patched.get('secret') is None:
        encrypted_secret = None
    else:
        encrypted_secret = encryptor.encrypt(patched['secret'])

    # Validate patched data against WebhookUpdate model
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
        'notification_path': data.notification_path,
        'secret': encrypted_secret,
    }
    set_clause = _set_clause('w', props)

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
    rules_tpl, rules_params = _rules_template(rule_dicts)
    unwind = _rule_unwind(rules_tpl)

    if data.third_party_service_slug:
        query: str = (
            'MATCH (w:Webhook {{slug: {old_slug}}})'
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
            f' {set_clause}'
            ' CREATE (w)-[impl:IMPLEMENTED_BY]->(tps)'
            ' SET impl.identifier_selector'
            ' = {identifier_selector}'
            ' WITH w, tps, impl' + unwind + _RULE_RETURN_TPS
        )
        params: dict[str, typing.Any] = {
            'old_slug': slug,
            'org_slug': org_slug,
            'tps_slug': data.third_party_service_slug,
            **props,
            'identifier_selector': data.identifier_selector,
            **rules_params,
        }
    else:
        query = (
            'MATCH (w:Webhook {{slug: {old_slug}}})'
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
            f' {set_clause}'
            ' WITH w' + unwind + _RULE_RETURN_NO_TPS
        )
        params = {
            'old_slug': slug,
            'org_slug': org_slug,
            **props,
            **rules_params,
        }

    try:
        records = await db.execute(
            query,
            params,
            ['webhook', 'tps', 'identifier_selector', 'rules'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Webhook with slug {data.slug!r} '
                f'or notification_path '
                f'{data.notification_path!r} already exists'
            ),
        ) from e

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Webhook with slug {slug!r} not found',
        )

    return models.WebhookResponse.from_graph_record(records[0])


@webhooks_router.delete('/{slug}', status_code=204)
async def delete_webhook(
    org_slug: str,
    slug: str,
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
    MATCH (w:Webhook {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
    DETACH DELETE r, w
    RETURN count(w) AS deleted
    """
    records = await db.execute(
        query,
        {'slug': slug, 'org_slug': org_slug},
        ['deleted'],
    )

    deleted = graph.parse_agtype(records[0]['deleted']) if records else 0
    if not records or deleted == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Webhook with slug {slug!r} not found',
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
