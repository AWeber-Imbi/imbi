"""Pull request read endpoints (ClickHouse-backed, read-only).

Two routers are provided:

- ``pull_requests_project_router`` — mounted under
  ``/organizations/{org_slug}/projects/{project_id}/pull-requests``
  returns PRs for a single project.

- ``pull_requests_router`` — mounted under
  ``/organizations/{org_slug}/pull-requests``
  returns PRs across all projects in the org.  The org's project IDs
  are resolved from the graph first so the response is scoped correctly.
"""

from __future__ import annotations

import datetime
import json
import logging
import typing

import fastapi
import pydantic
from imbi_common import clickhouse, graph

from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

pull_requests_router = fastapi.APIRouter(tags=['Pull Requests'])
pull_requests_project_router = fastapi.APIRouter(tags=['Pull Requests'])

DEFAULT_LIMIT: int = 50
MAX_LIMIT: int = 500

_TIMESTAMP_FIELDS: frozenset[str] = frozenset(
    {'created_at', 'updated_at', 'merged_at'}
)


class PullRequestResponse(pydantic.BaseModel):
    """A single pull request record from ClickHouse."""

    project_id: str
    pr_id: str
    pr_number: int
    title: str
    url: str
    state: str
    author: str
    draft: bool
    merged: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    merged_at: datetime.datetime | None = None
    additions: int
    deletions: int
    changed_files: int


class PullRequestListResponse(pydantic.BaseModel):
    data: list[PullRequestResponse]
    project_count: int
    total: int


# Default look-back window for the activity report when ``since`` is absent.
DEFAULT_ACTIVITY_DAYS: int = 30


class PRActivityRow(pydantic.BaseModel):
    """Per-author PR activity counts with the resolved Imbi user.

    ``login`` is always the raw GitHub login from the PR record.  The
    user fields are populated only when the login resolves to an Imbi
    user via that user's GitHub ``IdentityConnection``.
    """

    login: str
    email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    created: int
    merged: int


class PRActivityResponse(pydantic.BaseModel):
    """PR activity for the org, one row per GitHub author."""

    since: datetime.datetime
    members: int
    rows: list[PRActivityRow]


