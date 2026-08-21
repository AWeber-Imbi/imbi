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
    timestamp: datetime.datetime | None = None,
) -> None:
    """Persist a swept outcome.

    An attached deployment goes through ``append_deployment_event`` so a
    success still advances the environment's current-release pointer; an
    unattached one has no release for that pointer to name, so it is
    written straight to the node.

    *timestamp* is when the rollout actually ended, not when the sweep
    noticed.  It matters: the current-release pointer only moves
    forward, so closing a week-old success at sweep time would let it
    supersede a release that shipped after it.  See
    :func:`_close_out_at` for the bound that keeps a remote from
    reporting an end time the sweep could not have observed.

    Only a ``success`` moves an environment's current-release pointer
    (``_set_current_release``, reached through
    ``append_deployment_event``), so a swept ``failed`` cannot promote
    itself to "what is deployed" that way.  It used to arrive there by
    the back door: the readers that *derive* the current release ranked
    by timestamp alone, so any close-out written after a newer rollout
    won regardless of status.  Those readers now exclude ``failed`` and
    ``rolled_back`` -- see
    :func:`imbi.common.deployments.latest_released_deployments_by_project`.
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
            timestamp=timestamp,
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
        timestamp=timestamp,
        source=_SOURCE,
    )
    if isinstance(result, str):
        LOGGER.warning(
            'sweeper could not record deployment %s for project %s: %s',
            item.id,
            item.project_id,
            result,
        )


def _close_out_at(
    completed_at: datetime.datetime | None,
    item: deployments.StuckDeployment,
    now: datetime.datetime,
) -> datetime.datetime:
    """When a swept close-out should claim the rollout ended.

    The remote's completion time, never later than ``now``.  Falls back
    to when the deployment was created, as before, when the remote does
    not say.

    A remote status is not obliged to describe only the deployment it
    hangs off: GitHub's ``inactive`` is stamped with the moment a
    *later* deployment superseded this one, which is a real completion
    time belonging to the wrong rollout.
    :meth:`GitHubDeploymentPlugin.get_deployment_status` now skips
    those, so this bound guards the general case rather than that one --
    any remote reporting a completion the sweep could not have observed
    is pulled back to sweep time instead of landing in the future, where
    it would outrank every deployment that legitimately came after it.

    Deliberately one-sided.  Clamping *up* to ``created_at`` would be
    the wrong direction: a node created by resync carries an ingest-time
    ``created_at`` that can postdate the rollout it describes, and
    raising the close-out to meet it would push the timestamp later --
    which is exactly the failure this bound exists to prevent.
    """
    if completed_at is None:
        return item.created_at
    return min(deployments.as_utc(completed_at), now)


async def _expire_unpollable(
    db: graph.Graph,
    item: deployments.StuckDeployment,
    release_id: str | None,
    now: datetime.datetime,
    error: BaseException,
) -> int:
    """Expire a deployment whose run cannot be polled at all.

    This is the path the dominant stuck class takes.  A deployment
    dispatched months ago and never updated is polled against a run the
    remote no longer has, and the plugin raises rather than answering
    (GitHub's ``get_deployment_status`` calls ``raise_for_status``, so a
    vanished Deployment id is an ``httpx.HTTPStatusError``, not a
    result).  Without expiring here those rows would be polled, fail,
    and be skipped on every sweep forever -- exactly the state this
    sweeper exists to end.

    The note keeps :data:`EXPIRED_NOTE` as its prefix so it stays
    greppable, and names the error class after it so the reason the
    remote could not answer survives on the node.

    Returns 1 when it expired the deployment, 0 when it is still young
    enough to keep asking about.
    """
    if deployments.as_utc(item.created_at) >= now - EXPIRE_AFTER:
        return 0
    await _record(
        db,
        item,
        release_id,
        status='failed',
        note=f'{EXPIRED_NOTE}: {type(error).__name__}',
        run_url=None,
        timestamp=item.created_at,
    )
    return 1


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

    now = deployments.as_utc(now or datetime.datetime.now(datetime.UTC))
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
            #
            # This is deliberately narrow to ``fastapi.HTTPException``,
            # which only resolution raises.  A *remote* 404 -- the run
            # GitHub no longer has -- arrives as an
            # ``httpx.HTTPStatusError`` and must fall through to the
            # per-item handling below, which can expire it.  Widening
            # this to catch remote errors would strand the whole
            # project on its first vanished run.
            if exc.status_code in (400, 404):
                return None
            LOGGER.warning(
                'sweeper could not poll run %s for project %s: %s',
                item.external_run_id,
                item.project_id,
                exc.detail,
            )
            expired += await _expire_unpollable(db, item, release_id, now, exc)
            continue
        except Exception as exc:
            LOGGER.exception(
                'sweeper could not poll run %s for project %s',
                item.external_run_id,
                item.project_id,
            )
            expired += await _expire_unpollable(db, item, release_id, now, exc)
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
                timestamp=_close_out_at(run.completed_at, item, now),
            )
            resolved += 1
        elif deployments.as_utc(item.created_at) < now - EXPIRE_AFTER:
            await _record(
                db,
                item,
                release_id,
                status='failed',
                note=EXPIRED_NOTE,
                run_url=run.run_url,
                timestamp=item.created_at,
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
