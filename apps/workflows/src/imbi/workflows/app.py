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
from imbi.common import graph, iggy, lifespan, server
from imbi.common import settings as common_settings
from imbi.common.prompts import pool as prompt_pool
from imbi.workflows import engine, executors, settings, store

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
            runner = engine.Engine(
                store.Store(pool, worker_id),
                executors.Executors(executors.Api(client, config), db, config),
                config,
            )
            listener = asyncio.create_task(runner.listen())
            loop = asyncio.create_task(runner.run_forever(stop))
            try:
                yield runner
            finally:
                stop.set()
                runner.notify()
                await asyncio.wait({loop}, timeout=SHUTDOWN_DRAIN_TIMEOUT)
                for task in (loop, listener):
                    task.cancel()
                await asyncio.gather(loop, listener, return_exceptions=True)
    finally:
        await pool.close()
        await db.close()


@contextlib.asynccontextmanager
async def iggy_lifespan() -> abc.AsyncGenerator[None]:
    """Connect to Iggy, which takes run history to ClickHouse.

    Runs go on without it: the archive sweep of imbi-api publishes what
    the engine could not (ADR 0021, Run history).
    """
    try:
        connected = await iggy.initialize()
    except Exception:  # noqa: BLE001 -- the sweep publishes later
        LOGGER.warning('Iggy initialization failed', exc_info=True)
        connected = False
    if not connected:
        LOGGER.warning('Iggy is not available; the sweep publishes history')
    try:
        yield
    finally:
        await iggy.aclose()


class Status(pydantic.BaseModel):
    service: str = 'imbi-workflows'
    status: typing.Literal['ok']
    version: str
    started_at: datetime.datetime


def create_app() -> fastapi.FastAPI:
    app = fastapi.FastAPI(
        version=imbi.workflows.version,
        started_at=datetime.datetime.now(datetime.UTC),
        lifespan=lifespan.Lifespan(
            prompt_pool.pool_lifespan, iggy_lifespan, engine_lifespan
        ),
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
