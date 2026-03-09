import typing as t

import typer

from imbi_mcp.server import mcp

cli = typer.Typer(no_args_is_help=True)


@cli.command()
def serve(
    *,
    transport: t.Annotated[
        str,
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
    mcp.run(transport=transport, host=host, port=port)


@cli.callback()
def _callback() -> None:  # pyright: ignore[reportUnusedFunction]
    """Imbi MCP CLI"""
