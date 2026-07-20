"""Run the deployment resync and track its status.

The background resync acts with the resolved Integration's *service*
credential (PAT or GitHub App) via a synthetic service-account
principal -- the enqueueing user is recorded on the status for
display, not used for credentials or attribution (resync deliberately
writes no ``operations_log`` rows; ``DeploymentEvent.performed_by``
carries the original deployer resolved from the remote).

Last-sync state is persisted as properties on the ``Project`` node so
the UI can poll it without a dedicated status store.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import typing

import fastapi
import pydantic
from imbi_common import graph

from imbi_api import models
from imbi_api.auth import permissions

if typing.TYPE_CHECKING:
    from imbi_api.endpoints.project_deployments import ResyncSummary

LOGGER = logging.getLogger(__name__)

_MAX_ERROR_LEN = 500
_STATUS_WRITE_RETRIES = 3
_STATUS_RETRY_BACKOFF = 0.05

SyncState = typing.Literal['idle', 'queued', 'running', 'success', 'failed']

#: ``principal_name`` stamped on work the background resync performs.
REQUESTED_BY = 'deployment-sync'


class DeploymentSyncUnavailable(Exception):
    """The project cannot resync deployments (no capability/support)."""


class DeploymentSyncStatus(pydantic.BaseModel):
    """Last-resync state for a project's deployments."""

    status: SyncState = 'idle'
    last_synced_at: datetime.datetime | None = None
    observed: int | None = None
    releases_created: int | None = None
    releases_updated: int | None = None
    events_recorded: int | None = None
    errors: int | None = None
    error: str | None = None
    requested_by: str | None = None


def _system_auth() -> permissions.AuthContext:
    """Synthetic principal for the background resync worker.

    Never persisted; exists so ``resync_for_project`` has an
    ``AuthContext`` (its identity attach is best-effort and falls back
    to the Integration's service credentials for a userless principal).
    """
    return permissions.AuthContext(
        auth_method='client_credentials',
        service_account=models.ServiceAccount(
            slug=REQUESTED_BY, display_name='Imbi Deployment Sync'
        ),
    )


async def run_resync(
    db: graph.Graph, org_slug: str, project_id: str, limit: int
) -> ResyncSummary:
    """Run the deployment resync for one project.

    Raises :class:`DeploymentSyncUnavailable` when the project has no
    deployment capability (404) or its plugin does not support
    deployment sync (400); other failures propagate so the caller can
    record them.
    """
    # Imported here (not at module load) so the worker/service module
    # never pulls the endpoints package at import time.
    from imbi_api.endpoints import project_deployments

    try:
        return await project_deployments.resync_for_project(
            db,
            org_slug=org_slug,
            project_id=project_id,
            auth=_system_auth(),
            limit=limit,
        )
    except fastapi.HTTPException as exc:
        # 404: no deployment capability bound; 400: the plugin doesn't
        # support deployment sync.  Misconfiguration, not transient.
        if exc.status_code in (400, 404):
            raise DeploymentSyncUnavailable(str(exc.detail)) from exc
        raise


def now_iso() -> str:
    """Current UTC time in the ISO-8601 form stored on the Project node.

    Public so the enqueue endpoint can capture a pre-enqueue timestamp
    for :func:`set_status`'s ``only_if_before`` guard.
    """
    return datetime.datetime.now(datetime.UTC).isoformat()


def _is_write_conflict(exc: Exception) -> bool:
    """True if *exc* is AGE's concurrent-update conflict (TM_Updated)."""
    return 'failed to be updated' in str(exc)


