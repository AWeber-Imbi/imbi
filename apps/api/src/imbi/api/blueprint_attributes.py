"""Resolve filterable project attributes from blueprints.

Blueprint ``node`` schemas for the ``Project`` type contribute the
dynamic properties stored on each project vertex (e.g. ``framework``,
``programming_language``). This module flattens those schemas into a
catalog of filterable attributes, scoped to a project type.

Both the ``include_schema`` flag on the project-type listing (which
advertises the catalog) and the ``filter`` parameter on the project
listing (which validates filter fields against it) share this
resolver, so the advertised and accepted attribute sets cannot drift.
"""

import pydantic
from imbi_common import graph, models


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
