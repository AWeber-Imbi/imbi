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

import datetime
import json
import logging
import typing

import fastapi
import nanoid
from valkey import asyncio as valkey

from imbi.api.auth import permissions, principals
from imbi.api.maintenance import log
from imbi.api.scoring import queue as score_queue
from imbi.common import clickhouse, graph, versioning
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
    """Backfill recent remote deployments via the deployment plugin."""
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


_RELEASE_NODES_QUERY: typing.LiteralString = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
OPTIONAL MATCH (r)-[d:DEPLOYED_TO]->(:Environment)
RETURN r.id AS id,
       r.tag AS tag,
       r.committish AS committish,
       r.description AS description,
       r.links AS links,
       r.created_at AS created_at,
       count(d) AS edges
"""

_SET_RELEASE_COMMITTISH: typing.LiteralString = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release {{id: {id}}})
SET r.committish = {committish}
RETURN r.id AS id
"""

_SET_RELEASE_TAG: typing.LiteralString = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release {{id: {id}}})
SET r.tag = {tag},
    r.title = CASE WHEN COALESCE(r.title, '') = ''
        THEN {title} ELSE r.title END,
    r.description = CASE WHEN COALESCE(r.description, '') = ''
        THEN {description} ELSE r.description END,
    r.links = CASE WHEN COALESCE(r.links, '[]') = '[]'
        THEN {links} ELSE r.links END
RETURN r.id AS id
"""

_DELETE_RELEASE: typing.LiteralString = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release {{id: {id}}})
OPTIONAL MATCH (r)-[d:DEPLOYED_TO]->(:Environment)
WITH r, count(d) AS edges
WHERE edges = 0
DETACH DELETE r
"""


class _ReleaseNode(typing.NamedTuple):
    """One ``Release`` node as the repair pass sees it."""

    id: str
    tag: str | None
    committish: str
    description: str | None
    links: str | None
    created_at: str
    edges: int


def _links(node: _ReleaseNode) -> str | None:
    """The node's release links, or ``None`` when it carries none."""
    return node.links if node.links and node.links != '[]' else None


def _release_nodes(rows: list[dict[str, typing.Any]]) -> list[_ReleaseNode]:
    """Parse the repair query's rows, dropping any without an id/committish."""
    out: list[_ReleaseNode] = []
    for row in rows:
        node_id = graph.parse_agtype(row.get('id'))
        committish = graph.parse_agtype(row.get('committish'))
        if not node_id or not committish:
            continue
        tag = graph.parse_agtype(row.get('tag'))
        description = graph.parse_agtype(row.get('description'))
        links = graph.parse_agtype(row.get('links'))
        created_at = graph.parse_agtype(row.get('created_at'))
        edges = graph.parse_agtype(row.get('edges'))
        out.append(
            _ReleaseNode(
                id=str(node_id),
                tag=str(tag) if tag else None,
                committish=str(committish),
                description=str(description) if description else None,
                links=str(links) if links else None,
                created_at=str(created_at) if created_at else '',
                edges=int(edges) if isinstance(edges, int) else 0,
            )
        )
    return out


