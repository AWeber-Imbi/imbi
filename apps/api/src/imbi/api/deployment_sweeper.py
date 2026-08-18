"""Chase unfinished deployments to an answer.

Nothing owned the close-out of a deployment: the promote watcher wrote
its result to the project, the gateway webhook is fire-and-forget, and
the only reconciler was operator-triggered.  A workflow that failed
before posting its first deployment status emits no webhook at all, so
the deployment stayed ``pending`` forever -- 738 of them in the
production snapshot, growing by 30-110 a month.

This is the scheduled writer that closes them.  For every ``Deployment``
still ``pending``/``in_progress`` past :data:`STALE_AFTER`, it asks the
project's deployment plugin what the run actually did and records the
answer.  A run that cannot be resolved for :data:`EXPIRE_AFTER` is
marked ``failed`` with a note saying so -- the node's ``history`` keeps
the trail, so a late webhook that contradicts the sweeper is visible
rather than silently overwritten.

It also finishes the correlation the gateway could not: a deployment
recorded against project + environment alone (because no Release
matched at webhook time) is attached to its Release here, once the
Release exists.

Runs as the ``deployment-sweep`` maintenance operation, so it is
scheduler-driven (an ``ApiTarget`` POST from imbi-scheduler), operator-
triggerable from the Maintenance page, and recorded like every other
global run.
"""

from __future__ import annotations

import datetime
import logging
import typing

import fastapi

from imbi.common import deployments, graph

LOGGER = logging.getLogger(__name__)

#: How long a deployment may sit unfinished before the sweeper asks the
#: remote about it.  Long enough that an ordinary rollout finishes on
#: its own and the sweeper never sees it.
STALE_AFTER = datetime.timedelta(minutes=30)

#: How long the sweeper keeps asking before it gives up and calls the
#: deployment failed.  A run this old is not coming back: GitHub has
#: either lost it or never created it.
EXPIRE_AFTER = datetime.timedelta(days=7)

#: ``note`` written on a deployment the sweeper gave up on.  Grepable on
#: purpose: it is the difference between "the remote said it failed" and
#: "nobody ever said anything".
EXPIRED_NOTE = 'expired by sweeper'

_SOURCE = 'sweeper'

_TERMINAL: frozenset[str] = frozenset({'success', 'failed', 'rolled_back'})


class SweepSummary(typing.NamedTuple):
    """What one project's sweep did."""

    examined: int = 0
    resolved: int = 0
    expired: int = 0
    attached: int = 0

    @property
    def wrote_anything(self) -> bool:
        return bool(self.resolved or self.expired or self.attached)


_RELEASE_FOR_TAG: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
WHERE r.tag = {tag}
RETURN r.id AS id
LIMIT 1
"""

_RELEASE_FOR_COMMITTISH: typing.Final[typing.LiteralString] = """
MATCH (:Project {{id: {project_id}}})-[:HAS_RELEASE]->(r:Release)
WHERE r.committish = {committish}
   OR r.promoted_committish = {committish}
