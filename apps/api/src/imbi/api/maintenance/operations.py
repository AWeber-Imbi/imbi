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
import json
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
    ``complete_opslog_entry`` use.  ``_next_row_version`` is borrowed
    from that module rather than reimplemented because its monotonic
    guard is process-wide state.

    Only rows whose ``description`` is a plugin payload object missing a
    ``commit_sha`` are touched: free-text descriptions belong to
    human-authored entries, and a payload that already has the
    committish is already correlatable.
    """
    from imbi.api.endpoints.operations_log import _next_row_version

    try:
        payload = json.loads(str(row.get('description') or ''))
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get('commit_sha'):
        return None
    repaired = dict(row)
    repaired['description'] = json.dumps(
        {**payload, 'commit_sha': committish}, sort_keys=True
    )
    repaired['_row_version'] = _next_row_version(int(row['_row_version']))
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
        return 'skipped'

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
        return 'skipped'

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
        await client_instance.insert(
            'operations_log',
            [list(repair.values()) for repair in repairs],
            list(repairs[0].keys()),
        )
    return 'succeeded'
