"""Resolve + invoke the PR-sync plugin and track its status.

The on-demand sync acts with the ``github-pr-sync`` plugin's *service*
credential (PAT or GitHub App), so there is no acting user: the worker
resolves the plugin attached to a ``ThirdPartyService`` the project
``EXISTS_IN``, builds the :class:`PluginContext` it needs (project links
+ the connected ``service_plugins`` for host resolution), decrypts the
credential, and awaits the plugin's ``sync_all_history`` method.

Last-sync state is persisted as properties on the ``Project`` node so
the UI can poll it without a dedicated status store.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import typing

import pydantic
from imbi_common import graph
from imbi_common.plugins.base import PluginContext, ServicePlugin
from imbi_common.plugins.errors import PluginNotFoundError
from imbi_common.plugins.registry import RegistryEntry, get_plugin

from imbi_api.identity import attribution
from imbi_api.plugins import parse_options
from imbi_api.plugins.credentials import get_plugin_credentials

LOGGER = logging.getLogger(__name__)

_PR_SYNC_SLUG = 'github-pr-sync'
_MAX_ERROR_LEN = 500
_STATUS_WRITE_RETRIES = 3
_STATUS_RETRY_BACKOFF = 0.05

SyncState = typing.Literal['idle', 'queued', 'running', 'success', 'failed']


class PRSyncUnavailable(Exception):
    """No ``github-pr-sync`` plugin is reachable for the project."""


class PRSyncStatus(pydantic.BaseModel):
    """Last-sync state for a project's pull-request history."""

    status: SyncState = 'idle'
    last_synced_at: datetime.datetime | None = None
    prs_synced: int | None = None
    error: str | None = None
    requested_by: str | None = None


class _ResolvedPRSync(typing.NamedTuple):
    plugin_id: str
    entry: RegistryEntry
    tps_slug: str
    service_endpoint: str | None
    service_plugins: list[ServicePlugin]


class _SyncAllHistoryHandler(typing.Protocol):
    async def sync_all_history(
        self,
        *,
        ctx: PluginContext,
        credentials: dict[str, typing.Any],
    ) -> int: ...


async def _resolve_plugin(db: graph.Graph, project_id: str) -> _ResolvedPRSync:
    """Find the ``github-pr-sync`` plugin attached to a service the
    project ``EXISTS_IN`` and gather the sibling plugins on that service.

    Raises :class:`PRSyncUnavailable` when no such plugin is configured.
    """
    query: typing.LiteralString = """
    MATCH (proj:Project {{id: {project_id}}})
      -[:EXISTS_IN]->(tps:ThirdPartyService)
      -[:HAS_PLUGIN]->(psp:Plugin {{plugin_slug: {slug}}})
    OPTIONAL MATCH (tps)-[:HAS_PLUGIN]->(sib:Plugin)
    WITH tps, psp,
      collect(DISTINCT {{slug: sib.plugin_slug, options: sib.options}})
        AS siblings
    RETURN psp.id AS plugin_id,
           tps.slug AS tps_slug,
           tps.api_endpoint AS api_endpoint,
           siblings AS siblings
    LIMIT 1
    """
    records = await db.execute(
        query,
        {'project_id': project_id, 'slug': _PR_SYNC_SLUG},
        ['plugin_id', 'tps_slug', 'api_endpoint', 'siblings'],
    )
    if not records:
        raise PRSyncUnavailable(
            'No github-pr-sync plugin is connected to a service this '
            'project belongs to; configure it on the GitHub service.'
        )
    record = records[0]
    plugin_id = graph.parse_agtype(record.get('plugin_id'))
    if not plugin_id:
        raise PRSyncUnavailable('github-pr-sync plugin row is missing an id')
    try:
        entry = get_plugin(_PR_SYNC_SLUG)
    except PluginNotFoundError as exc:
        raise PRSyncUnavailable(
            'github-pr-sync plugin is not loaded in the registry'
        ) from exc
    tps_slug = graph.parse_agtype(record.get('tps_slug'))
    api_endpoint = graph.parse_agtype(record.get('api_endpoint'))
    siblings = typing.cast(
        'list[dict[str, typing.Any]]',
        graph.parse_agtype(record.get('siblings')) or [],
    )
    service_plugins: list[ServicePlugin] = []
    for sib in siblings:
        slug = sib.get('slug')
        if not slug:
            continue
        service_plugins.append(
            ServicePlugin(
                slug=str(slug), options=parse_options(sib.get('options'))
            )
        )
    return _ResolvedPRSync(
        plugin_id=str(plugin_id),
        entry=entry,
        tps_slug=str(tps_slug) if tps_slug else '',
        service_endpoint=str(api_endpoint) if api_endpoint else None,
        service_plugins=service_plugins,
    )


async def _build_context(
    db: graph.Graph,
    org_slug: str,
    project_id: str,
    resolved: _ResolvedPRSync,
) -> PluginContext:
    """Assemble the :class:`PluginContext` the plugin needs (no actor)."""
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
    assignment_options: dict[str, typing.Any] = {
        'service_slug': resolved.tps_slug,
    }
    if resolved.service_endpoint:
        assignment_options['service_endpoint'] = resolved.service_endpoint
    return PluginContext(
        project_id=project_id,
        project_slug=project_slug,
        org_slug=org_slug,
        team_slug=team_slug,
        assignment_options=assignment_options,
        service_plugins=resolved.service_plugins,
        project_links=project_links,
        project_type_slugs=project_type_slugs,
        third_party_service_slug=resolved.tps_slug or None,
        service_connections=service_connections,
        resolve_user_by_identity=attribution.make_user_resolver(
            db, resolved.service_plugins
        ),
    )


async def check_available(db: graph.Graph, project_id: str) -> None:
    """Raise :class:`PRSyncUnavailable` if the project can't be synced."""
    await _resolve_plugin(db, project_id)


async def run_sync(db: graph.Graph, org_slug: str, project_id: str) -> int:
    """Resolve the PR-sync plugin and run a full history backfill.

    Returns the number of PRs recorded.  Raises :class:`PRSyncUnavailable`
    when no plugin/credential is configured; other failures propagate so
    the caller can record them.
    """
    resolved = await _resolve_plugin(db, project_id)
    ctx = await _build_context(db, org_slug, project_id, resolved)
    credentials = await get_plugin_credentials(
        db, resolved.plugin_id, resolved.entry
    )
    handler = resolved.entry.handler_cls()
    sync = getattr(handler, 'sync_all_history', None)
    if sync is None:
        raise PRSyncUnavailable(
            'github-pr-sync plugin does not implement sync_all_history; '
            'upgrade imbi-plugin-github'
        )
    sync_fn = typing.cast('_SyncAllHistoryHandler', handler)
    return await sync_fn.sync_all_history(ctx=ctx, credentials=credentials)


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
