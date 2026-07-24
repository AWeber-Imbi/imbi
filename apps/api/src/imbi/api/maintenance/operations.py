"""Per-project execute functions for global maintenance operations.

Each ``execute_*`` runs one project's slice of a global run by reusing
the same service code the per-project Doctor endpoints call.  Outcomes:

- return ``'succeeded'`` / ``'skipped'`` (skipped means the operation
  does not apply -- e.g. no integration provides the capability);
- raise :class:`MaintenanceItemFailed` with a user-safe message for
  recordable failures (raw detail belongs in logs only);
- let :class:`~imbi.common.plugins.errors.PluginRateLimited` propagate
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
from valkey import asyncio as valkey

from imbi.api import models
from imbi.api.auth import permissions
from imbi.api.scoring import queue as score_queue
from imbi.common import clickhouse, graph
from imbi.common import models as common_models
from imbi.common.plugins.errors import PluginRateLimited

LOGGER = logging.getLogger(__name__)

#: ``requested_by`` / ``principal_name`` recorded on work this runs.
REQUESTED_BY = 'maintenance'

#: ``recorded_by`` stamped on ops-log rows the backfill writes, so they
#: are distinguishable from rows the in-product deploy/promote flows write.
OPSLOG_BACKFILL_RECORDED_BY = 'maintenance-opslog-backfill'

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
    from imbi.api.endpoints import project_analysis

    org_slug = await _org_slug_for(db, project_id)
    if org_slug is None:
        return 'skipped'
    await project_analysis.run_and_persist(
        db, org_slug, project_id, _system_auth()
    )
    return 'succeeded'


async def execute_remediate(
    db: graph.Graph, client: valkey.Valkey, project_id: str
) -> ExecuteOutcome:
    """Apply every fixable Project Doctor finding for one project.

    Skipped when the project has no persisted report or no fixable
    findings.  Each finding is applied best-effort; if any remediation
    reports ``failed`` the item is a failure (with a count), otherwise it
    succeeded.  The report is re-run and persisted so it reflects the
    fixes, mirroring the per-project ``remediate-all`` endpoint.
    """
    from imbi.api.endpoints import project_analysis

    org_slug = await _org_slug_for(db, project_id)
    if org_slug is None:
        return 'skipped'
    response = await project_analysis.remediate_all_for_project(
        db, org_slug=org_slug, project_id=project_id, auth=_system_auth()
    )
    if response is None or not response.outcomes:
        return 'skipped'
    failed = sum(1 for o in response.outcomes if o.result.status == 'failed')
    if failed:
        raise MaintenanceItemFailed(
            f'{failed} of {len(response.outcomes)} remediations failed; '
            'see server logs for details.'
        )
    return 'succeeded'


async def execute_commit_sync(
    db: graph.Graph, client: valkey.Valkey, project_id: str
) -> ExecuteOutcome:
    """Full commit/tag backfill, mirroring the queue consumer's status
    transitions so the per-project Doctor status stays truthful."""
    from imbi.api.commit_sync import service

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
    from imbi.api.pr_sync import service

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
    from imbi.api.endpoints import project_deployments

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


_DEPLOYMENT_EDGES_QUERY: typing.LiteralString = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
      -[d:DEPLOYED_TO]->(e:Environment)
RETURN e.slug AS env_slug,
       r.tag AS tag,
       r.committish AS committish,
       d.deployments AS deployments
"""


async def _existing_opslog_rows(
    project_id: str,
) -> tuple[set[str], set[tuple[str, str]]]:
    """Return the ``operations_log`` 'Deployed' rows already on file.

    Two dedupe indexes for one project: the set of ``external_run_id``
    values, and the set of ``(environment_slug, version)`` pairs.  Read
    ``FINAL`` so the ``ReplacingMergeTree`` collapse is applied and
    superseded rows don't resurrect a stale key.
    """
    sql = (
        'SELECT environment_slug, version, external_run_id'
        ' FROM operations_log FINAL'
        " WHERE entry_type = 'Deployed'"
        ' AND is_deleted = 0'
        ' AND project_id = {project_id:String}'
    )
    rows = await clickhouse.client.Clickhouse.get_instance().query(
        sql, {'project_id': project_id}
    )
    run_ids: set[str] = set()
    env_versions: set[tuple[str, str]] = set()
    for row in rows:
        run_id = row.get('external_run_id')
        if run_id:
            run_ids.add(str(run_id))
        env = str(row.get('environment_slug') or '')
        version = str(row.get('version') or '')
        if env and version:
            env_versions.add((env, version))
    return run_ids, env_versions


