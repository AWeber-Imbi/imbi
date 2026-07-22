import contextlib
import datetime
import logging
from typing import TYPE_CHECKING

import fastapi
import typer
from imbi_common import graph, lifespan, sentry, server

import imbi_assistant
from imbi_assistant import (
    app_status,
    client,
    endpoints,
    external_mcp,
    links,
    mcp,
    settings,
)

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


@contextlib.asynccontextmanager
async def _external_mcp_lifespan() -> abc.AsyncIterator[None]:
    # Runs after graph.graph_lifespan, so the graph has been
    # initialized; open a short-lived connection to read the
    # configured MCPServer nodes. A DB failure here must not
    # prevent the service from starting.
    db = graph.Graph()
    try:
        await db.open()
        try:
            await external_mcp.initialize(db)
        finally:
            await db.close()
    except Exception:
        logging.getLogger(__name__).exception(
            'Failed to initialize external MCP servers'
        )
        # Ensure a manager exists so request handling does not 500.
        await external_mcp.ensure_manager()
    try:
        yield
    finally:
        await external_mcp.aclose()


def create_app() -> fastapi.FastAPI:
    app = fastapi.FastAPI(
        title='Imbi Assistant',
        version=imbi_assistant.version,
        started_at=datetime.datetime.now(datetime.UTC),
        lifespan=lifespan.Lifespan(
            sentry.sentry_lifespan,
            graph.graph_lifespan,
            _anthropic_lifespan,
            _mcp_lifespan,
            _links_lifespan,
            _external_mcp_lifespan,
        ),
    )
    prefix = settings.get_assistant_settings().api_prefix
    app.include_router(app_status.router)
    app.include_router(endpoints.assistant_router, prefix=prefix)
    return app


cli = typer.Typer(no_args_is_help=True)
cli.command('serve')(
    server.bind_entrypoint(
        'imbi_assistant.app:create_app',
        default_port=8002,
    )
)


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi Assistant CLI"""
