"""Role and permission management endpoints."""

import logging
import typing

import fastapi
from imbi_common import models, neo4j
from neo4j import exceptions

from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

roles_router = fastapi.APIRouter(prefix='/roles', tags=['Roles'])


@roles_router.post('/', response_model=models.Role, status_code=201)
async def create_role(
    role: models.Role,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:create')),
    ],
) -> models.Role:
    """
    Create a new role.

    Parameters:
        role (models.Role): Role to create; its `slug` must be unique.

    Returns:
        models.Role: The created role.

    Raises:
        fastapi.HTTPException: HTTP 409 if a role with the same `slug`
            already exists.
    """
    try:
        return await neo4j.create_node(role)
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Role with slug {role.slug!r} already exists',
        ) from e


@roles_router.get('/', response_model=list[models.Role])
async def list_roles(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:read')),
    ],
) -> list[models.Role]:
    """
    Retrieve all roles ordered by priority (highest first) and then by name.

    Returns:
        list[models.Role]: Roles ordered by priority (descending) then name.
    """
    roles = []
    async for role in neo4j.fetch_nodes(
        models.Role, order_by=['priority DESC', 'name']
    ):
        roles.append(role)
    return roles


@roles_router.get('/{slug}', response_model=models.Role)
async def get_role(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:read')),
    ],
) -> models.Role:
    """
    Retrieve a role by its slug and load its permissions and parent role.

    Parameters:
        slug (str): The role's slug identifier.

    Returns:
        models.Role: The role with `permissions` and `parent_role`
            relationships populated.

    Raises:
        404: If no role with the given slug exists.
    """
    role = await neo4j.fetch_node(models.Role, {'slug': slug})
    if role is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Role with slug {slug!r} not found'
        )

    # Load permissions via direct Cypher query
    perm_query = """
    MATCH (r:Role {slug: $slug})-[:GRANTS]->(p:Permission)
    RETURN p
    ORDER BY p.name
    """
    async with neo4j.run(perm_query, slug=slug) as result:
        records = await result.data()
        role.permissions = [
            models.Permission(**neo4j.convert_neo4j_types(r['p']))
            for r in records
        ]

    # Load parent role via direct Cypher query
    parent_query = """
    MATCH (r:Role {slug: $slug})-[:INHERITS_FROM]->(parent:Role)
    RETURN parent
    """
    async with neo4j.run(parent_query, slug=slug) as result:
        records = await result.data()
        if records:
            role.parent_role = models.Role(
                **neo4j.convert_neo4j_types(records[0]['parent'])
            )

    return role


