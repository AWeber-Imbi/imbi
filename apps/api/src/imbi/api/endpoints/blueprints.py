"""Blueprint CRUD endpoints"""

import logging
import typing

import fastapi
import psycopg.errors
from imbi_common import graph, models

from imbi_api import openapi
from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

blueprint_router = fastapi.APIRouter(prefix='/blueprints', tags=['Blueprints'])


@blueprint_router.post('/', response_model=models.Blueprint, status_code=201)
async def create_blueprint(
    blueprint: models.Blueprint,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('blueprint:write')),
    ],
) -> models.Blueprint:
    """
    Create a new blueprint node in the graph database.

    If `blueprint.slug` is not provided, it will be generated from
    `blueprint.name`.

    Returns:
        models.Blueprint: The created blueprint with values returned
            from the database.

    Raises:
        401: Not authenticated.
        403: Missing `blueprint:write` permission.
        409: Blueprint with the same name and type already exists.
    """
    try:
        await db.merge(blueprint)
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Blueprint with name {blueprint.name!r} and type '
            f'{blueprint.type!r} already exists',
        ) from e
    try:
        await openapi.refresh_blueprint_models(db)
    except Exception:
        LOGGER.exception('Failed to refresh blueprint models')
    return blueprint


@blueprint_router.get('/', response_model=list[models.Blueprint])
async def list_blueprints(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('blueprint:read')),
    ],
    enabled: bool | None = None,
) -> list[models.Blueprint]:
    """
    Retrieve all blueprints, optionally filtered by enabled status.

    Parameters:
        enabled (bool | None): If provided, only return blueprints whose
            `enabled` field matches this value.

    Returns:
        list[Blueprint]: List of Blueprint models matching the query.
    """
    parameters: dict[str, typing.Any] = {}
    if enabled is not None:
        parameters['enabled'] = enabled

    return await db.match(
        models.Blueprint,
        parameters if parameters else None,
        order_by='name',
    )


@blueprint_router.get('/{type}', response_model=list[models.Blueprint])
async def list_blueprints_by_type(
    blueprint_type: typing.Annotated[
        typing.Literal['Team', 'Environment', 'ProjectType', 'Project'],
        fastapi.Path(alias='type'),
    ],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('blueprint:read')),
    ],
    enabled: bool | None = None,
) -> list[models.Blueprint]:
    """
    Retrieve all blueprints of the given type.

    Parameters:
        blueprint_type (Literal['Team', 'Environment',
            'ProjectType', 'Project']): Type of blueprint to return.
        enabled (bool | None): If provided, only include blueprints whose
            enabled status matches this value.

    Returns:
        list[models.Blueprint]: Blueprints of the specified type,
            ordered by name and filtered by `enabled` when given.
    """
    parameters: dict[str, typing.Any] = {
        'type': blueprint_type,
    }
    if enabled is not None:
        parameters['enabled'] = enabled

    return await db.match(models.Blueprint, parameters, order_by='name')


@blueprint_router.get('/{type}/{slug}', response_model=models.Blueprint)
async def get_blueprint(
    blueprint_type: typing.Annotated[
        typing.Literal['Team', 'Environment', 'ProjectType', 'Project'],
        fastapi.Path(alias='type'),
    ],
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('blueprint:read')),
    ],
) -> models.Blueprint:
    """
    Retrieve a blueprint identified by its type and slug.

    Parameters:
        slug (str): The blueprint slug (URL-safe identifier).

    Returns:
        models.Blueprint: The requested blueprint.

    Raises:
        404: If no blueprint exists with the given type and slug.
    """
    results = await db.match(
        models.Blueprint,
        {'slug': slug, 'type': blueprint_type},
    )
    blueprint = results[0] if results else None
    if blueprint is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Blueprint with slug {slug!r} and type '
            f'{blueprint_type!r} not found',
        )
    return blueprint


@blueprint_router.put('/{type}/{slug}', response_model=models.Blueprint)
async def update_blueprint(
    blueprint_type: typing.Annotated[
        typing.Literal['Team', 'Environment', 'ProjectType', 'Project'],
        fastapi.Path(alias='type'),
    ],
    slug: str,
    blueprint: models.Blueprint,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('blueprint:write')),
    ],
) -> models.Blueprint:
    """
    Update or create a blueprint (upsert).

    Validates that the URL `slug` and `type` match the provided
    `blueprint` payload before performing an upsert.

    Args:
        blueprint_type: Blueprint type from the URL path.
        slug: Blueprint slug from the URL path.
        blueprint: Blueprint payload to create or update.

    Returns:
        The created or updated Blueprint model.

    Raises:
        400: If the URL `slug` does not match `blueprint.slug` or the
            URL `type` does not match `blueprint.type`.
    """
    if blueprint.slug != slug or blueprint.type != blueprint_type:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Blueprint slug/type in body must match URL',
        )
    await db.merge(
        blueprint,
        match_on=['slug', 'type'],
    )
    try:
        await openapi.refresh_blueprint_models(db)
    except Exception:
        LOGGER.exception('Failed to refresh blueprint models')
    return blueprint


@blueprint_router.delete('/{type}/{slug}', status_code=204)
async def delete_blueprint(
    blueprint_type: typing.Annotated[
        typing.Literal['Team', 'Environment', 'ProjectType', 'Project'],
        fastapi.Path(alias='type'),
    ],
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('blueprint:delete')),
    ],
) -> None:
    """
    Delete a blueprint identified by its type and slug.

    Parameters:
        blueprint_type (Literal['Team', 'Environment',
            'ProjectType', 'Project']): The blueprint type.
        slug (str): The blueprint slug (URL-safe identifier).

    Raises:
        404: If no blueprint with the given type and slug exists.
    """
    query: typing.LiteralString = (
        'MATCH (n:Blueprint {{slug: {slug},'
        ' type: {blueprint_type}}})'
        ' DETACH DELETE n RETURN n'
    )
    records = await db.execute(
        query,
        {'slug': slug, 'blueprint_type': blueprint_type},
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Blueprint with slug {slug!r} and type '
            f'{blueprint_type!r} not found',
        )
    try:
        await openapi.refresh_blueprint_models(db)
    except Exception:
        LOGGER.exception('Failed to refresh blueprint models')
