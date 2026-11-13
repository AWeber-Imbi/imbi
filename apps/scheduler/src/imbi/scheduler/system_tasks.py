"""Tasks the scheduler creates for the platform itself.

Each entry is a ``kind: system`` task that calls imbi-api as the scheduler's
service account. At startup the scheduler creates each entry that does not
exist. It never changes a task that exists, so an operator's changes (a new
schedule, a pause) stay after a restart. A change to a default here does not
reach an installation that already has the task. To get the new default,
delete the task and restart the scheduler.
"""

import contextlib
import logging
import typing

from imbi.scheduler import models, settings, store
from imbi.scheduler.endpoints import tasks as tasks_endpoint

if typing.TYPE_CHECKING:
    from collections import abc

LOGGER = logging.getLogger(__name__)

#: The fields of each system task, as ``TaskCreate`` takes them, without
#: ``kind`` and ``identity``. The target must be an ``api`` target.
SYSTEM_TASKS: tuple[dict[str, typing.Any], ...] = (
    {
        'slug': 'marketplace-sync',
        'name': 'Sync agent marketplaces',
        'description': (
            'Starts the marketplace-sync maintenance operation, which reads '
            'the catalog of every agent marketplace again.'
        ),
        'trigger': {'kind': 'interval', 'hours': 1},
        'target': {
            'kind': 'api',
            'method': 'POST',
            'path': '/maintenance/operations/marketplace-sync/run',
        },
    },
)


async def seed(
    tasks: store.Tasks,
    definitions: tuple[dict[str, typing.Any], ...] = SYSTEM_TASKS,
) -> list[str]:
    """Create each system task that does not exist, and return their slugs."""
    account = settings.Scheduler().sa_slug
    created: list[str] = []
    for definition in definitions:
        task = tasks_endpoint.created(
            tasks_endpoint.TaskCreate(
                kind='system',
                identity=models.Identity(
                    kind='service_account', subject=account
                ),
                **definition,
            ),
            account,
        )
        try:
            await tasks.create(task)
        except store.DuplicateSlug:
            continue  # It exists. Keep it as the operator left it.
        LOGGER.info('Created system task %s', task.slug)
        created.append(task.slug)
    return created


@contextlib.asynccontextmanager
async def hook() -> 'abc.AsyncGenerator[None]':
    """Create the missing system tasks before the trigger loop starts.

    Register after :func:`imbi.scheduler.store.store_lifespan`, whose pool
    it borrows, and before the engine, so the first poll sees the tasks.
    """
    await seed(store.Tasks(store.pool()))
    yield
