import datetime
import typing

import pydantic

from imbi_common import models, neo4j


def _map_string_type(prop_schema: typing.Any) -> type[typing.Any]:
    """Map JSON Schema string format to appropriate Python type"""
    format_type = getattr(prop_schema, 'format', None)
    if format_type == 'email':
        return pydantic.EmailStr
    elif format_type in ('uri', 'url'):
        return pydantic.HttpUrl
    elif format_type == 'date-time':
        return datetime.datetime
    elif format_type == 'date':
        return datetime.date
    elif format_type == 'time':
        return datetime.time

    # Check for enum constraint
    enum_values = getattr(prop_schema, 'enum', None)
    if enum_values and isinstance(enum_values, list):
        # Create Literal type from enum values
        return typing.Literal[tuple(enum_values)]  # type: ignore[return-value]

    return str


def _map_array_type(prop_schema: typing.Any) -> type[typing.Any]:
    """Map JSON Schema array to appropriate list type"""
    items_schema = getattr(prop_schema, 'items', None)
    if not items_schema:
        return list

    items_type = getattr(items_schema, 'type', None)
    if items_type == 'string':
        return list[str]
    elif items_type == 'integer':
        return list[int]
    elif items_type == 'number':
        return list[float]
    elif items_type == 'boolean':
        return list[bool]
    else:
        return list


def _map_schema_type_to_python(prop_schema: typing.Any) -> type[typing.Any]:
    """Map JSON Schema type to Python type"""
    json_type = getattr(prop_schema, 'type', None)

    if json_type == 'string':
        return _map_string_type(prop_schema)
    elif json_type == 'integer':
        return int
    elif json_type == 'number':
        return float
    elif json_type == 'boolean':
        return bool
    elif json_type == 'array':
        return _map_array_type(prop_schema)
    elif json_type == 'object':
        return dict
    else:
        return typing.Any


async def get_model(
    model: type[pydantic.BaseModel],
) -> type[pydantic.BaseModel]:
    """Return a model class with blueprints applied"""
    blueprints: list[models.Blueprint] = []
    async for blueprint in neo4j.fetch_nodes(
        models.Blueprint,
        {'type': model.__name__, 'enabled': True},
        order_by='priority',
    ):
        blueprints.append(blueprint)

    kwargs: dict[str, typing.Any] = {}

    # Add all fields from the base model
    for field_name, field_info in model.model_fields.items():
        annotation = field_info.annotation
        kwargs[field_name] = (annotation, field_info)

    # Add fields from blueprints
    for blueprint in blueprints:
        if blueprint.json_schema.properties:
            for (
                prop_name,
                prop_schema,
            ) in blueprint.json_schema.properties.items():
                # Determine if field is required
                is_required = (
                    blueprint.json_schema.required is not None
                    and prop_name in blueprint.json_schema.required
                )

                # Map JSON Schema type to Python type
                field_type: typing.Any = _map_schema_type_to_python(
                    prop_schema
                )

                # Get metadata from schema
                schema_default = getattr(prop_schema, 'default', None)
                description = getattr(prop_schema, 'description', None)

                # Determine the field default
                if schema_default is not None:
                    default: typing.Any = schema_default
                elif not is_required:
                    field_type = field_type | None
                    default = None
                else:
                    default = ...

                # Create field with metadata if available
                if description or schema_default is not None:
                    field_info_obj = pydantic.Field(
                        default=default, description=description
                    )
                    kwargs[prop_name] = (field_type, field_info_obj)
                else:
                    kwargs[prop_name] = (field_type, default)

    return pydantic.create_model(
        model.__name__, __config__=model.model_config, **kwargs
    )
