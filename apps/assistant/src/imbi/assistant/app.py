import contextlib
import datetime
from typing import TYPE_CHECKING

import fastapi
import typer

import imbi.assistant
from imbi.assistant import (
    app_status,
    client,
    endpoints,
    links,
    mcp,
    settings,
)
from imbi.common import (
    external_mcp,
    graph,
    lifespan,
    posthog,
    sentry,
    server,
)
from imbi.common.prompts import pool as prompt_pool

if TYPE_CHECKING:
    from collections import abc


@contextlib.asynccontextmanager
async def _anthropic_lifespan() -> abc.AsyncIterator[None]:
    await client.initialize()
    try:
        yield
    finally:
        await client.aclose()


@contextlib.asynccontextmanager
async def _mcp_lifespan() -> abc.AsyncIterator[None]:
    await mcp.initialize()
    try:
        yield
    finally:
        await mcp.aclose()


@contextlib.asynccontextmanager
async def _links_lifespan() -> abc.AsyncIterator[None]:
    await links.initialize()
    yield


def create_app() -> fastapi.FastAPI:
    app = fastapi.FastAPI(
        title='Imbi Assistant',
        version=imbi.assistant.version,
        started_at=datetime.datetime.now(datetime.UTC),
        lifespan=lifespan.Lifespan(
            sentry.sentry_lifespan,
            graph.graph_lifespan,
            prompt_pool.pool_lifespan,
            _anthropic_lifespan,
            _mcp_lifespan,
            _links_lifespan,
            external_mcp.lifespan,
        ),
    )
    prefix = settings.get_assistant_settings().api_prefix
    app.include_router(app_status.router)
    app.include_router(endpoints.assistant_router, prefix=prefix)
    posthog.install(app)
    return app


cli = typer.Typer(no_args_is_help=True)
cli.command('serve')(
    server.bind_entrypoint(
        'imbi.assistant.app:create_app',
        default_port=8002,
    )
)


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi Assistant CLI"""
