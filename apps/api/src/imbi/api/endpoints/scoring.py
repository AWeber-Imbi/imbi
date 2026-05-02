"""Project score history, rollup, and rescore endpoints."""

from __future__ import annotations

import asyncio
import datetime
import logging
import typing

import fastapi
from imbi_common import clickhouse, graph, models

from imbi_api.auth import permissions
from imbi_api.domain import scoring as scoring_models
from imbi_api.endpoints.scoring_policies import load_policy
from imbi_api.scoring import OptionalValkeyClient
from imbi_api.scoring import queue as score_queue

LOGGER = logging.getLogger(__name__)

scoring_router = fastapi.APIRouter(tags=['Scoring'])


_GRANULARITY_EXPR = {
    'raw': 'timestamp',
    'hour': 'toStartOfHour(timestamp)',
    'day': 'toStartOfDay(timestamp)',
}


@scoring_router.get(
    '/organizations/{org_slug}/projects/{project_id}/score/history'
)
async def get_score_history(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('project:read')),
    ],
    granularity: typing.Literal['raw', 'hour', 'day'] = 'raw',
    from_: typing.Annotated[
        datetime.datetime | None, fastapi.Query(alias='from')
    ] = None,
    to: datetime.datetime | None = None,
) -> scoring_models.ScoreHistoryResponse:
    exists = await db.execute(
        'MATCH (p:Project {{id: {id}}})'
        '-[:OWNED_BY]->(:Team)'
        '-[:BELONGS_TO]->(:Organization {{slug: {org}}})'
        ' RETURN p.id AS id',
        {'id': project_id, 'org': org_slug},
        ['id'],
    )
    if not exists:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Project {project_id!r} not found',
        )
    bucket = _GRANULARITY_EXPR[granularity]
    where: list[str] = ['project_id = {project_id:String}']
    params: dict[str, typing.Any] = {'project_id': project_id}
    if from_ is not None:
        where.append('timestamp >= {from_ts:DateTime64(3)}')
        params['from_ts'] = from_
    if to is not None:
        where.append('timestamp <= {to_ts:DateTime64(3)}')
        params['to_ts'] = to
    where_sql = ' AND '.join(where)
    if granularity == 'raw':
        sql = (
            'SELECT timestamp, score, previous_score, change_reason'  # noqa: S608
            ' FROM score_history WHERE ' + where_sql + ' ORDER BY timestamp'
        )
    else:
        sql = (
            f'SELECT {bucket} AS ts, argMax(score, timestamp) AS score'  # noqa: S608
            ' FROM score_history WHERE '
            + where_sql
            + f' GROUP BY {bucket} ORDER BY ts'
        )
    rows = await clickhouse.query(sql, params)
    points: list[scoring_models.ScoreHistoryPoint] = []
    for row in rows:
        if granularity == 'raw':
            points.append(
                scoring_models.ScoreHistoryPoint(
                    timestamp=str(row['timestamp']),
                    score=float(row['score']),
                    previous_score=(
                        float(row['previous_score'])
                        if row.get('previous_score') is not None
                        else None
                    ),
                    change_reason=str(row.get('change_reason') or ''),
                )
            )
        else:
            points.append(
                scoring_models.ScoreHistoryPoint(
                    timestamp=str(row['ts']),
                    score=float(row['score']),
                )
            )
    return scoring_models.ScoreHistoryResponse(
        project_id=project_id,
        granularity=granularity,
        points=points,
    )


@scoring_router.get(
    '/organizations/{org_slug}/projects/{project_id}/score/trend'
)
async def get_score_trend(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('project:read')),
    ],
    days: int = 30,
) -> scoring_models.ScoreTrend:
    """Return the current score and its change over the last *days* days."""
    rows = await db.execute(
        'MATCH (p:Project {{id: {id}}})'
        '-[:OWNED_BY]->(:Team)'
        '-[:BELONGS_TO]->(:Organization {{slug: {org}}})'
        ' RETURN p.score AS score',
        {'id': project_id, 'org': org_slug},
        ['score'],
    )
    if not rows:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Project {project_id!r} not found'
        )
    raw_score = graph.parse_agtype(rows[0]['score'])
    current = float(raw_score) if raw_score is not None else None
    prev_rows = await clickhouse.query(
        'SELECT score FROM score_history'
        ' WHERE project_id = {project_id:String}'
        ' AND timestamp <= now() - INTERVAL {days:UInt16} DAY'
        ' ORDER BY timestamp DESC LIMIT 1',
        {'project_id': project_id, 'days': days},
    )
    previous = float(prev_rows[0]['score']) if prev_rows else None
    delta = (
        round(current - previous, 2)
        if current is not None and previous is not None
        else None
    )
    return scoring_models.ScoreTrend(
        current=current,
        previous=previous,
        delta=delta,
        period_days=days,
    )


