"""Resolve filterable project attributes from blueprints.

Blueprint ``node`` schemas for the ``Project`` type contribute the
dynamic properties stored on each project vertex (e.g. ``framework``,
``programming_language``). This module flattens those schemas into a
catalog of filterable attributes, scoped to a project type.

Both the ``include_schema`` flag on the project-type listing (which
advertises the catalog) and the ``filter`` parameter on the project
listing (which validates filter fields against it) share this
resolver, so the advertised and accepted attribute sets cannot drift.
The ticket list filters ticket custom fields with the same parser.
"""

import contextlib
import math
import re
import typing

import fastapi
import pydantic

from imbi.common import graph, models


class FilterableAttribute(pydantic.BaseModel):
    """A single project attribute that can be filtered on."""

    field: str
    type: str | None = None
    format: str | None = None
    enum: list[str] | None = None


def resolve(
    blueprints: list[models.Blueprint],
    type_slug: str | None,
) -> dict[str, FilterableAttribute]:
    """Return filterable attributes keyed by field name.

    ``blueprints`` must be the enabled ``Project`` blueprints ordered
    by ascending priority; later blueprints override earlier ones for
    the same field name.

    When ``type_slug`` is given, only blueprints whose ``project_type``
    filter includes it (or that have no ``project_type`` filter) are
    considered. When ``type_slug`` is ``None`` the union across every
    project type is returned. The ``environment`` filter is ignored:
    the property exists on the project vertex regardless of which
    environments the project is deployed in.
    """
    out: dict[str, FilterableAttribute] = {}
    for bp in blueprints:
        if bp.kind != 'node':
            continue
        f = bp.filter
        if (
            type_slug is not None
            and f is not None
            and f.project_type
            and type_slug not in f.project_type
        ):
            continue
        properties = bp.json_schema.properties
        if not properties:
            continue
        for name, prop in properties.items():
            out[name] = FilterableAttribute(
                field=name,
                type=getattr(prop, 'type', None),
                format=getattr(prop, 'format', None),
                enum=getattr(prop, 'enum', None),
            )
    return out


async def project_blueprints(
    db: graph.Graph,
) -> list[models.Blueprint]:
    """Fetch enabled ``Project`` blueprints ordered by priority."""
    return await db.match(
        models.Blueprint,
        {'type': 'Project', 'enabled': True},
        order_by='priority',
    )


_FILTER_FIELD_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_FILTER_OPS = frozenset({'eq', 'ne', 'in', 'not_in', 'exists', 'not_exists'})


def _coerce_filter_value(
    attribute: FilterableAttribute,
    raw_value: str,
    raw_filter: str,
) -> typing.Any:
    """Coerce a filter value to the attribute's declared JSON type.

    Filter values arrive as strings from the query parameter, but
    boolean and numeric attributes are stored as their native agtype;
    binding the raw string would compare ``'true'`` to ``true`` and
    never match. Attributes without a boolean/integer/number type are
    bound as strings, unchanged.

    Raises:
        fastapi.HTTPException: 400 when the value cannot represent the
            attribute's type.
    """
    if attribute.type == 'boolean':
        if raw_value in ('true', 'false'):
            return raw_value == 'true'
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                f'Filter {raw_filter!r} requires a true/false value '
                f'for boolean attribute {attribute.field!r}'
            ),
        )
    if attribute.type in ('integer', 'number'):
        # int() first so large integers don't round-trip through
        # float and lose precision.
        with contextlib.suppress(ValueError):
            return int(raw_value)
        if attribute.type == 'integer':
            raise fastapi.HTTPException(
                status_code=400,
                detail=(
                    f'Filter {raw_filter!r} requires an integer '
                    f'value for integer attribute {attribute.field!r}'
                ),
            )
        try:
            number = float(raw_value)
        except ValueError:
            number = math.inf
        # agtype has no NaN/Infinity literal, so non-finite values
        # cannot be bound; reject them like unparseable input.
        if not math.isfinite(number):
            raise fastapi.HTTPException(
                status_code=400,
                detail=(
                    f'Filter {raw_filter!r} requires a finite numeric '
                    f'value for number attribute {attribute.field!r}'
                ),
            )
        return number
    return raw_value


#: A parsed filter: the field, the operator, and the values (none for
#: ``exists`` and ``not_exists``; one for ``eq`` and ``ne``).
Predicate = tuple[str, str, list[typing.Any]]


def parse_filters(
    filters: list[str], whitelist: dict[str, FilterableAttribute]
) -> list[Predicate]:
    """Parse ``field:op[:value]`` predicates.

    Field names are validated against ``whitelist`` and an identifier
    pattern, so a caller can put them in a query. Values are coerced
    to the attribute's declared type.

    Raises:
        fastapi.HTTPException: 400 on malformed predicates, unknown
            operators, non-filterable fields, or values that cannot
            represent the attribute's type.

    """
    parsed: list[Predicate] = []
    for raw in filters:
        field, _, rest = raw.partition(':')
        op, _, value = rest.partition(':')
        if not field or not op:
            raise fastapi.HTTPException(
                status_code=400,
                detail=f'Invalid filter {raw!r}; expected field:op[:value]',
            )
        if op not in _FILTER_OPS:
            raise fastapi.HTTPException(
                status_code=400,
                detail=(
                    f'Unknown filter operator {op!r}; valid operators are '
                    f'{", ".join(sorted(_FILTER_OPS))}'
                ),
            )
        if field not in whitelist or not _FILTER_FIELD_RE.match(field):
            raise fastapi.HTTPException(
                status_code=400,
                detail=f'Attribute {field!r} is not filterable',
            )
        if op in ('exists', 'not_exists'):
            if value:
                raise fastapi.HTTPException(
                    status_code=400,
                    detail=(
                        f'Filter {raw!r} does not accept a value for '
                        f'operator {op!r}'
                    ),
                )
            parsed.append((field, op, []))
            continue
        if op in ('eq', 'ne') and value == '':
            raise fastapi.HTTPException(
                status_code=400,
                detail=f'Filter {raw!r} requires a value',
            )
        values = (
            [v for v in value.split(',') if v]
            if op in ('in', 'not_in')
            else [value]
        )
        if not values:
            raise fastapi.HTTPException(
                status_code=400,
                detail=f'Filter {raw!r} requires a value',
            )
        parsed.append(
            (
                field,
                op,
                [
                    _coerce_filter_value(whitelist[field], item, raw)
                    for item in values
                ],
            )
        )
    return parsed
