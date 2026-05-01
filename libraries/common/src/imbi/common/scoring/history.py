"""Persist score changes: ClickHouse first, then AGE."""

from __future__ import annotations

import datetime
import typing

from imbi_common import graph, models
from imbi_common.clickhouse import client as ch_client

_HISTORY_COLUMNS = [
    'project_id',
    'timestamp',
    'score',
    'previous_score',
    'change_reason',
]


# Hard invariant: write CH history first, then update AGE Project.score.
async def record_score_change(
    clickhouse: ch_client.Clickhouse,
    database: graph.Graph,
    project: models.Project,
    new_score: float,
    previous_score: float,
    change_reason: str,
) -> None:
    """Append a history row, then update the project's materialized score.

    Skipped when ``new_score == previous_score`` (exact equality).
    """
    if new_score == previous_score:
        return
    row: list[typing.Any] = [
        project.id,
        datetime.datetime.now(datetime.UTC),
        new_score,
        previous_score,
        change_reason,
    ]
    await clickhouse.insert('score_history', [row], _HISTORY_COLUMNS)
    await database.execute(
        'MATCH (p:Project {id: {id}}) SET p.score = {score}',
        {'id': project.id, 'score': new_score},
    )
