"""Task CRUD, lifecycle, and on-demand firing.

The PRD's table, minus every ``/credentials`` route (ADR 0002 removed the
credential store, so there is nothing for them to manage).

Creation takes a request model rather than :class:`models.Task` so the
server owns what the server should own: the id, the timestamps, the outcome
counters, ``created_by`` (the authenticated caller, never a claim in the
body), and ``next_run_at`` (computed from the trigger, so a task cannot be
created already due or never due).
"""

import datetime
import typing
import uuid

import fastapi
import pydantic

from imbi.common import patch as json_patch
from imbi.scheduler import (
    executor,
    identity,
    models,
    runs,
    settings,
    store,
    triggers,
)
from imbi.scheduler.endpoints import dependencies

router = fastapi.APIRouter(tags=['Scheduled Tasks'])

#: Fields the server owns. A patch that reaches for one of these is refused
#: rather than silently ignored, so a caller never believes it took effect.
READONLY_PATHS: frozenset[str] = frozenset(
    [
        '/id',
        '/created_at',
        '/created_by',
        '/updated_at',
        '/last_run_at',
        '/next_run_at',
        '/consecutive_skips',
        '/consecutive_no_effect',
    ]
)


class TaskCreate(pydantic.BaseModel):
    """A new scheduled task, as a caller supplies it."""

    model_config = pydantic.ConfigDict(extra='forbid')

    slug: str
    name: str
    description: str | None = None
    organization: str | None = None
    enabled: bool = True
    kind: typing.Literal['system', 'user'] = 'user'
    trigger: triggers.Trigger
    timezone: str = 'UTC'
    identity: models.Identity | None = None
    target: models.Target
    execution: models.ExecutionPolicy = models.ExecutionPolicy()
    tags: list[str] = []


def _created(body: TaskCreate, created_by: str) -> models.Task:
    """Build the task to store from a create request."""
    now = datetime.datetime.now(datetime.UTC)
    return _scheduled(
        models.Task(
            id=uuid.uuid4(),
            created_by=created_by,
            created_at=now,
            updated_at=now,
            **body.model_dump(),
        )
    )


def _scheduled(task: models.Task) -> models.Task:
    """Return `task` with its next firing computed from now.

    Through the model so the trigger's own timezone handling applies. A
    disabled task carries no firing time at all, rather than a stale one that
    would read as a misfire whenever it is re-enabled.
    """
    now = datetime.datetime.now(datetime.UTC)
    following = task.next_fire_time(now) if task.enabled else None
    return task.model_copy(update={'next_run_at': following})


@router.get(
    '/tasks',
    summary='List scheduled tasks',
    operation_id='listTasks',
    dependencies=[dependencies.requires(dependencies.READ)],
)
async def list_tasks(
    *,
    tasks: dependencies.Tasks,
    organization: str | None = None,
    kind: typing.Literal['system', 'user'] | None = None,
    enabled: bool | None = None,
    tag: str | None = None,
) -> list[models.Task]:
    """Return every task matching the filters supplied.

    Unfiltered by ownership: reading the schedule is not managing it, and an
    operator debugging why something fired needs to see the task that did it.
    """
    return await tasks.search(
        organization=organization, kind=kind, enabled=enabled, tag=tag
    )


@router.post(
    '/tasks',
    status_code=201,
    summary='Create a scheduled task',
    operation_id='createTask',
)
async def create_task(
    *,
    tasks: dependencies.Tasks,
    body: TaskCreate,
    auth: dependencies.RequiresCreate,
) -> models.Task:
    """Create a task owned by the authenticated caller."""
    dependencies.authorize_system_kind(auth, body.kind)
    try:
        task = _created(body, auth.principal_name)
    except pydantic.ValidationError as err:
        # The cross-field rules live on `models.Task`, not on the request
        # model: whether an identity is required depends on the target kind,
        # and duplicating that here would let the two disagree.
        raise fastapi.HTTPException(
            status_code=422, detail=_errors(err)
        ) from err
    try:
        return await tasks.create(task)
    except store.UnresolvableIdentity as err:
        # 422 rather than 500: the request is well-formed but names a
        # principal this scheduler could never run as, so every firing would
        # skip. Refusing at creation beats storing a task that never works.
        raise fastapi.HTTPException(status_code=422, detail=str(err)) from err


@router.get(
    '/tasks/{slug}',
    summary='Fetch a scheduled task',
    operation_id='getTask',
    dependencies=[dependencies.requires(dependencies.READ)],
)
async def get_task(
    *,
    tasks: dependencies.Tasks,
    slug: str,
) -> models.Task:
    """Return one task, including its computed ``next_run_at``."""
    return await dependencies.load(tasks, slug)


