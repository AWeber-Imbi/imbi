"""OpenAPI schema customization with blueprint-enhanced models.

This module provides functionality to generate OpenAPI documentation that
includes blueprint-enhanced model schemas. Since FastAPI evaluates
response_model at import time, we use a custom openapi() function to
inject dynamic schemas at runtime.

Usage:
    # In app.py lifespan:
    await openapi.refresh_blueprint_models()

    # In create_app():
    app.openapi = openapi.create_custom_openapi(app)
"""

import logging
import typing

import fastapi.openapi.utils
import imbi_common.blueprints
import imbi_common.models
import pydantic

LOGGER = logging.getLogger(__name__)

# Cache for blueprint-enhanced models
_blueprint_models: dict[str, type[pydantic.BaseModel]] = {}

# Cache for the generated OpenAPI schema
_schema_cache: dict[str, typing.Any] | None = None

# Mapping of API paths to their model types
# These paths will have their request/response schemas rewritten
PATH_MODEL_MAPPING: dict[str, str] = {
    '/organizations/': 'Organization',
    '/organizations/{slug}': 'Organization',
    '/teams/': 'Team',
    '/teams/{slug}': 'Team',
    '/environments/': 'Environment',
    '/environments/{slug}': 'Environment',
    '/project-types/': 'ProjectType',
    '/project-types/{slug}': 'ProjectType',
    '/projects/': 'Project',
    '/projects/{slug}': 'Project',
}


async def generate_blueprint_models() -> dict[str, type[pydantic.BaseModel]]:
    """Generate blueprint-enhanced models for all MODEL_TYPES.

    Returns:
        Dictionary mapping model type names to enhanced model classes.
    """
    models: dict[str, type[pydantic.BaseModel]] = {}

    for model_name, model_class in imbi_common.models.MODEL_TYPES.items():
        try:
            enhanced_model = await imbi_common.blueprints.get_model(
                model_class
            )
            models[model_name] = enhanced_model
            LOGGER.debug(
                'Generated blueprint model for %s with %d fields',
                model_name,
                len(enhanced_model.model_fields),
            )
        except Exception:
            LOGGER.exception(
                'Failed to generate blueprint model for %s', model_name
            )
            # Fall back to base model on error
            models[model_name] = model_class

    return models


async def refresh_blueprint_models() -> dict[str, type[pydantic.BaseModel]]:
    """Refresh the cached blueprint models.

    Call this at startup and when blueprints change.

    Returns:
        The updated dictionary of blueprint-enhanced models.
    """
    global _blueprint_models, _schema_cache

    LOGGER.info('Refreshing blueprint models for OpenAPI schema')
    _blueprint_models = await generate_blueprint_models()

    # Clear schema cache so it gets regenerated with new models
    _schema_cache = None

    LOGGER.info('Refreshed %d blueprint models', len(_blueprint_models))
    return _blueprint_models


def get_blueprint_models() -> dict[str, type[pydantic.BaseModel]]:
    """Get the currently cached blueprint models.

    Returns:
        Dictionary of blueprint-enhanced models, or empty dict if
        not yet refreshed.
    """
    return _blueprint_models