async def execute_release_repair(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Repair ``Release`` node identity for one project.

    Three defects, all of which leave a deployed release unrecognizable to
    the Deployments tab (it falls back to showing a bare SHA, and its
    release list empties out):

    1. A ``committish`` stored at full SHA length. Every writer is supposed
       to record ``sha[:7].lower()`` (see ``_resync_release_identity``), and
       the deploy path looks releases up by that short form -- so a
       long-form node can never be matched, and a deploy of it attaches to
       some other node for the same commit instead.
    2. An untagged node that owns the deployment history for a commit while
       a *sibling* node holds the tag. The tag moves onto the node with the
       history, along with the title/notes/links it was missing, rather than
       moving edges between nodes (which would rewrite deploy history).
    3. The now-redundant siblings. Deleted only when they carry no
       deployment edges at all, so no history is ever discarded; a
       duplicate that does carry edges is left in place and logged.

    Skipped when nothing needed repair. Idempotent: a second run over
    repaired data finds nothing and skips.
    """
    rows = await db.execute(
        _RELEASE_NODES_QUERY,
        {'project_id': project_id},
        [
            'id',
            'tag',
            'committish',
            'description',
            'links',
            'created_at',
            'edges',
        ],
    )
    nodes = _release_nodes(rows)
    if not nodes:
        return _skip(ctx, 'release-repair', 'Project has no releases.')

    normalized = 0
    shortened: list[_ReleaseNode] = []
    for node in nodes:
        short = versioning.short_committish(node.committish)
        if short == node.committish:
            shortened.append(node)
            continue
        await db.execute(
            _SET_RELEASE_COMMITTISH,
            {'project_id': project_id, 'id': node.id, 'committish': short},
            ['id'],
        )
        normalized += 1
        shortened.append(node._replace(committish=short))

    groups: dict[str, list[_ReleaseNode]] = {}
    for node in shortened:
        groups.setdefault(node.committish, []).append(node)

    retagged = 0
    salvaged = 0
    removed = 0
    for committish, group in groups.items():
        tags = {node.tag for node in group if node.tag}
        if len(group) < 2 or len(tags) != 1:
            # Nothing to fold: a lone node, or siblings disagreeing on the
            # tag (a retagged commit is ambiguous -- leave it alone).
            continue
        tag = tags.pop()
        # Whichever node carries the deployment history wins: moving edges
        # between nodes would rewrite deploy history, whereas moving the
        # *tag* onto the node that already owns the history preserves it.
        # Ties break on the oldest node so repeated runs pick the same one.
        target = min(group, key=lambda n: (-n.edges, n.created_at, n.id))
        # Notes live on whichever sibling the writer happened to fill in, so
        # salvage whatever the target lacks before the edge-less duplicates
        # are deleted. Each field is sourced independently, preferring the
        # tag carrier, and _SET_RELEASE_TAG's COALESCE guards leave anything
        # the target already holds alone.
        siblings = sorted(
            (n for n in group if n.id != target.id),
            key=lambda n: n.tag != tag,
        )
        description = target.description or next(
            (n.description for n in siblings if n.description), None
        )
        links = _links(target) or next(
            (_links(n) for n in siblings if _links(n)), None
        )
        salvages = bool(
            (description and not target.description)
            or (links and not _links(target))
        )
        if target.tag is None or salvages:
            await db.execute(
                _SET_RELEASE_TAG,
                {
                    'project_id': project_id,
                    'id': target.id,
                    'tag': tag,
                    'title': tag,
                    'description': description or '',
                    'links': links or '[]',
                },
                ['id'],
            )
            if target.tag is None:
                retagged += 1
            else:
                salvaged += 1
        for node in group:
            if node.id == target.id:
                continue
            if node.edges:
                LOGGER.warning(
                    'release-repair: project %s commit %s has a duplicate '
                    'release %s carrying %d deployment edge(s); left in '
                    'place for review',
                    project_id,
                    committish,
                    node.id,
                    node.edges,
                )
                # The one case here that wants a human: a duplicate this
                # cannot remove without discarding deployment history.
                ctx.log.record(
                    'skipped',
                    'duplicate-kept',
                    f'Duplicate release for {committish} carries '
                    f'{node.edges} deployment edge(s); left for review.',
                    release_id=node.id,
                    committish=committish,
                    edges=node.edges,
                )
                continue
            await db.execute(
                _DELETE_RELEASE,
                {'project_id': project_id, 'id': node.id},
                [],
            )
            removed += 1

    if not normalized and not retagged and not salvaged and not removed:
        return _skip(ctx, 'release-repair', 'Nothing needed repair.')
    LOGGER.info(
        'release-repair: project %s normalized=%d retagged=%d salvaged=%d '
        'removed=%d',
        project_id,
        normalized,
        retagged,
        salvaged,
        removed,
    )
    # Counts rather than a row per release: a project can carry hundreds,
    # and "normalized 300 committishes" is the fact an operator acts on.
    # The exceptions above get their own rows because they need one.
    ctx.log.record(
        'succeeded',
        'release-repair',
        f'Normalized {normalized}, moved {retagged} tag(s), salvaged '
        f'{salvaged}, removed {removed} duplicate(s).',
        normalized=normalized,
        retagged=retagged,
        salvaged=salvaged,
        removed=removed,
    )
    return 'succeeded'


_BLOCKED_RELEASES_QUERY: typing.LiteralString = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
WHERE r.blocked_at IS NOT NULL
RETURN r.id AS id,
       r.blocked_at AS blocked_at,
       r.blocked_by AS blocked_by,
       r.blocked_reason AS reason,
       r.blocked_scope AS scope
"""

_MIGRATE_BLOCK_QUERY: typing.LiteralString = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release
      {{id: {id}}})
