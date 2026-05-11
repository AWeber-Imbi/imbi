import functools
import inspect
import os
import pathlib
import re
import tomllib
import typing
from collections import abc
from importlib import resources

import click
import typer

# Flag is used to test uvicorn availability without mucking with imports
try:
    import uvicorn

    uvicorn_available = True
except ImportError:  # pragma: no cover
    uvicorn_available = False


class _UvicornRunParams(typing.TypedDict):
    """Provides type hinting for uvicorn.run parameters."""

    access_log: bool
    env_file: pathlib.Path | None
    factory: bool
    host: str
    log_config: dict[str, typing.Any]
    log_level: typing.NotRequired[str | int]
    port: int
    reload: typing.NotRequired[bool]
    reload_dirs: typing.NotRequired[list[str]]


def _verify_import(entrypoint: str) -> str:
    """Verify that `entrypoint` is a python import string."""
    if not re.match(r'^(?P<package>\w+)(?:\.\w+)*:\w+$', entrypoint):
        raise typer.BadParameter(
            'Must be formatted as <package>[.<module>...]:<function>'
        )
    return entrypoint


def serve(
    entrypoint: typing.Annotated[
        str,
        typer.Argument(
            help='Python import string for the application entrypoint',
            callback=_verify_import,
        ),
    ],
    *,
    dev: typing.Annotated[
        bool,
        typer.Option(
            help='Enable debug logging and uvicorn auto-reload',
        ),
    ] = False,
    env_file: typing.Annotated[
        pathlib.Path | None,
        typer.Option(
            help=(
                'Path to .env file to load environment variables from before'
                ' running the application'
            )
        ),
    ] = None,
    host: typing.Annotated[
        str, typer.Option(help='IP or host to bind to')
    ] = '127.0.0.1',
    log_config: typing.Annotated[
        pathlib.Path | None,
        typer.Option(help='Path to TOML log configuration file'),
    ] = None,
    port: typing.Annotated[int, typer.Option(help='Port to bind to')] = 8000,
    verbose: typing.Annotated[
        bool, typer.Option(help='Enable DEBUG logging for the application')
    ] = False,
) -> None:
    """Run the application using uvicorn.

    You must specify the entrypoint as <package>[.<module>...]:<function>.
    The function is called as an application factory and must return a
    fastapi.FastAPI instance.

    You can also set `UVICORN_` prefixed environment variables instead
    of using the command-line flags.

    The environment variable file can be used to load environment variables
    from a file before running the application. However, it cannot be used
    to set uvicorn control environment variables since it is loaded by
    uvicorn [bold]after[/bold] it is running.
    """
    if not uvicorn_available:
        raise click.UsageError(
            'uvicorn is not installed. Install it with the `server` extra'
        ) from None

    if log_config is None:
        config_data = tomllib.loads(
            resources.files('imbi_common')
            .joinpath('log-config.toml')
            .read_text()
        )
    else:
        config_data = tomllib.loads(log_config.read_text())

    loggers = typing.cast(
        'dict[str,dict[str,object]]', config_data.setdefault('loggers', {})
    )

    if dev or verbose:
        # NB - callback guarantees string format
        package_name = entrypoint.split(':')[0].split('.')[0]
        loggers.setdefault(package_name, {})['level'] = 'DEBUG'
        if dev:
            loggers.setdefault('imbi_common', {})['level'] = 'DEBUG'

    args: _UvicornRunParams = {
        'access_log': False,
        'factory': True,
        'env_file': env_file,
        'host': host,
        'log_config': config_data,
        'port': port,
    }
    if dev:
        args['reload'] = True
        extra_dirs = os.environ.get('IMBI_RELOAD_DIRS', '')
        reload_dirs = [p for p in extra_dirs.split(os.pathsep) if p]
        if reload_dirs:
            args['reload_dirs'] = reload_dirs
    uvicorn.run(entrypoint, **args)


def bind_entrypoint(
    entrypoint: str,
    *,
    default_port: int = 8000,
) -> abc.Callable[..., None]:
    """Create a wrapper for serve() with a pre-bound entrypoint.

    This helper function creates a new function that calls serve() with
    a hardcoded entrypoint value. The returned function has the same
    signature as serve() except the entrypoint parameter is removed.

    This is useful when you want to hardcode the entrypoint in your CLI
    so users don't need to specify it each time.

    Args:
        entrypoint: The Python import string (e.g., 'package.module:func')
        default_port: Default port for the ``--port`` option

    Returns:
        A callable that wraps serve() with the entrypoint pre-bound

    Example:
        >>> import typer
        >>> from imbi_common import server
        >>> cli = typer.Typer()
        >>> cli.command('serve')(
        ...     server.bind_entrypoint('my_package.api:create_app',
        ...                            default_port=8002)
        ... )
    """
    sig = inspect.signature(serve)
    # Remove the entrypoint parameter and override the port default
    new_params = []
    for p in sig.parameters.values():
        if p.name == 'entrypoint':
            continue
        if p.name == 'port' and default_port != 8000:
            p = p.replace(default=default_port)
        new_params.append(p)
    new_sig = sig.replace(parameters=new_params)

    @functools.wraps(serve)
    def wrapper(*args: typing.Any, **kwargs: typing.Any) -> None:
        return serve(entrypoint, *args, **kwargs)

    # Override the signature so typer can introspect it correctly
    wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
    return wrapper
