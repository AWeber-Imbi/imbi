"""The check of the values that blueprints define: the custom fields
of a ticket and the fields of a deployment."""

import typing

import fastapi
import jsonschema.exceptions
import jsonschema.validators
import pydantic
import referencing
import referencing.exceptions

from imbi.api import blueprint_sections
from imbi.common import blueprints, models


class _Values(pydantic.BaseModel):
    # A key that no blueprint declares is an error, not dropped.
    model_config = pydantic.ConfigDict(extra='forbid')


def validate(
    matches: list[models.Blueprint],
    values: dict[str, typing.Any],
    *,
    partial: bool,
    noun: str = 'ticket',
) -> dict[str, typing.Any]:
    """Return the clean values, as JSON, or raise 422.

    A full check (a create) gives each missing field its default. With
    ``partial`` (a ``PATCH``), only the keys in ``values`` are checked,
    and a ``None`` value stays ``None`` (it clears the key). ``noun``
    names the object in the error message.

    Raises:
        422: ``custom_fields_invalid``, with ``missing`` (the property
            of each required field that has no value) and ``invalid``
            (each field with a bad value, or that no blueprint
            declares).

    """
    if not matches and not values:
        return {}
    model = blueprints.apply_blueprints(_Values, matches)
    bounds = _bounds(matches)
    fields: dict[str, typing.Any] = {}
    for name, field in model.model_fields.items():
        annotation = field.rebuild_annotation()
        if name in bounds:
            annotation = typing.Annotated[annotation, bounds[name]]
        # A create also checks the blueprint defaults.
        fields[name] = (
            annotation,
            None
            if partial
            else pydantic.Field(default=field.default, validate_default=True),
        )
    model = pydantic.create_model(
        'BlueprintValues', __base__=_Values, **fields
    )
    sent = values
    if partial:
        # A None clears the key, also a hidden one that no matching
        # blueprint declares now.
        sent = {k: v for k, v in values.items() if v is not None}
    try:
        clean = model.model_validate(sent)
    except pydantic.ValidationError as e:
        raise _invalid(matches, e, noun) from e
    result = clean.model_dump(mode='json', exclude_none=True)
    # The model converts an array item in lax mode ("3" to 3), so the
    # schema check uses the sent value when there is one.
    raw = {k: sent.get(k, v) for k, v in result.items()}
    if nested := _schema_errors(matches, raw):
        raise _detail([], nested, noun)
    if partial:
        return {k: result.get(k) for k in values}
    return result


def _bounds(matches: list[models.Blueprint]) -> dict[str, typing.Any]:
    """Return the numeric bounds of each property that has one, as a
    :func:`pydantic.Field`."""
    result: dict[str, typing.Any] = {}
    for bp in matches:
        for name, prop in (bp.json_schema.properties or {}).items():
            result.pop(name, None)
            if any(
                v is not None
                for v in (
                    prop.minimum,
                    prop.maximum,
                    prop.exclusive_minimum,
                    prop.exclusive_maximum,
                )
            ):
                result[name] = pydantic.Field(
                    ge=prop.minimum,
                    le=prop.maximum,
                    gt=prop.exclusive_minimum,
                    lt=prop.exclusive_maximum,
                )
    return result


def _schema_errors(
    matches: list[models.Blueprint], values: dict[str, typing.Any]
) -> list[dict[str, str]]:
    """Check each object or array value against the full schema of its
    field. The shared helper checks only that the value is a dict, or
    the type of each array item.

    The value is checked against the schema of its field only, so the
    constraints of the root object (``required``, ``minProperties``)
    do not apply. A local ``$ref`` resolves against the whole schema of
    the blueprint that declares the field. The registry is empty, so a
    remote ``$ref`` is never fetched: it is an error.
    """
    # The last blueprint that declares a field owns it.
    owners: dict[str, models.Blueprint] = {}
    for bp in matches:
        for name, prop in (bp.json_schema.properties or {}).items():
            owners.pop(name, None)
            types: list[typing.Any] = [prop.type]
            if isinstance(prop.type, list):
                types = prop.type
            if {'object', 'array'} & set(types):
                owners[name] = bp
    errors: list[dict[str, str]] = []
    for name, value in values.items():
        if name not in owners:
            continue
        schema = typing.cast(
            dict[str, typing.Any],
            owners[name].json_schema.model_dump(  # pyright: ignore[reportUnknownMemberType]
                mode='json', by_alias=True, exclude_none=True
            ),
        )
        cls = jsonschema.validators.validator_for(schema)
        cls.check_schema(schema)
        # descend() keeps the resolver of the root schema and enters
        # the $id scope of the field, if the field has one.
        validator = cls(schema, registry=referencing.Registry[typing.Any]())
        try:
            # descend() is public but not in the Validator protocol.
            best = typing.cast(
                jsonschema.exceptions.ValidationError | None,
                jsonschema.exceptions.best_match(  # pyright: ignore[reportUnknownMemberType]
                    validator.descend(  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType,reportUnknownArgumentType]
                        value, schema['properties'][name]
                    )
                ),
            )
        except referencing.exceptions.Unresolvable as err:
            errors.append({'field': name, 'message': f'Unresolvable: {err}'})
            continue
        if best is not None:
            errors.append({'field': name, 'message': best.message})
    return errors


def _invalid(
    matches: list[models.Blueprint],
    error: pydantic.ValidationError,
    noun: str,
) -> fastapi.HTTPException:
    """Return the 422 of the D2 shape for a failed check."""
    properties: dict[str, models.Schema] = {}
    for bp in matches:
        properties.update(bp.json_schema.properties or {})
    missing: list[dict[str, typing.Any]] = []
    invalid: list[dict[str, str]] = []
    for item in error.errors():
        field = str(item['loc'][0]) if item['loc'] else ''
        if item['type'] == 'missing':
            prop = blueprint_sections.section_property(properties[field])
            missing.append({'field': field, **prop.model_dump(mode='json')})
        else:
            invalid.append({'field': field, 'message': item['msg']})
    return _detail(missing, invalid, noun)


def _detail(
    missing: list[dict[str, typing.Any]],
    invalid: list[dict[str, str]],
    noun: str,
) -> fastapi.HTTPException:
    """Return the 422 of the D2 shape."""
    return fastapi.HTTPException(
        status_code=422,
        detail={
            'error': 'custom_fields_invalid',
            'message': f'The {noun} is missing required custom fields'
            if missing
            else f'The custom fields of the {noun} are not valid',
            'missing': missing,
            'invalid': invalid,
        },
    )
