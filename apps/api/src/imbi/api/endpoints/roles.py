"""Role and permission management endpoints."""

import datetime
import logging
import typing

import fastapi
from imbi_common import neo4j
from neo4j import exceptions

from imbi_api import models
from imbi_api.auth import permissions
from imbi_api.relationships import relationship_link

LOGGER = logging.getLogger(__name__)

roles_router = fastapi.APIRouter(prefix='/roles', tags=['Roles'])


def _build_relationships(
    slug: str,
    permission_count: int = 0,
    user_count: int = 0,
) -> dict[str, models.RelationshipLink]:
    """Build relationships dict for a role."""
    return {
        'permissions': relationship_link(
            f'/api/roles/{slug}/permissions',
            permission_count,
        ),
        'users': relationship_link(
            f'/api/roles/{slug}/users',
            user_count,
        ),
    }


@roles_router.post('/', response_model=models.Role, status_code=201)
async def create_role(
    role: models.Role,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:create')),
    ],
) -> dict[str, typing.Any]:
    """Create a new role.

    Parameters:
        role: Role to create; its ``slug`` must be unique.

    Returns:
        The created role.

    Raises:
        409: If a role with the same slug already exists.

    """
    now = datetime.datetime.now(datetime.UTC)
    role.created_at = now
    role.updated_at = now
    try:
        created = await neo4j.create_node(role)
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Role with slug {role.slug!r} already exists',
        ) from e
    result = created.model_dump()
    result['relationships'] = _build_relationships(created.slug)
    return result


@roles_router.get('/')
async def list_roles(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:read')),
    ],
) -> list[dict[str, typing.Any]]:
    """Retrieve all roles with relationship counts.

    Returns:
        Roles ordered by priority (descending) then name.

    """
    query: typing.LiteralString = """
    MATCH (r:Role)
    OPTIONAL MATCH (r)-[:GRANTS]->(p:Permission)
    WITH r, count(DISTINCT p) AS permission_count
    OPTIONAL MATCH (u:User)-[m:MEMBER_OF]->(o:Organization)
    WHERE m.role = r.slug
    WITH r, permission_count,
         count(DISTINCT u) AS user_count
    RETURN r{.*} AS role,
           permission_count, user_count
    ORDER BY r.priority DESC, r.name
    """
    roles: list[dict[str, typing.Any]] = []
    records = await neo4j.query(query)
    for record in records:
        role = record['role']
        role['relationships'] = _build_relationships(
            role['slug'],
            record['permission_count'],
            record['user_count'],
        )
        roles.append(role)
    return roles


@roles_router.get('/{slug}')
async def get_role(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:read')),
    ],
) -> dict[str, typing.Any]:
    """Retrieve a role by its slug with permissions and counts.

    Parameters:
        slug: The role's slug identifier.

    Returns:
        The role with permissions, parent_role, and
        relationships populated.

    Raises:
        404: If no role with the given slug exists.

    """
    role = await neo4j.fetch_node(models.Role, {'slug': slug})
    if role is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role with slug {slug!r} not found',
        )

    # Load permissions via direct Cypher query
    perm_query: typing.LiteralString = """
    MATCH (r:Role {slug: $slug})-[:GRANTS]->(p:Permission)
    RETURN p
    ORDER BY p.name
    """
    records = await neo4j.query(perm_query, slug=slug)
    role.permissions = [models.Permission(**r['p']) for r in records]

    permission_count = len(role.permissions)

    # Load parent role via direct Cypher query
    parent_query: typing.LiteralString = """
    MATCH (r:Role {slug: $slug})-[:INHERITS_FROM]->(parent:Role)
    RETURN parent
    """
    records = await neo4j.query(parent_query, slug=slug)
    if records:
        role.parent_role = models.Role(**records[0]['parent'])

    # Count users with this role
    user_count_query: typing.LiteralString = """
    MATCH (u:User)-[m:MEMBER_OF]->(o:Organization)
    WHERE m.role = $slug
    RETURN count(DISTINCT u) AS user_count
    """
    records = await neo4j.query(user_count_query, slug=slug)
    user_count = records[0]['user_count'] if records else 0

    role_dict = role.model_dump()
    role_dict['relationships'] = _build_relationships(
        slug,
        permission_count,
        user_count,
    )
    return role_dict


@roles_router.get(
    '/{slug}/users',
    response_model=list[models.UserResponse],
)
async def list_role_users(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:read')),
    ],
) -> list[models.UserResponse]:
    """Retrieve all users assigned this role via org membership.

    Parameters:
        slug: Role slug identifier.

    Returns:
        Users with a MEMBER_OF relationship where the role
        property matches this role's slug.

    Raises:
        404: If role not found.

    """
    query: typing.LiteralString = """
    MATCH (r:Role {slug: $slug})
    OPTIONAL MATCH (u:User)-[m:MEMBER_OF]->(o:Organization)
    WHERE m.role = $slug
    RETURN r, collect(DISTINCT u) AS users
    """
    records = await neo4j.query(query, slug=slug)
    if not records or not records[0].get('r'):
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role with slug {slug!r} not found',
        )

    user_data = records[0].get('users', [])
    return [models.UserResponse(**u) for u in user_data if u]


