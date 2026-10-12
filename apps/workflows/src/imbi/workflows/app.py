"""imbi-workflows: the workflow engine with a ``/status`` endpoint."""

import asyncio
import contextlib
import datetime
import logging
import os
import socket
import typing
import uuid
from collections import abc

import fastapi
import httpx
import psycopg_pool
import pydantic
import typer

import imbi.workflows
from imbi.common import graph, lifespan, server
from imbi.common import settings as common_settings
from imbi.common.prompts import pool as prompt_pool
from imbi.workflows import bindings, engine, executors, settings, store

LOGGER = logging.getLogger(__name__)

#: How long shutdown waits for the calls in flight before it cancels.
SHUTDOWN_DRAIN_TIMEOUT = 25.0


@contextlib.asynccontextmanager
async def engine_lifespan() -> abc.AsyncGenerator[engine.Engine]:
    """Run the engine for the life of the process.

    The engine borrows nothing from other hooks: it opens its own graph
    and Postgres pool. imbi-api applies the schemas; this process only
    reads and writes them.
    """
    config = settings.Workflows()
    db = graph.Graph()
    await db.open()
    postgres = common_settings.Postgres()
    pool: store.Pool = psycopg_pool.AsyncConnectionPool(
        conninfo=str(postgres.url),
        min_size=postgres.min_pool_size,
        max_size=postgres.max_pool_size,
        open=False,
    )
    await pool.open()
    stop = asyncio.Event()
    worker_id = f'{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}'
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            steps = executors.Executors(
                executors.Api(client, config), db, config
            )
            runner = engine.Engine(store.Store(pool, worker_id), steps, config)
            reconciler = bindings.Reconciler(pool, client, steps, config)
            listener = asyncio.create_task(runner.listen(reconciler.notify))
            loop = asyncio.create_task(runner.run_forever(stop))
            sync = asyncio.create_task(reconciler.run_forever(stop))
            try:
                yield runner
            finally:
                stop.set()
                runner.notify()
                await asyncio.wait({loop}, timeout=SHUTDOWN_DRAIN_TIMEOUT)
                for task in (loop, listener, sync):
                    task.cancel()
                await asyncio.gather(
                    loop, listener, sync, return_exceptions=True
                )
    finally:
        await pool.close()
        await db.close()


class Status(pydantic.BaseModel):
    service: str = 'imbi-workflows'
    status: typing.Literal['ok']
    version: str
    started_at: datetime.datetime


def create_app() -> fastapi.FastAPI:
    app = fastapi.FastAPI(
        version=imbi.workflows.version,
        started_at=datetime.datetime.now(datetime.UTC),
        lifespan=lifespan.Lifespan(prompt_pool.pool_lifespan, engine_lifespan),
    )

    @app.get('/status', operation_id='getStatus')
    def status(request: fastapi.Request) -> Status:  # pyright: ignore[reportUnusedFunction]
        """Report that this process is up. It checks no dependency."""
        return Status(
            status='ok',
            version=request.app.version,
            started_at=request.app.extra['started_at'],
        )

    return app


cli = typer.Typer(no_args_is_help=True)
cli.command('serve')(
    server.bind_entrypoint('imbi.workflows.app:create_app', default_port=8006)
)


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi Workflows CLI"""
