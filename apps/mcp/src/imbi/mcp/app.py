import logging
import typing as t

import typer
from starlette.middleware import Middleware

from imbi.common import access_log
from imbi.common import logging as imbi_logging
from imbi.common.sentry import init as init_sentry
from imbi.mcp import server

_LOGGER = logging.getLogger(__name__)

Transport = t.Literal['stdio', 'http', 'sse', 'streamable-http']

cli = typer.Typer(no_args_is_help=True)


@cli.command()
def serve(  # noqa: PLR0913 - CLI options map 1:1 to parameters
    *,
    api_url: t.Annotated[
        str,
        typer.Option(
            help='Internal base URL of the Imbi API (cluster service)',
            envvar='IMBI_INTERNAL_API_URL',
        ),
    ] = 'http://localhost:8000',
    transport: t.Annotated[
        Transport,
        typer.Option(help='MCP transport type'),
    ] = 'streamable-http',
    host: t.Annotated[
        str,
        typer.Option(help='Host to bind to'),
    ] = '127.0.0.1',
    port: t.Annotated[
        int,
        typer.Option(help='Port to bind to'),
    ] = 8001,
    public_url: t.Annotated[
        str | None,
        typer.Option(
            help='Public base URL of the host fronting this server, '
            'WITHOUT the /mcp path (e.g. https://host). FastMCP '
            'appends its own /mcp mount path when advertising the '
            'OAuth resource; including it here doubles the path '
            '(/mcp/mcp) and breaks client discovery. Enables OAuth '
            'when set together with --auth-server-url.',
            envvar='IMBI_MCP_PUBLIC_URL',
        ),
    ] = None,
    auth_server_url: t.Annotated[
        str | None,
        typer.Option(
            help='Imbi OAuth issuer URL (e.g. https://host). Enables '
            'OAuth when set together with --public-url.',
            envvar='IMBI_MCP_AUTH_SERVER_URL',
        ),
    ] = None,
) -> None:
    """Run the Imbi MCP server."""
    init_sentry()
    try:
        mcp = server.create_server(
            api_url,
            public_url=public_url,
            auth_server_url=auth_server_url,
        )
    except Exception as err:
        raise typer.BadParameter(
            f'Failed to connect to Imbi API at {api_url}: {err}',
            param_hint='--api-url',
        ) from err
    if transport == 'stdio':
        mcp.run(transport=transport)
        return
    # FastMCP runs its own uvicorn rather than going through
    # ``imbi.common.server``, so the shared log config and the Imbi
    # access log have to be handed to it here. Without this the process
    # logs uvicorn's default access line, which has no principal and no
    # tool name.
    log_config = imbi_logging.get_log_config()
    mcp.run(
        transport=transport,
        host=host,
        port=port,
        middleware=[
            Middleware(access_log.AccessLogMiddleware, quiet_paths={'/status'})
        ],
        uvicorn_config={'access_log': False, 'log_config': log_config},
    )


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi MCP CLI"""