@roles_router.put('/{slug}', response_model=models.Role)
async def update_role(
    slug: str,
    role: models.Role,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:update')),
    ],
) -> dict[str, typing.Any]:
    """Update or create a role identified by slug.

    Parameters:
        slug: The role slug from the URL.
        role: Role data to upsert.

    Returns:
        The updated or newly created role.

    Raises:
        400: If attempting to modify a system role.

    """
    # Check if role is a system role
    existing_role = await neo4j.fetch_node(
        models.Role,
        {'slug': slug},
    )
    if existing_role and existing_role.is_system:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Cannot modify system role',
        )

    now = datetime.datetime.now(datetime.UTC)
    if existing_role:
        role.created_at = existing_role.created_at
    else:
        role.created_at = now
    role.updated_at = now
    await neo4j.upsert(role, {'slug': slug})

    # Fetch actual relationship counts from the database
    count_query: typing.LiteralString = """
    MATCH (r:Role {slug: $slug})
    OPTIONAL MATCH (r)-[:GRANTS]->(p:Permission)
    WITH r, count(DISTINCT p) AS permission_count
    OPTIONAL MATCH (u:User)-[m:MEMBER_OF]->(o:Organization)
    WHERE m.role = r.slug
    RETURN count(DISTINCT u) AS user_count,
           permission_count
    """
    records = await neo4j.query(count_query, slug=slug)
    permission_count = records[0]['permission_count'] if records else 0
    user_count = records[0]['user_count'] if records else 0

    result = role.model_dump()
    result['relationships'] = _build_relationships(
        slug,
        permission_count,
        user_count,
    )
    return result


@roles_router.delete('/{slug}', status_code=204)
async def delete_role(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:delete')),
    ],
) -> None:
    """Delete a role identified by its slug.

    System roles cannot be deleted.

    Parameters:
        slug: The slug identifier of the role to delete.

    Raises:
        400: If attempting to delete a system role.
        404: If no role with the given slug exists.

    """
    # Check if role exists and is not a system role
    role = await neo4j.fetch_node(models.Role, {'slug': slug})
    if role is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role with slug {slug!r} not found',
        )

    if role.is_system:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Cannot delete system role',
        )

    deleted = await neo4j.delete_node(
        models.Role,
        {'slug': slug},
    )
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role with slug {slug!r} not found',
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
    """Grant the named permission to the role.

    Parameters:
        slug: Role slug.
        permission_name: Permission name to grant.

    Raises:
        404: If the role or the permission does not exist.

    """
    # Check if role exists
    role = await neo4j.fetch_node(
        models.Role,
        {'slug': slug},
    )
    if role is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role with slug {slug!r} not found',
        )

    # Check if permission exists
    perm = await neo4j.fetch_node(
        models.Permission,
        {'name': permission_name},
    )
    if perm is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Permission {permission_name!r} not found',
        )

    # Create GRANTS relationship
    query: typing.LiteralString = """
    MATCH (role:Role {slug: $slug})
    MATCH (perm:Permission {name: $permission_name})
    MERGE (role)-[:GRANTS]->(perm)
    """
    await neo4j.query(query, slug=slug, permission_name=permission_name)

    LOGGER.info(
        'Granted permission %s to role %s',
        permission_name,
        slug,
    )


@roles_router.delete(
    '/{slug}/permissions/{permission_name}',
    status_code=204,
)
async def revoke_permission(
    slug: str,
    permission_name: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:update')),
    ],
) -> None:
    """Remove a granted permission from the specified role.

    Parameters:
        slug: Role slug identifying the role to modify.
        permission_name: Name of the permission to revoke.

    Raises:
        404: If the role does not exist or the permission is
            not granted to the role.

    """
    # Check if role exists
    role = await neo4j.fetch_node(
        models.Role,
        {'slug': slug},
    )
    if role is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role with slug {slug!r} not found',
        )

    # Delete GRANTS relationship
    query: typing.LiteralString = """
    MATCH (role:Role {slug: $slug})-[r:GRANTS]->
          (perm:Permission {name: $permission_name})
    DELETE r
    RETURN count(r) AS deleted
    """
    records = await neo4j.query(
        query, slug=slug, permission_name=permission_name
    )
    if not records or records[0]['deleted'] == 0:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Permission {permission_name!r} not granted'
            f' to role {slug!r}',
        )

    LOGGER.info(
        'Revoked permission %s from role %s',
        permission_name,
        slug,
    )
