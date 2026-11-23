"""The custom fields of tickets, which ``Ticket`` blueprints define.

A ``Ticket`` blueprint applies to a ticket when its filter matches the
type, the priority, and the labels of the ticket. Its properties are
the custom fields of the ticket. A create must give each required
field that has no default; a ``PATCH`` checks only the fields that it
sends. A value whose field stops matching stays in the row.
"""

import typing
from collections import abc

import fastapi
import jsonschema
import pydantic

from imbi.api import blueprint_attributes, blueprint_sections
from imbi.common import blueprints, graph, models


class _Values(pydantic.BaseModel):
    # A key that no blueprint declares is an error, not dropped.
    model_config = pydantic.ConfigDict(extra='forbid')


async def all_blueprints(db: graph.Graph) -> list[models.Blueprint]:
    """Return the enabled ``Ticket`` blueprints, by priority."""
    return await db.match(
        models.Blueprint,
        {'type': 'Ticket', 'enabled': True},
        order_by='priority',
    )


async def matched(
    db: graph.Graph, type: str, priority: str, labels: abc.Sequence[str]
) -> list[models.Blueprint]:
    """Return the enabled ``Ticket`` blueprints that match a ticket,
    by priority."""
    return await blueprints.matching_blueprints(
        db,
        'Ticket',
        {'ticket_type': type, 'priority': priority, 'label': list(labels)},
    )


async def for_new(
    db: graph.Graph,
    type: str,
    priority: str,
    labels: abc.Sequence[str],
    values: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Return the clean custom fields of a new ticket, with the defaults
    of the blueprints that match it, or raise 422 (see
    :func:`validate`)."""
    return validate(
        await matched(db, type, priority, labels), values, partial=False
    )


async def declared_values(
    db: graph.Graph,
    type: str,
    priority: str,
    labels: abc.Sequence[str],
    values: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    """Return the values whose keys the blueprints that match a ticket
    declare now. A hidden value (no matching blueprint declares its
    key) is dropped, so a copy of the values does not fail the check."""
    keys = {
        name
        for bp in await matched(db, type, priority, labels)
        for name in bp.json_schema.properties or {}
    }
    return {k: v for k, v in values.items() if k in keys}


async def filterable(
    db: graph.Graph,
) -> dict[str, blueprint_attributes.FilterableAttribute]:
    """Return the custom fields of every ``Ticket`` blueprint that the
    list can filter on."""
    return blueprint_attributes.resolve(await all_blueprints(db), None)


def sections(
    matches: list[models.Blueprint],
) -> list[blueprint_sections.BlueprintSection]:
    """Return the schema sections of the blueprints."""
    return [
        section
        for bp in matches
        if (section := blueprint_sections.build_section(bp, 'ticket'))
    ]


def validate(
    matches: list[models.Blueprint],
    values: dict[str, typing.Any],
    *,
    partial: bool,
) -> dict[str, typing.Any]:
    """Return the clean values, as JSON, or raise 422.

    A full check (a create) gives each missing field its default. With
    ``partial`` (a ``PATCH``), only the keys in ``values`` are checked,
    and a ``None`` value stays ``None`` (it clears the key).

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
    item_enums = _item_enums(matches)
    fields: dict[str, typing.Any] = {}
    for name, field in model.model_fields.items():
        annotation = field.rebuild_annotation()
        if name in item_enums:
            optional = type(None) in typing.get_args(annotation)
            annotation = item_enums[name]
            if optional:
                annotation = annotation | None
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
        'TicketCustomFields', __base__=_Values, **fields
    )
    sent = values
    if partial:
        # A None clears the key, also a hidden one that no matching
        # blueprint declares now.
        sent = {k: v for k, v in values.items() if v is not None}
    try:
        clean = model.model_validate(sent)
    except pydantic.ValidationError as e:
        raise _invalid(matches, e) from e
    result = clean.model_dump(mode='json', exclude_none=True)
    if nested := _nested_errors(matches, result):
        raise _detail([], nested)
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


def _item_enums(matches: list[models.Blueprint]) -> dict[str, typing.Any]:
    """Return a ``list[Literal[...]]`` for each array property whose
    items have a string enum. The shared helper checks only the item
    type."""
    result: dict[str, typing.Any] = {}
    for bp in matches:
        for name, prop in (bp.json_schema.properties or {}).items():
            result.pop(name, None)
            items = prop.items if prop.type == 'array' else None
            enum = getattr(items, 'enum', None)
            if enum and all(isinstance(v, str) for v in enum):
                result[name] = list[typing.Literal[tuple(enum)]]  # type: ignore[misc]
    return result


def _nested_errors(
    matches: list[models.Blueprint], values: dict[str, typing.Any]
) -> list[dict[str, str]]:
    """Check each object value against the nested schema of its field.
    The shared helper checks only that the value is a dict."""
    properties: dict[str, models.Schema] = {}
    for bp in matches:
        properties.update(bp.json_schema.properties or {})
    errors: list[dict[str, str]] = []
    for name, value in values.items():
        prop = properties.get(name)
        if prop is None or prop.type != 'object':
            continue
        schema = typing.cast(
            dict[str, typing.Any],
            prop.model_dump(  # pyright: ignore[reportUnknownMemberType]
                mode='json', by_alias=True, exclude_none=True
            ),
        )
        try:
            jsonschema.validate(value, schema)
        except jsonschema.ValidationError as err:
            errors.append({'field': name, 'message': err.message})
    return errors


def _invalid(
    matches: list[models.Blueprint], error: pydantic.ValidationError
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
    return _detail(missing, invalid)


def _detail(
    missing: list[dict[str, typing.Any]], invalid: list[dict[str, str]]
) -> fastapi.HTTPException:
    """Return the 422 of the D2 shape."""
    return fastapi.HTTPException(
        status_code=422,
        detail={
            'error': 'custom_fields_invalid',
            'message': 'The ticket is missing required custom fields'
            if missing
            else 'The custom fields of the ticket are not valid',
            'missing': missing,
            'invalid': invalid,
        },
    )
