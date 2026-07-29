"""Injected resources and the ownership rule.

Authentication is entirely :mod:`imbi.common.auth.permissions` -- the same
bearer handling, the same graph-resolved permissions, the same
``require_permission`` as imbi-api. What is local to this member is
authorization *over a task*, which the PRD states as: a caller manages the
tasks they created, and anything else needs ``scheduled_task:admin``.
"""

import typing

import fastapi

from imbi.common import lifespan
from imbi.common.auth import permissions
from imbi.scheduler import engine as engine_module
from imbi.scheduler import lifespans, models, store

#: Every permission this service checks. Named here so the routes read as the
#: PRD table does, and so a typo is an import error rather than a 403.
READ = 'scheduled_task:read'
CREATE = 'scheduled_task:create'
WRITE = 'scheduled_task:write'
DELETE = 'scheduled_task:delete'
RUN = 'scheduled_task:run'
ADMIN = 'scheduled_task:admin'


def _inject_tasks(context: lifespan.InjectLifespan) -> store.Tasks:
    return context.get_state(store.store_lifespan)


def _inject_engine(
    context: lifespan.InjectLifespan,
) -> engine_module.Engine:
    return context.get_state(lifespans.engine_hook)


Tasks = typing.Annotated[store.Tasks, fastapi.Depends(_inject_tasks)]

Engine = typing.Annotated[
    engine_module.Engine, fastapi.Depends(_inject_engine)
]

AuthContext = permissions.AuthContext


# One alias per permission. A route annotates its caller with the access it
# needs, which is also what stamps `x-imbi-permission` into the OpenAPI schema
# for AI consumers building per-caller toolsets. Spelled out rather than built
# by a helper because a helper returning `Any` is invisible to the type
# checker, and then every route's `auth` parameter becomes untyped.
RequiresRead = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission(READ)),
]
RequiresCreate = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission(CREATE)),
]
RequiresWrite = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission(WRITE)),
]
RequiresDelete = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission(DELETE)),
]
RequiresRun = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(permissions.require_permission(RUN)),
]


def authorize(auth: AuthContext, task: models.Task) -> None:
    """Raise 403 unless `auth` may manage `task`.

    A ``system`` task is off limits without ``scheduled_task:admin`` however
    it was created: those are the platform's own jobs, and the scheduler's
    service account is what created them, so ownership alone would hand
    control of every system task to that account's holders.
    """
    if ADMIN in auth.permissions or auth.is_admin:
        return
    if task.kind == 'system':
        raise fastapi.HTTPException(
            status_code=403,
            detail=f'{ADMIN} is required to manage system tasks',
        )
    if task.created_by != auth.principal_name:
        raise fastapi.HTTPException(
            status_code=403,
            detail=(
                f'{task.slug} belongs to {task.created_by}; '
                f'{ADMIN} is required to manage tasks owned by others'
            ),
        )


async def load(tasks: store.Tasks, slug: str) -> models.Task:
    """Return the task with `slug`, or raise 404."""
    task = await tasks.get(slug)
    if task is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'No such scheduled task: {slug}'
        )
    return task


async def load_for_management(
    tasks: store.Tasks, slug: str, auth: AuthContext
) -> models.Task:
    """Return the task with `slug`, enforcing the ownership rule.

    Existence is checked first, so a caller who cannot manage a task still
    learns it exists. That is the same disclosure every route here makes to
    anyone holding ``scheduled_task:read`` -- which the ownership rule does
    not restrict, since reading the schedule is not managing it.
    """
    task = await load(tasks, slug)
    authorize(auth, task)
    return task
