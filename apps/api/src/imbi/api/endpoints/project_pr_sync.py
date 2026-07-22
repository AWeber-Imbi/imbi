"""On-demand PR history sync endpoints (Project Doctor).

``POST /pull-requests/sync`` enqueues a background backfill of the
project's full pull-request history; ``GET /pull-requests/sync-status``
returns the last-run state for the UI to poll.  The work runs as a
Valkey-stream job using the resolved pr-sync integration's service
credential, so the endpoint only validates eligibility and enqueues.
"""

import typing

import fastapi
import pydantic
from imbi_common import graph

from imbi_api.auth import permissions
from imbi_api.plugins.resolution import resolve_capability
from imbi_api.pr_sync import service
from imbi_api.pr_sync.queue import enqueue_pr_sync
from imbi_api.scoring import OptionalValkeyClient

project_pr_sync_router = fastapi.APIRouter(tags=['Project: Pull Requests'])


class PRSyncEnqueueResponse(pydantic.BaseModel):
    """Result of enqueueing a PR history sync."""

    enqueued: bool


@project_pr_sync_router.post('/sync', status_code=202)
async def sync_pull_requests(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:pull-requests:write'),
        ),
    ],
    source: str | None = fastapi.Query(default=None),
) -> PRSyncEnqueueResponse:
    """Enqueue a full pull-request history backfill for the project.

    Resolves the project's ``pr-sync`` capability (404 when no
    integration provides it, 400 when several are bound and none is the
    default -- pass ``?source=<integration_slug>``) and confirms the
    resolved integration can run a sync right now.  Returns
    ``enqueued=False`` when the job was debounced or Valkey is
    unavailable.
    """
    resolved = await resolve_capability(db, project_id, 'pr-sync', source)
    try:
        await service.check_available(db, org_slug, project_id, resolved)
    except service.PRSyncUnavailable as exc:
        raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
    requested_by = auth.principal_name
    enqueued = await enqueue_pr_sync(
        valkey_client, org_slug, project_id, requested_by
    )
    if enqueued:
        await service.set_status(
            db,
            project_id,
            status='queued',
            requested_by=requested_by,
            retry=False,
        )
    return PRSyncEnqueueResponse(enqueued=enqueued)


@project_pr_sync_router.get('/sync-status')
async def get_pr_sync_status(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
) -> service.PRSyncStatus:
    """Return the project's last PR sync state."""
    del org_slug
    return await service.read_status(db, project_id)
