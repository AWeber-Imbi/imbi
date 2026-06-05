"""Resolve which scoring policies apply to a project."""

from __future__ import annotations

import logging

import pydantic

from imbi_common import blueprints, graph, models
from imbi_common.scoring.models import (
    AgePolicy,
    AnalysisResultPolicy,
    AttributePolicy,
    DeploymentStatusPolicy,
    LinkPresencePolicy,
    PresencePolicy,
    ScoringPolicy,
)

LOGGER = logging.getLogger(__name__)

Policy = (
    AttributePolicy
    | PresencePolicy
    | LinkPresencePolicy
    | AgePolicy
    | AnalysisResultPolicy
    | DeploymentStatusPolicy
)

_TYPE_QUERY = (
    'MATCH (p:Project {{id: {id}}})-[:TYPE]->(pt:ProjectType)'
    ' RETURN pt.slug AS slug'
)

_POLICY_QUERY = (
    'MATCH (p:ScoringPolicy {{enabled: true}})'
    ' OPTIONAL MATCH (p)-[:TARGETS]->(pt:ProjectType)'
    ' RETURN p, collect(pt.slug) AS targets'
)

_POLICY_ADAPTER: pydantic.TypeAdapter[Policy] = pydantic.TypeAdapter(
    ScoringPolicy
)


async def applicable_policies(
    database: graph.Graph,
    project: models.Project,
) -> tuple[list[Policy], type[models.Project]]:
    """Return (policies, extended_model_class) for *project*.

    The extended model class includes all blueprint fields relevant to
    the project's type(s) and must be used to reload the project so
    that attribute values are available for scoring.

    ``db.match()`` only fetches scalar properties and strips edge
    fields, so ``project.project_types`` is always empty — type slugs
    are queried from the graph directly.
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
    result: list[Policy] = []
    for row in rows:
        props = graph.parse_agtype(row['p'])
        if not isinstance(props, dict):
            continue
        category = props.get('category') or 'attribute'
        if category in {'attribute', 'presence', 'age'}:
            if props.get('attribute_name') not in attrs:
                continue
        # 'analysis_result' policies key off an AnalysisResult slug — no
        # Project model attribute to gate on, so skip the attrs filter.
        targets: list[str] = graph.parse_agtype(row['targets']) or []
        if targets and not project_type_slugs.intersection(targets):
            continue
        props['targets'] = targets
        props['category'] = category
        try:
            policy = _POLICY_ADAPTER.validate_python(props)
        except pydantic.ValidationError as err:
            LOGGER.warning(
                'Skipping invalid scoring policy %s (category=%s): %s',
                props.get('slug') or props.get('id'),
                category,
                err,
            )
            continue
        result.append(policy)
    return result, extended