@router.patch(
    '/tasks/{slug}',
    summary='Update a scheduled task',
    operation_id='patchTask',
)
async def patch_task(
    *,
    tasks: dependencies.Tasks,
    slug: str,
    operations: list[json_patch.PatchOperation],
    auth: dependencies.RequiresWrite,
) -> models.Task:
    """Apply an RFC 6902 patch, per the platform's PATCH convention.

    ``next_run_at`` is recomputed whenever the patch touches anything the
    firing time depends on. Leaving it alone would let a caller change a
    daily trigger to hourly and have the old time stand until it fired once
    more -- the change would appear to have been accepted and then ignored.
    """
    task = await dependencies.load_for_management(tasks, slug, auth)
    document = task.model_dump(mode='json')
    patched = json_patch.apply_patch(
        document, operations, readonly_paths=READONLY_PATHS
    )
    try:
        updated = models.Task.model_validate(patched)
    except pydantic.ValidationError as err:
        raise fastapi.HTTPException(
            status_code=422, detail=_errors(err)
        ) from err
    if updated.slug != task.slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='slug identifies the task and cannot be patched',
        )
    # Against the *patched* kind, not the stored one. `load_for_management`
    # has already authorized the caller for the task as it exists, which says
    # nothing about what they are turning it into: an owner holding only
    # `scheduled_task:write` could otherwise patch `/kind` to `system` and
    # take a task creation would never have let them make. Deliberately not
    # a readonly path, so an admin can still promote one.
    dependencies.authorize_system_kind(auth, updated.kind)
    # The same predicate ``Tasks.create`` and fire time use, so a patch cannot
    # put a task into a state creation would have refused.
    reason = identity.unresolvable(updated.identity, settings.get_settings())
    if reason is not None:
        raise fastapi.HTTPException(status_code=422, detail=reason)
    if _reschedules(task, updated):
        updated = _scheduled(updated)
    stored = await tasks.update(updated)
    if stored is None:  # pragma: no cover - it was loaded a moment ago
        raise fastapi.HTTPException(status_code=404, detail=slug)
    return stored


def _errors(err: pydantic.ValidationError) -> list[dict[str, typing.Any]]:
    """Return `err`'s errors as location, message, and type.

    Not ``ValidationError.errors()`` directly: it keeps the original exception
    under ``ctx`` and the rejected value under ``input``, neither of which
    FastAPI can serialize once a UUID or datetime is involved -- the response
    would become a 500 describing a 422. Dropping ``input`` also keeps the
    error from echoing the whole submitted document back.
    """
    return [
        {
            'loc': [str(part) for part in error['loc']],
            'msg': error['msg'],
            'type': error['type'],
        }
        for error in err.errors(include_context=False, include_url=False)
    ]


def _reschedules(before: models.Task, after: models.Task) -> bool:
    """Return whether the firing time has to be recomputed."""
    return (
        before.trigger != after.trigger
        or before.timezone != after.timezone
        or before.enabled != after.enabled
    )


@router.delete(
    '/tasks/{slug}',
    status_code=204,
    summary='Delete a scheduled task',
    operation_id='deleteTask',
)
async def delete_task(
    *,
    tasks: dependencies.Tasks,
    slug: str,
    auth: dependencies.RequiresDelete,
) -> fastapi.Response:
    """Delete a task. Its run history in ClickHouse is left alone."""
    await dependencies.load_for_management(tasks, slug, auth)
    await tasks.delete(slug)
    return fastapi.Response(status_code=204)


@router.post(
    '/tasks/{slug}/pause',
    summary='Disable a scheduled task',
    operation_id='pauseTask',
)
async def pause_task(
    *,
    tasks: dependencies.Tasks,
    slug: str,
    auth: dependencies.RequiresWrite,
) -> models.Task:
    """Disable a task without deleting it."""
    await dependencies.load_for_management(tasks, slug, auth)
    return await _set_enabled(tasks, slug, enabled=False)


@router.post(
    '/tasks/{slug}/resume',
    summary='Re-enable a scheduled task',
    operation_id='resumeTask',
)
async def resume_task(
    *,
    tasks: dependencies.Tasks,
    slug: str,
    auth: dependencies.RequiresWrite,
) -> models.Task:
    """Re-enable a task, rescheduling it from now.

    The stored ``next_run_at`` is in the past by the time anyone resumes, so
    without the reschedule the first tick would read it as a misfire.
    """
    await dependencies.load_for_management(tasks, slug, auth)
    return await _set_enabled(tasks, slug, enabled=True)


async def _set_enabled(
    tasks: store.Tasks, slug: str, *, enabled: bool
) -> models.Task:
    task = await tasks.set_enabled(slug, enabled=enabled)
    if task is None:  # pragma: no cover - it was loaded a moment ago
        raise fastapi.HTTPException(status_code=404, detail=slug)
    return task


@router.post(
    '/tasks/{slug}/run',
    summary='Fire a scheduled task now',
    operation_id='runTask',
)
async def run_task(
    *,
    tasks: dependencies.Tasks,
    engine: dependencies.Engine,
    slug: str,
    auth: dependencies.RequiresRun,
) -> runs.Run:
    """Fire the task immediately and return the resulting run.

    A disabled task still runs on demand: disabling stops the schedule, and
    an operator firing one by hand is usually testing whether it is safe to
    re-enable.
    """
    task = await dependencies.load_for_management(tasks, slug, auth)
    return await engine.run_now(task)


@router.post(
    '/tasks/{slug}/dry-run',
    summary='Render a firing without making it',
    operation_id='dryRunTask',
    dependencies=[dependencies.requires(dependencies.READ)],
)
async def dry_run_task(
    *,
    tasks: dependencies.Tasks,
    engine: dependencies.Engine,
    slug: str,
) -> executor.DryRun:
    """Resolve identity and render the target, making no outbound call.

    Under ``scheduled_task:read`` rather than ``:run`` because nothing
    happens -- and this is the endpoint an operator reaches for first when a
    task is misbehaving, so gating it behind write access would push them
    toward firing it for real to find out why.
    """
    task = await dependencies.load(tasks, slug)
    return await engine.dry_run(task)
