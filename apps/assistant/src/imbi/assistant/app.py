import datetime

import fastapi
import typer
from imbi_common import lifespan, server

import imbi_assistant
from imbi_assistant import app_status


def create_app() -> fastapi.FastAPI:
    app = fastapi.FastAPI(
        title='Imbi Assistant',
        version=imbi_assistant.version,
        started_at=datetime.datetime.now(datetime.UTC),
        lifespan=lifespan.Lifespan(),
    )
    app.include_router(app_status.router)
    return app


cli = typer.Typer(no_args_is_help=True)
cli.command('serve')(
    server.bind_entrypoint('imbi_assistant.app:create_app', default_port=8002)
)


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi Assistant CLI"""
