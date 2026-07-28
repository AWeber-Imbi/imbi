import datetime

import fastapi
import typer

import imbi.scheduler
from imbi.common import access_log, lifespan, server
from imbi.scheduler import app_status, lifespans, store


def create_app() -> fastapi.FastAPI:
    """Create and configure the FastAPI application instance."""
    app = fastapi.FastAPI(
        version=imbi.scheduler.version,
        started_at=datetime.datetime.now(datetime.UTC),
        # No graph lifespan: the scheduler reads no graph entities, and
        # `graph_lifespan` runs the full graph bootstrap (extensions, vlabels,
        # indexes, embeddings table, SQL functions) plus opens a second
        # psycopg pool — schema this member never touches, raced against
        # imbi-api's own bootstrap on every boot. It comes back with the
        # endpoints that resolve caller permissions from the graph.
        lifespan=lifespan.Lifespan(
            lifespans.clickhouse_hook, store.store_lifespan
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
