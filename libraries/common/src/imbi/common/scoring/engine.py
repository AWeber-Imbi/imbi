"""High-level entry point for computing a project's score."""

from __future__ import annotations

from imbi_common import graph, models
from imbi_common.scoring import attribute, policies
from imbi_common.scoring.models import ScoreBreakdown


async def compute_score(
    database: graph.Graph,
    project_id: str,
) -> tuple[float | None, ScoreBreakdown]:
    """Compute the floored score and breakdown for *project_id*.

    Returns ``(None, empty_breakdown)`` when no scoring policies apply to the
    project — the caller should clear any existing score rather than writing a
    new one.
    """
    matches = await database.match(models.Project, {'id': project_id})
    if not matches:
        raise ValueError(f'project {project_id!r} not found')
    project = matches[0]
    return await _compute(database, project)


async def _compute(
    database: graph.Graph,
    project: models.Project,
) -> tuple[float | None, ScoreBreakdown]:
    applicable, extended_cls = await policies.applicable_policies(
        database, project
    )
    if not applicable:
        return None, ScoreBreakdown(base_score=0.0, unfloored_total=0.0)
    # Reload with the extended model so blueprint attribute values are present.
    # db.match(models.Project) uses extra='ignore', silently dropping them.
    extended_matches = await database.match(extended_cls, {'id': project.id})
    if not extended_matches and extended_cls is not models.Project:
        raise ValueError(
            f'project {project.id!r} could not be reloaded as '
            f'{extended_cls.__name__}'
        )
    extended_project = extended_matches[0] if extended_matches else project
    base_score, contributions = attribute.compute_base_score(
        extended_project, applicable
    )
    floored = max(0.0, base_score)
    breakdown = ScoreBreakdown(
        base_score=base_score,
        unfloored_total=base_score,
        attribute_contributions=contributions,
    )
    return floored, breakdown
