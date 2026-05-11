import datetime

import fastapi
import typer
from imbi_common import access_log, graph, lifespan, server

import imbi_gateway
from imbi_gateway import app_status, lifespans, notifications


def create_app() -> fastapi.FastAPI:
    app = fastapi.FastAPI(
        version=imbi_gateway.version,
        started_at=datetime.datetime.now(datetime.UTC),
        lifespan=lifespan.Lifespan(
            graph.graph_lifespan, lifespans.clickhouse_hook
        ),
    )
    app.include_router(notifications.router)
    app.include_router(app_status.router)
    app.add_middleware(
        access_log.AccessLogMiddleware,
        quiet_paths={'/status', '/gateway/status'},
    )
    return app


cli = typer.Typer(no_args_is_help=True)
cli.command('serve')(server.bind_entrypoint('imbi_gateway.app:create_app'))


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi Gateway CLI"""
    # Providing an empty callback forces typer to require a command
    # name - https://typer.tiangolo.com/tutorial/commands/one-or-multiple/
    # This is only necessary since we only have one command.
