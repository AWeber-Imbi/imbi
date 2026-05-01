"""Resolve which attribute policies apply to a project."""

from __future__ import annotations

from imbi_common import blueprints, graph, models
from imbi_common.scoring.models import AttributePolicy

_POLICY_QUERY = (
    'MATCH (p:ScoringPolicy '
    "{category: 'attribute', enabled: true})"
    ' OPTIONAL MATCH (p)-[:TARGETS]->(pt:ProjectType)'
    ' WITH p, collect(pt.slug) AS targets'
    ' WHERE p.attribute_name IN {attrs}'
    '   AND (size(targets) = 0'
    '        OR any(t IN targets WHERE t IN {project_types}))'
    ' RETURN p'
)


async def applicable_policies(
    database: graph.Graph,
    project: models.Project,
) -> list[AttributePolicy]:
    """Return attribute policies that target *project*."""
    extended = await blueprints.get_model(database, models.Project)
    attrs = sorted(extended.model_fields.keys())
    project_type_slugs = [pt.slug for pt in project.project_types]
    rows = await database.execute(
        _POLICY_QUERY,
        {'attrs': attrs, 'project_types': project_type_slugs},
    )
    policies: list[AttributePolicy] = []
    for row in rows:
        for value in row.values():
            props = graph.parse_agtype(value)
            if isinstance(props, dict):
                policies.append(AttributePolicy.model_validate(props))
    return policies
