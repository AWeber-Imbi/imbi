"""Resolve which attribute policies apply to a project."""

from __future__ import annotations

from imbi_common import blueprints, graph, models
from imbi_common.scoring.models import AttributePolicy

_TYPE_QUERY = (
    'MATCH (p:Project {{id: {id}}})-[:TYPE]->(pt:ProjectType)'
    ' RETURN pt.slug AS slug'
)

_POLICY_QUERY = (
    "MATCH (p:ScoringPolicy {{category: 'attribute', enabled: true}})"
    ' OPTIONAL MATCH (p)-[:TARGETS]->(pt:ProjectType)'
    ' RETURN p, collect(pt.slug) AS targets'
)


async def applicable_policies(
    database: graph.Graph,
    project: models.Project,
) -> tuple[list[AttributePolicy], type[models.Project]]:
    """Return (policies, extended_model_class) for *project*.

    The extended model class includes all blueprint fields relevant to the
    project's type(s) and must be used to reload the project so that
    attribute values are available for scoring.

    ``db.match()`` only fetches scalar properties and strips edge fields, so
    ``project.project_types`` is always empty — type slugs are queried from
    the graph directly.
    """
    type_rows = await database.execute(
        _TYPE_QUERY, {'id': project.id}, columns=['slug']
    )
    type_slugs = [s for r in type_rows if (s := graph.parse_agtype(r['slug']))]
    context: dict[str, str | list[str]] | None = (
        {'project_type': type_slugs} if type_slugs else None
    )
    extended = await blueprints.get_model(
        database, models.Project, context=context
    )
    attrs = set(extended.model_fields.keys())
    project_type_slugs = set(type_slugs)
    rows = await database.execute(_POLICY_QUERY, columns=['p', 'targets'])
    result: list[AttributePolicy] = []
    for row in rows:
        props = graph.parse_agtype(row['p'])
        if not isinstance(props, dict):
            continue
        if props.get('attribute_name') not in attrs:
            continue
        targets: list[str] = graph.parse_agtype(row['targets']) or []
        if targets and not project_type_slugs.intersection(targets):
            continue
        props['targets'] = targets
        result.append(AttributePolicy.model_validate(props))
    return result, extended
