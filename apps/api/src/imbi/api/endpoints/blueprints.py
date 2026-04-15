"""Blueprint CRUD endpoints"""

import logging
import typing

import fastapi
import psycopg.errors
import pydantic
from imbi_common import graph, models

from imbi_api import openapi
from imbi_api import patch as json_patch
from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

blueprint_router = fastapi.APIRouter(prefix='/blueprints', tags=['Blueprints'])

# The virtual type used in URL paths for relationship blueprints.
_RELATIONSHIP = 'relationship'

BlueprintType = typing.Literal[
    'Team',
    'Environment',
    'ProjectType',
    'Project',
    'Organization',
    'ThirdPartyService',
    'relationship',
]


def _match_params(
    path_type: str,
    slug: str,
) -> dict[str, typing.Any]:
    """Build graph match parameters from a URL path type + slug.

    Node blueprints use ``type`` + ``slug``; relationship
    blueprints use ``kind='relationship'`` + ``slug``.
    """
    if path_type == _RELATIONSHIP:
        return {'kind': _RELATIONSHIP, 'slug': slug}
    return {'type': path_type, 'slug': slug}


@blueprint_router.post(
    '/',
    response_model=models.Blueprint,
    status_code=201,
)
async def create_blueprint(
    blueprint: models.Blueprint,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('blueprint:write'),
        ),
    ],
) -> models.Blueprint:
    """Create a new blueprint node in the graph database."""
    try:
        await db.merge(blueprint)
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'Blueprint with name {blueprint.name!r} already exists'),
        ) from e
    try:
        await openapi.refresh_blueprint_models(db)
    except Exception:
        LOGGER.exception('Failed to refresh blueprint models')
    return blueprint


@blueprint_router.get(
    '/',
    response_model=list[models.Blueprint],
)
async def list_blueprints(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('blueprint:read'),
        ),
    ],
    enabled: bool | None = None,
) -> list[models.Blueprint]:
    """Retrieve all blueprints, optionally filtered."""
    parameters: dict[str, typing.Any] = {}
    if enabled is not None:
        parameters['enabled'] = enabled

    return await db.match(
        models.Blueprint,
        parameters if parameters else None,
        order_by='name',
    )


@blueprint_router.get(
    '/{type}',
    response_model=list[models.Blueprint],
)
async def list_blueprints_by_type(
    blueprint_type: typing.Annotated[
        BlueprintType,
        fastapi.Path(alias='type'),
    ],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('blueprint:read'),
        ),
    ],
    enabled: bool | None = None,
) -> list[models.Blueprint]:
    """Retrieve blueprints filtered by node type or relationship."""
    parameters: dict[str, typing.Any] = {}
    if blueprint_type == _RELATIONSHIP:
        parameters['kind'] = _RELATIONSHIP
    else:
        parameters['type'] = blueprint_type
    if enabled is not None:
        parameters['enabled'] = enabled

    return await db.match(models.Blueprint, parameters, order_by='name')


@blueprint_router.get(
    '/{type}/{slug}',
    response_model=models.Blueprint,
)
async def get_blueprint(
    blueprint_type: typing.Annotated[
        BlueprintType,
        fastapi.Path(alias='type'),
    ],
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('blueprint:read'),
        ),
    ],
) -> models.Blueprint:
    """Retrieve a blueprint by type (or 'relationship') and slug."""
    results = await db.match(
        models.Blueprint,
        _match_params(blueprint_type, slug),
    )
    blueprint = results[0] if results else None
    if blueprint is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Blueprint with slug {slug!r} and '
                f'type {blueprint_type!r} not found'
            ),
        )
    return blueprint


