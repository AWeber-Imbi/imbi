"""High-level entry point for computing a project's score."""

from __future__ import annotations

from imbi_common import graph, models
from imbi_common.scoring import attribute, policies
from imbi_common.scoring.models import ScoreBreakdown


async def compute_score(
    database: graph.Graph,
    project_id: str,
) -> tuple[float, ScoreBreakdown]:
    """Compute the floored score and breakdown for *project_id*."""
    matches = await database.match(models.Project, {'id': project_id})
    if not matches:
        raise ValueError(f'project {project_id!r} not found')
    project = matches[0]
    return await _compute(database, project)


async def _compute(
    database: graph.Graph,
    project: models.Project,
) -> tuple[float, ScoreBreakdown]:
    applicable = await policies.applicable_policies(database, project)
    base_score, contributions = attribute.compute_base_score(
        project, applicable
    )
    floored = max(0.0, base_score)
    breakdown = ScoreBreakdown(
        base_score=base_score,
        unfloored_total=base_score,
        attribute_contributions=contributions,
    )
    return floored, breakdown
