"""Poll a dispatched release build and act on its outcome.

The promote endpoint dispatches the project's Release workflow and hands
off here.  This module owns the wait, in two phases: it polls the build
until it reaches a terminal state, then either blocks the release or
finishes the promote (resync tags, refresh the ``Release`` node, create
the Deployment) -- and then polls that Deployment's rollout to its own
terminal state.

Both phases matter to the caller.  Creating the Deployment takes about a
second; the rollout it starts takes minutes, and *that* is what "did my
promote ship?" means.  Reporting ``success`` at the handover would tell
the UI the promote was done while the rollout had not yet started.

Progress is persisted as ``promote_*`` properties on the ``Project``
node, mirroring :mod:`imbi.api.deployment_sync.service` -- the UI polls
it through ``GET /deployments/promote-status`` rather than holding a
connection open for the length of a build.

Unlike the resync worker, the enqueueing user *is* used for attribution:
a promote is something a person did, so ``requested_by`` reaches the
``DeploymentEvent`` and the ``operations_log`` row.  It is not used for
credentials -- a background worker has no per-user identity connection,
so plugin calls resolve the Integration's own service credential
(``best_effort_identity=True``).
"""

from __future__ import annotations

import asyncio
import collections.abc
import datetime
import logging
import typing

import pydantic

from imbi.api.auth import permissions, principals
from imbi.common import graph

LOGGER = logging.getLogger(__name__)

_MAX_ERROR_LEN = 500
_STATUS_WRITE_RETRIES = 3
_STATUS_RETRY_BACKOFF = 0.05

#: First gap between polls.  A release build is minutes long, so there is
#: nothing to gain from a tighter loop -- and the run is frequently still
#: ``queued`` for the first few of these.
POLL_INITIAL_SECONDS = 10.0
#: Ceiling the interval backs off to.
POLL_MAX_SECONDS = 30.0
#: Multiplier applied to the interval after each non-terminal poll.
POLL_BACKOFF = 1.5
#: How long to wait before giving up on a run.  This is not "how long a
#: build takes": ``release.yml`` declares
#: ``concurrency: release-${{ github.repository }}`` with
#: ``cancel-in-progress: false``, so a dispatch can sit queued behind
#: another release for the whole of one before its own first job starts.
TIMEOUT_SECONDS = 45 * 60

#: First gap between rollout polls.  Tighter than the build's: by this
#: point the user has already waited out a build, and a rollout is the
#: part they are watching for.
DEPLOY_POLL_INITIAL_SECONDS = 6.0
#: Ceiling the rollout interval backs off to.
DEPLOY_POLL_MAX_SECONDS = 30.0
#: How long to wait before giving up on a rollout.  Shorter than the
#: build timeout: a Deployment is not serialized behind other releases,
#: so a rollout that has not finished by now is stuck, not queued.
DEPLOY_TIMEOUT_SECONDS = 30 * 60

#: States a workflow run stops moving in.  ``DeploymentRun`` and
#: ``ArtifactRun`` share these, so both poll loops test against it.
TERMINAL_STATUSES = frozenset({'success', 'failure', 'cancelled'})

PromoteState = typing.Literal[
    'idle',
    'building',
    'deploying',
    'success',
    'build_failed',
    'deploy_failed',
    'failed',
]

#: ``principal_name`` stamped on work this worker performs itself.  The
#: promoting user is carried separately for attribution.
REQUESTED_BY = principals.RELEASE_PROMOTE


class PromoteStatus(pydantic.BaseModel):
    """In-flight (or last) promote state for a project."""

    status: PromoteState = 'idle'
    tag: str | None = None
    committish: str | None = None
    environment: str | None = None
    from_environment: str | None = None
    artifact_run_id: str | None = None
    artifact_run_url: str | None = None
    error: str | None = None
    requested_by: str | None = None
    updated_at: datetime.datetime | None = None


def system_auth() -> permissions.AuthContext:
    """Synthetic principal the watcher's plugin calls run under."""
    return principals.system_auth(REQUESTED_BY, 'Imbi Release Promote')


def now_iso() -> str:
    """Current UTC time in the ISO-8601 form stored on the Project node."""
    return datetime.datetime.now(datetime.UTC).isoformat()


def _is_write_conflict(exc: Exception) -> bool:
    """True if *exc* is AGE's concurrent-update conflict (TM_Updated)."""
    return 'failed to be updated' in str(exc)


