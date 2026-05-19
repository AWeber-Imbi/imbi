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
