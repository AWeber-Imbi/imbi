"""OpenAPI schema customization with blueprint-enhanced models.

This module generates OpenAPI documentation with separate request
and response schemas:

- **Request schemas**: Write model + blueprints (writable fields
  only — no timestamps, relationships, or expanded sub-objects)
- **Response schemas**: Write model + blueprints + relationships
  + timestamps

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

# Cache for blueprint-enhanced write models
_blueprint_models: dict[str, type[pydantic.BaseModel]] = {}

# Cache for blueprint-enhanced response models
_response_models: dict[str, type[pydantic.BaseModel]] = {}

# Cache for the generated OpenAPI schema
_schema_cache: dict[str, typing.Any] | None = None

# Mapping of API paths to their model types
PATH_MODEL_MAPPING: dict[str, str] = {
    '/organizations/{org_slug}/teams/': 'Team',
    '/organizations/{org_slug}/teams/{slug}': 'Team',
    '/organizations/{org_slug}/environments/': 'Environment',
    '/organizations/{org_slug}/environments/{slug}': 'Environment',
    '/organizations/{org_slug}/project-types/': 'ProjectType',
    '/organizations/{org_slug}/project-types/{slug}': 'ProjectType',
    '/projects/': 'Project',
    '/projects/{project_type_slug}/{slug}': 'Project',
}


async def generate_blueprint_models() -> tuple[
    dict[str, type[pydantic.BaseModel]],
    dict[str, type[pydantic.BaseModel]],
]:
    """Generate write and response models for all MODEL_TYPES.

    Returns:
        Tuple of (write_models, response_models) dictionaries.

    """
    write_models: dict[str, type[pydantic.BaseModel]] = {}
    response_models: dict[str, type[pydantic.BaseModel]] = {}

    for model_name, model_class in imbi_common.models.MODEL_TYPES.items():
        try:
            write_model = await imbi_common.blueprints.get_model(model_class)
            write_models[model_name] = write_model
            response_models[model_name] = (
                imbi_common.blueprints.make_response_model(write_model)
            )
            LOGGER.debug(
                'Generated blueprint models for %s',
                model_name,
            )
        except Exception:
            LOGGER.exception(
                'Failed to generate blueprint model for %s',
                model_name,
            )
            write_models[model_name] = model_class
            response_models[model_name] = (
                imbi_common.blueprints.make_response_model(model_class)
            )

    return write_models, response_models


async def refresh_blueprint_models() -> dict[str, type[pydantic.BaseModel]]:
    """Refresh the cached blueprint models.

    Call this at startup and when blueprints change.

    Returns:
        The updated dictionary of blueprint-enhanced write
        models.

    """
    global _blueprint_models, _response_models, _schema_cache

    LOGGER.info('Refreshing blueprint models for OpenAPI schema')
    _blueprint_models, _response_models = await generate_blueprint_models()

    _schema_cache = None

    LOGGER.info(
        'Refreshed %d blueprint models',
        len(_blueprint_models),
    )
    return _blueprint_models


def get_blueprint_models() -> dict[str, type[pydantic.BaseModel]]:
    """Get the currently cached write models."""
    return _blueprint_models


def create_custom_openapi(
    app: fastapi.FastAPI,
) -> typing.Callable[[], dict[str, typing.Any]]:
    """Create a custom OpenAPI generator with separate schemas.

    Generates OpenAPI schema with:
    1. Write schemas for request bodies (no read-only fields)
    2. Response schemas with relationships and timestamps

    """

    def custom_openapi() -> dict[str, typing.Any]:
        global _schema_cache

        if _schema_cache is not None:
            return _schema_cache

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

        if 'components' not in openapi_schema:
            openapi_schema['components'] = {}
        if 'schemas' not in openapi_schema['components']:
            openapi_schema['components']['schemas'] = {}

        schemas = typing.cast(
            dict[str, typing.Any],
            openapi_schema['components']['schemas'],
        )

        if _blueprint_models:
            for model_name in _blueprint_models:
                write_model = _blueprint_models[model_name]
                resp_model = _response_models[model_name]

                # Write schema (for request bodies)
                write_name = f'{model_name}Request'
                try:
                    schemas[write_name] = write_model.model_json_schema(
                        ref_template=('#/components/schemas/{model}')
                    )
                except Exception:
                    LOGGER.exception(
                        'Failed to generate write schema for %s',
                        model_name,
                    )

                # Response schema (with relationships)
                resp_name = f'{model_name}Response'
                try:
                    schemas[resp_name] = resp_model.model_json_schema(
                        ref_template=('#/components/schemas/{model}')
                    )
                except Exception:
                    LOGGER.exception(
                        'Failed to generate response schema for %s',
                        model_name,
                    )

            _hoist_defs_to_components(schemas)
            _rewrite_path_schemas(openapi_schema)

        _schema_cache = openapi_schema
        return openapi_schema

    return custom_openapi


def _hoist_defs_to_components(
    schemas: dict[str, typing.Any],
) -> None:
    """Move embedded ``$defs`` to top-level component schemas.

    ``model_json_schema(ref_template='#/components/schemas/{model}')``
    generates ``$ref`` values pointing to ``#/components/schemas/X``
    but embeds the actual definitions in a local ``$defs`` block.
    This hoists those definitions so the references resolve
    correctly when consumers (e.g. fastmcp) extract individual
    schemas.

    """
    for schema in list(schemas.values()):
        defs = schema.pop('$defs', None)
        if not defs:
            continue
        for def_name, def_schema in defs.items():
            if def_name not in schemas:
                schemas[def_name] = def_schema


def _rewrite_path_schemas(
    openapi_schema: dict[str, typing.Any],
) -> None:
    """Rewrite path schemas for request and response.

    Request bodies use write schemas (writable fields only).
    Response bodies use response schemas (with relationships).

    """
    paths: dict[str, typing.Any] = openapi_schema.get(
        'paths',
        {},
    )

    for path, model_type in PATH_MODEL_MAPPING.items():
        if path not in paths:
            continue

        request_ref = {
            '$ref': (f'#/components/schemas/{model_type}Request'),
        }
        response_ref = {
            '$ref': (f'#/components/schemas/{model_type}Response'),
        }
        array_ref: dict[str, typing.Any] = {
            'type': 'array',
            'items': response_ref,
        }

        path_ops: dict[str, typing.Any] = paths[path]
        for method, operation in path_ops.items():
            if not isinstance(operation, dict):
                continue

            op = typing.cast(dict[str, typing.Any], operation)

            if method in ('post', 'put', 'patch'):
                _rewrite_request_body(op, request_ref)

            _rewrite_response_schemas(
                op,
                path,
                method,
                response_ref,
                array_ref,
            )


def _rewrite_request_body(
    operation: dict[str, typing.Any],
    schema_ref: dict[str, str],
) -> None:
    """Rewrite request body schema."""
    request_body = operation.get('requestBody')
    if not isinstance(request_body, dict):
        return
    rb = typing.cast(dict[str, typing.Any], request_body)

    content = rb.get('content')
    if not isinstance(content, dict):
        return
    ct = typing.cast(dict[str, typing.Any], content)

    json_content = ct.get('application/json')
    if isinstance(json_content, dict):
        json_content['schema'] = schema_ref


def _rewrite_response_schemas(
    operation: dict[str, typing.Any],
    path: str,
    method: str,
    single_ref: dict[str, str],
    array_ref: dict[str, typing.Any],
) -> None:
    """Rewrite response schemas to reference response models."""
    responses = operation.get('responses')
    if not isinstance(responses, dict):
        return
    resp_map = typing.cast(dict[str, typing.Any], responses)

    for status in ('200', '201'):
        response = resp_map.get(status)
        if not isinstance(response, dict):
            continue
        resp = typing.cast(dict[str, typing.Any], response)

        content = resp.get('content')
        if not isinstance(content, dict):
            continue
        ct = typing.cast(dict[str, typing.Any], content)

        json_content = ct.get('application/json')
        if not isinstance(json_content, dict):
            continue

        if path.endswith('/') and method == 'get':
            json_content['schema'] = array_ref
        else:
            json_content['schema'] = single_ref


def clear_schema_cache() -> None:
    """Clear the cached OpenAPI schema."""
    global _schema_cache
    _schema_cache = None
    LOGGER.debug('Cleared OpenAPI schema cache')
