"""Resolve + invoke the commit-sync capability and track its status.

The on-demand sync acts with the resolved Integration's *service*
credential (PAT or GitHub App), so there is no acting user: the worker
resolves the ``commit-sync`` capability bound to the project via
:mod:`imbi.api.plugins.resolution`, builds the :class:`PluginContext` it
needs (project links + identity-capable integrations for attribution),
decrypts the credential, and awaits the capability's
``sync_all_history`` method.

Last-sync state is persisted as a handful of properties on the ``Project``
node so the UI can poll it without a dedicated status store.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import typing

import fastapi
import pydantic

from imbi.api.identity import attribution
from imbi.api.plugins.resolution import (
    ResolvedCapability,
    build_plugin_context,
    resolve_capability,
)
from imbi.common import graph
from imbi.common.plugins import decrypt_integration_credentials
from imbi.common.plugins.base import CommitSyncCapability, PluginContext

LOGGER = logging.getLogger(__name__)

_CAPABILITY_KIND = 'commit-sync'
# Persisted error strings are truncated so a noisy upstream message can't
# bloat the Project node.
_MAX_ERROR_LEN = 500
# Apache AGE aborts a SET with "Entity failed to be updated: <n>"
# (heap_update -> TM_Updated) when another transaction updates the same
# Project vertex concurrently. The worker's authoritative status writes
# retry the transient conflict so they still land under contention.
_STATUS_WRITE_RETRIES = 3
_STATUS_RETRY_BACKOFF = 0.05

SyncState = typing.Literal['idle', 'queued', 'running', 'success', 'failed']


class CommitSyncUnavailable(Exception):
    """No integration provides a usable commit-sync capability."""


class CommitSyncStatus(pydantic.BaseModel):
    """Last-sync state for a project's commit/tag history."""

    status: SyncState = 'idle'
    last_synced_at: datetime.datetime | None = None
    commits_synced: int | None = None
    tags_synced: int | None = None
    error: str | None = None
    requested_by: str | None = None


async def _build_context(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    resolved: ResolvedCapability,
) -> PluginContext:
    """Assemble the :class:`PluginContext` the capability needs (no actor)."""
    # Imported here (not at module load) so the worker/service module
    # never pulls the endpoints package at import time.
    from imbi.api.endpoints import _helpers

    project_slug, team_slug = await _helpers.lookup_project_slugs(
        db, project_id
    )
    project_links = await _helpers.lookup_project_links(db, project_id)
    project_type_slugs = await _helpers.lookup_project_type_slugs(
        db, project_id
    )
    service_connections = await _helpers.lookup_project_exists_in(
        db, project_id
    )
    integration_ids = await attribution.identity_integration_ids_for_project(
        db, project_id
    )
    return build_plugin_context(
        resolved,
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        project_links=project_links,
        project_type_slugs=project_type_slugs,
        service_connections=service_connections,
        resolve_user_by_identity=attribution.make_user_resolver(
            db, integration_ids
        ),
    )


async def check_available(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    resolved: ResolvedCapability,
) -> None:
    """Raise :class:`CommitSyncUnavailable` if *resolved* can't sync now.

    Used by the enqueue endpoint to fail fast (400) rather than queueing a
    job that the worker can only mark failed.
    """
    ctx = await _build_context(db, org_slug, project_id, resolved)
    credentials = decrypt_integration_credentials(
        resolved.encrypted_credentials
    )
    handler = typing.cast('CommitSyncCapability', resolved.capability_cls())
    available = await handler.check_available(ctx=ctx, credentials=credentials)
    if not available:
        raise CommitSyncUnavailable(
            'The resolved commit-sync integration cannot sync this '
            'project right now.'
        )


async def run_sync(
    db: graph.Graph, org_slug: str, project_id: str
) -> tuple[int, int]:
    """Resolve the commit-sync capability and run a full history backfill.

    Returns ``(commits_recorded, tags_recorded)``.  Raises
    :class:`CommitSyncUnavailable` when no integration provides the
    capability; other failures propagate so the caller can record them.
    """
    try:
        resolved = await resolve_capability(
            db, project_id, _CAPABILITY_KIND, None
        )
    except fastapi.HTTPException as exc:
        raise CommitSyncUnavailable(str(exc.detail)) from exc
    ctx = await _build_context(db, org_slug, project_id, resolved)
    credentials = decrypt_integration_credentials(
        resolved.encrypted_credentials
    )
    handler = typing.cast('CommitSyncCapability', resolved.capability_cls())
    return await handler.sync_all_history(ctx=ctx, credentials=credentials)


def _now_iso() -> str:
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
    commits: int = 0,
    tags: int = 0,
    error: str = '',
    retry: bool = True,
) -> None:
    """Persist last-sync state on the ``Project`` node (best-effort).

    *retry* re-attempts the write when AGE reports a transient concurrent
    update, so the worker's authoritative transitions (running -> success/
    failed) still land if a webhook touches the project mid-write. The
    enqueue endpoint passes ``retry=False`` for its optimistic ``queued``
    write: dropping that on conflict is correct, since the worker's newer
    ``running`` write must win rather than be clobbered back to ``queued``.
    """
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
    SET p.commit_sync_status = {status},
        p.commit_sync_at = {at},
        p.commit_sync_by = {by},
        p.commit_sync_commits = {commits},
        p.commit_sync_tags = {tags},
        p.commit_sync_error = {error}
    RETURN p.id AS id
    """
    params = {
        'project_id': project_id,
        'status': status,
        'at': _now_iso(),
        'by': requested_by,
        'commits': commits,
        'tags': tags,
        'error': error[:_MAX_ERROR_LEN],
    }
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
                    'commit-sync status write for %s lost a concurrent '
                    'update (status=%s); leaving the newer state in place',
                    project_id,
                    status,
                )
            else:
                LOGGER.warning(
                    'Failed to persist commit-sync status for project %s',
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


async def read_status(db: graph.Graph, project_id: str) -> CommitSyncStatus:
    """Read last-sync state from the ``Project`` node (``idle`` default)."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
    RETURN p.commit_sync_status AS status,
           p.commit_sync_at AS at,
           p.commit_sync_by AS requested_by,
           p.commit_sync_commits AS commits,
           p.commit_sync_tags AS tags,
           p.commit_sync_error AS error
    """
    records = await db.execute(
        query,
        {'project_id': project_id},
        ['status', 'at', 'requested_by', 'commits', 'tags', 'error'],
    )
    if not records:
        return CommitSyncStatus()
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
    return CommitSyncStatus(
        status=status,
        last_synced_at=last_synced_at,
        commits_synced=_opt_int(graph.parse_agtype(row.get('commits'))),
        tags_synced=_opt_int(graph.parse_agtype(row.get('tags'))),
        error=_opt_str(graph.parse_agtype(row.get('error'))),
        requested_by=_opt_str(graph.parse_agtype(row.get('requested_by'))),
    )
