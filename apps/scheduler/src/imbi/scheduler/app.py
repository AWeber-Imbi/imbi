import datetime

import fastapi
import typer

import imbi.scheduler
from imbi.common import access_log, graph, lifespan, server
from imbi.scheduler import app_status, endpoints, lifespans, store

#: Base path for the API, per PRD section 10. The Caddyfile mounts this
#: service under `/scheduler` with `handle_path`, which strips that segment,
#: so the prefix here is what a caller sees after it.
API_PREFIX = '/api'


def create_app() -> fastapi.FastAPI:
    """Create and configure the FastAPI application instance."""
    app = fastapi.FastAPI(
        version=imbi.scheduler.version,
        started_at=datetime.datetime.now(datetime.UTC),
        # `graph_lifespan` is here for the endpoints: every route below
        # `/tasks` resolves the caller's permissions from the graph, and
        # `graph.Pool` is what the shared auth dependency injects. It
        # costs the full graph bootstrap (extensions, vlabels, indexes,
        # embeddings table, SQL functions) against schema this member
        # never writes, raced with imbi-api's own bootstrap on every
        # boot -- the same bargain imbi-assistant already makes, and the
        # reason the trigger loop does NOT read the graph.
        # Order matters: `engine_hook` borrows the pool `store_lifespan`
        # opens, and the run history it writes needs ClickHouse.
        lifespan=lifespan.Lifespan(
            lifespans.clickhouse_hook,
            graph.graph_lifespan,
            store.store_lifespan,
            lifespans.engine_hook,
        ),
    )
    app.include_router(app_status.router)
    app.include_router(endpoints.router, prefix=API_PREFIX)
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