@roles_router.get('/{slug}/users', response_model=list[models.UserResponse])
async def list_role_users(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:read')),
    ],
) -> list[models.UserResponse]:
    """Retrieve all users who have been directly assigned this role.

    Parameters:
        slug: Role slug identifier.

    Returns:
        list[models.UserResponse]: Users with a direct HAS_ROLE
            relationship to this role.

    Raises:
        fastapi.HTTPException: HTTP 404 if role not found.
    """
    query = """
    MATCH (r:Role {slug: $slug})
    OPTIONAL MATCH (u:User)-[:HAS_ROLE]->(r)
    RETURN r, collect(u) AS users
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()
        if not records or not records[0].get('r'):
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Role with slug {slug!r} not found',
            )

        user_data = records[0].get('users', [])
        return [
            models.UserResponse(**neo4j.convert_neo4j_types(u))
            for u in user_data
            if u
        ]


@roles_router.get('/{slug}/groups', response_model=list[models.Group])
async def list_role_groups(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:read')),
    ],
) -> list[models.Group]:
    """Retrieve all groups that have been assigned this role.

    Parameters:
        slug: Role slug identifier.

    Returns:
        list[models.Group]: Groups with a direct ASSIGNED_ROLE
            relationship to this role.

    Raises:
        fastapi.HTTPException: HTTP 404 if role not found.
    """
    query = """
    MATCH (r:Role {slug: $slug})
    OPTIONAL MATCH (g:Group)-[:ASSIGNED_ROLE]->(r)
    RETURN r, collect(g) AS groups
    """
    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()
        if not records or not records[0].get('r'):
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Role with slug {slug!r} not found',
            )

        group_data = records[0].get('groups', [])
        return [
            models.Group(**neo4j.convert_neo4j_types(g))
            for g in group_data
            if g
        ]


@roles_router.put('/{slug}', response_model=models.Role)
async def update_role(
    slug: str,
    role: models.Role,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:update')),
    ],
) -> models.Role:
    """
    Update or create a role identified by slug.

    Parameters:
        slug (str): The role slug from the URL.
        role (models.Role): Role data to upsert; its `slug` must match
            the URL slug.

    Returns:
        models.Role: The updated or newly created role.

    Raises:
        fastapi.HTTPException: 400 if the URL slug and role.slug differ
            or if attempting to modify a system role.
        fastapi.HTTPException: 401 if the request is unauthenticated.
        fastapi.HTTPException: 403 if the caller lacks the
            `role:update` permission.
    """
    # Validate that URL slug matches role slug
    if role.slug != slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Slug in URL ({slug!r}) must match slug in '
            f'role data ({role.slug!r})',
        )

    # Check if role is a system role
    existing_role = await neo4j.fetch_node(models.Role, {'slug': slug})
    if existing_role and existing_role.is_system:
        raise fastapi.HTTPException(
            status_code=400, detail='Cannot modify system role'
        )

    await neo4j.upsert(role, {'slug': slug})
    return role


@roles_router.delete('/{slug}', status_code=204)
async def delete_role(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:delete')),
    ],
) -> None:
    """
    Delete a role identified by its slug.

    System roles cannot be deleted.

    Parameters:
        slug (str): The slug identifier of the role to delete.

    Raises:
        400: If attempting to delete a system role.
        404: If no role with the given slug exists.
    """
    # Check if role exists and is not a system role
    role = await neo4j.fetch_node(models.Role, {'slug': slug})
    if role is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Role with slug {slug!r} not found'
        )

    if role.is_system:
        raise fastapi.HTTPException(
            status_code=400, detail='Cannot delete system role'
        )

    deleted = await neo4j.delete_node(models.Role, {'slug': slug})
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Role with slug {slug!r} not found'
        )


@roles_router.post('/{slug}/permissions', status_code=204)
async def grant_permission(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:update')),
    ],
    permission_name: str = fastapi.Body(..., embed=True),
) -> None:
    """
    Grant the named permission to the role identified by `slug`.

    Creates a GRANTS relationship between the role and the permission
    in the database.

    Parameters:
        slug (str): Role slug.
        permission_name (str): Permission name to grant (e.g.,
            'blueprint:read').

    Raises:
        fastapi.HTTPException: 404 if the role or the permission does
            not exist.
        fastapi.HTTPException: 401 if the request is not authenticated.
        fastapi.HTTPException: 403 if the caller lacks the
            `role:update` permission.
    """
    # Check if role exists
    role = await neo4j.fetch_node(models.Role, {'slug': slug})
    if role is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Role with slug {slug!r} not found'
        )

    # Check if permission exists
    perm = await neo4j.fetch_node(models.Permission, {'name': permission_name})
    if perm is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Permission {permission_name!r} not found',
        )

    # Create GRANTS relationship
    query = """
    MATCH (role:Role {slug: $slug})
    MATCH (perm:Permission {name: $permission_name})
    MERGE (role)-[:GRANTS]->(perm)
    """
    async with neo4j.run(
        query, slug=slug, permission_name=permission_name
    ) as result:
        await result.consume()

    LOGGER.info('Granted permission %s to role %s', permission_name, slug)


@roles_router.delete('/{slug}/permissions/{permission_name}', status_code=204)
async def revoke_permission(
    slug: str,
    permission_name: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:update')),
    ],
) -> None:
    """
    Remove a granted permission from the specified role.

    Parameters:
        slug (str): Role slug identifying the role to modify.
        permission_name (str): Name of the permission to revoke.

    Raises:
        fastapi.HTTPException: 404 if the role does not exist or the
            permission is not granted to the role.
    """
    # Check if role exists
    role = await neo4j.fetch_node(models.Role, {'slug': slug})
    if role is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Role with slug {slug!r} not found'
        )

    # Delete GRANTS relationship
    query = """
    MATCH (role:Role {slug: $slug})-[r:GRANTS]->
          (perm:Permission {name: $permission_name})
    DELETE r
    RETURN count(r) AS deleted
    """
    async with neo4j.run(
        query, slug=slug, permission_name=permission_name
    ) as result:
        records = await result.data()
        if not records or records[0]['deleted'] == 0:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Permission {permission_name!r} not granted to '
                f'role {slug!r}',
            )

    LOGGER.info('Revoked permission %s from role %s', permission_name, slug)
