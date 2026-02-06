"""Group management endpoints."""

import logging
import typing

import fastapi
from imbi_common import models, neo4j
from neo4j import exceptions

from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

groups_router = fastapi.APIRouter(prefix='/groups', tags=['Groups'])


@groups_router.post('/', response_model=models.Group, status_code=201)
async def create_group(
    group: models.Group,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('group:create')),
    ],
) -> models.Group:
    """
    Create a new group.

    Parameters:
        group (models.Group): Group to create with unique slug.

    Returns:
        models.Group: The created group.

    Raises:
        fastapi.HTTPException: HTTP 409 if group with slug already exists.
    """
    try:
        return await neo4j.create_node(group)
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Group with slug {group.slug!r} already exists',
        ) from e


@groups_router.get('/', response_model=list[models.Group])
async def list_groups(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('group:read')),
    ],
) -> list[models.Group]:
    """
    Retrieve all groups ordered by name.

    Returns:
        list[models.Group]: Groups ordered alphabetically by name.
    """
    groups = []
    async for group in neo4j.fetch_nodes(models.Group, order_by='name'):
        groups.append(group)
    return groups


@groups_router.get('/{slug}', response_model=models.Group)
async def get_group(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('group:read')),
    ],
) -> models.Group:
    """
    Retrieve a group by slug with loaded relationships.

    Parameters:
        slug (str): Group slug identifier.

    Returns:
        models.Group: Group with loaded parent and roles, plus members.

    Raises:
        fastapi.HTTPException: HTTP 404 if group not found.
    """
    group = await neo4j.fetch_node(models.Group, {'slug': slug})
    if group is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Group with slug {slug!r} not found',
        )

    # Load roles via direct Cypher query
    roles_query = """
    MATCH (g:Group {slug: $slug})-[:ASSIGNED_ROLE]->(r:Role)
    RETURN r
    ORDER BY r.name
    """
    async with neo4j.run(roles_query, slug=slug) as result:
        records = await result.data()
        group.roles = [
            models.Role(**neo4j.convert_neo4j_types(r['r'])) for r in records
        ]

    # Load parent group via direct Cypher query
    parent_query = """
    MATCH (g:Group {slug: $slug})-[:PARENT_GROUP]->(parent:Group)
    RETURN parent
    """
    async with neo4j.run(parent_query, slug=slug) as result:
        records = await result.data()
        if records:
            group.parent = models.Group(
                **neo4j.convert_neo4j_types(records[0]['parent'])
            )

    return group


@groups_router.get('/{slug}/members', response_model=list[models.User])
async def list_group_members(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('group:read')),
    ],
) -> list[models.User]:
    """
    Retrieve all members of a group.

    Parameters:
        slug (str): Group slug identifier.

    Returns:
        list[models.User]: Users who are members of the group.

    Raises:
        fastapi.HTTPException: HTTP 404 if group not found.
    """
    query = """
    MATCH (g:Group {slug: $slug})
    OPTIONAL MATCH (u:User)-[:MEMBER_OF]->(g)
    RETURN g, collect(u) AS members
    """

    async with neo4j.run(query, slug=slug) as result:
        records = await result.data()
        if not records or not records[0].get('g'):
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Group with slug {slug!r} not found',
            )

        member_data = records[0].get('members', [])
        return [
            models.User(**neo4j.convert_neo4j_types(m))
            for m in member_data
            if m
        ]


@groups_router.put('/{slug}', response_model=models.Group)
async def update_group(
    slug: str,
    group: models.Group,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('group:update')),
    ],
) -> models.Group:
    """
    Update an existing group.

    Parameters:
        slug (str): Group slug from URL.
        group (models.Group): Updated group data.

    Returns:
        models.Group: The updated group.

    Raises:
        fastapi.HTTPException: HTTP 400 if URL slug doesn't match body
            slug, or HTTP 404 if group not found.
    """
    # Validate slug matches
    if group.slug != slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Slug in URL ({slug!r}) must match slug in body '
            f'({group.slug!r})',
        )

    # Verify group exists
    existing = await neo4j.fetch_node(models.Group, {'slug': slug})
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Group with slug {slug!r} not found',
        )

    await neo4j.upsert(group, {'slug': slug})
    return group


