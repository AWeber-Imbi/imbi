"""Per-project execute functions for global maintenance operations.

Each ``execute_*`` runs one project's slice of a global run by reusing
the same service code the per-project Doctor endpoints call.  Outcomes:

- return ``'succeeded'`` / ``'skipped'`` (skipped means the operation
  does not apply -- e.g. no integration provides the capability);
- raise :class:`MaintenanceItemFailed` with a user-safe message for
  recordable failures (raw detail belongs in logs only);
- let :class:`~imbi_common.plugins.errors.PluginRateLimited` propagate
  so the worker can requeue the project and pause the operation.

Endpoint modules are imported inside function bodies (the
``commit_sync.service`` pattern) so this module never pulls the
endpoints package at import time.
"""

from __future__ import annotations

import functools
import logging
import typing

import fastapi
from imbi_common import graph
from imbi_common.plugins.errors import PluginRateLimited
from valkey import asyncio as valkey

from imbi_api import models
from imbi_api.auth import permissions
from imbi_api.scoring import queue as score_queue

LOGGER = logging.getLogger(__name__)

#: ``requested_by`` / ``principal_name`` recorded on work this runs.
REQUESTED_BY = 'maintenance'

ExecuteOutcome = typing.Literal['succeeded', 'skipped']

_ORG_SLUG_QUERY: typing.LiteralString = (
    'MATCH (p:Project {{id: {project_id}}})-[:OWNED_BY]->(:Team)'
    '-[:BELONGS_TO]->(o:Organization) RETURN o.slug AS slug'
)


class MaintenanceItemFailed(Exception):
    """One project's operation failed; the message is user-safe."""


@functools.cache
def _system_auth() -> permissions.AuthContext:
    """Synthetic principal for background maintenance work.

    Never persisted; exists so service functions that record
    ``principal_name`` attribute the work to ``'maintenance'``.
    """
    return permissions.AuthContext(
        auth_method='client_credentials',
        service_account=models.ServiceAccount(
            slug=REQUESTED_BY, display_name='Imbi Maintenance'
        ),
    )


async def enumerate_all_projects(db: graph.Graph) -> list[str]:
    """Every project id -- maintenance operations self-classify
    inapplicable projects as skipped rather than pre-filtering (which
    would cost a capability resolution per project up front)."""
    return await score_queue.all_project_ids(db)


async def _org_slug_for(db: graph.Graph, project_id: str) -> str | None:
    rows = await db.execute(
        _ORG_SLUG_QUERY, {'project_id': project_id}, ['slug']
    )
    if not rows:
        return None
    value = graph.parse_agtype(rows[0].get('slug'))
    return str(value) if value else None


async def execute_analysis(
    db: graph.Graph, client: valkey.Valkey, project_id: str
) -> ExecuteOutcome:
    """Run the Doctor analysis and persist the report.

    Per-plugin errors already surface as synthetic ``fail`` findings
    inside the report, so an exception here is infrastructural.
    """
    from imbi_api.endpoints import project_analysis

    org_slug = await _org_slug_for(db, project_id)
    if org_slug is None:
        return 'skipped'
    await project_analysis.run_and_persist(
        db, org_slug, project_id, _system_auth()
    )
    return 'succeeded'


async def execute_commit_sync(
    db: graph.Graph, client: valkey.Valkey, project_id: str
) -> ExecuteOutcome:
    """Full commit/tag backfill, mirroring the queue consumer's status
    transitions so the per-project Doctor status stays truthful."""
    from imbi_api.commit_sync import service

    org_slug = await _org_slug_for(db, project_id)
    if org_slug is None:
        return 'skipped'
    await service.set_status(
        db, project_id, status='running', requested_by=REQUESTED_BY
    )
    try:
        commits, tags = await service.run_sync(db, org_slug, project_id)
    except service.CommitSyncUnavailable as exc:
        await service.set_status(
            db,
            project_id,
            status='failed',
            requested_by=REQUESTED_BY,
            error=str(exc),
        )
        return 'skipped'
    except PluginRateLimited:
        # Leave the project requeue-able; the worker pauses the op.
        await service.set_status(
            db, project_id, status='queued', requested_by=REQUESTED_BY
        )
        raise
    except Exception as exc:
        LOGGER.exception('maintenance commit-sync failed for %s', project_id)
        message = 'Commit sync failed. See server logs for details.'
        await service.set_status(
            db,
            project_id,
            status='failed',
            requested_by=REQUESTED_BY,
            error=message,
        )
        raise MaintenanceItemFailed(message) from exc
    await service.set_status(
        db,
        project_id,
        status='success',
        requested_by=REQUESTED_BY,
        commits=commits,
        tags=tags,
    )
    return 'succeeded'


async def execute_pr_sync(
    db: graph.Graph, client: valkey.Valkey, project_id: str
) -> ExecuteOutcome:
    """Full PR-history backfill; same shape as commit sync."""
    from imbi_api.pr_sync import service

    org_slug = await _org_slug_for(db, project_id)
    if org_slug is None:
        return 'skipped'
    await service.set_status(
        db, project_id, status='running', requested_by=REQUESTED_BY
    )
    try:
        prs = await service.run_sync(db, org_slug, project_id)
    except service.PRSyncUnavailable as exc:
        await service.set_status(
            db,
            project_id,
            status='failed',
            requested_by=REQUESTED_BY,
            error=str(exc),
        )
        return 'skipped'
    except PluginRateLimited:
        # Leave the project requeue-able; the worker pauses the op.
        await service.set_status(
            db, project_id, status='queued', requested_by=REQUESTED_BY
        )
        raise
    except Exception as exc:
        LOGGER.exception('maintenance pr-sync failed for %s', project_id)
        message = 'PR sync failed. See server logs for details.'
        await service.set_status(
            db,
            project_id,
            status='failed',
            requested_by=REQUESTED_BY,
            error=message,
        )
        raise MaintenanceItemFailed(message) from exc
    await service.set_status(
        db,
        project_id,
        status='success',
        requested_by=REQUESTED_BY,
        prs=prs,
    )
    return 'succeeded'


async def execute_deployment_resync(
    db: graph.Graph, client: valkey.Valkey, project_id: str
) -> ExecuteOutcome:
    """Backfill recent remote deployments via the deployment plugin."""
    from imbi_api.endpoints import project_deployments

    org_slug = await _org_slug_for(db, project_id)
    if org_slug is None:
        return 'skipped'
    try:
        await project_deployments.resync_for_project(
            db,
            org_slug=org_slug,
            project_id=project_id,
            auth=_system_auth(),
            limit=1,
        )
    except fastapi.HTTPException as exc:
        # 404: no deployment capability bound; 400: the plugin doesn't
        # support deployment sync. Neither is a failure of this run.
        if exc.status_code in (400, 404):
            return 'skipped'
        raise MaintenanceItemFailed(str(exc.detail)) from exc
    return 'succeeded'


async def execute_rescore(
    db: graph.Graph, client: valkey.Valkey, project_id: str
) -> ExecuteOutcome:
    """Enqueue a score recompute onto the existing scoring stream.

    Succeeded means enqueued -- the scoring workers do the computation
    with their own debounce/DLQ/history handling. Skipped means the
    project was debounced (a recompute is already queued).
    """
    enqueued = await score_queue.enqueue_recompute(
        client, project_id, 'bulk_rescore', REQUESTED_BY
    )
    return 'succeeded' if enqueued else 'skipped'
