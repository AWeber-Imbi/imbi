"""Global login-provider (SSO auth provider) management endpoints.

Login providers are org-less Integrations: authentication happens before
any organization context exists, so they are global/system-owned rather
than scoped under ``/organizations/{org_slug}/integrations``. At most one
provider across the whole instance may be flagged ``used_as_login``.

These endpoints operate only on Integrations that carry no ``BELONGS_TO``
organization edge; an org-owned service Integration cannot be read or
mutated through them (it 404s), and vice versa.
"""

import typing

import fastapi
import nanoid

from imbi.api.auth import login_providers as login_repo
from imbi.api.auth import permissions
from imbi.api.domain import models
from imbi.api.endpoints._helpers import conflict_on_unique_violation
from imbi.api.endpoints.integrations import (
    build_response,
    merged_update_props,
    require_login_capable,
)
from imbi.api.graph_sql import props_template, set_clause
from imbi.api.plugins.assignments import hydrate_integration
from imbi.api.plugins.credentials import patch_integration_credentials
from imbi.common import graph
from imbi.common.auth.encryption import TokenEncryption
from imbi.common.plugins.registry import get_plugin

auth_providers_router = fastapi.APIRouter(
    prefix='/login-providers', tags=['Auth Providers']
)

# Org-less Integrations only: OPTIONAL MATCH the organization edge and keep
# rows where it is absent (the anti-join pattern AGE supports).
_LIST_QUERY: typing.LiteralString = """
MATCH (i:Integration)
OPTIONAL MATCH (i)-[:BELONGS_TO]->(o:Organization)
WITH i, o
WHERE o IS NULL
RETURN i{{.*}} AS integration
ORDER BY i.name
"""

_GET_QUERY: typing.LiteralString = """
MATCH (i:Integration {{slug: {slug}}})
OPTIONAL MATCH (i)-[:BELONGS_TO]->(o:Organization)
WITH i, o
WHERE o IS NULL
RETURN i{{.*}} AS integration
LIMIT 1
"""


@auth_providers_router.get('/')
async def list_login_providers(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('integration:read')),
    ],
) -> list[models.IntegrationResponse]:
    """List every global (org-less) login-provider Integration."""
    _ = auth
    records = await db.execute(_LIST_QUERY, {}, ['integration'])
    return [
        build_response(graph.parse_agtype(r['integration'])) for r in records
    ]


@auth_providers_router.post('/', status_code=201)
async def create_login_provider(
    data: models.IntegrationCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('integration:create')),
    ],
) -> models.IntegrationResponse:
    """Create a global login provider (an org-less identity Integration).

    Raises:
        400: The plugin is not installed or does not declare a
            login-capable identity capability.
        409: An Integration with this slug already exists.

    """
    _ = auth
    require_login_capable(data.plugin)
    entry = get_plugin(data.plugin)

    capabilities: dict[str, typing.Any] = {}
    for capability in entry.manifest.capabilities:
        toggle = data.capabilities.get(capability.kind)
        if toggle is not None:
            capabilities[capability.kind] = {
                'enabled': toggle.enabled,
                'options': toggle.options,
            }
        else:
            capabilities[capability.kind] = {
                'enabled': capability.default_enabled,
                'options': {},
            }

    encryptor = TokenEncryption.get_instance()
    # Strip surrounding whitespace (paste artifacts) and drop blanks so a
    # credential is never stored with whitespace that breaks downstream
    # uses (e.g. an HTTP auth header).
    encrypted_credentials = {
        field: encryptor.encrypt(stripped)
        for field, value in data.credentials.items()
        if (stripped := value.strip())
    }

    props: dict[str, typing.Any] = {
        'id': nanoid.generate(),
        'name': data.name,
        'slug': data.slug,
        'description': data.description,
        'icon': data.icon,
        'plugin': data.plugin,
        'vendor': data.vendor,
        'service_url': (str(data.service_url) if data.service_url else None),
        'category': data.category,
        'status': data.status,
        'options': data.options,
        'encrypted_credentials': encrypted_credentials,
        'capabilities': capabilities,
        'links': data.links,
        'identifiers': data.identifiers,
    }
    create_tpl = props_template(props)
    query = (
        f'CREATE (i:Integration {create_tpl})'
        ' RETURN i{{.*}} AS integration'
    )

    with conflict_on_unique_violation(
        f'Integration with slug {data.slug!r} already exists',
    ):
        records = await db.execute(query, props, ['integration'])

    return build_response(graph.parse_agtype(records[0]['integration']))


