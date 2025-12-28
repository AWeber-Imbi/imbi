import pathlib
import tomllib
import typing
from importlib import resources

import typer
import uvicorn

from imbi import settings, version

main = typer.Typer()


class UvicornParameters(typing.TypedDict):
    factory: bool
    host: str
    log_config: dict[str, typing.Any]
    port: int
    reload: typing.NotRequired[bool]
    reload_dirs: typing.NotRequired[list[str]]
    reload_excludes: typing.NotRequired[list[str]]
    proxy_headers: typing.NotRequired[bool]
    headers: typing.NotRequired[list[tuple[str, str]]]
    date_header: typing.NotRequired[bool]
    server_header: typing.NotRequired[bool]
    ws: typing.Literal[
        'auto', 'none', 'websockets', 'websockets-sansio', 'wsproto'
    ]


@main.command()
def run_server(
    *,
    dev: bool = False,
) -> None:
    """Main entrypoint for Imbi, starts HTTP server"""
    config = settings.ServerConfig()

    log_config_file = resources.files('imbi') / 'log-config.toml'
    log_config = tomllib.loads(log_config_file.read_text())

    params: UvicornParameters = {
        'factory': True,
        'host': config.host,
        'port': config.port,
        'log_config': log_config,
        'proxy_headers': True,
        'headers': [('Server', f'imbi/{version}')],
        'date_header': True,
        'server_header': False,
        'ws': 'none',
    }

    if dev or config.environment == 'development':
        loggers = typing.cast(
            'dict[str, dict[str, object]]',
            log_config.setdefault('loggers', {}),
        )
        loggers.setdefault('imbi', {})
        loggers['imbi']['level'] = 'DEBUG'

        params.update(
            {
                'reload': True,
                'reload_dirs': [str(pathlib.Path.cwd() / 'src' / 'imbi')],
                'reload_excludes': ['**/*.pyc'],
            }
        )

    uvicorn.run('imbi.app:create_app', **params)
