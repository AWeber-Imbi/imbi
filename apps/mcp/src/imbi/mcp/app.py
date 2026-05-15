import logging
import os
import typing as t

import sentry_sdk
import typer

from imbi_mcp import server

_LOGGER = logging.getLogger(__name__)

Transport = t.Literal['stdio', 'http', 'sse', 'streamable-http']

cli = typer.Typer(no_args_is_help=True)


def _init_sentry() -> None:
    """Initialize Sentry SDK if SENTRY_DSN is configured."""
    dsn = os.environ.get('SENTRY_DSN')
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        send_default_pii=False,
        server_name=os.environ.get('SERVICE', 'imbi-mcp'),
        traces_sample_rate=float(
            os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0.1')
        ),
    )
    _LOGGER.info('Sentry initialized for imbi-mcp')


@cli.command()
def serve(
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
) -> None:
    """Run the Imbi MCP server."""
    _init_sentry()
    try:
        mcp = server.create_server(api_url)
    except Exception as err:
        raise typer.BadParameter(
            f'Failed to connect to Imbi API at {api_url}: {err}',
            param_hint='--api-url',
        ) from err
    mcp.run(transport=transport, host=host, port=port)


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi MCP CLI"""
