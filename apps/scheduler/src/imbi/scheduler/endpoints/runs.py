"""Run history and cancellation.

History lives in ClickHouse and task definitions in Postgres, so a run is
read from one and authorized against the other: the ownership rule is a
property of the task, and a run only carries its ``task_id``.
"""

import typing
import uuid

import fastapi
import pydantic

from imbi.scheduler import runs as runs_module
from imbi.scheduler.endpoints import dependencies

router = fastapi.APIRouter(tags=['Scheduled Task Runs'])

DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 500


class CancelResult(pydantic.BaseModel):
    """The outcome of asking a run to stop.

    ``requested`` rather than ``cancelled``: the request is recorded and
    broadcast synchronously, but the replica running the job is the one that
    acts on it, so a caller learns the ask landed rather than that the job is
    already stopped. Poll ``GET /runs/{run_id}`` for the terminal state.
    """

    run_id: str
    requested: bool
    detail: str


@router.get(
    '/tasks/{slug}/runs',
    summary='List a task run history',
    operation_id='listTaskRuns',
)
async def list_task_runs(
    *,
    tasks: dependencies.Tasks,
    slug: str,
    auth: dependencies.RequiresRead,
    limit: typing.Annotated[
        int, fastapi.Query(ge=1, le=MAX_HISTORY_LIMIT)
    ] = DEFAULT_HISTORY_LIMIT,
    offset: typing.Annotated[int, fastapi.Query(ge=0)] = 0,
) -> list[runs_module.Run]:
    """Return the task's runs, newest first."""
    del auth
    task = await dependencies.load(tasks, slug)
    return await runs_module.for_task(task.id, limit=limit, offset=offset)


@router.get(
    '/runs/{run_id}',
    summary='Fetch a single run',
    operation_id='getRun',
)
async def get_run(
    *,
    run_id: str,
    auth: dependencies.RequiresRead,
) -> runs_module.Run:
    """Return one run with its response excerpt and timings."""
    del auth
    run = await runs_module.get(run_id)
    if run is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'No such run: {run_id}'
        )
    return run


@router.post(
    '/runs/{run_id}/cancel',
    summary='Cancel an in-flight run',
    operation_id='cancelRun',
)
async def cancel_run(
    *,
    tasks: dependencies.Tasks,
    engine: dependencies.Engine,
    run_id: str,
    auth: dependencies.RequiresRun,
) -> CancelResult:
    """Ask the replica running `run_id` to stop it.

    Authorized against the run's task, so cancelling somebody else's job
    needs the same ``scheduled_task:admin`` as editing it. A run whose task
    has since been deleted is cancellable by anyone holding
    ``scheduled_task:run``: there is no owner left to check, and refusing
    would leave a job nobody can stop.
    """
    run = await runs_module.get(run_id)
    if run is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f'No such run: {run_id}'
        )
    task = await tasks.get_by_id(uuid.UUID(run.task_id))
    if task is not None:
        dependencies.authorize(auth, task)
    if run.is_terminal:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Run {run_id} already finished as {run.state}',
        )
    requested = await engine.cancel(run_id)
    if not requested:
        # No lease: the run finished between the history read and now, or the
        # lease expired because the replica running it died. Either way there
        # is nothing to interrupt, and 409 says so without implying the run
        # never existed.
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Run {run_id} is not in flight; it finished or its '
                'execution lease expired'
            ),
        )
    return CancelResult(
        run_id=run_id,
        requested=True,
        detail=(
            'Cancellation requested. The replica running this job will '
            'interrupt it; poll the run for its terminal state.'
        ),
    )
