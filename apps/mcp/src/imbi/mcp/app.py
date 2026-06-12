import logging
import typing as t

import typer
from imbi_common.sentry import init as init_sentry

from imbi_mcp import server

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
    mcp.run(transport=transport, host=host, port=port)


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi MCP CLI"""