WHERE r.blocked_at IS NOT NULL
CREATE (r)-[:BLOCKED_BY]->(b:Blocker {{id: {blocker_id},
                                       type: {type},
                                       description: {description},
                                       external_ref: {external_ref},
                                       status: 'open',
                                       scope: {scope},
                                       created_at: {created_at},
                                       created_by: {created_by}}})
SET r.blocked_at = NULL,
    r.blocked_by = NULL,
    r.blocked_reason = NULL,
    r.blocked_scope = NULL,
    r.updated_at = {now}
RETURN r.id AS id
"""


async def execute_blocker_migration(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Move a project's release blocks onto ``Blocker`` nodes.

    Block state used to be ``blocked_at`` / ``blocked_by`` /
    ``blocked_reason`` / ``blocked_scope`` on the ``Release`` itself.
    Every writer and reader now goes through
    ``(:Release)-[:BLOCKED_BY]->(:Blocker)``, so a release still carrying
    the flags would read as shippable -- this converts each one into the
    open blocker it stood for and clears the flags.

    ``blocked_scope = 'tag'`` was only ever written by the release-build
    watcher, so those become ``build-failure`` blockers keeping the
    tag-only scope; everything else was an operator blocking by hand and
    becomes a commit-wide ``manual`` blocker.  Both carry the
    ``external_ref`` their endpoint uses, so a later block or unblock
    lands on the migrated blocker instead of adding another.

    Idempotent: clearing the flags is what makes a second run find
    nothing and skip.  The write itself also requires ``blocked_at`` to
    still be set, so two overlapping runs that read the same flagged
    release create one blocker, not two.
    """
    del client
    from imbi.api.endpoints import project_deployments

    rows = await db.execute(
        _BLOCKED_RELEASES_QUERY,
        {'project_id': project_id},
        ['id', 'blocked_at', 'blocked_by', 'reason', 'scope'],
    )
    if not rows:
        return _skip(
            ctx, 'blocker-migration', 'No release still carries the flags.'
        )
    now = datetime.datetime.now(datetime.UTC).isoformat()
    migrated = 0
    for row in rows:
        release_id = graph.parse_agtype(row.get('id'))
        if not release_id:
            continue
        scope = graph.parse_agtype(row.get('scope'))
        tag_scoped = str(scope) == 'tag' if scope else False
        blocked_at = graph.parse_agtype(row.get('blocked_at'))
        blocked_by = graph.parse_agtype(row.get('blocked_by'))
        reason = graph.parse_agtype(row.get('reason'))
        written = await db.execute(
            _MIGRATE_BLOCK_QUERY,
            {
                'project_id': project_id,
                'id': str(release_id),
                'blocker_id': nanoid.generate(),
                'type': 'build-failure' if tag_scoped else 'manual',
                'description': str(reason) if reason else 'Blocked',
                'external_ref': (
                    project_deployments.BUILD_FAILURE_REF
                    if tag_scoped
                    else project_deployments.MANUAL_BLOCK_REF
                ),
                'scope': 'tag' if tag_scoped else 'commit',
                'created_at': str(blocked_at) if blocked_at else now,
                'created_by': str(blocked_by) if blocked_by else REQUESTED_BY,
                'now': now,
            },
            ['id'],
        )
        # The WHERE guard makes the write conditional: a concurrent run
        # that already cleared the flags leaves nothing to match, so the
        # release must not count as migrated here.
        if written:
            migrated += 1
    if not migrated:
        return _skip(
            ctx,
            'blocker-migration',
            'Another run cleared the flags first; nothing to migrate.',
        )
    LOGGER.info(
        'blocker-migration: project %s migrated=%d', project_id, migrated
    )
    ctx.log.record(
        'succeeded',
        'blocker-migration',
        f'Converted {migrated} release block(s) into blockers.',
        migrated=migrated,
    )
    return 'succeeded'