_DIMENSION_QUERY: dict[str, typing.LiteralString] = {
    'team': (
        'MATCH (p:Project)-[:OWNED_BY]->(t:Team)'
        ' RETURN p.id AS project_id, t.slug AS dim_key'
    ),
    'project_type': (
        'MATCH (p:Project)-[:TYPE]->(pt:ProjectType)'
        ' RETURN p.id AS project_id, pt.slug AS dim_key'
    ),
    'organization': (
        'MATCH (p:Project)-[:OWNED_BY]->(:Team)'
        '-[:BELONGS_TO]->(o:Organization)'
        ' RETURN p.id AS project_id, o.slug AS dim_key'
    ),
}


@scoring_router.get('/scores/rollup')
async def score_rollup(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('project:read')),
    ],
    dimension: typing.Literal['team', 'project_type', 'organization'] = 'team',
) -> list[scoring_models.ScoreRollupRow]:
    """Return current-score rollup grouped by the requested dimension.

    Uses ``score_latest`` (one row per project, current score only)
    so projects with many history entries do not skew aggregates.
    """
    # Fetch project → dimension key mapping from the graph
    dim_records = await db.execute(
        _DIMENSION_QUERY[dimension], {}, ['project_id', 'dim_key']
    )
    project_dim: dict[str, str] = {}
    for rec in dim_records:
        pid = graph.parse_agtype(rec['project_id'])
        key = graph.parse_agtype(rec['dim_key'])
        if pid and key:
            project_dim[str(pid)] = str(key)

    if not project_dim:
        return []

    # Fetch current scores from ClickHouse (one row per project)
    sql = (
        'SELECT project_id,'
        ' latest_score,'
        ' last_updated'
        ' FROM score_latest'
        ' WHERE project_id IN {project_ids:Array(String)}'
    )
    ch_rows = await clickhouse.query(sql, {'project_ids': list(project_dim)})

    # Aggregate by dimension key in Python
    scores_by_key: dict[str, list[float]] = {}
    last_updated_by_key: dict[str, str | None] = {}
    for row in ch_rows:
        pid = str(row.get('project_id') or '')
        dim_key = project_dim.get(pid)
        if not dim_key:
            continue
        latest = float(row.get('latest_score') or 0.0)
        last_upd = (
            str(row['last_updated']) if row.get('last_updated') else None
        )
        scores_by_key.setdefault(dim_key, []).append(latest)
        existing_upd = last_updated_by_key.get(dim_key)
        if last_upd and (existing_upd is None or last_upd > existing_upd):
            last_updated_by_key[dim_key] = last_upd
        elif dim_key not in last_updated_by_key:
            last_updated_by_key[dim_key] = None

    out: list[scoring_models.ScoreRollupRow] = []
    for key in sorted(scores_by_key):
        project_scores = scores_by_key[key]
        out.append(
            scoring_models.ScoreRollupRow(
                dimension=dimension,
                key=key,
                latest_score=max(project_scores),
                avg_score=sum(project_scores) / len(project_scores),
                last_updated=last_updated_by_key.get(key),
            )
        )
    return out


@scoring_router.post('/scoring/rescore')
async def rescore(
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('scoring_policy:rescore_all')
        ),
    ],
    body: scoring_models.RescoreRequest | None = None,
) -> scoring_models.RescoreResponse:
    body = body or scoring_models.RescoreRequest()
    project_ids: list[str] = []
    if body.project_id:
        project_ids = [body.project_id]
    elif body.policy_slug:
        policy = await load_policy(db, body.policy_slug)
        if policy is None:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Policy {body.policy_slug!r} not found',
            )
        project_ids = await score_queue.affected_projects(db, policy)
    elif body.blueprint_slug:
        # Load the blueprint to access its filter, then resolve project ids
        # the same way _enqueue_for_blueprint does.
        bp_rows = await db.execute(
            'MATCH (b:Blueprint {{slug: {slug}}}) RETURN b',
            {'slug': body.blueprint_slug},
            ['b'],
        )
        if not bp_rows:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Blueprint {body.blueprint_slug!r} not found',
            )
        bp_raw = graph.parse_agtype(bp_rows[0]['b'])
        type_slugs: list[str] = []
        if isinstance(bp_raw, dict):
            bp_raw_dict: dict[str, typing.Any] = bp_raw  # type: ignore[assignment]
            raw_filter: object = bp_raw_dict.get('filter')
            if isinstance(raw_filter, dict):
                raw_pt = raw_filter.get('project_type') or []  # type: ignore[union-attr]
                type_slugs = [str(s) for s in raw_pt]  # type: ignore[union-attr]
            elif isinstance(raw_filter, models.BlueprintFilter) and (
                raw_filter.project_type
            ):
                type_slugs = list(raw_filter.project_type)
        if type_slugs:
            id_lists = await asyncio.gather(
                *[score_queue.all_project_ids(db, ts) for ts in type_slugs]
            )
            project_ids = [pid for sub in id_lists for pid in sub]
        else:
            project_ids = await score_queue.all_project_ids(db)
    else:
        project_ids = await score_queue.all_project_ids(
            db, body.project_type_slug
        )
    requested_by = auth.user.email if auth.user else auth.principal_name
    results = await asyncio.gather(
        *[
            score_queue.enqueue_recompute(
                valkey_client, pid, 'bulk_rescore', requested_by=requested_by
            )
            for pid in project_ids
        ]
    )
    return scoring_models.RescoreResponse(enqueued=sum(results))
