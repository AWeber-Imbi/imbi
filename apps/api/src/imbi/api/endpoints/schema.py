"""Schema generation endpoints for models with blueprints applied."""

import logging
import typing

import fastapi
from imbi_common import blueprints, models

from imbi_api import openapi
from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

schema_router = fastapi.APIRouter(tags=['Schema'])


@schema_router.get('/schema/{model_type}')
async def get_model_schema(
    model_type: typing.Literal[
        'Organization', 'Team', 'Environment', 'ProjectType', 'Project'
    ],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> dict[str, typing.Any]:
    """
    Get JSON schema for a specific model type with all enabled blueprints
    applied.

    The returned schema includes:
    - Base model fields (name, slug, description, etc.)
    - Custom fields from all enabled blueprints for this model type
    - Fields are merged in priority order (ascending)

    Parameters:
        model_type: The model type to generate schema for

    Returns:
        dict: JSON Schema (Draft 2020-12) for the model with blueprints applied

    Raises:
        401: Not authenticated
        422: Invalid model type (handled by FastAPI path validation)
    """
    LOGGER.debug('Generating schema for model type: %s', model_type)

    # Get the base model class
    model_class = models.MODEL_TYPES[model_type]

    # Apply blueprints to get dynamic model
    dynamic_model = await blueprints.get_model(model_class)

    # Generate and return JSON schema
    schema = typing.cast(
        dict[str, typing.Any], dynamic_model.model_json_schema()
    )

    LOGGER.debug(
        'Generated schema for %s with %d properties',
        model_type,
        len(schema.get('properties', {})),
    )

    return schema


@schema_router.get('/schemata')
async def get_all_schemas(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> dict[str, dict[str, typing.Any]]:
    """
    Get JSON schemas for all supported model types with blueprints applied.

    Returns a dictionary mapping model type names to their JSON schemas.
    Each schema includes base model fields plus custom fields from enabled
    blueprints.

    Returns:
        dict: Mapping of model type to JSON Schema
            Example:
            {
                "Organization": {...json schema...},
                "Team": {...json schema...},
                ...
            }

    Raises:
        401: Not authenticated
    """
    LOGGER.debug('Generating schemas for all model types')

    schemas = {}
    for model_type, model_class in models.MODEL_TYPES.items():
        # Apply blueprints to get dynamic model
        dynamic_model = await blueprints.get_model(model_class)

        # Generate JSON schema
        schemas[model_type] = dynamic_model.model_json_schema()

        LOGGER.debug(
            'Generated schema for %s with %d properties',
            model_type,
            len(schemas[model_type].get('properties', {})),
        )

    LOGGER.debug('Generated %d schemas total', len(schemas))

    return schemas


@schema_router.post('/schema/refresh', status_code=200)
async def refresh_schemas(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('blueprint:write')),
    ],
) -> dict[str, int]:
    """
    Refresh OpenAPI schema with current blueprint definitions.

    This endpoint regenerates the cached blueprint-enhanced models used in
    the OpenAPI documentation. Call this after creating, updating, or
    deleting blueprints to reflect changes in the API documentation.

    Returns:
        dict: Count of refreshed models
            Example: {"refreshed_models": 5}

    Raises:
        401: Not authenticated
        403: Missing blueprint:write permission
    """
    LOGGER.info(
        'Refreshing OpenAPI schema models, requested by %s',
        auth.user.email,
    )
    models_dict = await openapi.refresh_blueprint_models()
    return {'refreshed_models': len(models_dict)}
