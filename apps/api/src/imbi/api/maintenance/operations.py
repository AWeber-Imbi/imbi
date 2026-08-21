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

import json
import logging
import typing

import fastapi
from valkey import asyncio as valkey

from imbi.api.auth import permissions, principals
from imbi.api.maintenance import log
from imbi.api.scoring import queue as score_queue
from imbi.common import clickhouse, graph
from imbi.common import models as common_models
from imbi.common.plugins.errors import PluginRateLimited

LOGGER = logging.getLogger(__name__)

#: ``requested_by`` / ``principal_name`` recorded on work this runs.
REQUESTED_BY = principals.MAINTENANCE

#: ``recorded_by`` stamped on ops-log rows the backfill writes, so they
#: are distinguishable from rows the in-product deploy/promote flows write.
OPSLOG_BACKFILL_RECORDED_BY = principals.OPSLOG_BACKFILL

ExecuteOutcome = typing.Literal['succeeded', 'skipped']

#: Recorded whenever an operation cannot resolve a project's owning
#: organization, which every org-scoped service call needs.
_NO_ORG = 'Project has no owning organization.'

_ORG_SLUG_QUERY: typing.LiteralString = (
    'MATCH (p:Project {{id: {project_id}}})-[:OWNED_BY]->(:Team)'
    '-[:BELONGS_TO]->(o:Organization) RETURN o.slug AS slug'
)


class MaintenanceItemFailed(Exception):
    """One project's operation failed; the message is user-safe."""


def _skip(
    ctx: log.MaintenanceContext,
    action: str,
    message: str = '',
    **detail: object,
) -> ExecuteOutcome:
    """Record why this item was skipped, then skip it.

    A bare ``return 'skipped'`` leaves an operator to guess between "no
    integration", "nothing to do", and "no organization"; the attempt row
    says only that nothing happened.
    """
    ctx.log.record('skipped', action, message, **detail)
    return 'skipped'


def _system_auth() -> permissions.AuthContext:
    """Synthetic principal background maintenance work runs under."""
    return principals.system_auth(REQUESTED_BY, 'Imbi Maintenance')


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
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Run the Doctor analysis and persist the report.

    Per-plugin errors already surface as synthetic ``fail`` findings
    inside the report, so an exception here is infrastructural.
    """
    from imbi.api.endpoints import project_analysis

    org_slug = await _org_slug_for(db, project_id)
    if org_slug is None:
        return _skip(ctx, 'no-organization', _NO_ORG)
    await project_analysis.run_and_persist(
        db, org_slug, project_id, _system_auth()
    )
    return 'succeeded'


async def execute_remediate(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
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
        return _skip(ctx, 'no-organization', _NO_ORG)
    response = await project_analysis.remediate_all_for_project(
        db, org_slug=org_slug, project_id=project_id, auth=_system_auth()
    )
    if response is None or not response.outcomes:
        return _skip(
            ctx, 'remediate', 'No persisted report, or no fixable findings.'
        )
    # One row per remediation that did not work: which finding, which
    # plugin, and what it said. Successful fixes stay as a count -- a
    # project with forty findings would otherwise write forty rows to
    # say nothing an operator will read.
    for outcome in response.outcomes:
        if outcome.result.status == 'failed':
            ctx.log.record(
                'failed',
                'remediate',
                outcome.result.message,
                finding=outcome.slug,
                plugin=outcome.plugin_id,
            )
    failed = sum(1 for o in response.outcomes if o.result.status == 'failed')
    fixed = sum(1 for o in response.outcomes if o.result.status == 'fixed')
    ctx.log.record(
        'failed' if failed else 'succeeded',
        'remediate',
        f'{fixed} of {len(response.outcomes)} findings fixed.',
        fixed=fixed,
        failed=failed,
        total=len(response.outcomes),
    )
    if failed:
        raise MaintenanceItemFailed(
            f'{failed} of {len(response.outcomes)} remediations failed; '
            'see server logs for details.'
        )
    return 'succeeded'


async def execute_commit_sync(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Full commit/tag backfill, mirroring the queue consumer's status
    transitions so the per-project Doctor status stays truthful."""
    from imbi.api.commit_sync import service

    org_slug = await _org_slug_for(db, project_id)
    if org_slug is None:
        return _skip(ctx, 'no-organization', _NO_ORG)
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
        return _skip(ctx, 'commit-sync', str(exc))
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
    ctx.log.record(
        'succeeded',
        'commit-sync',
        f'Synced {commits} commit(s) and {tags} tag(s).',
        commits=commits,
        tags=tags,
    )
    return 'succeeded'