async def set_status(
    db: graph.Graph,
    project_id: str,
    *,
    status: SyncState,
    requested_by: str = '',
    summary: ResyncSummary | None = None,
    error: str = '',
    retry: bool = True,
    only_if_before: str | None = None,
) -> None:
    """Persist last-resync state on the ``Project`` node (best-effort).

    *retry* re-attempts the write when AGE reports a transient
    concurrent update, so the worker's authoritative transitions
    (running -> success/failed) still land if a webhook touches the
    project mid-write.  The enqueue endpoint passes ``retry=False`` for
    its optimistic ``queued`` write: dropping that on conflict is
    correct, since the worker's newer ``running`` write must win.

    *only_if_before* skips the write entirely when the stored
    ``deployment_sync_at`` has already advanced to or past the given
    ISO-8601 timestamp.  AGE only raises a conflict for truly
    concurrent transactions, so without this guard an optimistic
    ``queued`` write that merely executes *after* the worker finished
    would silently clobber the newer terminal status.
    """
    guard: typing.LiteralString = (
        ''
        if only_if_before is None
        else """
    WHERE p.deployment_sync_at IS NULL
       OR p.deployment_sync_at < {only_if_before}"""
    )
    query: typing.LiteralString = (
        """
    MATCH (p:Project {{id: {project_id}}})"""
        + guard
        + """
    SET p.deployment_sync_status = {status},
        p.deployment_sync_at = {at},
        p.deployment_sync_by = {by},
        p.deployment_sync_observed = {observed},
        p.deployment_sync_releases_created = {releases_created},
        p.deployment_sync_releases_updated = {releases_updated},
        p.deployment_sync_events = {events},
        p.deployment_sync_errors = {errors},
        p.deployment_sync_error = {error}
    RETURN p.id AS id
    """
    )
    params = {
        'project_id': project_id,
        'status': status,
        'at': now_iso(),
        'by': requested_by,
        'observed': summary.observed if summary else 0,
        'releases_created': summary.releases_created if summary else 0,
        'releases_updated': summary.releases_updated if summary else 0,
        'events': summary.events_recorded if summary else 0,
        'errors': len(summary.errors) if summary else 0,
        'error': error[:_MAX_ERROR_LEN],
    }
    if only_if_before is not None:
        params['only_if_before'] = only_if_before
    attempts = _STATUS_WRITE_RETRIES if retry else 1
    for attempt in range(attempts):
        try:
            await db.execute(query, params, ['id'])
            return
        except Exception as exc:  # noqa: BLE001
            conflict = _is_write_conflict(exc)
            if retry and conflict and attempt + 1 < attempts:
                await asyncio.sleep(_STATUS_RETRY_BACKOFF * (attempt + 1))
                continue
            if conflict:
                LOGGER.debug(
                    'deployment-sync status write for %s lost a concurrent '
                    'update (status=%s); leaving the newer state in place',
                    project_id,
                    status,
                )
            else:
                LOGGER.warning(
                    'Failed to persist deployment-sync status for project %s',
                    project_id,
                    exc_info=True,
                )
            return


def _opt_str(value: object) -> str | None:
    text = str(value) if value is not None else ''
    return text or None


def _opt_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


async def read_status(
    db: graph.Graph, project_id: str
) -> DeploymentSyncStatus:
    """Read last-resync state from the ``Project`` node (``idle`` default)."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
    RETURN p.deployment_sync_status AS status,
           p.deployment_sync_at AS at,
           p.deployment_sync_by AS requested_by,
           p.deployment_sync_observed AS observed,
           p.deployment_sync_releases_created AS releases_created,
           p.deployment_sync_releases_updated AS releases_updated,
           p.deployment_sync_events AS events,
           p.deployment_sync_errors AS errors,
           p.deployment_sync_error AS error
    """
    records = await db.execute(
        query,
        {'project_id': project_id},
        [
            'status',
            'at',
            'requested_by',
            'observed',
            'releases_created',
            'releases_updated',
            'events',
            'errors',
            'error',
        ],
    )
    if not records:
        return DeploymentSyncStatus()
    row = records[0]
    status_raw = graph.parse_agtype(row.get('status'))
    status: SyncState = 'idle'
    if status_raw in ('queued', 'running', 'success', 'failed', 'idle'):
        status = status_raw
    at_raw = _opt_str(graph.parse_agtype(row.get('at')))
    last_synced_at: datetime.datetime | None = None
    if at_raw:
        try:
            last_synced_at = datetime.datetime.fromisoformat(at_raw)
        except ValueError:
            last_synced_at = None
    return DeploymentSyncStatus(
        status=status,
        last_synced_at=last_synced_at,
        observed=_opt_int(graph.parse_agtype(row.get('observed'))),
        releases_created=_opt_int(
            graph.parse_agtype(row.get('releases_created'))
        ),
        releases_updated=_opt_int(
            graph.parse_agtype(row.get('releases_updated'))
        ),
        events_recorded=_opt_int(graph.parse_agtype(row.get('events'))),
        errors=_opt_int(graph.parse_agtype(row.get('errors'))),
        error=_opt_str(graph.parse_agtype(row.get('error'))),
        requested_by=_opt_str(graph.parse_agtype(row.get('requested_by'))),
    )
