"""Webhook management endpoints."""

import json
import logging
import typing

import fastapi
from imbi_common import neo4j
from imbi_common.auth import encryption
from neo4j import exceptions

from imbi_api.auth import permissions
from imbi_api.domain import models

LOGGER = logging.getLogger(__name__)

webhooks_router = fastapi.APIRouter(tags=['Webhooks'])


@webhooks_router.post('/', status_code=201)
async def create_webhook(
    org_slug: str,
    data: models.WebhookCreate,
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

    # Build rule creation clauses
    rule_params: list[dict[str, object]] = []
    for idx, rule in enumerate(data.rules):
        rule_params.append(
            {
                'filter_expression': rule.filter_expression,
                'handler': rule.handler,
                'handler_config': json.dumps(rule.handler_config),
                'ordinal': idx,
            }
        )

    if data.third_party_service_slug:
        query: typing.LiteralString = """
        MATCH (o:Organization {slug: $org_slug})
        MATCH (tps:ThirdPartyService {slug: $tps_slug})
              -[:BELONGS_TO]->(o)
        CREATE (w:Webhook $props)
        CREATE (w)-[:BELONGS_TO]->(o)
        CREATE (w)-[impl:IMPLEMENTED_BY]->(tps)
        SET impl.identifier_selector = $identifier_selector
        WITH w, tps, o, impl
        UNWIND
            CASE WHEN size($rules) = 0 THEN [null]
                 ELSE $rules END AS rule_data
        FOREACH (_ IN CASE WHEN rule_data IS NOT NULL
                           THEN [1] ELSE [] END |
            CREATE (r:WebhookRule {
                filter_expression: rule_data.filter_expression,
                handler: rule_data.handler,
                handler_config: rule_data.handler_config,
                ordinal: rule_data.ordinal
            })
            CREATE (r)-[:ACTIONS]->(w)
        )
        WITH DISTINCT w, tps, impl
        OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
        WITH w, tps, impl, r
        ORDER BY r.ordinal
        WITH w, tps, impl,
             collect(r{
                .filter_expression, .handler,
                .handler_config, .ordinal})
                AS rules
        RETURN w{.*} AS webhook,
               tps{.*} AS tps,
               impl.identifier_selector AS identifier_selector,
               [x IN rules | x {.filter_expression, .handler, .handler_config}]
                   AS rules
        """
        params: dict[str, typing.Any] = {
            'org_slug': org_slug,
            'tps_slug': data.third_party_service_slug,
            'props': props,
            'identifier_selector': data.identifier_selector,
            'rules': rule_params,
        }
    else:
        query = """
        MATCH (o:Organization {slug: $org_slug})
        CREATE (w:Webhook $props)
        CREATE (w)-[:BELONGS_TO]->(o)
        WITH w, o
        UNWIND
            CASE WHEN size($rules) = 0 THEN [null]
                 ELSE $rules END AS rule_data
        FOREACH (_ IN CASE WHEN rule_data IS NOT NULL
                           THEN [1] ELSE [] END |
            CREATE (r:WebhookRule {
                filter_expression: rule_data.filter_expression,
                handler: rule_data.handler,
                handler_config: rule_data.handler_config,
                ordinal: rule_data.ordinal
            })
            CREATE (r)-[:ACTIONS]->(w)
        )
        WITH DISTINCT w
        OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
        WITH w, r
        ORDER BY r.ordinal
        WITH w,
             collect(r{
                .filter_expression, .handler,
                .handler_config, .ordinal})
                AS rules
        RETURN w{.*} AS webhook,
               null AS tps,
               null AS identifier_selector,
               [x IN rules | x {.filter_expression, .handler, .handler_config}]
                   AS rules
        """
        params = {
            'org_slug': org_slug,
            'props': props,
            'rules': rule_params,
        }

    try:
        async with neo4j.run(query, **params) as result:
            records = await result.data()
    except exceptions.ConstraintError as e:
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

    return models.WebhookResponse.from_neo4j_record(records[0])


@webhooks_router.get('/')
async def list_webhooks(
    org_slug: str,
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
          (o:Organization {slug: $org_slug})
    OPTIONAL MATCH (w)-[impl:IMPLEMENTED_BY]->(tps:ThirdPartyService)
    OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
    WITH w, tps, impl, r
    ORDER BY r.ordinal
    WITH w, tps, impl,
         collect(r{
                .filter_expression, .handler,
                .handler_config, .ordinal})
            AS all_rules
    RETURN w{.*} AS webhook,
           tps{.*} AS tps,
           impl.identifier_selector AS identifier_selector,
           [x IN all_rules | x {.filter_expression, .handler, .handler_config}]
               AS rules
    ORDER BY w.name
    """
    async with neo4j.run(query, org_slug=org_slug) as result:
        records = await result.data()
    return [models.WebhookResponse.from_neo4j_record(r) for r in records]


@webhooks_router.get('/{slug}')
async def get_webhook(
    org_slug: str,
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('webhook:read'),
        ),
    ],
) -> models.WebhookResponse:
    """Get a webhook by slug."""
    query: typing.LiteralString = """
    MATCH (w:Webhook {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    OPTIONAL MATCH (w)-[impl:IMPLEMENTED_BY]->(tps:ThirdPartyService)
    OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
    WITH w, tps, impl, r
    ORDER BY r.ordinal
    WITH w, tps, impl,
         collect(r{
                .filter_expression, .handler,
                .handler_config, .ordinal})
            AS all_rules
    RETURN w{.*} AS webhook,
           tps{.*} AS tps,
           impl.identifier_selector AS identifier_selector,
           [x IN all_rules | x {.filter_expression, .handler, .handler_config}]
               AS rules
    """
    async with neo4j.run(
        query,
        slug=slug,
        org_slug=org_slug,
    ) as result:
        records = await result.data()

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Webhook with slug {slug!r} not found',
        )
    return models.WebhookResponse.from_neo4j_record(records[0])


@webhooks_router.put('/{slug}')
async def update_webhook(
    org_slug: str,
    slug: str,
    data: models.WebhookUpdate,
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
    MATCH (w:Webhook {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    RETURN w{.*} AS webhook
    """
    async with neo4j.run(
        check_query,
        slug=slug,
        org_slug=org_slug,
    ) as result:
        existing = await result.data()

    if not existing:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Webhook with slug {slug!r} not found',
        )

    encryptor = encryption.TokenEncryption.get_instance()

    # Distinguish omitted secret (preserve existing) from explicit
    # null (clear) or a new value (encrypt and store).
    existing_webhook = existing[0]['webhook']
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

    rule_params: list[dict[str, str | int]] = []
    for idx, rule in enumerate(data.rules):
        rule_params.append(
            {
                'filter_expression': rule.filter_expression,
                'handler': rule.handler,
                'handler_config': json.dumps(rule.handler_config),
                'ordinal': idx,
            }
        )

    # Delete old rules and IMPLEMENTED_BY, then recreate
    if data.third_party_service_slug:
        query: typing.LiteralString = """
        MATCH (w:Webhook {slug: $old_slug})
              -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
        MATCH (tps:ThirdPartyService {slug: $tps_slug})
              -[:BELONGS_TO]->(o)
        OPTIONAL MATCH (old_r:WebhookRule)-[:ACTIONS]->(w)
        DETACH DELETE old_r
        WITH DISTINCT w, o, tps
        OPTIONAL MATCH (w)-[old_impl:IMPLEMENTED_BY]->()
        DELETE old_impl
        WITH DISTINCT w, o, tps
        SET w = $props
        CREATE (w)-[impl:IMPLEMENTED_BY]->(tps)
        SET impl.identifier_selector = $identifier_selector
        WITH w, tps, impl
        UNWIND
            CASE WHEN size($rules) = 0 THEN [null]
                 ELSE $rules END AS rule_data
        FOREACH (_ IN CASE WHEN rule_data IS NOT NULL
                           THEN [1] ELSE [] END |
            CREATE (r:WebhookRule {
                filter_expression: rule_data.filter_expression,
                handler: rule_data.handler,
                handler_config: rule_data.handler_config,
                ordinal: rule_data.ordinal
            })
            CREATE (r)-[:ACTIONS]->(w)
        )
        WITH DISTINCT w, tps, impl
        OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
        WITH w, tps, impl, r
        ORDER BY r.ordinal
        WITH w, tps, impl,
             collect(r{
                .filter_expression, .handler,
                .handler_config, .ordinal})
                AS rules
        RETURN w{.*} AS webhook,
               tps{.*} AS tps,
               impl.identifier_selector AS identifier_selector,
               [x IN rules | x {.filter_expression, .handler, .handler_config}]
                   AS rules
        """
        params: dict[str, typing.Any] = {
            'old_slug': slug,
            'org_slug': org_slug,
            'tps_slug': data.third_party_service_slug,
            'props': props,
            'identifier_selector': data.identifier_selector,
            'rules': rule_params,
        }
    else:
        query = """
        MATCH (w:Webhook {slug: $old_slug})
              -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
        OPTIONAL MATCH (old_r:WebhookRule)-[:ACTIONS]->(w)
        DETACH DELETE old_r
        WITH DISTINCT w, o
        OPTIONAL MATCH (w)-[old_impl:IMPLEMENTED_BY]->()
        DELETE old_impl
        WITH DISTINCT w
        SET w = $props
        WITH w
        UNWIND
            CASE WHEN size($rules) = 0 THEN [null]
                 ELSE $rules END AS rule_data
        FOREACH (_ IN CASE WHEN rule_data IS NOT NULL
                           THEN [1] ELSE [] END |
            CREATE (r:WebhookRule {
                filter_expression: rule_data.filter_expression,
                handler: rule_data.handler,
                handler_config: rule_data.handler_config,
                ordinal: rule_data.ordinal
            })
            CREATE (r)-[:ACTIONS]->(w)
        )
        WITH DISTINCT w
        OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
        WITH w, r
        ORDER BY r.ordinal
        WITH w,
             collect(r{
                .filter_expression, .handler,
                .handler_config, .ordinal})
                AS rules
        RETURN w{.*} AS webhook,
               null AS tps,
               null AS identifier_selector,
               [x IN rules | x {.filter_expression, .handler, .handler_config}]
                   AS rules
        """
        params = {
            'old_slug': slug,
            'org_slug': org_slug,
            'props': props,
            'rules': rule_params,
        }

    try:
        async with neo4j.run(query, **params) as result:
            records = await result.data()
    except exceptions.ConstraintError as e:
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

    return models.WebhookResponse.from_neo4j_record(records[0])


@webhooks_router.delete('/{slug}', status_code=204)
async def delete_webhook(
    org_slug: str,
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('webhook:delete'),
        ),
    ],
) -> None:
    """Delete a webhook and its rules."""
    query: typing.LiteralString = """
    MATCH (w:Webhook {slug: $slug})
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    OPTIONAL MATCH (r:WebhookRule)-[:ACTIONS]->(w)
    DETACH DELETE r, w
    RETURN count(w) AS deleted
    """
    async with neo4j.run(
        query,
        slug=slug,
        org_slug=org_slug,
    ) as result:
        records = await result.data()

    if not records or records[0]['deleted'] == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Webhook with slug {slug!r} not found',
        )


