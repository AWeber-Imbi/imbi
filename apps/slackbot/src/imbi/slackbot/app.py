import contextlib
import datetime
from typing import TYPE_CHECKING

import fastapi
import typer
from imbi_common import graph, lifespan, sentry, server

import imbi_slackbot
from imbi_slackbot import (
    app_status,
    client,
    identity,
    links,
    mcp,
    slack_handler,
)

if TYPE_CHECKING:
    from collections import abc


@contextlib.asynccontextmanager
async def _anthropic_lifespan() -> abc.AsyncGenerator[None, None]:
    await client.initialize()
    try:
        yield
    finally:
        await client.aclose()


@contextlib.asynccontextmanager
async def _mcp_lifespan() -> abc.AsyncGenerator[None, None]:
    await mcp.initialize()
    try:
        yield
    finally:
        await mcp.aclose()


@contextlib.asynccontextmanager
async def _links_lifespan() -> abc.AsyncGenerator[None, None]:
    await links.initialize()
    yield


@contextlib.asynccontextmanager
async def _slack_lifespan() -> abc.AsyncGenerator[None, None]:
    # Runs last so the graph, Anthropic client, and MCP tools are ready
    # before the bot starts accepting Slack events.
    await slack_handler.initialize()
    try:
        yield
    finally:
        await slack_handler.aclose()


def create_app() -> fastapi.FastAPI:
    # Capture the shared graph connection for identity resolution once
    # ``graph_lifespan`` opens it.
    graph.set_on_startup(identity.on_graph_ready)

    app = fastapi.FastAPI(
        title='Imbi Slack Bot',
        version=imbi_slackbot.version,
        started_at=datetime.datetime.now(datetime.UTC),
        lifespan=lifespan.Lifespan(
            sentry.sentry_lifespan,
            graph.graph_lifespan,
            _anthropic_lifespan,
            _mcp_lifespan,
            _links_lifespan,
            _slack_lifespan,
        ),
    )
    app.include_router(app_status.router)
    return app


cli = typer.Typer(no_args_is_help=True)
cli.command('serve')(
    server.bind_entrypoint(
        'imbi_slackbot.app:create_app',
        default_port=8004,
    )
)


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi Slack Bot CLI"""