@groups_router.delete('/{slug}', status_code=204)
async def delete_group(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('group:delete')),
    ],
) -> None:
    """
    Delete a group.

    Parameters:
        slug (str): Group slug to delete.

    Raises:
        fastapi.HTTPException: HTTP 404 if group not found.
    """
    deleted = await neo4j.delete_node(models.Group, {'slug': slug})
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Group with slug {slug!r} not found',
        )


@groups_router.post('/{slug}/parent', status_code=204)
async def set_parent_group(
    slug: str,
    parent_data: dict[str, str],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('group:update')),
    ],
) -> None:
    """
    Set the parent group for a group.

    Parameters:
        slug (str): Child group slug.
        parent_data (dict): Dictionary with 'parent_slug' key.

    Raises:
        fastapi.HTTPException: HTTP 400 if creating circular reference
            or self-parenting, or HTTP 404 if group not found.
    """
    parent_slug = parent_data.get('parent_slug')
    if not parent_slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='parent_slug is required',
        )

    # Prevent self-parenting
    if slug == parent_slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Group cannot be its own parent',
        )

    # Check for circular reference
    circular_query = """
    MATCH path = (child:Group {slug: $parent_slug})-[:PARENT_GROUP*]->(
        ancestor:Group {slug: $slug})
    RETURN count(path) AS circular
    """

    async with neo4j.run(
        circular_query, slug=slug, parent_slug=parent_slug
    ) as result:
        records = await result.data()
        if records and records[0].get('circular', 0) > 0:
            raise fastapi.HTTPException(
                status_code=400,
                detail='Cannot create circular parent relationship',
            )

    # Set parent relationship
    query = """
    MATCH (child:Group {slug: $slug})
    MATCH (parent:Group {slug: $parent_slug})
    OPTIONAL MATCH (child)-[old:PARENT_GROUP]->()
    DELETE old
    MERGE (child)-[:PARENT_GROUP]->(parent)
    RETURN child, parent
    """

    async with neo4j.run(query, slug=slug, parent_slug=parent_slug) as result:
        records = await result.data()
        if not records:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Group {slug!r} or parent {parent_slug!r} not found',
            )


@groups_router.delete('/{slug}/parent', status_code=204)
async def remove_parent_group(
    slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('group:update')),
    ],
) -> None:
    """
    Remove the parent group relationship.

    Parameters:
        slug (str): Child group slug.
    """
    query = """
    MATCH (child:Group {slug: $slug})-[r:PARENT_GROUP]->()
    DELETE r
    """

    async with neo4j.run(query, slug=slug) as result:
        await result.consume()


@groups_router.post('/{slug}/roles', status_code=204)
async def assign_role_to_group(
    slug: str,
    role_data: dict[str, str],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('group:update')),
    ],
) -> None:
    """
    Assign a role to a group.

    Parameters:
        slug (str): Group slug.
        role_data (dict): Dictionary with 'role_slug' key.

    Raises:
        fastapi.HTTPException: HTTP 404 if group or role not found.
    """
    role_slug = role_data.get('role_slug')
    if not role_slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='role_slug is required',
        )

    query = """
    MATCH (g:Group {slug: $slug})
    MATCH (r:Role {slug: $role_slug})
    MERGE (g)-[:ASSIGNED_ROLE]->(r)
    RETURN g, r
    """

    async with neo4j.run(query, slug=slug, role_slug=role_slug) as result:
        records = await result.data()
        if not records:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Group {slug!r} or role {role_slug!r} not found',
            )


@groups_router.delete('/{slug}/roles/{role_slug}', status_code=204)
async def unassign_role_from_group(
    slug: str,
    role_slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('group:update')),
    ],
) -> None:
    """
    Unassign a role from a group.

    Parameters:
        slug (str): Group slug.
        role_slug (str): Role slug to unassign.

    Raises:
        fastapi.HTTPException: HTTP 404 if relationship doesn't exist.
    """
    query = """
    MATCH (g:Group {slug: $slug})-[r:ASSIGNED_ROLE]->
          (role:Role {slug: $role_slug})
    DELETE r
    RETURN count(r) AS deleted
    """

    async with neo4j.run(query, slug=slug, role_slug=role_slug) as result:
        records = await result.data()
        if not records or records[0].get('deleted', 0) == 0:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Group {slug!r} does not have role {role_slug!r}',
            )
