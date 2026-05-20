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


@scoring_router.get('/scores/monthly-improvement')
async def score_monthly_improvement(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('project:read')),
    ],
    year: int = fastapi.Query(ge=2020, le=2100),
    month: int = fastapi.Query(ge=1, le=12),
    dimension: typing.Literal['team', 'project_type', 'organization'] = 'team',
) -> list[scoring_models.MonthlyImprovementRow]:
    """Return avg-score and improvement per dimension group for a month.

    Improvement = avg(last project score in *selected* month)
                - avg(last project score in *previous* month).
    Only projects scored in the selected month are counted.
    """
    cur_start = datetime.datetime(year, month, 1, tzinfo=datetime.UTC)
    if month == 12:
        nxt_start = datetime.datetime(year + 1, 1, 1, tzinfo=datetime.UTC)
    else:
        nxt_start = datetime.datetime(year, month + 1, 1, tzinfo=datetime.UTC)
    if month == 1:
        prev_start = datetime.datetime(year - 1, 12, 1, tzinfo=datetime.UTC)
    else:
        prev_start = datetime.datetime(year, month - 1, 1, tzinfo=datetime.UTC)

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

    pid_list = list(project_dim)

    cur_rows, prev_rows = await asyncio.gather(
        clickhouse.query(
            'SELECT project_id, argMax(score, timestamp) AS score'
            ' FROM score_history'
            ' WHERE project_id IN {pids:Array(String)}'
            ' AND timestamp >= {t0:DateTime64(3)}'
            ' AND timestamp < {t1:DateTime64(3)}'
            ' GROUP BY project_id',
            {'pids': pid_list, 't0': cur_start, 't1': nxt_start},
        ),
        clickhouse.query(
            'SELECT project_id, argMax(score, timestamp) AS score'
            ' FROM score_history'
            ' WHERE project_id IN {pids:Array(String)}'
            ' AND timestamp >= {t0:DateTime64(3)}'
            ' AND timestamp < {t1:DateTime64(3)}'
            ' GROUP BY project_id',
            {'pids': pid_list, 't0': prev_start, 't1': cur_start},
        ),
    )

    cur_scores: dict[str, float] = {
        str(r['project_id']): float(r['score']) for r in cur_rows
    }
    prev_scores: dict[str, float] = {
        str(r['project_id']): float(r['score']) for r in prev_rows
    }

    cur_by_key: dict[str, list[float]] = {}
    prev_by_key: dict[str, list[float]] = {}
    for pid, dim_key in project_dim.items():
        if pid in cur_scores:
            cur_by_key.setdefault(dim_key, []).append(cur_scores[pid])
        if pid in prev_scores:
            prev_by_key.setdefault(dim_key, []).append(prev_scores[pid])

    all_keys = sorted(cur_by_key)
    out: list[scoring_models.MonthlyImprovementRow] = []
    for key in all_keys:
        cur_list = cur_by_key.get(key, [])
        prev_list = prev_by_key.get(key, [])
        cur_avg = sum(cur_list) / len(cur_list) if cur_list else None
        prev_avg = sum(prev_list) / len(prev_list) if prev_list else None
        improvement = (
            round(cur_avg - prev_avg, 4)
            if cur_avg is not None and prev_avg is not None
            else None
        )
        out.append(
            scoring_models.MonthlyImprovementRow(
                dimension=dimension,
                key=key,
                current_avg_score=round(cur_avg, 4)
                if cur_avg is not None
                else None,
                previous_avg_score=round(prev_avg, 4)
                if prev_avg is not None
                else None,
                improvement=improvement,
                project_count=len(cur_list),
            )
        )
    return out


