"""Service account management endpoints"""

import datetime
import logging
import typing

import fastapi
import psycopg
import pydantic
from imbi_common import graph

from imbi_api import models
from imbi_api import patch as json_patch
from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

service_accounts_router = fastapi.APIRouter(
    prefix='/service-accounts', tags=['Service Accounts']
)


@service_accounts_router.post(
    '',
    response_model=models.ServiceAccountResponse,
    status_code=201,
)
async def create_service_account(
    sa_create: models.ServiceAccountCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:create')
        ),
    ],
) -> models.ServiceAccountResponse:
    """Create a new service account."""
    sa = models.ServiceAccount(
        slug=sa_create.slug,
        display_name=sa_create.display_name,
        description=sa_create.description,
        is_active=sa_create.is_active,
        created_at=datetime.datetime.now(datetime.UTC),
    )

    try:
        await db.create(sa)
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'Service account with slug {sa.slug!r} already exists'),
        ) from e

    # Create MEMBER_OF relationship to organization with role
    membership_query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
    MATCH (o:Organization {{slug: {org_slug}}})
    MATCH (r:Role {{slug: {role_slug}}})
    MERGE (s)-[m:MEMBER_OF]->(o)
    SET m.role = {role_slug}
    RETURN o.name AS org_name,
           o.slug AS org_slug,
           r.slug AS role
    """
    records = await db.execute(
        membership_query,
        {
            'slug': sa.slug,
            'org_slug': sa_create.organization_slug,
            'role_slug': sa_create.role_slug,
        },
        ['org_name', 'org_slug', 'role'],
    )
    if not records:
        # Rollback: delete the service account node
        del_query: typing.LiteralString = """
        MATCH (s:ServiceAccount {{slug: {slug}}})
        DETACH DELETE s
        """
        await db.execute(
            del_query,
            {'slug': sa.slug},
        )
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Organization {sa_create.organization_slug!r}'
                f' or role {sa_create.role_slug!r} not found'
            ),
        )

    organizations: list[models.OrgMembership] = []
    for record in records:
        organizations.append(
            models.OrgMembership(
                organization_name=graph.parse_agtype(record['org_name']),
                organization_slug=graph.parse_agtype(record['org_slug']),
                role=graph.parse_agtype(record['role']),
            )
        )

    return models.ServiceAccountResponse(
        slug=sa.slug,
        display_name=sa.display_name,
        description=sa.description,
        is_active=sa.is_active,
        created_at=sa.created_at,
        organizations=organizations,
    )


@service_accounts_router.get(
    '', response_model=list[models.ServiceAccountResponse]
)
async def list_service_accounts(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:read')
        ),
    ],
    is_active: bool | None = None,
) -> list[models.ServiceAccountResponse]:
    """List all service accounts."""
    parameters: dict[str, bool] = {}
    if is_active is not None:
        parameters['is_active'] = is_active

    nodes = await db.match(
        models.ServiceAccount,
        parameters if parameters else None,
        order_by='slug',
    )

    accounts: list[models.ServiceAccountResponse] = []
    for sa in nodes:
        accounts.append(
            models.ServiceAccountResponse(
                slug=sa.slug,
                display_name=sa.display_name,
                description=sa.description,
                is_active=sa.is_active,
                created_at=sa.created_at,
                last_authenticated=sa.last_authenticated,
            )
        )
    return accounts


@service_accounts_router.get(
    '/{slug}', response_model=models.ServiceAccountResponse
)
async def get_service_account(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:read')
        ),
    ],
) -> models.ServiceAccountResponse:
    """Get a service account by slug."""
    results = await db.match(models.ServiceAccount, {'slug': slug})
    sa = results[0] if results else None
    if sa is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Service account {slug!r} not found',
        )

    # Load organization memberships
    org_query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
          -[m:MEMBER_OF]->(o:Organization)
    RETURN o.name AS org_name,
           o.slug AS org_slug,
           m.role AS role
    ORDER BY o.name
    """
    records = await db.execute(
        org_query,
        {'slug': slug},
        ['org_name', 'org_slug', 'role'],
    )
    organizations: list[models.OrgMembership] = []
    for record in records:
        organizations.append(
            models.OrgMembership(
                organization_name=graph.parse_agtype(record['org_name']),
                organization_slug=graph.parse_agtype(record['org_slug']),
                role=graph.parse_agtype(record['role']),
            )
        )

    return models.ServiceAccountResponse(
        slug=sa.slug,
        display_name=sa.display_name,
        description=sa.description,
        is_active=sa.is_active,
        created_at=sa.created_at,
        last_authenticated=sa.last_authenticated,
        organizations=organizations,
    )