def create_custom_openapi(
    app: fastapi.FastAPI,
) -> typing.Callable[[], dict[str, typing.Any]]:
    """Create a custom OpenAPI generator that includes blueprint schemas.

    This function returns a callable that generates OpenAPI schema with:
    1. Blueprint-enhanced model schemas in components/schemas
    2. Path operations rewritten to reference the enhanced schemas

    Args:
        app: The FastAPI application instance.

    Returns:
        A callable that generates the OpenAPI schema dictionary.
    """

    def custom_openapi() -> dict[str, typing.Any]:
        global _schema_cache

        # Return cached schema if available
        if _schema_cache is not None:
            return _schema_cache

        # Generate base OpenAPI schema
        openapi_schema = fastapi.openapi.utils.get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            summary=app.summary,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
            servers=app.servers,
            terms_of_service=app.terms_of_service,
            contact=app.contact,
            license_info=app.license_info,
        )

        # Add blueprint-enhanced schemas to components
        if _blueprint_models:
            if 'components' not in openapi_schema:
                openapi_schema['components'] = {}
            if 'schemas' not in openapi_schema['components']:
                openapi_schema['components']['schemas'] = {}

            for model_name, model_class in _blueprint_models.items():
                schema_name = f'{model_name}WithBlueprints'
                try:
                    openapi_schema['components']['schemas'][schema_name] = (
                        model_class.model_json_schema(
                            ref_template='#/components/schemas/{model}'
                        )
                    )
                    LOGGER.debug(
                        'Added %s schema to OpenAPI components', schema_name
                    )
                except Exception:
                    LOGGER.exception(
                        'Failed to generate schema for %s', model_name
                    )

            # Rewrite path operations to reference blueprint schemas
            _rewrite_path_schemas(openapi_schema)

        _schema_cache = openapi_schema
        return openapi_schema

    return custom_openapi


def _rewrite_path_schemas(openapi_schema: dict[str, typing.Any]) -> None:
    """Rewrite path request/response schemas to reference blueprint models.

    This modifies the openapi_schema in place.

    Args:
        openapi_schema: The OpenAPI schema dictionary to modify.
    """
    paths = openapi_schema.get('paths', {})

    for path, model_type in PATH_MODEL_MAPPING.items():
        if path not in paths:
            continue

        schema_name = f'{model_type}WithBlueprints'
        single_ref = {'$ref': f'#/components/schemas/{schema_name}'}
        array_ref = {'type': 'array', 'items': single_ref}

        for method, operation in paths[path].items():
            if not isinstance(operation, dict):
                continue

            # Rewrite request body schema (for post/put/patch)
            if method in ('post', 'put', 'patch'):
                _rewrite_request_body(operation, single_ref)

            # Rewrite response schemas
            _rewrite_response_schemas(
                operation, path, method, single_ref, array_ref
            )


def _rewrite_request_body(
    operation: dict[str, typing.Any],
    schema_ref: dict[str, str],
) -> None:
    """Rewrite request body schema to reference blueprint model.

    Args:
        operation: The operation dictionary from OpenAPI paths.
        schema_ref: The $ref schema to use.
    """
    request_body = operation.get('requestBody')
    if not isinstance(request_body, dict):
        return

    content = request_body.get('content')
    if not isinstance(content, dict):
        return

    json_content = content.get('application/json')
    if isinstance(json_content, dict):
        json_content['schema'] = schema_ref


def _rewrite_response_schemas(
    operation: dict[str, typing.Any],
    path: str,
    method: str,
    single_ref: dict[str, str],
    array_ref: dict[str, typing.Any],
) -> None:
    """Rewrite response schemas to reference blueprint models.

    Args:
        operation: The operation dictionary from OpenAPI paths.
        path: The API path (used to determine if list endpoint).
        method: The HTTP method.
        single_ref: The $ref schema for single item responses.
        array_ref: The array schema for list responses.
    """
    responses = operation.get('responses')
    if not isinstance(responses, dict):
        return

    for status in ('200', '201'):
        response = responses.get(status)
        if not isinstance(response, dict):
            continue

        content = response.get('content')
        if not isinstance(content, dict):
            continue

        json_content = content.get('application/json')
        if not isinstance(json_content, dict):
            continue

        # Use array schema for list endpoints (GET on collection paths)
        if path.endswith('/') and method == 'get':
            json_content['schema'] = array_ref
        else:
            json_content['schema'] = single_ref


def clear_schema_cache() -> None:
    """Clear the cached OpenAPI schema.

    Call this when blueprints are modified to force schema regeneration.
    """
    global _schema_cache
    _schema_cache = None
    LOGGER.debug('Cleared OpenAPI schema cache')
