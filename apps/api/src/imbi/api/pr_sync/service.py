"""Resolve + invoke the pr-sync capability and track its status.

The on-demand sync acts with the resolved Integration's *service*
credential (PAT or GitHub App), so there is no acting user: the worker
resolves the ``pr-sync`` capability bound to the project via
:mod:`imbi_api.plugins.resolution`, builds the :class:`PluginContext` it
needs (project links + identity-capable integrations for attribution),
decrypts the credential, and awaits the capability's
``sync_all_history`` method.

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
from imbi_common.plugins import decrypt_integration_credentials
from imbi_common.plugins.base import PluginContext, PullRequestSyncCapability

from imbi_api.identity import attribution
from imbi_api.plugins.resolution import (
    ResolvedCapability,
    build_plugin_context,
    resolve_capability,
)

LOGGER = logging.getLogger(__name__)

_CAPABILITY_KIND = 'pr-sync'
_MAX_ERROR_LEN = 500
_STATUS_WRITE_RETRIES = 3
_STATUS_RETRY_BACKOFF = 0.05

SyncState = typing.Literal['idle', 'queued', 'running', 'success', 'failed']


class PRSyncUnavailable(Exception):
    """No integration provides a usable pr-sync capability."""


class PRSyncStatus(pydantic.BaseModel):
    """Last-sync state for a project's pull-request history."""

    status: SyncState = 'idle'
    last_synced_at: datetime.datetime | None = None
    prs_synced: int | None = None
    error: str | None = None
    requested_by: str | None = None


async def _build_context(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    resolved: ResolvedCapability,
) -> PluginContext:
    """Assemble the :class:`PluginContext` the capability needs (no actor)."""
    from imbi_api.endpoints import _helpers

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
    """Raise :class:`PRSyncUnavailable` if *resolved* can't sync now."""
    ctx = await _build_context(db, org_slug, project_id, resolved)
    credentials = decrypt_integration_credentials(
        resolved.encrypted_credentials
    )
    handler = typing.cast(
        'PullRequestSyncCapability', resolved.capability_cls()
    )
    available = await handler.check_available(ctx=ctx, credentials=credentials)
    if not available:
        raise PRSyncUnavailable(
            'The resolved pr-sync integration cannot sync this project '
            'right now.'
        )


async def run_sync(db: graph.Graph, org_slug: str, project_id: str) -> int:
    """Resolve the pr-sync capability and run a full history backfill.

    Returns the number of PRs recorded.  Raises :class:`PRSyncUnavailable`
    when no integration provides the capability; other failures propagate
    so the caller can record them.
    """
    try:
        resolved = await resolve_capability(
            db, project_id, _CAPABILITY_KIND, None
        )
    except fastapi.HTTPException as exc:
        raise PRSyncUnavailable(str(exc.detail)) from exc
    ctx = await _build_context(db, org_slug, project_id, resolved)
    credentials = decrypt_integration_credentials(
        resolved.encrypted_credentials
    )
    handler = typing.cast(
        'PullRequestSyncCapability', resolved.capability_cls()
    )
    return await handler.sync_all_history(ctx=ctx, credentials=credentials)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _is_write_conflict(exc: Exception) -> bool:
    return 'failed to be updated' in str(exc)


async def set_status(
    db: graph.Graph,
    project_id: str,
    *,
    status: SyncState,
    requested_by: str = '',
    prs: int = 0,
    error: str = '',
    retry: bool = True,
) -> None:
    """Persist last-sync state on the ``Project`` node (best-effort)."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
    SET p.pr_sync_status = {status},
        p.pr_sync_at = {at},
        p.pr_sync_by = {by},
        p.pr_sync_prs = {prs},
        p.pr_sync_error = {error}
    RETURN p.id AS id
    """
    params = {
        'project_id': project_id,
        'status': status,
        'at': _now_iso(),
        'by': requested_by,
        'prs': prs,
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
                    'pr-sync status write for %s lost a concurrent '
                    'update (status=%s); leaving the newer state in place',
                    project_id,
                    status,
                )
            else:
                LOGGER.warning(
                    'Failed to persist pr-sync status for project %s',
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


async def read_status(db: graph.Graph, project_id: str) -> PRSyncStatus:
    """Read last-sync state from the ``Project`` node (``idle`` default)."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
    RETURN p.pr_sync_status AS status,
           p.pr_sync_at AS at,
           p.pr_sync_by AS requested_by,
           p.pr_sync_prs AS prs,
           p.pr_sync_error AS error
    """
    records = await db.execute(
        query,
        {'project_id': project_id},
        ['status', 'at', 'requested_by', 'prs', 'error'],
    )
    if not records:
        return PRSyncStatus()
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
    return PRSyncStatus(
        status=status,
        last_synced_at=last_synced_at,
        prs_synced=_opt_int(graph.parse_agtype(row.get('prs'))),
        error=_opt_str(graph.parse_agtype(row.get('error'))),
        requested_by=_opt_str(graph.parse_agtype(row.get('requested_by'))),
    )
