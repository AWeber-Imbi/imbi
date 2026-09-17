"""Persist score changes: the Iggy stream first, then AGE."""

from __future__ import annotations

import datetime
import typing

from imbi.common import graph, iggy, models
from imbi.common.scoring.models import ScoreBreakdown


async def clear_score(
    database: graph.Graph,
    project: models.Project,
) -> None:
    """Remove the score property from the project node.

    The current ``project.score`` is moved to ``previous_score`` so the
    transition is observable, mirroring ``record_score_change``.
    """
    await database.execute(
        'MATCH (p:Project {{id: {id}}})'
        ' SET p.previous_score = {previous_score}, p.score = null'
        ' RETURN p',
        {'id': project.id, 'previous_score': project.score},
        columns=['p'],
    )


# Hard invariant: publish the history row first, then update AGE
# Project.score.
async def record_score_change(
    database: graph.Graph,
    project: models.Project,
    new_score: float,
    previous_score: float,
    change_reason: str,
    breakdown: ScoreBreakdown | None = None,
) -> None:
    """Append a history row, then update the project's materialized score.

    Skipped when ``new_score == previous_score`` (exact equality).
    """
    if new_score == previous_score:
        return
    breakdown_data = (
        breakdown.model_dump(mode='json') if breakdown is not None else {}
    )
    row: dict[str, typing.Any] = {
        'project_id': project.id,
        'timestamp': datetime.datetime.now(datetime.UTC),
        'score': new_score,
        'previous_score': previous_score,
        'change_reason': change_reason,
        'breakdown': breakdown_data,
    }
    await iggy.publish_rows('score_history', 'scoring', [row])
    await database.execute(
        'MATCH (p:Project {{id: {id}}})'
        ' SET p.score = {score}, p.previous_score = {previous_score}'
        ' RETURN p',
        {
            'id': project.id,
            'score': new_score,
            'previous_score': previous_score,
        },
        columns=['p'],
    )