def _row_to_response(row: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Attach UTC tzinfo to naive datetime columns from ClickHouse."""
    out: dict[str, typing.Any] = {}
    for k, v in row.items():
        if (
            k in _TIMESTAMP_FIELDS
            and isinstance(v, datetime.datetime)
            and v.tzinfo is None
        ):
            v = v.replace(tzinfo=datetime.UTC)
        out[k] = v
    return out


async def _fetch_org_project_ids(
    db: graph.Pool,
    org_slug: str,
) -> list[str]:
    """Return all project IDs belonging to the org."""
    query: typing.LiteralString = """
    MATCH (p:Project)-[:OWNED_BY]->(:Team)
          -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})
    RETURN p.id AS id
    """
    records = await db.execute(query, {'org_slug': org_slug}, ['id'])
    return [
        graph.parse_agtype(r['id'])
        for r in records
        if graph.parse_agtype(r['id'])
    ]


async def _list_prs(
    *,
    project_ids: list[str],
    state: str | None = None,
    author: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> PullRequestListResponse:
    """Run the ClickHouse query and return a paginated response."""
    if limit < 1 or limit > MAX_LIMIT:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'limit must be 1..{MAX_LIMIT}',
        )
    if offset < 0:
        raise fastapi.HTTPException(
            status_code=400,
            detail='offset must be >= 0',
        )
    if not project_ids:
        return PullRequestListResponse(data=[], project_count=0, total=0)

    clauses: list[str] = ['project_id IN {project_ids:Array(String)}']
    params: dict[str, typing.Any] = {'project_ids': project_ids}

    if state is not None:
        clauses.append('state = {state:String}')
        params['state'] = state

    if author is not None:
        clauses.append('author = {author:String}')
        params['author'] = author

    where = ' AND '.join(clauses)
    count_sql = (
        'SELECT count() AS total,'  # noqa: S608
        ' count(DISTINCT project_id) AS project_count'
        ' FROM pull_requests FINAL WHERE ' + where
    )
    params['limit'] = limit
    params['offset'] = offset
    data_sql = (
        'SELECT * FROM pull_requests FINAL WHERE '  # noqa: S608
        + where
        + ' ORDER BY created_at DESC, pr_id DESC'
        + ' LIMIT {limit:UInt32} OFFSET {offset:UInt32}'
    )

    count_rows = await clickhouse.query(count_sql, params)
    total = int(count_rows[0]['total']) if count_rows else 0
    project_count = int(count_rows[0]['project_count']) if count_rows else 0

    data_rows = await clickhouse.query(data_sql, params)
    return PullRequestListResponse(
        data=[
            PullRequestResponse.model_validate(_row_to_response(r))
            for r in data_rows
        ],
        project_count=project_count,
        total=total,
    )


@pull_requests_project_router.get(
    '/',
    response_model=PullRequestListResponse,
)
async def list_project_pull_requests(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
    state: str | None = None,
    author: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> PullRequestListResponse:
    """List pull requests for a single project.

    Optional ``state`` filter accepts ``open`` or ``closed``.
    Optional ``author`` filter accepts a GitHub login.
    Results are ordered newest first.
    """
    org_project_ids = await _fetch_org_project_ids(db, org_slug)
    if project_id not in org_project_ids:
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Project {project_id!r} not found in organization'
                f' {org_slug!r}'
            ),
        )
    return await _list_prs(
        project_ids=[project_id],
        state=state,
        author=author,
        limit=limit,
        offset=offset,
    )


@pull_requests_router.get(
    '/',
    response_model=PullRequestListResponse,
)
async def list_org_pull_requests(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
    state: str | None = None,
    author: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> PullRequestListResponse:
    """List pull requests across all projects in the organization.

    The set of projects is resolved from the graph so results are
    scoped to the calling user's org.  Optional ``state`` filter
    accepts ``open`` or ``closed``.  Optional ``author`` filter
    accepts a GitHub login.  Results are ordered newest first.
    """
    project_ids = await _fetch_org_project_ids(db, org_slug)
    return await _list_prs(
        project_ids=project_ids,
        state=state,
        author=author,
        limit=limit,
        offset=offset,
    )


def _parse_since(value: str | None) -> datetime.datetime:
    """Parse the ``since`` query param (inclusive lower bound, UTC).

    Accepts a ``YYYY-MM-DD`` date or a full ISO timestamp; defaults to
    ``DEFAULT_ACTIVITY_DAYS`` ago at midnight UTC when absent.
    """
    if not value:
        start = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            days=DEFAULT_ACTIVITY_DAYS
        )
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        day = datetime.date.fromisoformat(value)
    except ValueError:
        pass
    else:
        return datetime.datetime.combine(
            day, datetime.time.min, tzinfo=datetime.UTC
        )
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        raise fastapi.HTTPException(
            status_code=400,
            detail='since must be an ISO date (YYYY-MM-DD) or timestamp',
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed


def _login_from_metadata(raw: typing.Any) -> str | None:
    """Extract the GitHub ``login`` from an IdentityConnection metadata.

    ``metadata`` is stored as a JSON-encoded string literal by the graph
    client, so decode the agtype, then JSON-decode a string payload.
    """
    parsed = graph.parse_agtype(raw)
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError, TypeError:
            return None
    if isinstance(parsed, dict):
        login = typing.cast('dict[str, typing.Any]', parsed).get('login')
        return str(login) if login else None
    return None


async def _fetch_login_users(
    db: graph.Pool,
) -> dict[str, dict[str, str | None]]:
    """Map lower-cased GitHub login -> Imbi user display fields.

    Built from every active ``IdentityConnection`` whose metadata carries
    a ``login``.  Logins without a connection simply won't appear.
    """
    query: typing.LiteralString = """
    MATCH (u:User)-[:HAS_IDENTITY]->(c:IdentityConnection)
    WHERE c.status = 'active'
    RETURN u.email AS email,
           u.display_name AS display_name,
           u.avatar_url AS avatar_url,
           c.metadata AS metadata
    """
    records = await db.execute(
        query, {}, ['email', 'display_name', 'avatar_url', 'metadata']
    )
    out: dict[str, dict[str, str | None]] = {}
    for row in records:
        login = _login_from_metadata(row.get('metadata'))
        if not login:
            continue
        avatar = graph.parse_agtype(row.get('avatar_url'))
        out[login.lower()] = {
            'email': graph.parse_agtype(row['email']),
            'display_name': graph.parse_agtype(row['display_name']),
            'avatar_url': str(avatar) if avatar else None,
        }
    return out


async def _fetch_pr_activity(
    project_ids: list[str],
    since: datetime.datetime,
) -> list[dict[str, typing.Any]]:
    """Aggregate created/merged PR counts per author since *since*.

    A PR counts toward ``created`` when created on/after ``since`` and
    toward ``merged`` when merged on/after ``since`` -- the two use
    different anchors, so a PR opened earlier but merged in-window still
    contributes to ``merged``.
    """
    if not project_ids:
        return []
    # Alias the aggregates to non-column names: aliasing ``AS merged``
    # would shadow the ``merged`` column, and ClickHouse then resolves
    # ``merged`` in WHERE to the aggregate (ILLEGAL_AGGREGATION).
    sql = (
        'SELECT author,'
        ' countIf(created_at >= {since:DateTime64(3)}) AS created_count,'
        ' countIf(merged AND merged_at >= {since:DateTime64(3)})'
        ' AS merged_count'
        ' FROM pull_requests FINAL'
        ' WHERE project_id IN {project_ids:Array(String)}'
        ' AND (created_at >= {since:DateTime64(3)}'
        ' OR (merged AND merged_at >= {since:DateTime64(3)}))'
        ' GROUP BY author'
    )
    return await clickhouse.query(
        sql, {'project_ids': project_ids, 'since': since}
    )


@pull_requests_router.get('/activity', response_model=PRActivityResponse)
async def pull_request_activity(
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:read'),
        ),
    ],
    since: str | None = None,
) -> PRActivityResponse:
    """Per-team-member PR activity (created/merged) across the org.

    ``since`` is an inclusive lower bound (``YYYY-MM-DD`` or ISO
    timestamp); it defaults to 30 days ago.  Authors are resolved to
    Imbi users via their GitHub identity connections where possible;
    unresolved logins are returned as-is.  Rows are ordered by merged
    then created, descending.
    """
    since_dt = _parse_since(since)
    project_ids = await _fetch_org_project_ids(db, org_slug)
    counts = await _fetch_pr_activity(project_ids, since_dt)
    login_users = await _fetch_login_users(db)
    rows: list[PRActivityRow] = []
    for row in counts:
        login = str(row.get('author') or '')
        created = int(row.get('created_count') or 0)
        merged = int(row.get('merged_count') or 0)
        if not login or (created == 0 and merged == 0):
            continue
        user = login_users.get(login.lower())
        rows.append(
            PRActivityRow(
                login=login,
                email=user['email'] if user else None,
                display_name=user['display_name'] if user else None,
                avatar_url=user['avatar_url'] if user else None,
                created=created,
                merged=merged,
            )
        )
    rows.sort(key=lambda r: (r.merged, r.created, r.login), reverse=True)
    return PRActivityResponse(since=since_dt, members=len(rows), rows=rows)