async def execute_opslog_backfill(
    db: graph.Graph, client: valkey.Valkey, project_id: str
) -> ExecuteOutcome:
    """Backfill ``operations_log`` 'Deployed' rows from the graph edges.

    Deployments recorded outside Imbi carry their deployer only on
    ``DeploymentEvent.performed_by`` on the ``DEPLOYED_TO`` edge; the
    ops-log 'Deployed' rows that ``lookup_ops_log_performed_by`` reads to
    resolve "Deployed by" are written solely by the in-product
    deploy/promote flows.  This walks every deployment edge, and for each
    ``success`` event that carries a ``performed_by`` writes a matching
    ops-log row when one does not already exist, closing the attribution
    gap for those releases.

    Events with an empty ``performed_by`` are skipped entirely -- never
    insert one, because ``argMax(performed_by, occurred_at)`` would let a
    newer empty row mask a real deployer.  Events are processed
    newest-first per edge so the most recent attributed deployer is the
    one that survives dedupe for a given ``(environment, version)``.

    Skipped when the project has no deployment edges or every attributed
    event already has a matching ops-log row.
    """
    from imbi.api.endpoints._helpers import (
        deployed_operation_log,
        lookup_project_slugs,
    )
    from imbi.api.endpoints.projects import ops_log_version_candidates

    rows = await db.execute(
        _DEPLOYMENT_EDGES_QUERY,
        {'project_id': project_id},
        ['env_slug', 'tag', 'committish', 'deployments'],
    )
    if not rows:
        return 'skipped'

    existing_run_ids, existing_env_versions = await _existing_opslog_rows(
        project_id
    )
    project_slug, _team_slug = await lookup_project_slugs(db, project_id)

    pending: list[common_models.OperationLog] = []
    for row in rows:
        env_slug = graph.parse_agtype(row.get('env_slug'))
        if not isinstance(env_slug, str) or not env_slug:
            continue
        tag_val = graph.parse_agtype(row.get('tag'))
        committish_val = graph.parse_agtype(row.get('committish'))
        tag = str(tag_val) if tag_val else None
        committish = str(committish_val) if committish_val else None
        version = tag or committish
        if not version:
            continue
        candidates = ops_log_version_candidates(tag, committish)
        events = common_models.parse_deployment_events(
            graph.parse_agtype(row.get('deployments')), on_error='skip'
        )
        for event in sorted(events, key=lambda e: e.timestamp, reverse=True):
            if event.status != 'success' or not event.performed_by:
                continue
            run_id = event.external_run_id
            if run_id and run_id in existing_run_ids:
                continue
            if any((env_slug, v) in existing_env_versions for v in candidates):
                continue
            pending.append(
                deployed_operation_log(
                    project_id=project_id,
                    project_slug=project_slug,
                    environment_slug=env_slug,
                    recorded_by=OPSLOG_BACKFILL_RECORDED_BY,
                    performed_by=event.performed_by,
                    action='opslog-backfill',
                    version=version,
                    run_url=event.external_run_url,
                    external_run_id=event.external_run_id,
                    occurred_at=event.timestamp,
                )
            )
            if run_id:
                existing_run_ids.add(run_id)
            existing_env_versions.add((env_slug, version))

    if not pending:
        return 'skipped'

    columns: list[str] = []
    values: list[list[typing.Any]] = []
    for entry in pending:
        dumped = entry.model_dump(by_alias=True, mode='python')
        dumped['is_deleted'] = 1 if entry.is_deleted else 0
        if not columns:
            columns = list(dumped.keys())
        values.append(list(dumped.values()))
    await clickhouse.client.Clickhouse.get_instance().insert(
        'operations_log', values, columns
    )
    return 'succeeded'