# -- Project EXISTS_IN endpoints -------------------------------------------


project_services_router = fastapi.APIRouter(
    tags=['Project Services'],
)


@project_services_router.get('/')
async def list_project_services(
    org_slug: str,
    project_id: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
) -> list[models.ExistsInResponse]:
    """List third-party services this project exists in."""
    query: typing.LiteralString = """
    MATCH (p:Project {id: $project_id})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    MATCH (p)-[ei:EXISTS_IN]->(tps:ThirdPartyService)
    RETURN tps.slug AS service_slug,
           tps.name AS service_name,
           ei.identifier AS identifier,
           ei.canonical_link AS canonical_link
    ORDER BY tps.name
    """
    async with neo4j.run(
        query,
        org_slug=org_slug,
        project_id=project_id,
    ) as result:
        records = await result.data()

    return [
        models.ExistsInResponse(
            third_party_service_slug=r['service_slug'],
            third_party_service_name=r['service_name'],
            identifier=r['identifier'],
            canonical_link=r.get('canonical_link'),
        )
        for r in records
    ]


@project_services_router.post('/', status_code=201)
async def create_project_service(
    org_slug: str,
    project_id: str,
    data: models.ExistsInCreate,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> models.ExistsInResponse:
    """Add an EXISTS_IN link between a project and a service."""
    query: typing.LiteralString = """
    MATCH (p:Project {id: $project_id})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    MATCH (tps:ThirdPartyService {slug: $tps_slug})
          -[:BELONGS_TO]->(o)
    MERGE (p)-[ei:EXISTS_IN]->(tps)
    SET ei.identifier = $identifier,
        ei.canonical_link = $canonical_link
    RETURN tps.slug AS service_slug,
           tps.name AS service_name,
           ei.identifier AS identifier,
           ei.canonical_link AS canonical_link
    """
    async with neo4j.run(
        query,
        org_slug=org_slug,
        project_id=project_id,
        tps_slug=data.third_party_service_slug,
        identifier=data.identifier,
        canonical_link=data.canonical_link,
    ) as result:
        records = await result.data()

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
        third_party_service_slug=r['service_slug'],
        third_party_service_name=r['service_name'],
        identifier=r['identifier'],
        canonical_link=r.get('canonical_link'),
    )


@project_services_router.delete(
    '/{service_slug}',
    status_code=204,
)
async def delete_project_service(
    org_slug: str,
    project_id: str,
    service_slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:write'),
        ),
    ],
) -> None:
    """Remove an EXISTS_IN link."""
    query: typing.LiteralString = """
    MATCH (p:Project {id: $project_id})
          -[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {slug: $org_slug})
    MATCH (p)-[ei:EXISTS_IN]->
          (tps:ThirdPartyService {slug: $tps_slug})
    DELETE ei
    RETURN count(ei) AS deleted
    """
    async with neo4j.run(
        query,
        org_slug=org_slug,
        project_id=project_id,
        tps_slug=service_slug,
    ) as result:
        records = await result.data()

    if not records or records[0]['deleted'] == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'EXISTS_IN link between project '
                f'{project_id!r} and service '
                f'{service_slug!r} not found'
            ),
        )
