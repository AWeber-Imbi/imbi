"""Third-party service management endpoints."""

import json
import logging
import typing

import fastapi
import psycopg
from imbi_common import graph
from imbi_common.auth import encryption

from imbi_api.auth import permissions
from imbi_api.domain import models

LOGGER = logging.getLogger(__name__)


_SERVICE_JSON_FIELDS: dict[str, list[str] | dict[str, typing.Any]] = {
    'links': {},
    'identifiers': {},
}
_APP_JSON_FIELDS: dict[str, list[str] | dict[str, typing.Any]] = {
    'scopes': [],
    'settings': {},
}


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

    Returns a string like ``SET s.name = {name}, s.slug = {slug}``.

    """
    if not props:
        return ''
    assignments = ', '.join(f'{alias}.{k} = {{{k}}}' for k in props)
    return f'SET {assignments}'


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
    create_tpl = _props_template(graph_props)

    if data.team_slug:
        query: str = (
            'MATCH (o:Organization {{slug: {org_slug}}})'
            ' MATCH (t:Team {{slug: {team_slug}}})'
            '-[:BELONGS_TO]->(o)'
            f' CREATE (s:ThirdPartyService {create_tpl})'
            ' CREATE (s)-[:BELONGS_TO]->(o)'
            ' CREATE (s)-[:MANAGED_BY]->(t)'
            ' RETURN s{{.*, organization: o{{.*}},'
            ' team: t{{.*}}}} AS service'
        )
        params: dict[str, typing.Any] = {
            'org_slug': org_slug,
            'team_slug': data.team_slug,
            **graph_props,
        }
    else:
        query = (
            'MATCH (o:Organization {{slug: {org_slug}}})'
            f' CREATE (s:ThirdPartyService {create_tpl})'
            ' CREATE (s)-[:BELONGS_TO]->(o)'
            ' RETURN s{{.*, organization: o{{.*}},'
            ' team: null}} AS service'
        )
        params = {
            'org_slug': org_slug,
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


@third_party_services_router.put('/{slug}')
async def update_third_party_service(
    org_slug: str,
    slug: str,
    data: models.ThirdPartyServiceUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission(
                'third_party_service:update',
            ),
        ),
    ],
) -> models.ThirdPartyServiceResponse:
    """Update a third-party service.

    Parameters:
        slug: Service slug from URL.
        data: Updated service data.

    Returns:
        The updated service.

    Raises:
        404: Service not found
        409: Slug conflict

    """
    # Fetch existing to validate it exists
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
    set_clause = _set_clause('s', graph_props)

    if data.team_slug:
        update_query: str = (
            'MATCH (s:ThirdPartyService {{slug: {cur_slug}}})'
            ' -[:BELONGS_TO]->(o:Organization'
            ' {{slug: {org_slug}}})'
            ' MATCH (t:Team {{slug: {team_slug}}})'
            '-[:BELONGS_TO]->(o)'
            ' OPTIONAL MATCH (s)-[old_mgr:MANAGED_BY]->()'
            ' DELETE old_mgr'
            ' WITH s, o, t'
            f' {set_clause}'
            ' CREATE (s)-[:MANAGED_BY]->(t)'
            ' RETURN s{{.*, organization: o{{.*}},'
            ' team: t{{.*}}}} AS service'
        )
        update_params: dict[str, typing.Any] = {
            'cur_slug': slug,
            'org_slug': org_slug,
            'team_slug': data.team_slug,
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
            f' {set_clause}'
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
    With w, tps, impl,
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
    app_tpl = _props_template(graph_props)

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


@third_party_services_router.put(
    '/{slug}/applications/{app_slug}',
)
async def update_service_application(
    org_slug: str,
    slug: str,
    app_slug: str,
    data: models.ServiceApplicationUpdate,
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
    """Update non-secret application fields.

    Secret fields cannot be updated via this endpoint. Use
    ``PUT /secrets`` instead.
    """
    existing = await _fetch_application(db, org_slug, slug, app_slug)
    props = data.model_dump(mode='json')

    # Preserve existing secret values unchanged
    for field in models.SECRET_FIELDS:
        props[field] = existing.get(field)

    graph_props = _serialize_json_fields(props, _APP_JSON_FIELDS)
    app_set = _set_clause('a', graph_props)

    update_query: str = (
        'MATCH (a:ServiceApplication {{slug: {cur_app_slug}}})'
        ' -[:REGISTERED_IN]->(s:ThirdPartyService'
        ' {{slug: {svc_slug}}})'
        ' -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})'
        f' {app_set}'
        ' RETURN a{{.*}} AS app'
    )
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


@third_party_services_router.put(
    '/{slug}/applications/{app_slug}/secrets',
)
async def update_application_secrets(
    org_slug: str,
    slug: str,
    app_slug: str,
    data: models.ServiceApplicationSecretsUpdate,
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
    """Update one or more application secrets.

    Only provided (non-null) fields are updated. Requires admin
    privileges.
    """
    if not auth.is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail=('Admin privileges required to update secrets'),
        )

    existing = await _fetch_application(db, org_slug, slug, app_slug)
    encryptor = encryption.TokenEncryption.get_instance()

    # Build updated secret values: encrypt new, keep existing
    secret_params: dict[str, typing.Any] = {}
    for field in models.SECRET_FIELDS:
        new_val = getattr(data, field)
        if new_val is not None:
            secret_params[field] = encryptor.encrypt(new_val)
        else:
            secret_params[field] = existing.get(field)

    update_query: typing.LiteralString = """
    MATCH (a:ServiceApplication {{slug: {app_slug}}})
          -[:REGISTERED_IN]->(s:ThirdPartyService
                              {{slug: {svc_slug}}})
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    SET a.client_secret = {client_secret},
        a.webhook_secret = {webhook_secret},
        a.private_key = {private_key},
        a.signing_secret = {signing_secret}
    RETURN a{{.*}} AS app
    """
    records = await db.execute(
        update_query,
        {
            'app_slug': app_slug,
            'svc_slug': slug,
            'org_slug': org_slug,
            **secret_params,
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
