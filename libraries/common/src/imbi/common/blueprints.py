import datetime
import typing

import pydantic

from imbi_common import age, models


def _coerce_enum_case(
    enum_values: list[str],
) -> typing.Callable[[typing.Any], typing.Any]:
    """Return a validator that coerces values to match enum case."""
    lookup = {v.casefold(): v for v in enum_values}

    def _coerce(value: typing.Any) -> typing.Any:
        if isinstance(value, str):
            return lookup.get(value.casefold(), value)
        return value

    return _coerce


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
    if (
        enum_values
        and isinstance(enum_values, list)
        and all(isinstance(v, str) for v in enum_values)
    ):
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


def _apply_blueprints[ModelType: pydantic.BaseModel](
    model: type[ModelType], blueprints: list[models.Blueprint]
) -> type[ModelType]:
    kwargs: dict[str, typing.Any] = {}

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

                # Wrap enum string fields with a case-coercing
                # BeforeValidator so that incoming values are
                # matched case-insensitively against the
                # blueprint-defined enum values.
                enum_values = getattr(prop_schema, 'enum', None)
                if (
                    enum_values
                    and isinstance(enum_values, list)
                    and getattr(prop_schema, 'type', None) == 'string'
                    and all(isinstance(v, str) for v in enum_values)
                ):
                    field_type = typing.Annotated[
                        field_type,
                        pydantic.BeforeValidator(
                            _coerce_enum_case(enum_values)
                        ),
                    ]

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

    return pydantic.create_model(model.__name__, __base__=model, **kwargs)


def _matches_filter(
    blueprint: models.Blueprint,
    context: dict[str, str | list[str]] | None,
) -> bool:
    """Check if a blueprint's filter matches the given context.

    Filter semantics:
    - ``None`` filter (or empty lists) matches everything.
    - Each non-empty filter field must have a corresponding
      context value that appears in the filter's list.
    - All non-empty filter fields must match (AND).

    The ``project_type`` context value may be a list of slugs
    (for multi-type projects). A match occurs when any of
    the project's types appear in the blueprint's filter list.

    """
    bp_filter = blueprint.filter
    if bp_filter is None:
        return True
    if context is None:
        # No context — only unfiltered blueprints match.
        if bp_filter.project_type or bp_filter.environment:
            return False
        return True
    for field in ('project_type', 'environment'):
        allowed: list[str] = getattr(bp_filter, field)
        if not allowed:
            continue
        ctx_value = context.get(field)
        if ctx_value is None:
            return False
        # Support list values (multi-type): match if any
        # context value appears in the allowed list.
        if isinstance(ctx_value, list):
            if not any(v in allowed for v in ctx_value):
                return False
        elif ctx_value not in allowed:
            return False
    return True


async def get_model[ModelType: pydantic.BaseModel](
    model: type[ModelType],
    context: dict[str, str | list[str]] | None = None,
) -> type[ModelType]:
    """Return a model class with matching blueprints applied.

    Parameters:
        model: The base Pydantic model class to extend.
        context: Optional filter context. When provided, only
            blueprints whose ``filter`` matches this context
            are applied.  Blueprints with no filter are always
            included.  Example::

                {'project_type': 'apis'}
                {'project_type': 'apis',
                 'environment': 'production'}

    """
    all_blueprints: list[models.Blueprint] = []
    async for blueprint in age.fetch_nodes(
        models.Blueprint,
        {'type': model.__name__, 'enabled': True},
        order_by='priority',
    ):
        all_blueprints.append(blueprint)

    matched = [bp for bp in all_blueprints if _matches_filter(bp, context)]
    return _apply_blueprints(model, matched)


def make_response_model[ModelType: pydantic.BaseModel](
    write_model: type[ModelType],
) -> type[ModelType]:
    """Create a response model from a write model.

    Adds ``relationships`` to the write model for use in API
    responses. The write model already has timestamps and
    blueprint fields; this adds the response-only enrichments.

    """
    return pydantic.create_model(
        f'{write_model.__name__}Response',
        __base__=write_model,
        relationships=(
            dict[str, models.RelationshipLink] | None,
            None,
        ),
    )
