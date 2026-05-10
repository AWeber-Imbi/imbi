import typing as t

import typer

from imbi_mcp import server

Transport = t.Literal['stdio', 'http', 'sse', 'streamable-http']

cli = typer.Typer(no_args_is_help=True)


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
