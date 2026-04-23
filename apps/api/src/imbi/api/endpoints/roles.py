"""Role and permission management endpoints."""

import datetime
import logging
import typing

import fastapi
import psycopg.errors
import pydantic
from imbi_common import graph

from imbi_api import models
from imbi_api import patch as json_patch
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
    db: graph.Pool,
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
        created = await db.create(role)
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Role with slug {role.slug!r} already exists',
        ) from e
    result = created.model_dump()
    result['relationships'] = _build_relationships(role.slug)
    return result


@roles_router.get('/')
async def list_roles(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:read')),
    ],
) -> list[dict[str, typing.Any]]:
    """Retrieve all roles with relationship counts.

    Returns:
        Roles ordered by priority (descending) then name.

    """
    query: typing.LiteralString = (
        'MATCH (r:Role)'
        ' OPTIONAL MATCH (r)-[:GRANTS]->(p:Permission)'
        ' WITH r, count(DISTINCT p) AS permission_count'
        ' OPTIONAL MATCH (u:User)-[m:MEMBER_OF]->'
        '(o:Organization)'
        ' WHERE m.role = r.slug'
        ' WITH r, permission_count,'
        '      count(DISTINCT u) AS user_count'
        ' RETURN r, permission_count, user_count'
        ' ORDER BY r.priority DESC, r.name'
    )
    roles: list[dict[str, typing.Any]] = []
    records = await db.execute(
        query,
        columns=['r', 'permission_count', 'user_count'],
    )
    for record in records:
        role = graph.parse_agtype(record['r'])
        role['relationships'] = _build_relationships(
            role['slug'],
            graph.parse_agtype(record['permission_count']),
            graph.parse_agtype(record['user_count']),
        )
        roles.append(role)
    return roles


@roles_router.get('/{slug}')
async def get_role(
    slug: str,
    db: graph.Pool,
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
    results = await db.match(models.Role, {'slug': slug})
    role = results[0] if results else None
    if role is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role with slug {slug!r} not found',
        )

    # Load permissions via direct Cypher query
    perm_query: typing.LiteralString = (
        'MATCH (r:Role {{slug: {slug}}})-[:GRANTS]->'
        '(p:Permission)'
        ' RETURN p'
        ' ORDER BY p.name'
    )
    records = await db.execute(
        perm_query,
        {'slug': slug},
        columns=['p'],
    )
    role.permissions = [
        models.Permission(**graph.parse_agtype(r['p'])) for r in records
    ]

    permission_count = len(role.permissions)

    # Load parent role via direct Cypher query
    parent_query: typing.LiteralString = (
        'MATCH (r:Role {{slug: {slug}}})-[:INHERITS_FROM]->'
        '(parent:Role)'
        ' RETURN parent'
    )
    records = await db.execute(
        parent_query,
        {'slug': slug},
        columns=['parent'],
    )
    if records:
        role.parent_role = models.Role(
            **graph.parse_agtype(records[0]['parent'])
        )

    # Count users with this role
    user_count_query: typing.LiteralString = (
        'MATCH (u:User)-[m:MEMBER_OF]->(o:Organization)'
        ' WHERE m.role = {slug}'
        ' RETURN count(DISTINCT u) AS user_count'
    )
    records = await db.execute(
        user_count_query,
        {'slug': slug},
        columns=['user_count'],
    )
    user_count = graph.parse_agtype(records[0]['user_count']) if records else 0

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
    db: graph.Pool,
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
    query: typing.LiteralString = (
        'MATCH (r:Role {{slug: {slug}}})'
        ' OPTIONAL MATCH (u:User)-[m:MEMBER_OF]->'
        '(o:Organization)'
        ' WHERE m.role = {slug}'
        ' RETURN r, collect(DISTINCT u) AS users'
    )
    records = await db.execute(
        query,
        {'slug': slug},
        columns=['r', 'users'],
    )
    if not records or not records[0].get('r'):
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role with slug {slug!r} not found',
        )

    raw_users: typing.Any = graph.parse_agtype(records[0].get('users', '[]'))
    if isinstance(raw_users, str):
        raw_users = []
    return [models.UserResponse(**u) for u in raw_users if u]


