"""On-demand commit/tag history sync endpoints (Project Doctor).

``POST /sync`` enqueues a background backfill of the project's full
default-branch commit history and tag list; ``GET /sync-status`` returns
the last-run state for the UI to poll.  The work runs as a Valkey-stream
job (no request-scoped user) using the ``github-commit-sync`` plugin's
service credential, so the endpoint only validates eligibility and
enqueues.
"""

import typing

import fastapi
import pydantic
from imbi_common import graph

from imbi_api.auth import permissions
from imbi_api.commit_sync import service
from imbi_api.commit_sync.queue import enqueue_commit_sync
from imbi_api.plugins.resolution import resolve_plugin
from imbi_api.scoring import OptionalValkeyClient

project_commit_sync_router = fastapi.APIRouter(tags=['Project: Commits'])


class CommitSyncEnqueueResponse(pydantic.BaseModel):
    """Result of enqueueing a commit/tag sync."""

    enqueued: bool


@project_commit_sync_router.post('/sync', status_code=202)
async def sync_commits_and_tags(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:write'),
        ),
    ],
) -> CommitSyncEnqueueResponse:
    """Enqueue a full commit + tag history backfill for the project.

    Requires the project to have a GitHub deployment plugin (the same
    gate as deployment resync) and a connected ``github-commit-sync``
    plugin to provide the service credential.  Returns ``enqueued=False``
    when the job was debounced or Valkey is unavailable.
    """
    # Eligibility gate: a deployment plugin must resolve (404 otherwise).
    await resolve_plugin(db, project_id, 'deployment', None)
    try:
        await service.check_available(db, project_id)
    except service.CommitSyncUnavailable as exc:
        raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
    requested_by = auth.principal_name
    enqueued = await enqueue_commit_sync(
        valkey_client, org_slug, project_id, requested_by
    )
    if enqueued:
        # Optimistic, best-effort: if the worker has already flipped the
        # project to ``running``, that newer write must win -- so this one
        # does not retry the concurrent-update conflict.
        await service.set_status(
            db,
            project_id,
            status='queued',
            requested_by=requested_by,
            retry=False,
        )
    return CommitSyncEnqueueResponse(enqueued=enqueued)


@project_commit_sync_router.get('/sync-status')
async def get_commit_sync_status(
    org_slug: str,
    project_id: str,
    db: graph.Pool,
    _auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('project:deployment:read'),
        ),
    ],
) -> service.CommitSyncStatus:
    """Return the project's last commit/tag sync state."""
    del org_slug
    return await service.read_status(db, project_id)
