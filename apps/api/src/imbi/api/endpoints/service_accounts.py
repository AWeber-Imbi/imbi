"""Service account management endpoints"""

import datetime
import logging
import typing

import fastapi
from imbi_common import neo4j
from neo4j import exceptions

from imbi_api import models
from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

service_accounts_router = fastapi.APIRouter(
    prefix='/service-accounts', tags=['Service Accounts']
)


@service_accounts_router.post(
    '', response_model=models.ServiceAccountResponse, status_code=201
)
async def create_service_account(
    sa_create: models.ServiceAccountCreate,
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
        await neo4j.create_node(sa)
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Service account with slug {sa.slug!r} already exists',
        ) from e

    # Create MEMBER_OF relationship to organization with role
    membership_query = """
    MATCH (s:ServiceAccount {slug: $slug})
    MATCH (o:Organization {slug: $org_slug})
    MATCH (r:Role {slug: $role_slug})
    MERGE (s)-[m:MEMBER_OF]->(o)
    SET m.role = $role_slug
    RETURN o.name AS org_name, o.slug AS org_slug, r.slug AS role
    """
    organizations: list[models.OrgMembership] = []
    async with neo4j.run(
        membership_query,
        slug=sa.slug,
        org_slug=sa_create.organization_slug,
        role_slug=sa_create.role_slug,
    ) as result:
        records = await result.data()
        if not records:
            # Rollback: delete the service account node
            query = """
            MATCH (s:ServiceAccount {slug: $slug})
            DETACH DELETE s
            """
            async with neo4j.run(query, slug=sa.slug) as _:
                pass
            raise fastapi.HTTPException(
                status_code=404,
                detail=(
                    f'Organization {sa_create.organization_slug!r}'
                    f' or role {sa_create.role_slug!r} not found'
                ),
            )
        for record in records:
            organizations.append(
                models.OrgMembership(
                    organization_name=record['org_name'],
                    organization_slug=record['org_slug'],
                    role=record['role'],
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

    accounts: list[models.ServiceAccountResponse] = []
    async for sa in neo4j.fetch_nodes(
        models.ServiceAccount,
        parameters if parameters else None,
        order_by='slug',
    ):
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
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:read')
        ),
    ],
) -> models.ServiceAccountResponse:
    """Get a service account by slug."""
    sa = await neo4j.fetch_node(models.ServiceAccount, {'slug': slug})
    if sa is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Service account {slug!r} not found',
        )

    # Load organization memberships
    org_query = """
    MATCH (s:ServiceAccount {slug: $slug})
          -[m:MEMBER_OF]->(o:Organization)
    RETURN o.name AS org_name,
           o.slug AS org_slug,
           m.role AS role
    ORDER BY o.name
    """
    organizations: list[models.OrgMembership] = []
    async with neo4j.run(org_query, slug=slug) as result:
        records = await result.data()
        for record in records:
            organizations.append(
                models.OrgMembership(
                    organization_name=record['org_name'],
                    organization_slug=record['org_slug'],
                    role=record['role'],
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

    existing = await neo4j.fetch_node(models.ServiceAccount, {'slug': slug})
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
    await neo4j.upsert(updated, {'slug': slug})

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
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:delete')
        ),
    ],
) -> None:
    """Delete a service account and all related credentials."""
    query = """
    MATCH (s:ServiceAccount {slug: $slug})
    OPTIONAL MATCH (s)<-[:OWNED_BY]-(owned)
    DETACH DELETE owned, s
    RETURN count(s) AS deleted
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()

    if not records or records[0]['deleted'] == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Service account {slug!r} not found',
        )


@service_accounts_router.post('/{slug}/organizations', status_code=204)
async def add_to_organization(
    slug: str,
    membership: dict[str, str],
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

    query = """
    MATCH (s:ServiceAccount {slug: $slug})
    MATCH (o:Organization {slug: $org_slug})
    MATCH (r:Role {slug: $role_slug})
    MERGE (s)-[m:MEMBER_OF]->(o)
    SET m.role = $role_slug
    RETURN s, o, r
    """
    async with neo4j.run(
        query,
        slug=slug,
        org_slug=org_slug,
        role_slug=role_slug,
    ) as result:
        records = await result.data()
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

    query = """
    MATCH (s:ServiceAccount {slug: $slug})
          -[m:MEMBER_OF]->(o:Organization {slug: $org_slug})
    MATCH (r:Role {slug: $role_slug})
    SET m.role = $role_slug
    RETURN s, o, r
    """
    async with neo4j.run(
        query,
        slug=slug,
        org_slug=org_slug,
        role_slug=role_slug,
    ) as result:
        records = await result.data()
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
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('service_account:update')
        ),
    ],
) -> None:
    """Remove a service account from an organization."""
    query = """
    MATCH (s:ServiceAccount {slug: $slug})
          -[m:MEMBER_OF]->(o:Organization {slug: $org_slug})
    DELETE m
    RETURN count(m) AS deleted
    """
    async with neo4j.run(query, slug=slug, org_slug=org_slug) as result:
        records = await result.data()
        if not records or records[0].get('deleted', 0) == 0:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Service account {slug!r} is not a '
                f'member of organization {org_slug!r}',
            )