@service_accounts_router.put(
    '/{slug}', response_model=models.ServiceAccountResponse
)
async def update_service_account(
    slug: str,
    sa_update: models.ServiceAccountUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> models.ServiceAccountResponse:
    """Update a service account."""
    if sa_update.slug != slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Slug in URL ({slug!r}) must match '
            f'slug in body ({sa_update.slug!r})',
        )

    results = await db.match(models.ServiceAccount, {'slug': slug})
    existing = results[0] if results else None
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Service account {slug!r} not found',
        )

    updated = models.ServiceAccount(
        slug=sa_update.slug,
        display_name=sa_update.display_name,
        description=sa_update.description,
        is_active=sa_update.is_active,
        created_at=existing.created_at,
        last_authenticated=existing.last_authenticated,
    )
    await db.merge(updated, match_on=['slug'])

    return models.ServiceAccountResponse(
        slug=updated.slug,
        display_name=updated.display_name,
        description=updated.description,
        is_active=updated.is_active,
        created_at=updated.created_at,
        last_authenticated=updated.last_authenticated,
    )


@service_accounts_router.patch(
    '/{slug}', response_model=models.ServiceAccountResponse
)
async def patch_service_account(
    slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> models.ServiceAccountResponse:
    """Partially update a service account using JSON Patch (RFC 6902).

    Parameters:
        slug: Service account slug from URL.
        operations: JSON Patch operations.

    Returns:
        The updated service account.

    Raises:
        400: Invalid patch, read-only path, or slug change attempted.
        404: Service account not found.
        422: Patch test failed or validation error.

    """
    results = await db.match(models.ServiceAccount, {'slug': slug})
    existing = results[0] if results else None
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Service account {slug!r} not found',
        )

    current = {
        'slug': existing.slug,
        'display_name': existing.display_name,
        'description': existing.description,
        'is_active': existing.is_active,
    }

    patched = json_patch.apply_patch(current, operations)

    if patched.get('slug') != slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Service account slug cannot be changed via PATCH',
        )

    try:
        updated = models.ServiceAccount(
            slug=patched['slug'],
            display_name=patched.get('display_name', existing.display_name),
            description=patched.get('description', existing.description),
            is_active=patched.get('is_active', existing.is_active),
            created_at=existing.created_at,
            last_authenticated=existing.last_authenticated,
        )
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    await db.merge(updated, match_on=['slug'])

    return models.ServiceAccountResponse(
        slug=updated.slug,
        display_name=updated.display_name,
        description=updated.description,
        is_active=updated.is_active,
        created_at=updated.created_at,
        last_authenticated=updated.last_authenticated,
    )


@service_accounts_router.delete('/{slug}', status_code=204)
async def delete_service_account(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:delete')
        ),
    ],
) -> None:
    """Delete a service account and all related credentials."""
    query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
    OPTIONAL MATCH (s)<-[:OWNED_BY]-(owned)
    DETACH DELETE owned, s
    RETURN count(s) AS deleted
    """
    records = await db.execute(
        query,
        {'slug': slug},
        ['deleted'],
    )

    deleted = graph.parse_agtype(records[0]['deleted']) if records else 0
    if not records or deleted == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Service account {slug!r} not found',
        )


@service_accounts_router.post('/{slug}/organizations', status_code=204)
async def add_to_organization(
    slug: str,
    membership: dict[str, str],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> None:
    """Add a service account to an organization with a role."""
    org_slug = membership.get('organization_slug')
    role_slug = membership.get('role_slug')
    if not org_slug or not role_slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='organization_slug and role_slug are required',
        )

    query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
    MATCH (o:Organization {{slug: {org_slug}}})
    MATCH (r:Role {{slug: {role_slug}}})
    MERGE (s)-[m:MEMBER_OF]->(o)
    SET m.role = {role_slug}
    RETURN s, o, r
    """
    records = await db.execute(
        query,
        {
            'slug': slug,
            'org_slug': org_slug,
            'role_slug': role_slug,
        },
        ['s', 'o', 'r'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Service account {slug!r}, '
            f'organization {org_slug!r}, '
            f'or role {role_slug!r} not found',
        )


@service_accounts_router.put(
    '/{slug}/organizations/{org_slug}',
    status_code=204,
)
async def update_organization_role(
    slug: str,
    org_slug: str,
    role_data: dict[str, str],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> None:
    """Change a service account's role in an organization."""
    role_slug = role_data.get('role_slug')
    if not role_slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='role_slug is required',
        )

    query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
          -[m:MEMBER_OF]->(o:Organization {{slug: {org_slug}}})
    MATCH (r:Role {{slug: {role_slug}}})
    SET m.role = {role_slug}
    RETURN s, o, r
    """
    records = await db.execute(
        query,
        {
            'slug': slug,
            'org_slug': org_slug,
            'role_slug': role_slug,
        },
        ['s', 'o', 'r'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Membership for {slug!r} in {org_slug!r}'
                f' or role {role_slug!r} not found'
            ),
        )


@service_accounts_router.delete(
    '/{slug}/organizations/{org_slug}', status_code=204
)
async def remove_from_organization(
    slug: str,
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> None:
    """Remove a service account from an organization."""
    query: typing.LiteralString = """
    MATCH (s:ServiceAccount {{slug: {slug}}})
          -[m:MEMBER_OF]->(o:Organization {{slug: {org_slug}}})
    DELETE m
    RETURN count(m) AS deleted
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
            detail=f'Service account {slug!r} is not a '
            f'member of organization {org_slug!r}',
        )
