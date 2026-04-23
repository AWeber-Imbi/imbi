"""Third-party service management endpoints."""

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
from imbi_api.graph_sql import props_template, set_clause

LOGGER = logging.getLogger(__name__)


_SERVICE_JSON_FIELDS: dict[str, list[str] | dict[str, typing.Any]] = {
    'links': {},
    'identifiers': {},
}
_APP_JSON_FIELDS: dict[str, list[str] | dict[str, typing.Any]] = {
    'scopes': [],
    'settings': {},
}


def _build_service_response(
    record: dict[str, typing.Any],
) -> models.ThirdPartyServiceResponse:
    """Build a ThirdPartyServiceResponse from a graph record."""
    service = graph.parse_agtype(record['service'])
    service = _deserialize_json_fields(service, _SERVICE_JSON_FIELDS)
    return models.ThirdPartyServiceResponse(**service)


def _serialize_json_fields(
    props: dict[str, typing.Any],
    fields: dict[str, list[str] | dict[str, typing.Any]],
) -> dict[str, typing.Any]:
    """Serialize list/dict fields to JSON strings for graph."""
    result = dict(props)
    for key in fields:
        if key in result and not isinstance(result[key], str):
            result[key] = json.dumps(result[key])
    return result


def _deserialize_json_fields(
    record: dict[str, typing.Any],
    fields: dict[str, list[str] | dict[str, typing.Any]],
) -> dict[str, typing.Any]:
    """Deserialize JSON string fields back to Python objects."""
    obj = dict(record)
    for key, default in fields.items():
        val = obj.get(key)
        if isinstance(val, str):
            try:
                obj[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                obj[key] = default
        elif val is None:
            obj[key] = default
    return obj


def _strip_secrets(
    app: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Remove secret fields from an application dict."""
    for field in models.SECRET_FIELDS:
        app.pop(field, None)
    return app


def _build_secrets_response(
    app: dict[str, typing.Any],
    encryptor: encryption.TokenEncryption,
) -> models.ServiceApplicationSecrets:
    """Decrypt secret fields and build a secrets response."""
    client_secret = encryptor.decrypt(app['client_secret'])
    if client_secret is None:
        msg = 'Decryption failed for client_secret'
        raise ValueError(msg)
    return models.ServiceApplicationSecrets(
        client_secret=client_secret,
        webhook_secret=(
            encryptor.decrypt(app['webhook_secret'])
            if app.get('webhook_secret') is not None
            else None
        ),
        private_key=(
            encryptor.decrypt(app['private_key'])
            if app.get('private_key') is not None
            else None
        ),
        signing_secret=(
            encryptor.decrypt(app['signing_secret'])
            if app.get('signing_secret') is not None
            else None
        ),
    )


third_party_services_router = fastapi.APIRouter(
    tags=['Third-Party Services'],
)


@third_party_services_router.post('/', status_code=201)
async def create_third_party_service(
    org_slug: str,
    data: models.ThirdPartyServiceCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'third_party_service:create',
            ),
        ),
    ],
) -> models.ThirdPartyServiceResponse:
    """Create a new third-party service linked to an organization.

    Returns:
        The created third-party service.

    Raises:
        404: Organization or team not found
        409: Service with slug already exists

    """
    props = {
        'name': data.name,
        'slug': data.slug,
        'description': data.description,
        'icon': data.icon,
        'vendor': data.vendor,
        'service_url': (str(data.service_url) if data.service_url else None),
        'category': data.category,
        'status': data.status,
        'links': data.links,
        'identifiers': data.identifiers,
    }

    graph_props = _serialize_json_fields(props, _SERVICE_JSON_FIELDS)
    create_tpl = props_template(graph_props)

    query: str = (
        'MATCH (o:Organization {{slug: {org_slug}}})'
        ' OPTIONAL MATCH (t:Team {{slug: {team_slug}}})'
        '-[:BELONGS_TO]->(o)'
        ' WITH o, t'
        ' WHERE {team_slug} IS NULL OR t IS NOT NULL'
        f' CREATE (s:ThirdPartyService {create_tpl})'
        ' CREATE (s)-[:BELONGS_TO]->(o)'
        ' FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END |'
        ' CREATE (s)-[:MANAGED_BY]->(t))'
        ' RETURN s{{.*, organization: o{{.*}},'
        ' team: t{{.*}}}} AS service'
    )
    params: dict[str, typing.Any] = {
        'org_slug': org_slug,
        'team_slug': data.team_slug,
        **graph_props,
    }

    try:
        records = await db.execute(
            query,
            params,
            ['service'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Third-party service with slug {data.slug!r} already exists'
            ),
        ) from e

    if not records:
        if data.team_slug:
            raise fastapi.HTTPException(
                status_code=404,
                detail=(
                    f'Organization {org_slug!r} '
                    f'or team {data.team_slug!r} not found'
                ),
            )
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Organization with slug {org_slug!r} not found'),
        )

    return _build_service_response(records[0])


@third_party_services_router.get('/')
async def list_third_party_services(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'third_party_service:read',
            ),
        ),
    ],
) -> list[models.ThirdPartyServiceResponse]:
    """List third-party services for an organization.

    Returns:
        Services ordered by name, each including their
        organization and optional team.

    """
    query: typing.LiteralString = """
    MATCH (s:ThirdPartyService)-[:BELONGS_TO]->
          (o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (s)-[:MANAGED_BY]->(t:Team)
    RETURN s{{.*, organization: o{{.*}}, team: t{{.*}}}}
        AS service
    ORDER BY s.name
    """
    records = await db.execute(
        query,
        {'org_slug': org_slug},
        ['service'],
    )
    return [_build_service_response(record) for record in records]


@third_party_services_router.get('/{slug}')
async def get_third_party_service(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'third_party_service:read',
            ),
        ),
    ],
) -> models.ThirdPartyServiceResponse:
    """Get a third-party service by slug.

    Parameters:
        slug: Service slug identifier.

    Returns:
        Service with organization and optional team.

    Raises:
        404: Service not found

    """
    query: typing.LiteralString = """
    MATCH (s:ThirdPartyService {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (s)-[:MANAGED_BY]->(t:Team)
    RETURN s{{.*, organization: o{{.*}}, team: t{{.*}}}}
        AS service
    """
    records = await db.execute(
        query,
        {'slug': slug, 'org_slug': org_slug},
        ['service'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Third-party service with slug {slug!r} not found'),
        )
    return _build_service_response(records[0])


@third_party_services_router.patch('/{slug}')
async def patch_third_party_service(
    org_slug: str,
    slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('third_party_service:update'),
        ),
    ],
) -> models.ThirdPartyServiceResponse:
    """Partially update a third-party service using JSON Patch (RFC 6902).

    Parameters:
        org_slug: Organization slug from URL path.
        slug: Third-party service slug from URL.
        operations: JSON Patch operations.

    Returns:
        The updated third-party service.

    Raises:
        400: Invalid patch or read-only path.
        404: Service not found.
        409: Slug conflict.
        422: Patch test failed or validation error.

    """
    fetch_query: typing.LiteralString = """
    MATCH (s:ThirdPartyService {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (s)-[:MANAGED_BY]->(t:Team)
    RETURN s{{.*, organization: o{{.*}}, team: t{{.*}}}}
        AS service
    """
    records = await db.execute(
        fetch_query,
        {'slug': slug, 'org_slug': org_slug},
        ['service'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Third-party service with slug {slug!r} not found'),
        )

    service = graph.parse_agtype(records[0]['service'])
    service = _deserialize_json_fields(service, _SERVICE_JSON_FIELDS)

    team = service.get('team')
    patchable: dict[str, typing.Any] = {
        'name': service.get('name'),
        'slug': service.get('slug'),
        'vendor': service.get('vendor'),
        'description': service.get('description'),
        'icon': service.get('icon'),
        'service_url': service.get('service_url'),
        'category': service.get('category'),
        'status': service.get('status', 'active'),
        'links': service.get('links', {}),
        'identifiers': service.get('identifiers', {}),
        'team_slug': (team.get('slug') if team else None),
    }

    patched = json_patch.apply_patch(patchable, operations)

    try:
        data = models.ThirdPartyServiceUpdate(**patched)
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    return await _execute_service_update(slug, org_slug, data, db)


@third_party_services_router.delete('/{slug}', status_code=204)
async def delete_third_party_service(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'third_party_service:delete',
            ),
        ),
    ],
) -> None:
    """Delete a third-party service.

    Parameters:
        slug: Service slug to delete.

    Raises:
        404: Service not found

    """
    query: typing.LiteralString = """
    MATCH (s:ThirdPartyService {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    OPTIONAL MATCH (a:ServiceApplication)
                   -[:REGISTERED_IN]->(s)
    DETACH DELETE a, s
    RETURN count(s) AS deleted
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
            detail=(f'Third-party service with slug {slug!r} not found'),
        )


# --- Service Webhook endpoints ---


@third_party_services_router.get(
    '/{slug}/webhooks/',
)
async def list_service_webhooks(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('webhook:read'),
        ),
    ],
) -> list[models.WebhookResponse]:
    """List webhooks linked to a third-party service."""
    query: typing.LiteralString = """
    MATCH (w:Webhook)-[impl:IMPLEMENTED_BY]->
          (tps:ThirdPartyService {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    MATCH (w)-[:BELONGS_TO]->(o)
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
        {'slug': slug, 'org_slug': org_slug},
        ['webhook', 'tps', 'identifier_selector', 'rules'],
    )
    return [models.WebhookResponse.from_graph_record(r) for r in records]


# --- Service Application endpoints ---


@third_party_services_router.get(
    '/{slug}/applications/',
)
async def list_service_applications(
    org_slug: str,
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'third_party_service:read',
            ),
        ),
    ],
) -> list[models.ServiceApplicationResponse]:
    """List applications registered in a third-party service."""
    query: typing.LiteralString = """
    MATCH (a:ServiceApplication)-[:REGISTERED_IN]->
          (s:ThirdPartyService {{slug: {slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN a{{.*}} AS app
    ORDER BY a.name
    """
    records = await db.execute(
        query,
        {'slug': slug, 'org_slug': org_slug},
        ['app'],
    )

    apps: list[models.ServiceApplicationResponse] = []
    for record in records:
        app = graph.parse_agtype(record['app'])
        app = _deserialize_json_fields(app, _APP_JSON_FIELDS)
        _strip_secrets(app)
        apps.append(models.ServiceApplicationResponse(**app))
    return apps


@third_party_services_router.post(
    '/{slug}/applications/',
    status_code=201,
)
async def create_service_application(
    org_slug: str,
    slug: str,
    data: models.ServiceApplicationCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'third_party_service:update',
            ),
        ),
    ],
) -> models.ServiceApplicationResponse:
    """Create an application under a third-party service."""
    # Check uniqueness of app slug within this service
    check_query: typing.LiteralString = """
    MATCH (a:ServiceApplication {{slug: {app_slug}}})
          -[:REGISTERED_IN]->(s:ThirdPartyService
                              {{slug: {svc_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN count(a) AS cnt
    """
    check_records = await db.execute(
        check_query,
        {
            'app_slug': data.slug,
            'svc_slug': slug,
            'org_slug': org_slug,
        },
        ['cnt'],
    )

    if check_records and graph.parse_agtype(check_records[0]['cnt']) > 0:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Application {data.slug!r} already exists in service {slug!r}'
            ),
        )

    # Encrypt secrets
    encryptor = encryption.TokenEncryption.get_instance()
    props = data.model_dump(mode='json')
    props['client_secret'] = encryptor.encrypt(data.client_secret)
    if props.get('webhook_secret') is not None:
        props['webhook_secret'] = encryptor.encrypt(
            props['webhook_secret'],
        )
    if props.get('private_key') is not None:
        props['private_key'] = encryptor.encrypt(props['private_key'])
    if props.get('signing_secret') is not None:
        props['signing_secret'] = encryptor.encrypt(
            props['signing_secret'],
        )

    graph_props = _serialize_json_fields(props, _APP_JSON_FIELDS)
    app_tpl = props_template(graph_props)

    create_query: str = (
        'MATCH (s:ThirdPartyService {{slug: {svc_slug}}})'
        ' -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})'
        f' CREATE (a:ServiceApplication {app_tpl})'
        ' CREATE (a)-[:REGISTERED_IN]->(s)'
        ' RETURN a{{.*}} AS app'
    )
    records = await db.execute(
        create_query,
        {
            'svc_slug': slug,
            'org_slug': org_slug,
            **graph_props,
        },
        ['app'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Third-party service with slug {slug!r} not found'),
        )

    app = graph.parse_agtype(records[0]['app'])
    app = _deserialize_json_fields(app, _APP_JSON_FIELDS)
    _strip_secrets(app)
    return models.ServiceApplicationResponse(**app)


async def _execute_service_update(
    slug: str,
    org_slug: str,
    update_data: models.ThirdPartyServiceUpdate,
    db: graph.Graph,
) -> models.ThirdPartyServiceResponse:
    """Run the team/no-team Cypher update for a third-party service.

    Parameters:
        slug: The current slug to match on.
        org_slug: The organization slug.
        update_data: Validated update payload.
        db: Graph pool connection.

    Returns:
        The updated service response.

    Raises:
        409: Slug conflict.
        404: Service not found.

    """
    props = {
        'name': update_data.name,
        'slug': update_data.slug,
        'description': update_data.description,
        'icon': update_data.icon,
        'vendor': update_data.vendor,
        'service_url': (
            str(update_data.service_url) if update_data.service_url else None
        ),
        'category': update_data.category,
        'status': update_data.status,
        'links': update_data.links,
        'identifiers': update_data.identifiers,
    }

    graph_props = _serialize_json_fields(props, _SERVICE_JSON_FIELDS)
    set_stmt = set_clause('s', graph_props)

    if update_data.team_slug:
        update_query: str = (
            'MATCH (s:ThirdPartyService {{slug: {cur_slug}}})'
            ' -[:BELONGS_TO]->(o:Organization'
            ' {{slug: {org_slug}}})'
            ' MATCH (t:Team {{slug: {team_slug}}})'
            '-[:BELONGS_TO]->(o)'
            ' OPTIONAL MATCH (s)-[old_mgr:MANAGED_BY]->()'
            ' DELETE old_mgr'
            ' WITH s, o, t'
            f' {set_stmt}'
            ' CREATE (s)-[:MANAGED_BY]->(t)'
            ' RETURN s{{.*, organization: o{{.*}},'
            ' team: t{{.*}}}} AS service'
        )
        update_params: dict[str, typing.Any] = {
            'cur_slug': slug,
            'org_slug': org_slug,
            'team_slug': update_data.team_slug,
            **graph_props,
        }
    else:
        update_query = (
            'MATCH (s:ThirdPartyService {{slug: {cur_slug}}})'
            ' -[:BELONGS_TO]->(o:Organization'
            ' {{slug: {org_slug}}})'
            ' OPTIONAL MATCH (s)-[old_mgr:MANAGED_BY]->()'
            ' DELETE old_mgr'
            ' WITH s, o'
            f' {set_stmt}'
            ' RETURN s{{.*, organization: o{{.*}},'
            ' team: null}} AS service'
        )
        update_params = {
            'cur_slug': slug,
            'org_slug': org_slug,
            **graph_props,
        }

    try:
        updated = await db.execute(
            update_query,
            update_params,
            ['service'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                'Third-party service with slug '
                f'{props["slug"]!r} already exists'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Third-party service with slug {slug!r} not found'),
        )

    return _build_service_response(updated[0])


async def _fetch_application(
    db: graph.Graph,
    org_slug: str,
    svc_slug: str,
    app_slug: str,
) -> dict[str, typing.Any]:
    """Fetch a single application or raise 404."""
    query: typing.LiteralString = """
    MATCH (a:ServiceApplication {{slug: {app_slug}}})
          -[:REGISTERED_IN]->(s:ThirdPartyService
                              {{slug: {svc_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN a{{.*}} AS app
    """
    records = await db.execute(
        query,
        {
            'app_slug': app_slug,
            'svc_slug': svc_slug,
            'org_slug': org_slug,
        },
        ['app'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Application {app_slug!r} not found in service {svc_slug!r}'
            ),
        )
    app = graph.parse_agtype(records[0]['app'])
    return _deserialize_json_fields(app, _APP_JSON_FIELDS)


@third_party_services_router.get(
    '/{slug}/applications/{app_slug}',
)
async def get_service_application(
    org_slug: str,
    slug: str,
    app_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'third_party_service:read',
            ),
        ),
    ],
) -> models.ServiceApplicationResponse:
    """Get a single application by slug.

    Secret fields are not included in the response. Use the
    ``/secrets`` sub-resource to retrieve or update secrets.
    """
    app = await _fetch_application(db, org_slug, slug, app_slug)
    _strip_secrets(app)
    return models.ServiceApplicationResponse(**app)


_APP_SECRET_PATHS: frozenset[str] = frozenset(
    f'/{field}' for field in models.SECRET_FIELDS
)


class _ServiceApplicationPatchFields(pydantic.BaseModel):
    """Internal validator for non-secret application fields."""

    slug: str = pydantic.Field(
        pattern=r'^[a-z][a-z0-9-]*$',
        min_length=2,
        max_length=64,
    )
    name: str = pydantic.Field(min_length=1, max_length=128)
    description: str | None = None
    app_type: str = pydantic.Field(min_length=1, max_length=64)
    application_url: str | None = None
    client_id: str = pydantic.Field(min_length=1)
    scopes: list[str] = pydantic.Field(default_factory=list)
    settings: dict[str, str | int | bool] = pydantic.Field(
        default_factory=dict,
    )
    status: typing.Literal['active', 'inactive', 'revoked'] = 'active'

    model_config = pydantic.ConfigDict(extra='forbid')


@third_party_services_router.patch(
    '/{slug}/applications/{app_slug}',
)
async def patch_service_application(
    org_slug: str,
    slug: str,
    app_slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'third_party_service:update',
            ),
        ),
    ],
) -> models.ServiceApplicationResponse:
    """Partially update non-secret application fields via JSON Patch.

    Secret fields (``client_secret``, ``webhook_secret``, ``private_key``,
    ``signing_secret``) cannot be modified here — use the ``/secrets``
    sub-resource instead. Attempts to patch them return 400.

    Parameters:
        org_slug: Organization slug from URL.
        slug: Third-party service slug from URL.
        app_slug: Application slug from URL.
        operations: JSON Patch operations.

    Returns:
        The updated application (secrets stripped).

    Raises:
        400: Invalid patch or secret path targeted.
        404: Application not found.
        409: Slug conflict.
        422: Patch test failed or validation error.

    """
    existing = await _fetch_application(db, org_slug, slug, app_slug)

    patchable = {
        k: v for k, v in existing.items() if k not in models.SECRET_FIELDS
    }

    readonly = json_patch.READONLY_PATHS | _APP_SECRET_PATHS
    patched = json_patch.apply_patch(patchable, operations, readonly)

    try:
        validated = _ServiceApplicationPatchFields(**patched)
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    props = validated.model_dump(mode='json')

    graph_props = _serialize_json_fields(props, _APP_JSON_FIELDS)
    app_set = set_clause('a', graph_props)

    update_query: str = (
        'MATCH (a:ServiceApplication {{slug: {cur_app_slug}}})'
        ' -[:REGISTERED_IN]->(s:ThirdPartyService'
        ' {{slug: {svc_slug}}})'
        ' -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})'
        f' {app_set}'
        ' RETURN a{{.*}} AS app'
    )
    try:
        updated = await db.execute(
            update_query,
            {
                'cur_app_slug': app_slug,
                'svc_slug': slug,
                'org_slug': org_slug,
                **graph_props,
            },
            ['app'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Application {props["slug"]!r} already exists'
                f' in service {slug!r}'
            ),
        ) from e

    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Application {app_slug!r} not found in service {slug!r}'),
        )

    app = graph.parse_agtype(updated[0]['app'])
    app = _deserialize_json_fields(app, _APP_JSON_FIELDS)
    _strip_secrets(app)
    return models.ServiceApplicationResponse(**app)


@third_party_services_router.delete(
    '/{slug}/applications/{app_slug}',
    status_code=204,
)
async def delete_service_application(
    org_slug: str,
    slug: str,
    app_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'third_party_service:delete',
            ),
        ),
    ],
) -> None:
    """Delete a service application."""
    query: typing.LiteralString = """
    MATCH (a:ServiceApplication {{slug: {app_slug}}})
          -[:REGISTERED_IN]->(s:ThirdPartyService
                              {{slug: {svc_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    DETACH DELETE a
    RETURN count(a) AS deleted
    """
    records = await db.execute(
        query,
        {
            'app_slug': app_slug,
            'svc_slug': slug,
            'org_slug': org_slug,
        },
        ['deleted'],
    )

    deleted = graph.parse_agtype(records[0]['deleted']) if records else 0
    if not records or deleted == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Application {app_slug!r} not found in service {slug!r}'),
        )


# --- Application Secrets sub-resource ---


@third_party_services_router.get(
    '/{slug}/applications/{app_slug}/secrets',
)
async def get_application_secrets(
    org_slug: str,
    slug: str,
    app_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'third_party_service:read',
            ),
        ),
    ],
) -> models.ServiceApplicationSecrets:
    """Retrieve decrypted application secrets.

    Requires admin privileges.
    """
    if not auth.is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail=('Admin privileges required to access secrets'),
        )

    app = await _fetch_application(db, org_slug, slug, app_slug)
    encryptor = encryption.TokenEncryption.get_instance()
    return _build_secrets_response(app, encryptor)


def _require_secret_field(path: str) -> str:
    """Validate that a JSON Pointer path targets a known secret field.

    Returns the field name. Raises 400 otherwise.
    """
    if not path.startswith('/') or '/' in path[1:]:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Invalid secret path {path!r}',
        )
    field = path[1:]
    if field not in models.SECRET_FIELDS:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Path {path!r} is not a recognized secret field;'
                f' allowed: {sorted(models.SECRET_FIELDS)}'
            ),
        )
    return field


@third_party_services_router.patch(
    '/{slug}/applications/{app_slug}/secrets',
)
async def patch_application_secrets(
    org_slug: str,
    slug: str,
    app_slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'third_party_service:update',
            ),
        ),
    ],
) -> models.ServiceApplicationSecrets:
    """Update application secrets via JSON Patch.

    Each operation's ``value`` is plaintext; the handler encrypts it
    before persisting. Only fields in ``models.SECRET_FIELDS`` are
    addressable. Requires admin privileges.
    """
    if not auth.is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail='Admin privileges required to update secrets',
        )

    existing = await _fetch_application(db, org_slug, slug, app_slug)
    encryptor = encryption.TokenEncryption.get_instance()

    secret_updates: dict[str, str | None] = {}
    for op in operations:
        field = _require_secret_field(op.path)
        if op.op in ('add', 'replace'):
            if not isinstance(op.value, str) or not op.value:
                raise fastapi.HTTPException(
                    status_code=400,
                    detail=(
                        f'Secret {field!r} requires a non-empty string value'
                    ),
                )
            secret_updates[field] = encryptor.encrypt(op.value)
        elif op.op == 'remove':
            if field == 'client_secret':
                raise fastapi.HTTPException(
                    status_code=400,
                    detail='client_secret is required and cannot be removed',
                )
            secret_updates[field] = None
        else:
            raise fastapi.HTTPException(
                status_code=400,
                detail=(
                    f'Operation {op.op!r} is not supported on secrets;'
                    ' use add, replace, or remove'
                ),
            )

    if not secret_updates:
        return _build_secrets_response(existing, encryptor)

    app_set = set_clause('a', secret_updates)
    update_query: str = (
        'MATCH (a:ServiceApplication {{slug: {app_slug}}})'
        ' -[:REGISTERED_IN]->(s:ThirdPartyService'
        ' {{slug: {svc_slug}}})'
        ' -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})'
        f' {app_set}'
        ' RETURN a{{.*}} AS app'
    )
    records = await db.execute(
        update_query,
        {
            'app_slug': app_slug,
            'svc_slug': slug,
            'org_slug': org_slug,
            **secret_updates,
        },
        ['app'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Application {app_slug!r} not found in service {slug!r}'),
        )

    updated_app = graph.parse_agtype(records[0]['app'])
    return _build_secrets_response(updated_app, encryptor)


@third_party_services_router.delete(
    '/{slug}/applications/{app_slug}/secrets/{field}',
    status_code=204,
)
async def delete_application_secret(
    org_slug: str,
    slug: str,
    app_slug: str,
    field: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'third_party_service:update',
            ),
        ),
    ],
) -> None:
    """Clear a single optional application secret. Admin-only.

    ``client_secret`` is required and cannot be cleared via this
    endpoint.
    """
    if not auth.is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail='Admin privileges required to update secrets',
        )

    if field not in models.SECRET_FIELDS:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Field {field!r} is not a recognized secret;'
                f' allowed: {sorted(models.SECRET_FIELDS)}'
            ),
        )
    if field == 'client_secret':
        raise fastapi.HTTPException(
            status_code=400,
            detail='client_secret is required and cannot be cleared',
        )

    await _fetch_application(db, org_slug, slug, app_slug)

    app_set = set_clause('a', {field: None})
    update_query: str = (
        'MATCH (a:ServiceApplication {{slug: {app_slug}}})'
        ' -[:REGISTERED_IN]->(s:ThirdPartyService'
        ' {{slug: {svc_slug}}})'
        ' -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})'
        f' {app_set}'
        ' RETURN a{{.*}} AS app'
    )
    records = await db.execute(
        update_query,
        {
            'app_slug': app_slug,
            'svc_slug': slug,
            'org_slug': org_slug,
            field: None,
        },
        ['app'],
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(f'Application {app_slug!r} not found in service {slug!r}'),
        )