@roles_router.get(
    '/{slug}/service-accounts',
    response_model=list[models.ServiceAccountResponse],
)
async def list_role_service_accounts(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:read')),
    ],
) -> list[models.ServiceAccountResponse]:
    """Retrieve service accounts assigned this role.

    Parameters:
        slug: Role slug identifier.

    Returns:
        Service accounts with a MEMBER_OF relationship where the
        role property matches this role's slug.

    Raises:
        404: If role not found.

    """
    query: typing.LiteralString = (
        'MATCH (r:Role {{slug: {slug}}})'
        ' OPTIONAL MATCH (s:ServiceAccount)-[m:MEMBER_OF]->'
        '(o:Organization)'
        ' WHERE m.role = {slug}'
        ' RETURN r, collect(DISTINCT s) AS service_accounts'
    )
    records = await db.execute(
        query,
        {'slug': slug},
        columns=['r', 'service_accounts'],
    )
    if not records or not records[0].get('r'):
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role with slug {slug!r} not found',
        )

    raw_sa: typing.Any = graph.parse_agtype(
        records[0].get('service_accounts', '[]')
    )
    if isinstance(raw_sa, str):
        raw_sa = []
    return [models.ServiceAccountResponse(**sa) for sa in raw_sa if sa]


@roles_router.patch('/{slug}')
async def patch_role(
    slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('role:update')),
    ],
) -> dict[str, typing.Any]:
    """Partially update a role using JSON Patch (RFC 6902).

    Parameters:
        slug: Role slug from URL.
        operations: JSON Patch operations.

    Returns:
        The updated role with relationships.

    Raises:
        400: Invalid patch, read-only path, or validation error.
        404: Role not found.
        422: Patch test failed.

    """
    results = await db.match(models.Role, {'slug': slug})
    existing = results[0] if results else None
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role with slug {slug!r} not found',
        )

    if existing.is_system:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Cannot modify system role',
        )

    current = existing.model_dump(mode='json')
    current.pop('created_at', None)
    current.pop('updated_at', None)
    current.pop('permissions', None)
    current.pop('parent_role', None)

    patched = json_patch.apply_patch(current, operations)

    try:
        role = models.Role(**patched)
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    role.created_at = existing.created_at
    role.updated_at = datetime.datetime.now(datetime.UTC)
    await db.merge(role, match_on=['slug'])

    count_query: typing.LiteralString = (
        'MATCH (r:Role {{slug: {slug}}})'
        ' OPTIONAL MATCH (r)-[:GRANTS]->(p:Permission)'
        ' WITH r, count(DISTINCT p) AS permission_count'
        ' OPTIONAL MATCH (u:User)-[m:MEMBER_OF]->'
        '(o:Organization)'
        ' WHERE m.role = r.slug'
        ' RETURN count(DISTINCT u) AS user_count,'
        '        permission_count'
    )
    records = await db.execute(
        count_query,
        {'slug': role.slug},
        columns=['user_count', 'permission_count'],
    )
    permission_count = (
        graph.parse_agtype(records[0]['permission_count']) if records else 0
    )
    user_count = graph.parse_agtype(records[0]['user_count']) if records else 0

    result = role.model_dump()
    result['relationships'] = _build_relationships(
        role.slug,
        permission_count,
        user_count,
    )
    return result


@roles_router.delete('/{slug}', status_code=204)
async def delete_role(
    slug: str,
    db: graph.Pool,
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
    results = await db.match(models.Role, {'slug': slug})
    role = results[0] if results else None
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

    query: typing.LiteralString = (
        'MATCH (n:Role {{slug: {slug}}}) DETACH DELETE n RETURN n'
    )
    records = await db.execute(query, {'slug': slug})
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role with slug {slug!r} not found',
        )


@roles_router.post('/{slug}/permissions', status_code=204)
async def grant_permission(
    slug: str,
    db: graph.Pool,
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
    results = await db.match(models.Role, {'slug': slug})
    role = results[0] if results else None
    if role is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role with slug {slug!r} not found',
        )

    # Check if permission exists
    perm_results = await db.match(
        models.Permission,
        {'name': permission_name},
    )
    perm = perm_results[0] if perm_results else None
    if perm is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Permission {permission_name!r} not found',
        )

    # Create GRANTS relationship
    query: typing.LiteralString = (
        'MATCH (role:Role {{slug: {slug}}})'
        ' MATCH (perm:Permission {{name: {permission_name}}})'
        ' MERGE (role)-[g:GRANTS]->(perm)'
        ' RETURN g'
    )
    await db.execute(
        query,
        {'slug': slug, 'permission_name': permission_name},
    )

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
    db: graph.Pool,
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
    results = await db.match(models.Role, {'slug': slug})
    role = results[0] if results else None
    if role is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Role with slug {slug!r} not found',
        )

    # Delete GRANTS relationship
    query: typing.LiteralString = (
        'MATCH (role:Role {{slug: {slug}}})-[r:GRANTS]->'
        '(perm:Permission {{name: {permission_name}}})'
        ' DELETE r'
        ' RETURN count(r) AS deleted'
    )
    records = await db.execute(
        query,
        {'slug': slug, 'permission_name': permission_name},
        columns=['deleted'],
    )
    deleted_count = graph.parse_agtype(records[0]['deleted']) if records else 0
    if not deleted_count:
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
