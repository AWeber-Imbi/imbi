"""Injected resources and the ownership rule.

Authentication is entirely :mod:`imbi.common.auth.permissions` -- the same
bearer handling, the same graph-resolved permissions, the same
``require_permission`` as imbi-api. What is local to this member is
authorization *over a task*, which the PRD states as: a caller manages the
tasks they created, and anything else needs ``scheduled_task:admin``.
"""

import typing

import fastapi

from imbi.common.auth import permissions
from imbi.scheduler import lifespans, models, store

#: Every permission this service checks. Named here so the routes read as the
#: PRD table does, and so a typo is an import error rather than a 403.
READ = 'scheduled_task:read'
CREATE = 'scheduled_task:create'
WRITE = 'scheduled_task:write'
DELETE = 'scheduled_task:delete'
RUN = 'scheduled_task:run'
ADMIN = 'scheduled_task:admin'

# Each injected resource is declared beside the lifespan hook that opens it,
# so there is one dependency identity per resource. A second alias here would
# mean a test overriding one of them silently misses routes wired to the other.
Tasks = store.TaskStore
Engine = lifespans.EngineDependency

AuthContext = permissions.AuthContext


def requires(permission: str) -> typing.Any:
    """Return a route-level dependency enforcing `permission`.

    For routes that need the permission checked but never read the resulting
    context -- the read-only ones. Route-level rather than a parameter so
    there is no unused argument to discard, and the permission stays
    introspectable: the OpenAPI stamper walks the whole dependency tree.
    """
    return fastapi.Depends(permissions.require_permission(permission))


# An alias per permission whose routes actually use the context, to hand to
# `authorize`. Spelled out rather than built by a helper because a helper
# returning `Any` is invisible to the type checker, which would leave every
# route's `auth` parameter untyped.
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


def is_admin(auth: AuthContext) -> bool:
    """Return whether `auth` may manage tasks it does not own."""
    return ADMIN in auth.permissions or auth.is_admin


def authorize_system_kind(auth: AuthContext, kind: str) -> None:
    """Raise 403 unless `auth` may act on a task of `kind`.

    A ``system`` task is off limits without ``scheduled_task:admin`` however
    it was created: those are the platform's own jobs, and the scheduler's
    service account is what creates them, so ownership alone would hand
    control of every system task to that account's holders. Creation checks
    this too -- against the requested kind rather than a stored one -- which
    is why it lives here and not inside :func:`authorize`.
    """
    if kind == 'system' and not is_admin(auth):
        raise fastapi.HTTPException(
            status_code=403,
            detail=f'{ADMIN} is required to manage system tasks',
        )


def authorize(auth: AuthContext, task: models.Task) -> None:
    """Raise 403 unless `auth` may manage `task`."""
    if is_admin(auth):
        return
    authorize_system_kind(auth, task.kind)
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