RETURN r.id AS id
LIMIT 1
"""


async def _resolve_release(
    db: graph.Graph, item: deployments.StuckDeployment
) -> str | None:
    """Find the Release a gateway event could not resolve at the time.

    Tag first, committish second -- the same order the gateway itself
    uses, and for the same reason: the tag names the artifact while the
    commit under it moves.
    """
    if item.release_tag:
        rows = await db.execute(
            _RELEASE_FOR_TAG,
            {'project_id': item.project_id, 'tag': item.release_tag},
            ['id'],
        )
        if rows:
            return str(graph.parse_agtype(rows[0]['id']))
    if item.release_committish:
        rows = await db.execute(
            _RELEASE_FOR_COMMITTISH,
            {
                'project_id': item.project_id,
                'committish': item.release_committish,
            },
            ['id'],
        )
        if rows:
            return str(graph.parse_agtype(rows[0]['id']))
    return None


async def _record(
    db: graph.Graph,
    item: deployments.StuckDeployment,
    release_id: str | None,
    *,
    status: deployments.DeploymentStatus,
    note: str | None,
    run_url: str | None,
) -> None:
    """Persist a swept outcome.

    An attached deployment goes through ``append_deployment_event`` so a
    success still advances the environment's current-release pointer; an
    unattached one has no release for that pointer to name, so it is
    written straight to the node.
    """
    if release_id is None:
        await deployments.upsert_deployment(
            db,
            org_slug=item.org_slug,
            project_id=item.project_id,
            env_slug=item.env_slug,
            status=status,
            note=note,
            external_run_id=item.external_run_id,
            external_run_url=run_url,
            source=_SOURCE,
        )
        return
    from imbi.api.endpoints.releases import append_deployment_event

    result = await append_deployment_event(
        db,
        org_slug=item.org_slug,
        project_id=item.project_id,
        release_id=release_id,
        env_slug=item.env_slug,
        status=status,
        note=note,
        external_run_id=item.external_run_id,
        external_run_url=run_url,
        source=_SOURCE,
    )
    if isinstance(result, str):
        LOGGER.warning(
            'sweeper could not record deployment %s for project %s: %s',
            item.id,
            item.project_id,
            result,
        )


async def sweep_project(
    db: graph.Graph,
    project_id: str,
    *,
    now: datetime.datetime | None = None,
) -> SweepSummary | None:
    """Sweep one project's unfinished deployments.

    Returns ``None`` when the project has no deployment capability
    bound -- there is nothing to ask, which is not a failure -- and a
    summary otherwise.  A per-deployment plugin failure is logged and
    skipped so one bad run does not stall the rest of the project.
    """
    from imbi.api.endpoints import project_deployments

    now = now or datetime.datetime.now(datetime.UTC)
    stuck = await deployments.stuck_deployments(
        db, project_id=project_id, cutoff=now - STALE_AFTER
    )
    if not stuck:
        return SweepSummary()

    examined = resolved = expired = attached = 0
    for item in stuck:
        examined += 1
        release_id = item.release_id
        if release_id is None:
            release_id = await _resolve_release(db, item)
            if release_id is not None and await deployments.attach_release(
                db,
                project_id=item.project_id,
                deployment_id=item.id,
                release_id=release_id,
            ):
                attached += 1
        try:
            run = await project_deployments.poll_promote_rollout(
                db,
                org_slug=item.org_slug,
                project_id=item.project_id,
                run_id=item.external_run_id,
            )
        except fastapi.HTTPException as exc:
            # 404: nothing provides the deployment capability; 400: the
            # bound plugin can't answer.  Either way no deployment of
            # this project is resolvable, so stop rather than repeat the
            # same resolution failure per row.
            if exc.status_code in (400, 404):
                return None
            LOGGER.warning(
                'sweeper could not poll run %s for project %s: %s',
                item.external_run_id,
                item.project_id,
                exc.detail,
            )
            continue
        except Exception:
            LOGGER.exception(
                'sweeper could not poll run %s for project %s',
                item.external_run_id,
                item.project_id,
            )
            continue

        status = deployments.RUN_STATUS_TO_STATUS.get(run.status)
        if status is not None and status in _TERMINAL:
            await _record(
                db,
                item,
                release_id,
                status=status,
                note=f'closed by sweeper: run {run.status}',
                run_url=run.run_url,
            )
            resolved += 1
        elif item.created_at < now - EXPIRE_AFTER:
            await _record(
                db,
                item,
                release_id,
                status='failed',
                note=EXPIRED_NOTE,
                run_url=run.run_url,
            )
            expired += 1
        elif status is not None and status != item.status:
            # Still running, but further along than the record says.
            await _record(
                db,
                item,
                release_id,
                status=status,
                note=None,
                run_url=run.run_url,
            )
            resolved += 1

    return SweepSummary(examined, resolved, expired, attached)
