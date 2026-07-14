"""Global maintenance operation endpoints (admin Maintenance page).

The operation list is registry-driven (:mod:`imbi_api.maintenance`):
the UI renders whatever this returns, so adding an operation to the
registry is all that is required for a new button to appear.
"""

import datetime
import logging
import typing

import fastapi
import pydantic
from imbi_common import graph

from imbi_api.auth import permissions
from imbi_api.maintenance import (
    OPERATIONS,
    MaintenanceSlug,
    OperationDefinition,
    state,
)
from imbi_api.scoring import OptionalValkeyClient

LOGGER = logging.getLogger(__name__)

maintenance_router = fastapi.APIRouter(
    prefix='/maintenance', tags=['Admin: Maintenance']
)

RequireRead = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(
        permissions.require_permission('admin:maintenance:read'),
    ),
]
RequireManage = typing.Annotated[
    permissions.AuthContext,
    fastapi.Depends(
        permissions.require_permission('admin:maintenance:manage'),
    ),
]


class MaintenanceProgress(pydantic.BaseModel):
    """Counters for an operation's current or last run."""

    total: int = 0
    remaining: int = 0
    in_flight: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


class MaintenanceOperation(pydantic.BaseModel):
    """One registry operation merged with its run state."""

    slug: str
    label: str
    description: str
    running: bool
    state: state.RunState
    progress: MaintenanceProgress | None = None
    started_at: datetime.datetime | None = None
    started_by: str | None = None
    completed_at: datetime.datetime | None = None
    #: Per-project failure detail; only populated on the per-operation
    #: GET to keep the list response small.
    failures: dict[str, str] | None = None


class MaintenanceRunResponse(pydantic.BaseModel):
    """Acknowledgement that a run was started."""

    run_id: str
    total: int


def _to_operation(
    definition: OperationDefinition,
    status: state.RunStatus,
    failures: dict[str, str] | None = None,
) -> MaintenanceOperation:
    progress: MaintenanceProgress | None = None
    if status.state != 'idle':
        progress = MaintenanceProgress(
            total=status.total,
            remaining=status.remaining,
            in_flight=status.in_flight,
            succeeded=status.succeeded,
            failed=status.failed,
            skipped=status.skipped,
        )
    return MaintenanceOperation(
        slug=definition.slug,
        label=definition.label,
        description=definition.description,
        running=status.state == 'running',
        state=status.state,
        progress=progress,
        started_at=status.started_at,
        started_by=status.started_by,
        completed_at=status.completed_at,
        failures=failures,
    )


def _definition_or_404(slug: str) -> OperationDefinition:
    definition = OPERATIONS.get(typing.cast('MaintenanceSlug', slug))
    if definition is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'Unknown maintenance operation {slug!r}'
        )
    return definition


@maintenance_router.get('/operations')
async def list_maintenance_operations(
    auth: RequireRead,
    client: OptionalValkeyClient,
) -> list[MaintenanceOperation]:
    """The operation registry merged with each operation's run state."""
    _ = auth
    if client is None:
        raise fastapi.HTTPException(
            status_code=503,
            detail='Maintenance state is unavailable '
            '(Valkey is not connected).',
        )
    results: list[MaintenanceOperation] = []
    for definition in OPERATIONS.values():
        status = await state.read_status(client, definition.slug)
        results.append(_to_operation(definition, status))
    return results


@maintenance_router.get('/operations/{slug}')
async def get_maintenance_operation(
    slug: str,
    auth: RequireRead,
    client: OptionalValkeyClient,
) -> MaintenanceOperation:
    """One operation's run state, including per-project failures."""
    _ = auth
    definition = _definition_or_404(slug)
    if client is None:
        raise fastapi.HTTPException(
            status_code=503,
            detail='Maintenance state is unavailable '
            '(Valkey is not connected).',
        )
    status = await state.read_status(client, definition.slug)
    failures = await state.read_failures(client, definition.slug)
    return _to_operation(definition, status, failures or None)


@maintenance_router.post('/operations/{slug}/run', status_code=202)
async def run_maintenance_operation(
    slug: str,
    auth: RequireManage,
    db: graph.Pool,
    client: OptionalValkeyClient,
) -> MaintenanceRunResponse:
    """Start a global run of the operation across all projects."""
    definition = _definition_or_404(slug)
    if client is None:
        raise fastapi.HTTPException(
            status_code=503,
            detail='Queueing is unavailable (Valkey is not connected).',
        )
    project_ids = await definition.enumerate(db)
    status = await state.start_run(
        client, definition.slug, project_ids, auth.principal_name
    )
    if status is None:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'{definition.label} is already running.',
        )
    LOGGER.info(
        'maintenance %s run %s started by %s (%d projects)',
        definition.slug,
        status.run_id,
        auth.principal_name,
        status.total,
    )
    return MaintenanceRunResponse(
        run_id=status.run_id or '', total=status.total
    )


@maintenance_router.post('/operations/{slug}/cancel')
async def cancel_maintenance_operation(
    slug: str,
    auth: RequireManage,
    client: OptionalValkeyClient,
) -> MaintenanceOperation:
    """Cancel the operation's in-progress run."""
    definition = _definition_or_404(slug)
    if client is None:
        raise fastapi.HTTPException(
            status_code=503,
            detail='Queueing is unavailable (Valkey is not connected).',
        )
    cancelled = await state.cancel_run(client, definition.slug)
    if not cancelled:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'{definition.label} is not running.',
        )
    LOGGER.info(
        'maintenance %s run cancelled by %s',
        definition.slug,
        auth.principal_name,
    )
    status = await state.read_status(client, definition.slug)
    return _to_operation(definition, status)
