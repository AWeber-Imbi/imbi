"""Lifecycle plugin fan-out for project state-change endpoints.

When a project state changes -- create, update, archive, unarchive,
delete, or relocate -- the API dispatches the event to every plugin
assigned to ``plugin_type='lifecycle'`` (project or project-type level).
Plugins receive a :class:`PluginContext` with hydrated identity and
return a :class:`LifecycleResult` describing their per-plugin outcome.

Only ``on_project_archived`` is a required plugin hook; every other
event's missing hook resolves to ``status='skipped'``.  Failure of one
plugin never poisons the others and never rolls back the Imbi-side
state change -- the operator's intent is authoritative.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import logging
import typing

import fastapi
import nanoid
import pydantic
from imbi_common import graph
from imbi_common.clickhouse import client as ch_client
from imbi_common.plugins.base import (
    LifecyclePlugin,
    LifecycleResult,
    LinkWriteback,
    PluginContext,
    ServiceConnection,
    ServiceWriteback,
)
from imbi_common.plugins.errors import PluginCredentialsMissing

from imbi_api.auth import permissions
from imbi_api.identity.host_integration import call_with_identity_retry
from imbi_api.plugins import call_with_timeout
from imbi_api.plugins.credentials import get_plugin_credentials
from imbi_api.plugins.resolution import (
    ResolvedPlugin,
    resolve_all_plugins,
    resolve_service_plugins,
)

# ``_helpers`` lives in ``imbi_api.endpoints`` whose package ``__init__``
# imports every endpoint module (including ``projects``).  Since
# ``projects`` re-imports this module to call :func:`dispatch_lifecycle`,
# a top-level ``from imbi_api.endpoints._helpers import ...`` would
# create a circular import.  Pull the helpers in lazily inside
# :func:`dispatch_lifecycle` to keep both modules free of the cycle.

LOGGER = logging.getLogger(__name__)

LifecycleEvent = typing.Literal[
    'created',
    'updated',
    'archived',
    'unarchived',
    'deleted',
    'relocated',
]

#: Map of lifecycle events to the matching ``LifecyclePlugin`` hook
#: name.  Centralized here so both the dispatcher and any future
#: capability checks read from the same source.
_EVENT_METHOD: dict[LifecycleEvent, str] = {
    'created': 'on_project_created',
    'updated': 'on_project_updated',
    'archived': 'on_project_archived',
    'unarchived': 'on_project_unarchived',
    'deleted': 'on_project_deleted',
    'relocated': 'on_project_relocated',
}


@dataclasses.dataclass(slots=True)
class LifecycleContextBundle:
    """Pre-fetched project context for the lifecycle dispatcher.

    The delete endpoint needs the project's slug / links / type slugs
    *before* ``DETACH DELETE`` runs (otherwise the helpers would look
    up a project that no longer exists).  Callers that already hold the
    data -- including the rest of the lifecycle path that could
    short-circuit a round trip -- pass a bundle through to
    :func:`dispatch_lifecycle`.  Callers that don't hold it can let the
    dispatcher fetch it implicitly (the archive / unarchive path still
    does this for back-compat).
    """

    project_slug: str
    team_slug: str | None
    project_links: dict[str, str]
    project_type_slugs: list[str]
    service_connections: list[ServiceConnection] = dataclasses.field(
        default_factory=list
    )


async def build_lifecycle_context_bundle(
    db: graph.Graph, project_id: str
) -> LifecycleContextBundle:
    """Pre-fetch lifecycle context the dispatcher would otherwise look up.

    Use this before a ``DETACH DELETE`` so the bundle survives the
    write, and pass it as ``bundle=`` to :func:`dispatch_lifecycle`.
    """
    from imbi_api.endpoints._helpers import (
        lookup_project_exists_in,
        lookup_project_links,
        lookup_project_slugs,
        lookup_project_type_slugs,
    )

    # Independent DB lookups; gather them concurrently so each lifecycle
    # dispatch pays one round-trip latency rather than several.
    (
        (project_slug, team_slug),
        project_links,
        project_type_slugs,
        service_connections,
    ) = await asyncio.gather(
        lookup_project_slugs(db, project_id),
        lookup_project_links(db, project_id),
        lookup_project_type_slugs(db, project_id),
        lookup_project_exists_in(db, project_id),
    )
    return LifecycleContextBundle(
        project_slug=project_slug,
        team_slug=team_slug,
        project_links=project_links,
        project_type_slugs=project_type_slugs,
        service_connections=service_connections,
    )


class LifecycleInvocation(pydantic.BaseModel):
    """Per-plugin outcome surfaced to the operator after a lifecycle event."""

    plugin_id: str
    plugin_slug: str
    status: typing.Literal['ok', 'skipped', 'failed']
    message: str | None = None
    artifacts: dict[str, str] = {}


async def dispatch_lifecycle(
    db: graph.Graph,
    project_id: str,
    org_slug: str,
    event: LifecycleEvent,
    auth: permissions.AuthContext,
    *,
    bundle: LifecycleContextBundle | None = None,
    previous_project_slug: str | None = None,
    previous_project_type_slugs: list[str] | None = None,
    previous_team_slug: str | None = None,
    project_name: str | None = None,
    project_description: str | None = None,
    project_ui_url: str | None = None,
) -> list[LifecycleInvocation]:
    """Invoke every lifecycle plugin assigned to ``project_id``.

    Returns one :class:`LifecycleInvocation` per plugin.  Empty list
    when no lifecycle plugins are assigned.  All exceptions are caught
    and translated into a ``status='failed'`` result so the caller can
    surface them without rolling back the Imbi state change.

    Pass ``bundle`` for events like ``'deleted'`` where the caller
    needs to capture project context before a destructive write;
    otherwise the dispatcher looks the data up.  The optional
    ``previous_*`` fields populate :class:`PluginContext` for plugins
    that need a before/after view (``'updated'`` / ``'relocated'``).
    """
    resolved_plugins = await resolve_all_plugins(db, project_id, 'lifecycle')
    if not resolved_plugins:
        return []

    if bundle is None:
        bundle = await build_lifecycle_context_bundle(db, project_id)

    service_plugins = await resolve_service_plugins(db, project_id)

    results: list[LifecycleInvocation] = []
    for resolved in resolved_plugins:
        ctx = PluginContext(
            project_id=project_id,
            project_slug=bundle.project_slug,
            org_slug=org_slug,
            team_slug=bundle.team_slug,
            assignment_options=resolved.options,
            project_links=bundle.project_links,
            project_type_slugs=bundle.project_type_slugs,
            previous_project_slug=previous_project_slug,
            previous_project_type_slugs=previous_project_type_slugs or [],
            previous_team_slug=previous_team_slug,
            project_name=project_name,
            project_description=project_description,
            project_ui_url=project_ui_url,
            third_party_service_slug=resolved.third_party_service_slug,
            service_connections=bundle.service_connections,
            service_plugins=service_plugins,
        )
        invocation = await _invoke_one(db, ctx, resolved, event, auth)
        results.append(invocation)
    # H17: emit all per-plugin events in a single ClickHouse insert
    # rather than one round-trip per plugin. The dispatch loop hits N
    # plugins serially, so a project assigned to a handful of plugins
    # was paying N CH round trips on every lifecycle tick.
    if results:
        await _emit_events_batch(project_id, event, results, auth)
    return results


async def _invoke_one(
    db: graph.Graph,
    ctx: PluginContext,
    resolved: ResolvedPlugin,
    event: LifecycleEvent,
    auth: permissions.AuthContext,
) -> LifecycleInvocation:
    """Run a single plugin and return its :class:`LifecycleInvocation`.

    Failures from the plugin, missing credentials, missing identity,
    timeouts, and ``NotImplementedError`` (for plugins without a hook
    for this event) are all translated to a
    :class:`LifecycleInvocation` instead of bubbling.
    """
    handler = typing.cast(LifecyclePlugin, resolved.entry.handler_cls())
    method_name = _EVENT_METHOD[event]

    # Detect a truly-unimplemented hook (the plugin inherits the base
    # ``LifecyclePlugin`` stub) *before* we call into it.  This lets a
    # real ``NotImplementedError`` raised by an implemented hook surface
    # as ``status='failed'`` via the generic exception handler instead of
    # being misreported as ``skipped``.  ``on_project_archived`` is the
    # only required hook -- a missing impl there still maps to ``failed``.
    method = getattr(handler, method_name)
    base_method = getattr(LifecyclePlugin, method_name, None)
    if (
        base_method is not None
        and getattr(method, '__func__', method) is base_method
    ):
        if event == 'archived':
            return LifecycleInvocation(
                plugin_id=resolved.plugin_id,
                plugin_slug=resolved.plugin_slug,
                status='failed',
                message=f'Plugin does not implement {method_name}',
            )
        return LifecycleInvocation(
            plugin_id=resolved.plugin_id,
            plugin_slug=resolved.plugin_slug,
            status='skipped',
            message=f'Plugin does not implement {method_name}',
        )

    # call_with_identity_retry re-attaches identity onto a fresh context
    # before invoking ``_call`` (attached defaults to False here), so the
    # plugin mutates that inner context, not ``ctx``. Capture any link
    # writeback it reports through the closure so we can persist the
    # link after the call regardless of which context instance was used.
    captured_writeback: list[LinkWriteback] = []
    captured_service_writeback: list[ServiceWriteback] = []

    async def _call(c: PluginContext) -> LifecycleResult:
        credentials = await _resolve_credentials(db, c, resolved)
        method = getattr(handler, method_name)
        res: LifecycleResult = await call_with_timeout(method(c, credentials))
        if c.link_writeback is not None:
            captured_writeback.append(c.link_writeback)
        if c.service_writeback is not None:
            captured_service_writeback.append(c.service_writeback)
        return res

    try:
        result = await call_with_identity_retry(
            db, ctx, resolved, auth, fn=_call
        )
    except fastapi.HTTPException as exc:
        return LifecycleInvocation(
            plugin_id=resolved.plugin_id,
            plugin_slug=resolved.plugin_slug,
            status='failed',
            message=_extract_http_detail(exc),
        )
    except PluginCredentialsMissing as exc:
        return LifecycleInvocation(
            plugin_id=resolved.plugin_id,
            plugin_slug=resolved.plugin_slug,
            status='failed',
            message=str(exc),
        )
    except Exception as exc:
        LOGGER.exception(
            'Lifecycle plugin %s (%s) raised on %s for project %s',
            resolved.plugin_slug,
            resolved.plugin_id,
            event,
            ctx.project_id,
        )
        return LifecycleInvocation(
            plugin_id=resolved.plugin_id,
            plugin_slug=resolved.plugin_slug,
            status='failed',
            message=f'{type(exc).__name__}: {exc}',
        )

    if captured_writeback or captured_service_writeback:
        # Lazy import to avoid the endpoints/_helpers <-> this-module
        # cycle described above.
        from imbi_api.endpoints._helpers import (
            persist_link_writeback,
            persist_service_writeback,
        )

        if captured_writeback:
            ctx.link_writeback = captured_writeback[-1]
            await persist_link_writeback(db, ctx)
        if captured_service_writeback:
            ctx.service_writeback = captured_service_writeback[-1]
            await persist_service_writeback(db, ctx)

    return LifecycleInvocation(
        plugin_id=resolved.plugin_id,
        plugin_slug=resolved.plugin_slug,
        status=result.status,
        message=result.message,
        artifacts=result.artifacts,
    )


async def _resolve_credentials(
    db: graph.Graph,
    ctx: PluginContext,
    resolved: ResolvedPlugin,
) -> dict[str, str]:
    """Pick the credentials for a lifecycle call.

    Prefers the per-user identity bearer token when one is hydrated,
    otherwise falls back to the plugin's own credential blob (service
    account PAT).  Raises :class:`PluginCredentialsMissing` when
    neither is available so the dispatcher surfaces a clear ``failed``
    invocation.
    """
    if ctx.identity is not None and ctx.identity.access_token:
        return {'access_token': ctx.identity.access_token}
    credentials = await get_plugin_credentials(
        db, resolved.plugin_id, resolved.entry
    )
    if not credentials.get('access_token') and not credentials.get('token'):
        raise PluginCredentialsMissing(
            f'No credentials available for plugin '
            f'{resolved.plugin_slug!r}: bind an identity or configure '
            f'a service-account token.'
        )
    return credentials


def _extract_http_detail(exc: fastapi.HTTPException) -> str:
    detail: object = exc.detail
    if isinstance(detail, dict):
        detail_dict = typing.cast(dict[str, object], detail)
        error = str(detail_dict.get('error') or 'http_error')
        plugin_id = detail_dict.get('plugin_id')
        # ``identity_required`` carries a ``start_url`` the UI needs to
        # surface; preserve it in the formatted string so the lifecycle
        # event log can reproduce the original re-auth handoff.
        start_url = detail_dict.get('start_url')
        parts: list[str] = []
        if plugin_id:
            parts.append(f'plugin_id={plugin_id}')
        if start_url:
            parts.append(f'start_url={start_url}')
        if parts:
            return f'{error} ({", ".join(parts)})'
        return error
    return str(detail)


_EVENT_COLUMNS = [
    'id',
    'project_id',
    'recorded_at',
    'type',
    'third_party_service',
    'attributed_to',
    'metadata',
    'payload',
]


async def _emit_events_batch(
    project_id: str,
    event: LifecycleEvent,
    invocations: list[LifecycleInvocation],
    auth: permissions.AuthContext,
) -> None:
    """Log all per-plugin lifecycle events in one ClickHouse insert.

    Errors here never bubble — the operator action already succeeded
    and a ClickHouse hiccup must not poison the response. H17: this
    replaces the per-invocation insert that was paying N round trips
    for an N-plugin lifecycle dispatch.
    """
    if not invocations:
        return
    now = datetime.datetime.now(datetime.UTC)
    principal = auth.principal_name
    rows: list[list[typing.Any]] = [
        [
            nanoid.generate(),
            project_id,
            now,
            f'plugin.lifecycle.{event}',
            invocation.plugin_slug,
            principal,
            {'plugin_id': invocation.plugin_id},
            {
                'status': invocation.status,
                'message': invocation.message,
                'artifacts': invocation.artifacts,
            },
        ]
        for invocation in invocations
    ]
    try:
        await ch_client.Clickhouse.get_instance().insert(
            'events', rows, _EVENT_COLUMNS
        )
    except Exception:
        LOGGER.exception(
            'Failed to emit %d lifecycle events for project %s',
            len(rows),
            project_id,
        )