async def execute_pr_sync(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Full PR-history backfill; same shape as commit sync."""
    from imbi.api.pr_sync import service

    org_slug = await _org_slug_for(db, project_id)
    if org_slug is None:
        return _skip(ctx, 'no-organization', _NO_ORG)
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
        return _skip(ctx, 'pr-sync', str(exc))
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
    ctx.log.record(
        'succeeded', 'pr-sync', f'Synced {prs} pull request(s).', prs=prs
    )
    return 'succeeded'


async def execute_deployment_resync(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Backfill recent remote deployments via the deployment plugin.

    Also reconciles the ``current_release`` pointer against the
    deployment the provider reports as active, when the plugin can
    report one. This is the only caller that reconciles: repairing a
    pointer is a background correction, and the webhook-lapse queue and
    the operator-triggered resync both stay observation-only.
    """
    from imbi.api.endpoints import project_deployments

    org_slug = await _org_slug_for(db, project_id)
    if org_slug is None:
        return _skip(ctx, 'no-organization', _NO_ORG)
    try:
        await project_deployments.resync_for_project(
            db,
            org_slug=org_slug,
            project_id=project_id,
            auth=_system_auth(),
            limit=1,
            reconcile=True,
        )
    except fastapi.HTTPException as exc:
        # 404: no deployment capability bound; 400: the plugin doesn't
        # support deployment sync. Neither is a failure of this run.
        if exc.status_code in (400, 404):
            return _skip(
                ctx,
                'deployment-resync',
                str(exc.detail),
                status_code=exc.status_code,
            )
        raise MaintenanceItemFailed(str(exc.detail)) from exc
    ctx.log.record('succeeded', 'deployment-resync', 'Backfilled deployments.')
    return 'succeeded'


async def execute_deployment_sweep(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Close out deployments the remote finished but nobody recorded.

    Also backfills two things from git notes: the per-commit verdicts
    in ``imbi.commit_drift``, once per project, and
    ``Release.drift_detected`` for releases no note has answered yet --
    the webhook-loss cover for drift ingestion, the same way the sweep
    itself covers deployment status.  Skipped means the project has no
    deployment capability bound, or had nothing unfinished old enough to
    chase, no unanswered releases, and no notes to record.
    """
    from imbi.api import deployment_sweeper, drift

    summary = await deployment_sweeper.sweep_project(db, project_id)
    stamped: int | None = None
    recorded: int | None = None
    failures: list[str] = []
    org_slug = await _org_slug_for(db, project_id)
    if org_slug is not None:
        try:
            stamped = await drift.sweep_project(
                db, org_slug=org_slug, project_id=project_id
            )
        except PluginRateLimited:
            # Leave the project requeue-able; the worker pauses the op.
            raise
        except Exception:
            # Best-effort backfill: the deployment sweep already
            # completed and its result stands.
            failures.append('drift backfill')
            LOGGER.exception(
                'maintenance drift backfill failed for %s', project_id
            )
            ctx.log.record(
                'failed',
                'drift-backfill',
                'Drift backfill failed. See server logs for details.',
            )
        # Its own try: this one reads ClickHouse, and a ClickHouse
        # problem must not cost the Release stamping above.
        try:
            recorded = await drift.backfill_verdicts(
                db, org_slug=org_slug, project_id=project_id
            )
        except PluginRateLimited:
            raise
        except Exception:
            failures.append('recording drift verdicts')
            LOGGER.exception(
                'per-commit drift backfill failed for %s', project_id
            )
            ctx.log.record(
                'failed',
                'drift-verdicts',
                'Recording drift verdicts failed. See server logs.',
            )
    if (
        (summary is None or not summary.examined)
        and not stamped
        and not recorded
    ):
        if failures:
            # Nothing succeeded *and* something broke, so this is not a
            # quiet no-op.  Raising is how an operation reports a failed
            # item -- ``ExecuteOutcome`` has no ``'failed'`` member --
            # and it stops the attempt row claiming there was nothing to
            # do when in fact the work could not be done.
            raise MaintenanceItemFailed(
                f'{" and ".join(failures)} failed. '
                'See server logs for details.'
            )
        return _skip(
            ctx,
            'deployment-sweep',
            'Nothing unfinished to chase and no unanswered releases.',
        )
    if summary is not None and summary.examined:
        ctx.log.record(
            'succeeded',
            'deployment-sweep',
            f'{summary.resolved} closed out, {summary.expired} marked '
            f'failed, {summary.attached} attached to a release.',
            examined=summary.examined,
            resolved=summary.resolved,
            expired=summary.expired,
            attached=summary.attached,
        )
    if stamped:
        ctx.log.record(
            'succeeded',
            'drift-backfill',
            f'Stamped {stamped} release(s) from git notes.',
            stamped=stamped,
        )
    if recorded:
        ctx.log.record(
            'succeeded',
            'drift-verdicts',
            f'Recorded {recorded} per-commit drift verdict(s).',
            recorded=recorded,
        )
    return 'succeeded'


async def execute_deployment_status_repair(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Put back the ``success`` resync overwrote with ``rolled_back``.

    Reads each mislabelled node's own ``history`` rather than the
    remote, so it costs no API calls and cannot be rate-limited.
    Skipped means the project has no ``rolled_back`` deployments.
    """
    from imbi.api import deployment_status_repair

    summary = await deployment_status_repair.repair_project(db, project_id)
    if not summary.examined:
        return _skip(
            ctx,
            'deployment-status-repair',
            'No deployments marked rolled back.',
        )
    if not summary.repaired:
        # Everything examined lacked a recoverable ``success``.  Report
        # it rather than claiming a repair: these nodes stay wrong and
        # an operator should know the count is not shrinking.
        return _skip(
            ctx,
            'deployment-status-repair',
            f'{summary.unrepairable} rolled-back deployment(s) record no '
            f'prior success to restore.',
            examined=summary.examined,
            unrepairable=summary.unrepairable,
        )
    ctx.log.record(
        'succeeded',
        'deployment-status-repair',
        f'Restored {summary.repaired} deployment(s) to success; '
        f'{summary.unrepairable} had no prior success recorded.',
        examined=summary.examined,
        repaired=summary.repaired,
        unrepairable=summary.unrepairable,
    )
    return 'succeeded'


async def execute_rescore(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Enqueue a score recompute onto the existing scoring stream.

    Succeeded means enqueued -- the scoring workers do the computation
    with their own debounce/DLQ/history handling. Skipped means the
    project was debounced (a recompute is already queued).
    """
    enqueued = await score_queue.enqueue_recompute(
        client, project_id, 'bulk_rescore', REQUESTED_BY
    )
    if not enqueued:
        return _skip(
            ctx, 'rescore', 'A recompute is already queued; debounced.'
        )
    return 'succeeded'


_DEPLOYMENT_EDGES_QUERY: typing.LiteralString = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
      -[d:DEPLOYED_TO]->(e:Environment)
RETURN e.slug AS env_slug,
       r.tag AS tag,
       r.committish AS committish,
       d.deployments AS deployments
"""


def _commit_sha_repairs(
    *,
    env_slug: str,
    committish: str | None,
    candidates: list[str],
    existing_rows: dict[tuple[str, str], list[dict[str, typing.Any]]],
    repaired_ids: set[str],
) -> list[dict[str, typing.Any]]:
    """Rows to re-insert so one deployment edge's env carries its sha.

    Probes both version candidates because an untagged deploy stored the
    committish where a tagged one stored the tag.  ``repaired_ids`` is
    updated in place: two releases cut from the same commit both resolve
    the same untagged row, and it should be rewritten once.
    """
    if not committish:
        return []
    repairs: list[dict[str, typing.Any]] = []
    for candidate in candidates:
        for existing in existing_rows.get((env_slug, candidate), []):
            entry_id = str(existing.get('id') or '')
            if entry_id in repaired_ids:
                continue
            repair = _with_commit_sha(existing, committish)
            if repair is None:
                continue
            repaired_ids.add(entry_id)
            repairs.append(repair)
    return repairs


def _with_commit_sha(
    row: dict[str, typing.Any], committish: str
) -> dict[str, typing.Any] | None:
    """Rewrite an existing ops-log row to carry ``commit_sha``.

    Returns the row to re-insert, or ``None`` when there is nothing to
    repair.  ``operations_log`` is a ``ReplacingMergeTree``, so an insert
    that reuses the row's ``id`` with a bumped ``_row_version`` replaces
    it -- the same read-modify-insert the PATCH endpoint and
    ``complete_opslog_entry`` use.  ``next_row_version`` is borrowed
    from that module rather than reimplemented because its monotonic
    guard is process-wide state.

    Only rows whose ``description`` is a plugin payload object missing a
    ``commit_sha`` are touched: free-text descriptions belong to
    human-authored entries, and a payload that already has the
    committish is already correlatable.
    """
    from imbi.api.endpoints.operations_log import next_row_version

    try:
        decoded: object = json.loads(str(row.get('description') or ''))
    except ValueError:
        return None
    if not isinstance(decoded, dict):
        return None
    payload = typing.cast(dict[str, typing.Any], decoded)
    if payload.get('commit_sha'):
        return None
    repaired = dict(row)
    repaired['description'] = json.dumps(
        {**payload, 'commit_sha': committish}, sort_keys=True
    )
    repaired['_row_version'] = next_row_version(int(row['_row_version']))
    return repaired


async def _existing_opslog_rows(
    project_id: str,
) -> tuple[set[str], dict[tuple[str, str], list[dict[str, typing.Any]]]]:
    """Return the ``operations_log`` 'Deployed' rows already on file.

    Two views of one project's rows: the set of ``external_run_id``
    values, and the full rows grouped by ``(environment_slug,
    version)``.  Both dedupe inserts; the grouped rows also let the
    enrichment pass rewrite a row in place, which is why this reads whole
    rows rather than the three key columns.  Read ``FINAL`` so the
    ``ReplacingMergeTree`` collapse is applied and superseded rows don't
    resurrect a stale key.
    """
    sql = (
        'SELECT * FROM operations_log FINAL'
        " WHERE entry_type = 'Deployed'"
        ' AND is_deleted = 0'
        ' AND project_id = {project_id:String}'
    )
    rows = await clickhouse.client.Clickhouse.get_instance().query(
        sql, {'project_id': project_id}
    )
    run_ids: set[str] = set()
    by_env_version: dict[tuple[str, str], list[dict[str, typing.Any]]] = {}
    for row in rows:
        run_id = row.get('external_run_id')
        if run_id:
            run_ids.add(str(run_id))
        env = str(row.get('environment_slug') or '')
        version = str(row.get('version') or '')
        if env and version:
            by_env_version.setdefault((env, version), []).append(row)
    return run_ids, by_env_version


async def execute_opslog_backfill(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
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

    It also repairs the rows that already exist: any 'Deployed' row whose
    audit payload predates ``commit_sha`` is re-inserted with the
    committish from its deployment edge, so the operations-log UI can
    join every environment of one release train (see
    :func:`_commit_sha_repairs`).

    Skipped when the project has no deployment edges, or every attributed
    event already has a matching ops-log row and no row needs a
    committish filled in.
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
        return _skip(
            ctx, 'opslog-backfill', 'Project has no deployment history.'
        )

    existing_run_ids, existing_rows = await _existing_opslog_rows(project_id)
    existing_env_versions = set(existing_rows)
    project_slug, _team_slug = await lookup_project_slugs(db, project_id)

    pending: list[common_models.OperationLog] = []
    repairs: list[dict[str, typing.Any]] = []
    repaired_ids: set[str] = set()
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
        # Rows written before the audit payload carried `commit_sha` can
        # only be joined to the rest of their release train by tag, which
        # leaves an untagged environment stranded. The edge knows the
        # committish, so fill it in on the rows that already exist.
        repairs.extend(
            _commit_sha_repairs(
                env_slug=env_slug,
                committish=committish,
                candidates=candidates,
                existing_rows=existing_rows,
                repaired_ids=repaired_ids,
            )
        )
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
                    commit_sha=committish,
                    run_url=event.external_run_url,
                    external_run_id=event.external_run_id,
                    occurred_at=event.timestamp,
                )
            )
            if run_id:
                existing_run_ids.add(run_id)
            existing_env_versions.add((env_slug, version))

    if not pending and not repairs:
        return _skip(
            ctx,
            'opslog-backfill',
            'Every attributed deployment already has its ops-log entry.',
        )

    client_instance = clickhouse.client.Clickhouse.get_instance()
    if pending:
        columns: list[str] = []
        values: list[list[typing.Any]] = []
        for entry in pending:
            dumped = entry.model_dump(by_alias=True, mode='python')
            dumped['is_deleted'] = 1 if entry.is_deleted else 0
            if not columns:
                columns = list(dumped.keys())
            values.append(list(dumped.values()))
        await client_instance.insert('operations_log', values, columns)
    if repairs:
        # A separate insert: the repaired rows come off ``SELECT *`` and
        # need not share the model dump's column order.
        LOGGER.debug(
            'opslog-backfill: filling commit_sha on %d row(s) of project %s',
            len(repairs),
            project_id,
        )
        repair_columns = list(repairs[0].keys())
        await client_instance.insert(
            'operations_log',
            [
                [repair[column] for column in repair_columns]
                for repair in repairs
            ],
            repair_columns,
        )
    ctx.log.record(
        'succeeded',
        'opslog-backfill',
        f'Wrote {len(pending)} entry(ies) and filled the committish in on '
        f'{len(repairs)}.',
        written=len(pending),
        repaired=len(repairs),
    )
    return 'succeeded'


async def _orphan_release_check(
    db: graph.Graph,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
    dry_run: bool,
) -> ExecuteOutcome:
    from imbi.api import orphan_releases

    action = 'orphan-release-check' if dry_run else 'orphan-release-purge'
    org_slug = await _org_slug_for(db, project_id)
    if org_slug is None:
        return _skip(ctx, 'no-organization', _NO_ORG)
    summary = await orphan_releases.purge_orphan_releases(
        db, project_id, org_slug=org_slug, dry_run=dry_run
    )
    if summary is None:
        # The integration cannot confirm tag absence; already logged.
        return _skip(
            ctx,
            action,
            "This project's integration cannot confirm whether a tag "
            'exists on the remote.',
        )
    if summary.unresolved:
        # Candidates whose tag lookup failed. Nothing is deleted for
        # them, and an operator re-running the purge should know why the
        # count did not move.
        ctx.log.record(
            'skipped',
            action,
            f'{summary.unresolved} candidate(s) could not be resolved '
            'against the remote.',
            unresolved=summary.unresolved,
        )
    # Only a remote-confirmed orphan counts as work: candidates whose
    # tag exists (or could not be checked) leave nothing to report or
    # delete, and 'succeeded' would misread as "orphans handled".
    if not summary.orphans:
        return _skip(
            ctx,
            action,
            f'{summary.candidates} candidate(s), none confirmed orphaned.',
            tagged=summary.tagged,
            candidates=summary.candidates,
        )
    ctx.log.record(
        'succeeded',
        action,
        f'{summary.orphans} orphaned release(s)'
        + (
            ' found (dry run).'
            if dry_run
            # deleted trails orphans when the delete's re-check declines
            # -- the release gained history since the read. Reporting
            # orphans here would claim a deletion that did not happen.
            else f'; {summary.deleted} deleted, with '
            f'{summary.blockers_deleted} blocker(s).'
        ),
        candidates=summary.candidates,
        orphans=summary.orphans,
        deleted=summary.deleted,
        blockers_deleted=summary.blockers_deleted,
        dry_run=dry_run,
    )
    return 'succeeded'


async def execute_orphan_release_check(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Report Releases whose tag the remote confirms never existed.

    Writes nothing.  Skipped means no remote-confirmed orphans, or the
    project's integration cannot answer (logged).
    """
    del client
    return await _orphan_release_check(db, project_id, ctx=ctx, dry_run=True)


async def execute_orphan_release_purge(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Delete Releases whose tag the remote confirms never existed.

    See :func:`imbi.api.orphan_releases.purge_orphan_releases`.
    ``PluginRateLimited`` propagates so the worker requeues the project.
    """
    del client
    return await _orphan_release_check(db, project_id, ctx=ctx, dry_run=False)


#: Reindex work items are ``Label:node_id`` -- the maintenance framework
#: distributes opaque item id strings, and a reindex spans every model
#: that declares ``Embeddable`` fields, not one node type.
_REINDEX_ITEM_SEPARATOR = ':'


async def enumerate_embeddable_nodes(db: graph.Graph) -> list[str]:
    """Every ``Label:node_id`` whose model declares embeddable fields."""
    items: list[str] = []
    for node_type in graph.embeddable_node_types():
        label = node_type.__name__
        rows = await db.execute(
            f'MATCH (n:{label}) RETURN n.id AS id', {}, ['id']
        )
        items.extend(
            f'{label}{_REINDEX_ITEM_SEPARATOR}{node_id}'
            for node_id in (graph.parse_agtype(row.get('id')) for row in rows)
            if node_id
        )
    return items


async def execute_search_reindex(
    db: graph.Graph,
    client: valkey.Valkey,
    item_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Rebuild one node's search embeddings from its current properties.

    Shares :func:`_search_index.index` with the endpoint write paths so
    there is one definition of "re-read the node and embed it".  Skipped
    when the node went away between enumeration and execution, or when
    its label is no longer embeddable (a run that outlives a model
    change).  ``raise_on_error`` is set so an embedding failure is
    recorded against the node instead of counting as a success --
    reindexing *is* the operation here.
    """
    # Imported here, not at module scope: ``imbi.api.endpoints`` pulls in
    # the maintenance router, which imports this module back.
    from imbi.api.endpoints import _search_index

    label, _, node_id = item_id.partition(_REINDEX_ITEM_SEPARATOR)
    node_type = {t.__name__: t for t in graph.embeddable_node_types()}.get(
        label
    )
    if node_type is None:
        return _skip(
            ctx,
            'search-reindex',
            f'{label} is no longer an embeddable node type.',
            label=label,
        )
    try:
        embedded = await _search_index.index(
            db, node_type, node_id, raise_on_error=True
        )
    except Exception as exc:
        LOGGER.exception('search-reindex failed for %s', item_id)
        raise MaintenanceItemFailed(
            'Could not rebuild the search index for this node.'
        ) from exc
    if not embedded:
        return _skip(
            ctx,
            'search-reindex',
            'Node went away between enumeration and execution.',
            label=label,
        )
    return 'succeeded'