@blueprint_router.put(
    '/{type}/{slug}',
    response_model=models.Blueprint,
)
async def update_blueprint(
    blueprint_type: typing.Annotated[
        BlueprintType,
        fastapi.Path(alias='type'),
    ],
    slug: str,
    blueprint: models.Blueprint,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('blueprint:write'),
        ),
    ],
) -> models.Blueprint:
    """Update or create a blueprint (upsert)."""
    if blueprint.slug != slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Blueprint slug in body must match URL',
        )
    if blueprint_type == _RELATIONSHIP:
        if blueprint.kind != _RELATIONSHIP:
            raise fastapi.HTTPException(
                status_code=400,
                detail='Blueprint kind must be relationship',
            )
        match_on = ['slug', 'kind']
    else:
        if blueprint.type != blueprint_type:
            raise fastapi.HTTPException(
                status_code=400,
                detail='Blueprint type in body must match URL',
            )
        match_on = ['slug', 'type']
    await db.merge(blueprint, match_on=match_on)
    try:
        await openapi.refresh_blueprint_models(db)
    except Exception:
        LOGGER.exception('Failed to refresh blueprint models')
    return blueprint


@blueprint_router.patch(
    '/{type}/{slug}',
    response_model=models.Blueprint,
)
async def patch_blueprint(
    blueprint_type: typing.Annotated[
        BlueprintType,
        fastapi.Path(alias='type'),
    ],
    slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('blueprint:write'),
        ),
    ],
) -> models.Blueprint:
    """Partially update a blueprint using JSON Patch (RFC 6902).

    Parameters:
        blueprint_type: Blueprint type from URL (or 'relationship').
        slug: Blueprint slug from URL.
        operations: JSON Patch operations.

    Returns:
        The updated blueprint.

    Raises:
        400: Invalid patch, read-only path, or slug/type mismatch.
        404: Blueprint not found.
        422: Patch test failed or validation error.

    """
    results = await db.match(
        models.Blueprint,
        _match_params(blueprint_type, slug),
    )
    existing = results[0] if results else None
    if existing is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Blueprint with slug {slug!r} and '
                f'type {blueprint_type!r} not found'
            ),
        )

    current = existing.model_dump(mode='json')
    current.pop('created_at', None)
    current.pop('updated_at', None)

    patched = json_patch.apply_patch(current, operations)

    if patched.get('slug') != slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Blueprint slug cannot be changed via PATCH',
        )
    if blueprint_type == _RELATIONSHIP:
        if patched.get('kind') != _RELATIONSHIP:
            raise fastapi.HTTPException(
                status_code=400,
                detail='Blueprint kind must remain relationship',
            )
        match_on = ['slug', 'kind']
    else:
        if patched.get('type') != blueprint_type:
            raise fastapi.HTTPException(
                status_code=400,
                detail='Blueprint type cannot be changed via PATCH',
            )
        match_on = ['slug', 'type']

    try:
        blueprint = models.Blueprint(**patched)
    except pydantic.ValidationError as e:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Validation error: {e.errors()}',
        ) from e

    await db.merge(blueprint, match_on=match_on)
    try:
        await openapi.refresh_blueprint_models(db)
    except Exception:
        LOGGER.exception('Failed to refresh blueprint models')
    return blueprint


@blueprint_router.delete('/{type}/{slug}', status_code=204)
async def delete_blueprint(
    blueprint_type: typing.Annotated[
        BlueprintType,
        fastapi.Path(alias='type'),
    ],
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('blueprint:delete'),
        ),
    ],
) -> None:
    """Delete a blueprint by type (or 'relationship') and slug."""
    if blueprint_type == _RELATIONSHIP:
        match_clause = (
            "MATCH (n:Blueprint {{slug: {slug}, kind: 'relationship'}})"
        )
    else:
        match_clause = (
            'MATCH (n:Blueprint {{slug: {slug}, type: {blueprint_type}}})'
        )
    query: typing.LiteralString = match_clause + ' DETACH DELETE n RETURN n'
    records = await db.execute(
        query,
        {
            'slug': slug,
            'blueprint_type': blueprint_type,
        },
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Blueprint with slug {slug!r} and '
                f'type {blueprint_type!r} not found'
            ),
        )
    try:
        await openapi.refresh_blueprint_models(db)
    except Exception:
        LOGGER.exception('Failed to refresh blueprint models')
