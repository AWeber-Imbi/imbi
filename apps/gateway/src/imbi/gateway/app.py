import fastapi
import typer
from imbi_common import server

cli = typer.Typer(no_args_is_help=True)
cli.command('serve')(server.bind_entrypoint('imbi_gateway.app:create_app'))


def create_app() -> fastapi.FastAPI:
    return fastapi.FastAPI()


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi Gateway CLI"""
    # Providing an empty callback forces typer to require a command
    # name - https://typer.tiangolo.com/tutorial/commands/one-or-multiple/
    # This is only necessary since we only have one command.