@auth_providers_router.get('/{slug}')
async def get_login_provider(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('integration:read')),
    ],
) -> models.IntegrationResponse:
    """Get a global login provider by slug.

    Raises:
        404: No org-less Integration with this slug exists.

    """
    _ = auth
    records = await db.execute(_GET_QUERY, {'slug': slug}, ['integration'])
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Login provider with slug {slug!r} not found',
        )
    return build_response(graph.parse_agtype(records[0]['integration']))


@auth_providers_router.patch('/{slug}')
async def update_login_provider(
    slug: str,
    data: models.IntegrationUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('integration:update')),
    ],
) -> models.IntegrationResponse:
    """Partially update a global login provider (options/capabilities/name).

    Raises:
        404: No org-less Integration with this slug exists.

    """
    _ = auth
    records = await db.execute(_GET_QUERY, {'slug': slug}, ['integration'])
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Login provider with slug {slug!r} not found',
        )
    existing = hydrate_integration(
        graph.parse_agtype(records[0]['integration'])
    )
    props = merged_update_props(data, existing)
    if not props:
        return build_response(graph.parse_agtype(records[0]['integration']))

    query = (
        'MATCH (i:Integration {{slug: {slug}}})'
        ' OPTIONAL MATCH (i)-[:BELONGS_TO]->(o:Organization)'
        ' WITH i, o'
        ' WHERE o IS NULL'
        f' {set_clause("i", props)}'
        ' RETURN i{{.*}} AS integration'
    )
    updated = await db.execute(query, {'slug': slug, **props}, ['integration'])
    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Login provider with slug {slug!r} not found',
        )
    return build_response(graph.parse_agtype(updated[0]['integration']))


@auth_providers_router.put('/{slug}/credentials')
async def update_login_provider_credentials(
    slug: str,
    data: models.IntegrationCredentialsUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('integration:update')),
    ],
) -> dict[str, list[str]]:
    """Patch a global login provider's encrypted credentials.

    Raises:
        404: Login provider not found.
        409: Concurrent modification; retry.

    """
    _ = auth
    fields = await patch_integration_credentials(
        db, slug, None, data.credentials
    )
    return {'credential_fields': fields}


_DEMOTE_OTHERS: typing.LiteralString = """
MATCH (other:Integration)
OPTIONAL MATCH (other)-[:BELONGS_TO]->(o:Organization)
WITH other, o
WHERE other.slug <> {slug} AND other.used_as_login = true AND o IS NULL
SET other.used_as_login = false
"""

_SET_USED_AS_LOGIN: typing.LiteralString = """
MATCH (i:Integration {{slug: {slug}}})
OPTIONAL MATCH (i)-[:BELONGS_TO]->(o:Organization)
WITH i, o
WHERE o IS NULL
SET i.used_as_login = {used_as_login}
RETURN i{{.*}} AS integration
"""


@auth_providers_router.put('/{slug}/used-as-login')
async def set_used_as_login(
    slug: str,
    data: models.LoginProviderUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('integration:update')),
    ],
) -> models.IntegrationResponse:
    """Promote/demote a login provider as the instance-wide SSO provider.

    At most one login provider may be active across the whole instance, so
    promoting one demotes any other. Login happens before org context, so
    this flag is global, not per-organization.

    Raises:
        404: Login provider not found.

    """
    _ = auth
    # Promote the org-less target first so a missing (or organization-owned)
    # target returns 404 without first disabling the active SSO provider.
    updated = await db.execute(
        _SET_USED_AS_LOGIN,
        {'slug': slug, 'used_as_login': data.used_as_login},
        ['integration'],
    )
    if not updated:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Login provider with slug {slug!r} not found',
        )
    if data.used_as_login:
        await db.execute(_DEMOTE_OTHERS, {'slug': slug}, [])
    login_repo.invalidate_cache()
    return build_response(graph.parse_agtype(updated[0]['integration']))


@auth_providers_router.delete('/{slug}', status_code=204)
async def delete_login_provider(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('integration:delete')),
    ],
) -> None:
    """Delete a global login provider.

    Raises:
        404: Login provider not found.

    """
    _ = auth
    query: typing.LiteralString = """
    MATCH (i:Integration {{slug: {slug}}})
    OPTIONAL MATCH (i)-[:BELONGS_TO]->(o:Organization)
    WITH i, o
    WHERE o IS NULL
    DETACH DELETE i
    RETURN count(i) AS deleted
    """
    records = await db.execute(query, {'slug': slug}, ['deleted'])
    deleted = graph.parse_agtype(records[0]['deleted']) if records else 0
    login_repo.invalidate_cache()
    if not records or deleted == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Login provider with slug {slug!r} not found',
        )
