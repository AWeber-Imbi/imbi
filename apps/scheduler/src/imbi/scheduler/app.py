import datetime

import fastapi
import typer

import imbi.scheduler
from imbi.common import access_log, graph, lifespan, server
from imbi.scheduler import app_status, lifespans


def create_app() -> fastapi.FastAPI:
    """Create and configure the FastAPI application instance."""
    app = fastapi.FastAPI(
        version=imbi.scheduler.version,
        started_at=datetime.datetime.now(datetime.UTC),
        lifespan=lifespan.Lifespan(
            graph.graph_lifespan, lifespans.clickhouse_hook
        ),
    )
    app.include_router(app_status.router)
    app.add_middleware(
        access_log.AccessLogMiddleware,
        quiet_paths={'/status', '/scheduler/status'},
    )
    return app


cli = typer.Typer(no_args_is_help=True)
cli.command('serve')(server.bind_entrypoint('imbi.scheduler.app:create_app'))


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi Scheduler CLI"""
    # Providing an empty callback forces typer to require a command
    # name - https://typer.tiangolo.com/tutorial/commands/one-or-multiple/
    # This is only necessary since we only have one command.