async def _release_dup_merge(
    db: graph.Graph,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
    dry_run: bool,
) -> ExecuteOutcome:
    from imbi.api import deployment_migration

    action = 'release-dup-merge-report' if dry_run else 'release-dup-merge'
    org_slug = await _org_slug_for(db, project_id)
    if org_slug is None:
        return _skip(ctx, 'no-organization', _NO_ORG)
    summary = await deployment_migration.merge_duplicate_releases(
        db, project_id, org_slug=org_slug, dry_run=dry_run
    )
    if not summary.groups:
        return _skip(ctx, action, 'No releases share a tag.')
    ctx.log.record(
        'succeeded',
        action,
        f'{summary.groups} tag group(s), {summary.merged} release(s) '
        f'folded in' + (' (dry run).' if dry_run else '.'),
        groups=summary.groups,
        merged=summary.merged,
        repointed_deployments=summary.repointed_deployments,
        repointed_blockers=summary.repointed_blockers,
        dry_run=dry_run,
    )
    return 'succeeded'


async def execute_release_dup_merge_report(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Report duplicate ``(project, tag)`` Release groups; writes nothing.

    Skipped means the project has no duplicates (or no organization).
    The per-group plan -- which node survives and why -- is logged.
    """
    del client
    return await _release_dup_merge(db, project_id, ctx=ctx, dry_run=True)


async def execute_release_dup_merge(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Merge duplicate ``(project, tag)`` Release nodes into one.

    See :func:`imbi.api.deployment_migration.merge_duplicate_releases`.
    ``PluginRateLimited`` from the tag resolution propagates so the
    worker requeues the project.
    """
    del client
    return await _release_dup_merge(db, project_id, ctx=ctx, dry_run=False)


async def _deployment_migration(
    db: graph.Graph,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
    dry_run: bool,
) -> ExecuteOutcome:
    from imbi.api import deployment_migration

    action = (
        'deployment-migration-report' if dry_run else 'deployment-migration'
    )
    summary = await deployment_migration.migrate_deployment_arrays(
        db, project_id, dry_run=dry_run
    )
    if not summary.edges:
        return _skip(ctx, action, 'No legacy deployment history left.')
    if summary.malformed:
        # Entries no DeploymentEvent could be made of. They are dropped,
        # and until now that only reached the server log.
        ctx.log.record(
            'failed',
            action,
            f'{summary.malformed} array entry(ies) failed validation and '
            'were dropped.',
            malformed=summary.malformed,
            dry_run=dry_run,
        )
    ctx.log.record(
        'succeeded',
        action,
        f'{summary.entries} legacy entry(ies) became {summary.created} '
        f'deployment(s)' + (' (dry run).' if dry_run else '.'),
        edges=summary.edges,
        entries=summary.entries,
        created=summary.created,
        existing=summary.existing,
        cleared_edges=summary.cleared_edges,
        dry_run=dry_run,
    )
    return 'succeeded'


async def execute_deployment_migration_report(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Report what the array-to-node migration would do; writes nothing."""
    del client
    return await _deployment_migration(db, project_id, ctx=ctx, dry_run=True)


async def execute_deployment_migration(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Migrate legacy ``DEPLOYED_TO`` array entries to Deployment nodes.

    See :func:`imbi.api.deployment_migration.migrate_deployment_arrays`.
    Skipped means the project has no un-migrated arrays left.
    """
    del client
    return await _deployment_migration(db, project_id, ctx=ctx, dry_run=False)


async def _orphan_release_check(
    db: graph.Graph,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
    dry_run: bool,
) -> ExecuteOutcome:
    from imbi.api import deployment_migration

    action = 'orphan-release-check' if dry_run else 'orphan-release-purge'
    org_slug = await _org_slug_for(db, project_id)
    if org_slug is None:
        return _skip(ctx, 'no-organization', _NO_ORG)
    summary = await deployment_migration.purge_orphan_releases(
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
            else f' deleted, with {summary.blockers_deleted} blocker(s).'
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

    See :func:`imbi.api.deployment_migration.purge_orphan_releases`.
    ``PluginRateLimited`` propagates so the worker requeues the project.
    """
    del client
    return await _orphan_release_check(db, project_id, ctx=ctx, dry_run=False)


#: Reindex work items are ``Label:node_id`` -- the maintenance framework
#: distributes opaque item id strings, and a reindex spans every model
#: that declares ``Embeddable`` fields, not one node type.
_REINDEX_ITEM_SEPARATOR = ':'


async def execute_sbom_backfill(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Publish ClickHouse component batches from the graph edges.

    Phase two of the SBoM component migration. Releases ingested before
    dual write have their component sets only as
    ``USES_COMPONENT_RELEASE`` edges; this publishes a ``backfill``
    batch for each one that has no batch yet.

    Safe to run beside live SBoM ingests. Readers resolve a release with
    ``argMax(batch_id, (source = 'ingest', recorded_at))``, so an ingest
    batch outranks a backfill one whatever order the two land in.

    Because of that same ordering, this **fills but does not repair**: a
    release whose ingest batch is wrong keeps it, and this reports
    success having changed nothing for it. Skipped means every release
    already had a batch, or the project has no component edges.
    """
    from imbi.api import sbom_backfill

    del client
    summary = await sbom_backfill.backfill_project(db, project_id)
    if not summary.releases_published:
        return _skip(
            ctx,
            'sbom-backfill',
            f'Every release already has a batch ({summary.releases_skipped} '
            'checked), or the project has no component edges.',
            releases_skipped=summary.releases_skipped,
        )
    LOGGER.info(
        'SBoM backfill published %d batch(es), %d component row(s), '
        'skipped %d already-batched release(s) for project %s',
        summary.releases_published,
        summary.components_written,
        summary.releases_skipped,
        project_id,
    )
    ctx.log.record(
        'succeeded',
        'sbom-backfill',
        f'Published {summary.releases_published} batch(es) covering '
        f'{summary.components_written} component row(s); '
        f'{summary.releases_skipped} release(s) already had one.',
        releases_published=summary.releases_published,
        releases_skipped=summary.releases_skipped,
        components_written=summary.components_written,
    )
    return 'succeeded'


async def execute_sbom_backfill_report(
    db: graph.Graph,
    client: valkey.Valkey,
    project_id: str,
    *,
    ctx: log.MaintenanceContext,
) -> ExecuteOutcome:
    """Report releases whose two stores disagree; writes nothing.

    Compares content rather than counts: each release's
    ``(component_id, component_release_id, version)`` set is sorted and
    hashed on both sides. Equal counts over different members is the
    failure a backfill can introduce, and counting cannot see it.

    Succeeded means disagreements were found and logged -- the same
    report-operation convention as ``release-dup-merge-report``, where
    the outcome says whether there is anything to look at. Skipped means
    the project's stores agree.
    """
    from imbi.api import sbom_backfill

    del client
    summary = await sbom_backfill.reconcile_project(db, project_id)
    if summary.ok:
        return _skip(
            ctx,
            'sbom-backfill-report',
            f'Both stores agree across {summary.matched} release(s).',
            matched=summary.matched,
        )
    # A row per disagreeing release, which is the whole point of a
    # report: "succeeded" on its own says something was found and makes
    # an operator go read the server logs to learn what.
    for release_id, reason in summary.mismatched.items():
        LOGGER.warning(
            'SBoM reconcile mismatch on project %s release %s: %s',
            project_id,
            release_id,
            reason,
        )
        ctx.log.record(
            'failed',
            'sbom-mismatch',
            reason,
            release_id=release_id,
        )
    LOGGER.warning(
        'SBoM reconcile found %d mismatched release(s) against %d '
        'matching for project %s',
        len(summary.mismatched),
        summary.matched,
        project_id,
    )
    ctx.log.record(
        'succeeded',
        'sbom-backfill-report',
        f'{len(summary.mismatched)} release(s) disagree between the graph '
        f'and ClickHouse; {summary.matched} agree.',
        mismatched=len(summary.mismatched),
        matched=summary.matched,
    )
    return 'succeeded'


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