@scoring_router.get('/scores/history-by-team')
async def score_history_by_team(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('project:read')),
    ],
    granularity: typing.Literal['hour', 'day'] = 'day',
    from_: typing.Annotated[
        datetime.datetime | None, fastapi.Query(alias='from')
    ] = None,
    to: datetime.datetime | None = None,
) -> scoring_models.ScoreHistoryByTeamResponse:
    """Return avg score history per team, bucketed by granularity."""
    dim_records = await db.execute(
        _DIMENSION_QUERY['team'], {}, ['project_id', 'dim_key']
    )
    project_team: dict[str, str] = {}
    for rec in dim_records:
        pid = graph.parse_agtype(rec['project_id'])
        key = graph.parse_agtype(rec['dim_key'])
        if pid and key:
            project_team[str(pid)] = str(key)
    if not project_team:
        return scoring_models.ScoreHistoryByTeamResponse(
            granularity=granularity, teams=[]
        )
    bucket = _GRANULARITY_EXPR[granularity]
    where: list[str] = ['project_id IN {project_ids:Array(String)}']
    params: dict[str, typing.Any] = {'project_ids': list(project_team)}
    if from_ is not None:
        where.append('timestamp >= {from_ts:DateTime64(3)}')
        params['from_ts'] = from_
    if to is not None:
        where.append('timestamp <= {to_ts:DateTime64(3)}')
        params['to_ts'] = to
    where_sql = ' AND '.join(where)
    sql = (
        f'SELECT {bucket} AS ts, project_id,'  # noqa: S608
        ' argMax(score, timestamp) AS score'
        ' FROM score_history WHERE '
        + where_sql
        + ' GROUP BY ts, project_id ORDER BY ts'
    )
    rows = await clickhouse.query(sql, params)
    team_ts_scores: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        pid = str(row['project_id'])
        team = project_team.get(pid)
        if not team:
            continue
        ts = str(row['ts'])
        score = float(row['score'])
        team_ts_scores.setdefault(team, {}).setdefault(ts, []).append(score)
    teams: list[scoring_models.TeamScoreSeries] = []
    for team_key in sorted(team_ts_scores):
        ts_scores = team_ts_scores[team_key]
        points = [
            scoring_models.TeamScoreHistoryPoint(
                timestamp=ts,
                score=round(sum(scores) / len(scores), 4),
            )
            for ts, scores in sorted(ts_scores.items())
        ]
        teams.append(
            scoring_models.TeamScoreSeries(key=team_key, points=points)
        )
    return scoring_models.ScoreHistoryByTeamResponse(
        granularity=granularity, teams=teams
    )


@scoring_router.get('/scores/history-feed')
async def score_history_feed(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('project:read')),
    ],
    from_: typing.Annotated[
        datetime.datetime | None, fastapi.Query(alias='from')
    ] = None,
    to: datetime.datetime | None = None,
    limit: typing.Annotated[int, fastapi.Query(ge=1, le=500)] = 200,
) -> list[scoring_models.GlobalScoreEvent]:
    """Return recent raw score change events across all projects."""
    project_records = await db.execute(
        'MATCH (p:Project)-[:OWNED_BY]->(t:Team)'
        ' RETURN p.id AS project_id, p.name AS project_name,'
        ' t.slug AS team_slug',
        {},
        ['project_id', 'project_name', 'team_slug'],
    )
    project_info: dict[str, tuple[str, str]] = {}
    for rec in project_records:
        pid = graph.parse_agtype(rec['project_id'])
        name = graph.parse_agtype(rec['project_name'])
        team = graph.parse_agtype(rec['team_slug'])
        if pid and name and team:
            project_info[str(pid)] = (str(name), str(team))
    if not project_info:
        return []
    where: list[str] = [
        'project_id IN {project_ids:Array(String)}',
        "change_reason != ''",
    ]
    params: dict[str, typing.Any] = {'project_ids': list(project_info)}
    if from_ is not None:
        where.append('timestamp >= {from_ts:DateTime64(3)}')
        params['from_ts'] = from_
    if to is not None:
        where.append('timestamp <= {to_ts:DateTime64(3)}')
        params['to_ts'] = to
    params['limit'] = limit
    where_sql = ' AND '.join(where)
    sql = (
        'SELECT timestamp, project_id, score, previous_score, change_reason'  # noqa: S608
        ' FROM score_history WHERE '
        + where_sql
        + ' ORDER BY timestamp DESC LIMIT {limit:UInt32}'
    )
    rows = await clickhouse.query(sql, params)
    out: list[scoring_models.GlobalScoreEvent] = []
    for row in rows:
        pid = str(row['project_id'])
        info = project_info.get(pid)
        if not info:
            continue
        project_name, team_key = info
        out.append(
            scoring_models.GlobalScoreEvent(
                timestamp=str(row['timestamp']),
                project_id=pid,
                project_name=project_name,
                team_key=team_key,
                score=float(row['score']),
                previous_score=(
                    float(row['previous_score'])
                    if row.get('previous_score') is not None
                    else None
                ),
                change_reason=str(row.get('change_reason') or '') or None,
            )
        )
    return out


@scoring_router.post('/scoring/rescore')
async def rescore(
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
    body: scoring_models.RescoreRequest | None = None,
) -> scoring_models.RescoreResponse:
    body = body or scoring_models.RescoreRequest()
    # Single-project rescore only needs scoring_policy:rescore; any wider
    # scope (policy, blueprint, project_type, or global) requires
    # scoring_policy:rescore_all.
    if body.project_id and not (
        body.policy_slug or body.blueprint_slug or body.project_type_slug
    ):
        required = 'scoring_policy:rescore'
    else:
        required = 'scoring_policy:rescore_all'
    if not auth.is_admin and required not in auth.permissions:
        raise fastapi.HTTPException(
            status_code=403,
            detail=f'Permission denied: {required} required',
        )
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