async def set_status(
    db: graph.Graph,
    project_id: str,
    *,
    status: PromoteState,
    tag: str = '',
    committish: str = '',
    environment: str = '',
    from_environment: str = '',
    artifact_run_id: str = '',
    artifact_run_url: str = '',
    requested_by: str = '',
    error: str = '',
    retry: bool = True,
) -> None:
    """Persist promote state on the ``Project`` node (best-effort).

    *retry* re-attempts on AGE's transient concurrent-update conflict so
    the worker's authoritative transitions still land when a webhook
    touches the project mid-write, exactly as
    :func:`imbi.api.deployment_sync.service.set_status` does.

    There is deliberately no ``only_if_before`` guard here: unlike a
    resync, a promote is not coalescable, so every transition in a single
    promote's lifecycle is strictly ordered by the one worker driving it.
    """
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
    SET p.promote_status = {status},
        p.promote_at = {at},
        p.promote_by = {by},
        p.promote_tag = {tag},
        p.promote_committish = {committish},
        p.promote_environment = {environment},
        p.promote_from_environment = {from_environment},
        p.promote_run_id = {run_id},
        p.promote_run_url = {run_url},
        p.promote_error = {error}
    RETURN p.id AS id
    """
    params = {
        'project_id': project_id,
        'status': status,
        'at': now_iso(),
        'by': requested_by,
        'tag': tag,
        'committish': committish,
        'environment': environment,
        'from_environment': from_environment,
        'run_id': artifact_run_id,
        'run_url': artifact_run_url,
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
                    'release-promote status write for %s lost a concurrent '
                    'update (status=%s); leaving the newer state in place',
                    project_id,
                    status,
                )
            else:
                LOGGER.warning(
                    'Failed to persist promote status for project %s',
                    project_id,
                    exc_info=True,
                )
            return


def _opt_str(value: object) -> str | None:
    text = str(value) if value is not None else ''
    return text or None


def _opt_dt(value: object) -> datetime.datetime | None:
    text = _opt_str(value)
    if text is None:
        return None
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return None


async def read_status(db: graph.Graph, project_id: str) -> PromoteStatus:
    """Read promote state from the ``Project`` node (``idle`` default)."""
    query: typing.LiteralString = """
    MATCH (p:Project {{id: {project_id}}})
    RETURN p.promote_status AS status,
           p.promote_at AS at,
           p.promote_by AS requested_by,
           p.promote_tag AS tag,
           p.promote_committish AS committish,
           p.promote_environment AS environment,
           p.promote_from_environment AS from_environment,
           p.promote_run_id AS run_id,
           p.promote_run_url AS run_url,
           p.promote_error AS error
    """
    keys = [
        'status',
        'at',
        'requested_by',
        'tag',
        'committish',
        'environment',
        'from_environment',
        'run_id',
        'run_url',
        'error',
    ]
    records = await db.execute(query, {'project_id': project_id}, keys)
    if not records:
        return PromoteStatus()
    row = {key: graph.parse_agtype(records[0].get(key)) for key in keys}
    status = _opt_str(row['status']) or 'idle'
    if status not in typing.get_args(PromoteState):
        # A value written by a newer/older build than this one is data we
        # can't interpret; report idle rather than failing the read and
        # blanking the whole panel.
        LOGGER.warning(
            'Unrecognized promote status %r on project %s; reporting idle',
            status,
            project_id,
        )
        status = 'idle'
    return PromoteStatus(
        status=typing.cast('PromoteState', status),
        tag=_opt_str(row['tag']),
        committish=_opt_str(row['committish']),
        environment=_opt_str(row['environment']),
        from_environment=_opt_str(row['from_environment']),
        artifact_run_id=_opt_str(row['run_id']),
        artifact_run_url=_opt_str(row['run_url']),
        error=_opt_str(row['error']),
        requested_by=_opt_str(row['requested_by']),
        updated_at=_opt_dt(row['at']),
    )


class WatchJob(pydantic.BaseModel):
    """One promote awaiting its release build.

    Carries everything the completion path needs so the worker never has
    to re-derive it from a panel the user has since navigated away from.
    ``release_id`` names the ``Release`` node the promote created
    up-front, so a failed build has something to block.
    """

    org_slug: str
    project_id: str
    release_id: str
    tag: str
    committish: str
    to_environment: str
    from_environment: str = ''
    run_id: str = ''
    run_url: str = ''
    requested_by: str = ''
    #: ``false`` for releasable-only projects: build and release, no deploy.
    deploy: bool = True


async def run_watch(
    db: graph.Graph,
    job: WatchJob,
    *,
    valkey_client: object = None,
    timeout_seconds: float = TIMEOUT_SECONDS,
    deploy_timeout_seconds: float = DEPLOY_TIMEOUT_SECONDS,
    sleep: collections.abc.Callable[[float], collections.abc.Awaitable[None]]
    | None = None,
) -> PromoteState:
    """Poll ``job``'s release build and rollout, and act on the outcome.

    Returns the state persisted on the way out.  *sleep* is injectable so
    tests can drive the loop without real time passing; *valkey_client*
    is passed through to the tag resync the success path enqueues.
    *timeout_seconds* bounds the build, *deploy_timeout_seconds* the
    rollout that follows it.

    A run id we never learned (``run_id=''`` -- the bodiless-204 dispatch
    on appliances without the ``2026-03-10`` API version) cannot be
    watched.  That is not a build failure, so the release is *not*
    blocked: the state goes ``failed`` with an explanation and the tag is
    left shippable, because the build may well have succeeded.
    """
    from imbi.api.endpoints import project_deployments

    napper = sleep or asyncio.sleep

    async def mark(
        state: PromoteState, *, error: str = '', run_url: str | None = None
    ) -> None:
        """Persist *state*, carrying the job's identity on every write."""
        await set_status(
            db,
            job.project_id,
            status=state,
            tag=job.tag,
            committish=job.committish,
            environment=job.to_environment,
            from_environment=job.from_environment,
            artifact_run_id=job.run_id,
            artifact_run_url=run_url if run_url is not None else job.run_url,
            requested_by=job.requested_by,
            error=error,
        )

    if not job.run_id:
        LOGGER.warning(
            'release-promote for project %s tag %s has no run id; cannot '
            'watch the build',
            job.project_id,
            job.tag,
        )
        await mark(
            'failed',
            error=(
                'The release workflow was dispatched but the remote did not '
                'report which run it started, so Imbi cannot confirm the '
                'build. Check the run on the remote, then deploy the tag '
                'directly once it is green.'
            ),
        )
        return 'failed'

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    interval = POLL_INITIAL_SECONDS
    status = 'unknown'
    run_url = job.run_url

    while True:
        run = await project_deployments.poll_artifact_run(
            db,
            org_slug=job.org_slug,
            project_id=job.project_id,
            run_id=job.run_id,
        )
        status = run.status
        run_url = run.run_url or run_url
        if status in TERMINAL_STATUSES:
            break
        if loop.time() >= deadline:
            LOGGER.warning(
                'release-promote for project %s tag %s timed out after %.0fs '
                'with the run still %s',
                job.project_id,
                job.tag,
                timeout_seconds,
                status,
            )
            minutes = int(timeout_seconds // 60)
            await project_deployments.fail_promote_build(
                db,
                org_slug=job.org_slug,
                project_id=job.project_id,
                tag=job.tag,
                reason=(
                    f'Release build did not finish within {minutes} minutes '
                    f'(last seen {status})'
                ),
                requested_by=job.requested_by,
            )
            await mark(
                'build_failed',
                error=(
                    f'Release build did not finish within {minutes} minutes. '
                    f'The release is blocked; unblock it to retry.'
                ),
                run_url=run_url or '',
            )
            return 'build_failed'
        await mark('building', run_url=run_url or '')
        await napper(interval)
        interval = min(interval * POLL_BACKOFF, POLL_MAX_SECONDS)

    if status != 'success':
        LOGGER.info(
            'release-promote build for project %s tag %s reported %s',
            job.project_id,
            job.tag,
            status,
        )
        await project_deployments.fail_promote_build(
            db,
            org_slug=job.org_slug,
            project_id=job.project_id,
            tag=job.tag,
            reason=f'Release build reported {status}',
            requested_by=job.requested_by,
        )
        await mark(
            'build_failed',
            error=(
                f'The release build {status}. The release is blocked; fix '
                f'the build and promote a new version, or unblock this one '
                f'to retry it.'
            ),
            run_url=run_url or '',
        )
        return 'build_failed'

    await mark('deploying' if job.deploy else 'success', run_url=run_url or '')
    try:
        deployment = await project_deployments.complete_promote_build(
            db,
            org_slug=job.org_slug,
            project_id=job.project_id,
            release_id=job.release_id,
            tag=job.tag,
            committish=job.committish,
            to_environment=job.to_environment,
            from_environment=job.from_environment,
            requested_by=job.requested_by,
            run_id=job.run_id,
            run_url=run_url,
            deploy=job.deploy,
            valkey_client=valkey_client,
        )
    except Exception as exc:
        LOGGER.exception(
            'release-promote completion failed for project %s tag %s',
            job.project_id,
            job.tag,
        )
        # The build succeeded and the tag exists, so the release is not
        # blocked -- only Imbi's follow-through failed.  Surface it and
        # leave the tag shippable so a redeploy can finish the job.
        await mark(
            'failed',
            error=(
                f'Release built, but Imbi could not finish the promote: {exc}'
            ),
            run_url=run_url or '',
        )
        return 'failed'

    if deployment is None or not deployment.run_id:
        # Releasable-only (no Deployment to watch), or a plugin that
        # created one without telling us which.  Neither is a failure,
        # and neither leaves anything to poll.
        if job.deploy and deployment is not None:
            LOGGER.warning(
                'release-promote for project %s tag %s created a deployment '
                'with no run id; cannot watch the rollout',
                job.project_id,
                job.tag,
            )
        await mark('success', run_url=run_url or '')
        return 'success'

    try:
        return await _watch_rollout(
            db,
            job,
            run_id=deployment.run_id,
            initial_status=deployment.status,
            build_run_url=run_url or '',
            mark=mark,
            napper=napper,
            timeout_seconds=deploy_timeout_seconds,
        )
    except Exception as exc:
        LOGGER.exception(
            'release-promote rollout watch failed for project %s tag %s',
            job.project_id,
            job.tag,
        )
        # Same reasoning as the completion failure above: the tag and the
        # Deployment both exist, so leave the release shippable.  Without
        # this the status would stay ``deploying`` forever and the UI
        # would poll a promote that nothing is driving.
        await mark(
            'failed',
            error=(f'Deployment started, but Imbi lost track of it: {exc}'),
            run_url=run_url or '',
        )
        return 'failed'


async def _watch_rollout(
    db: graph.Graph,
    job: WatchJob,
    *,
    run_id: str,
    initial_status: str,
    build_run_url: str,
    mark: collections.abc.Callable[..., collections.abc.Awaitable[None]],
    napper: collections.abc.Callable[[float], collections.abc.Awaitable[None]],
    timeout_seconds: float,
) -> PromoteState:
    """Poll the promote's Deployment until the rollout settles.

    A failed rollout does *not* block the release: the build was green
    and the tag is real, so the ordinary fix is to redeploy the same tag
    once the cause is fixed, which a block would refuse.  That is the
    difference between ``deploy_failed`` here and ``build_failed`` in the
    build phase.

    *build_run_url* is carried onto every write so the status keeps
    pointing at the run that built the artifact.  The Deployment's own
    URL is deliberately not swapped in: ``artifact_run_id`` names the
    build run, and pairing it with a rollout URL would describe two
    different runs as one.
    """
    from imbi.api.endpoints import project_deployments

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    interval = DEPLOY_POLL_INITIAL_SECONDS
    status = initial_status
    target = job.to_environment or 'its environment'

    while status not in TERMINAL_STATUSES:
        if loop.time() >= deadline:
            minutes = int(timeout_seconds // 60)
            LOGGER.warning(
                'release-promote rollout for project %s tag %s timed out '
                'after %.0fs with the deployment still %s',
                job.project_id,
                job.tag,
                timeout_seconds,
                status,
            )
            await mark(
                'deploy_failed',
                error=(
                    f'The deployment to {target} did not finish within '
                    f'{minutes} minutes (last seen {status}). The release is '
                    f'not blocked -- redeploy {job.tag} once the cause is '
                    f'fixed.'
                ),
                run_url=build_run_url,
            )
            return 'deploy_failed'
        await mark('deploying', run_url=build_run_url)
        await napper(interval)
        interval = min(interval * POLL_BACKOFF, DEPLOY_POLL_MAX_SECONDS)
        run = await project_deployments.poll_promote_rollout(
            db,
            org_slug=job.org_slug,
            project_id=job.project_id,
            run_id=run_id,
        )
        status = run.status

    if status != 'success':
        LOGGER.info(
            'release-promote rollout for project %s tag %s reported %s',
            job.project_id,
            job.tag,
            status,
        )
        await mark(
            'deploy_failed',
            error=(
                f'The deployment of {job.tag} to {target} {status}. The '
                f'release is not blocked -- redeploy it once the cause is '
                f'fixed.'
            ),
            run_url=build_run_url,
        )
        return 'deploy_failed'

    await mark('success', run_url=build_run_url)
    return 'success'
