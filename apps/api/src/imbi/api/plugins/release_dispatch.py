"""Release-tracking plugin fan-out for new ``Release`` nodes.

After the API creates a ``Release`` node, it calls every Integration
bound to the project for ``release-tracking`` (e.g. Sentry records the
release). The call is best-effort and runs after the write: a failure
is logged and recorded as an event, and never undoes the release.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import typing

import nanoid

from imbi.api.plugins import call_with_timeout
from imbi.api.plugins.lifecycle_dispatch import resolve_credentials
from imbi.api.plugins.resolution import (
    ResolvedCapability,
    build_plugin_context,
    resolve_all_capabilities,
)
from imbi.common import graph, iggy
from imbi.common.plugins.base import (
    LifecycleResult,
    PluginContext,
    ReleaseTrackingCapability,
    TrackedRelease,
)

LOGGER = logging.getLogger(__name__)

#: Strong references to running dispatches, so the event loop does not
#: collect a task before it finishes.
_TASKS: set[asyncio.Task[None]] = set()

_ORG_QUERY: typing.LiteralString = """
MATCH (:Project {{id: {project_id}}})
      -[:OWNED_BY]->(:Team)-[:BELONGS_TO]->(o:Organization)
RETURN o.slug AS org_slug
"""


def schedule_release_created(
    db: graph.Graph, project_id: str, release: TrackedRelease
) -> None:
    """Run :func:`dispatch_release_created` without waiting for it.

    A task, not ``BackgroundTasks``: most release writers are workers
    with no request to attach to.
    """
    task = asyncio.create_task(
        dispatch_release_created(db, project_id, release)
    )
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def _invoke(
    resolved: ResolvedCapability, ctx: PluginContext, release: TrackedRelease
) -> LifecycleResult:
    handler = typing.cast(ReleaseTrackingCapability, resolved.capability_cls())
    try:
        return await call_with_timeout(
            handler.on_release_created(
                ctx, resolve_credentials(ctx, resolved), release
            )
        )
    except Exception as exc:
        LOGGER.exception(
            'Release-tracking plugin %s (%s) raised for release %s',
            resolved.plugin_slug,
            resolved.integration_id,
            release.id,
        )
        return LifecycleResult(
            status='failed', message=f'{type(exc).__name__}: {exc}'
        )


async def dispatch_release_created(
    db: graph.Graph, project_id: str, release: TrackedRelease
) -> None:
    """Call ``on_release_created`` on every bound Integration.

    Never raises: the release already exists, so the caller has nothing
    to undo.
    """
    # Lazy import: ``imbi.api.endpoints`` imports every endpoint module,
    # and the release endpoints import this module.
    from imbi.api.endpoints._helpers import (
        lookup_project_exists_in,
        lookup_project_links,
        lookup_project_slugs,
    )

    # ponytail: one dispatch per new release; a resync that finds many
    # old tags repeats the resolution per tag. Batch per project if that
    # shows up.
    try:
        resolved_list = await resolve_all_capabilities(
            db, project_id, 'release-tracking'
        )
        if not resolved_list:
            return
        (
            org_rows,
            (project_slug, team_slug),
            project_links,
            service_connections,
        ) = await asyncio.gather(
            db.execute(_ORG_QUERY, {'project_id': project_id}, ['org_slug']),
            lookup_project_slugs(db, project_id),
            lookup_project_links(db, project_id),
            lookup_project_exists_in(db, project_id),
        )
        if not org_rows:
            return
        org_slug = str(graph.parse_agtype(org_rows[0]['org_slug']))
        results = await asyncio.gather(
            *(
                _invoke(
                    resolved,
                    build_plugin_context(
                        resolved,
                        project_id=project_id,
                        project_slug=project_slug,
                        org_slug=org_slug,
                        team_slug=team_slug,
                        project_links=project_links,
                        service_connections=service_connections,
                    ),
                    release,
                )
                for resolved in resolved_list
            )
        )
        now = datetime.datetime.now(datetime.UTC)
        await iggy.publish_rows(
            'events',
            'lifecycle',
            [
                {
                    'id': nanoid.generate(),
                    'project_id': project_id,
                    'recorded_at': now,
                    'type': 'plugin.release-tracking.created',
                    'integration': resolved.integration_slug,
                    'attributed_to': release.created_by or '',
                    'metadata': {
                        'plugin_id': resolved.integration_id,
                        'release_id': release.id,
                    },
                    'payload': {
                        'status': result.status,
                        'message': result.message,
                        'artifacts': result.artifacts,
                    },
                }
                for resolved, result in zip(
                    resolved_list, results, strict=True
                )
            ],
        )
    except Exception:
        LOGGER.exception(
            'Release-tracking dispatch failed for release %s of project %s',
            release.id,
            project_id,
        )
