import contextlib
import datetime
from collections import abc

import fastapi
import typer
from imbi_common import age, lifespan, server

import imbi_assistant
from imbi_assistant import app_status, client, endpoints, mcp


@contextlib.asynccontextmanager
async def _age_lifespan() -> abc.AsyncIterator[None]:
    await age.initialize()
    try:
        yield
    finally:
        await age.aclose()


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


def create_app() -> fastapi.FastAPI:
    app = fastapi.FastAPI(
        title='Imbi Assistant',
        version=imbi_assistant.version,
        started_at=datetime.datetime.now(datetime.UTC),
        lifespan=lifespan.Lifespan(
            _age_lifespan,
            _anthropic_lifespan,
            _mcp_lifespan,
        ),
    )
    app.include_router(app_status.router)
    app.include_router(endpoints.assistant_router)
    return app


cli = typer.Typer(no_args_is_help=True)
cli.command('serve')(
    server.bind_entrypoint('imbi_assistant.app:create_app', default_port=8002)
)


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi Assistant CLI"""
