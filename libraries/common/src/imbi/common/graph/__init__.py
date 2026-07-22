"""Graph subpackage — Apache AGE, Cypher, embeddings, chunking."""

import contextlib
import typing
from collections import abc

import fastapi

from imbi.common import lifespan
from imbi.common.graph.client import (
    Graph,
    SearchResult,
    parse_agtype,
)
from imbi.common.graph.initializer import initialize

OnStartup = abc.Callable[[Graph], abc.Awaitable[None]]

_on_startup: OnStartup | None = None


def set_on_startup(callback: OnStartup) -> None:
    """Register a callback invoked after the graph pool opens."""
    global _on_startup
    _on_startup = callback


@contextlib.asynccontextmanager
async def graph_lifespan() -> abc.AsyncIterator[Graph]:
    await initialize()
    graph = Graph()
    await graph.open()
    try:
        if _on_startup is not None:
            await _on_startup(graph)
        yield graph
    finally:
        await graph.close()


async def _inject_graph(
    context: lifespan.InjectLifespan,
) -> abc.AsyncIterator[Graph]:
    yield context.get_state(graph_lifespan)


Pool = typing.Annotated[
    Graph,
    fastapi.Depends(_inject_graph),
]


__all__ = [
    'Graph',
    'OnStartup',
    'Pool',
    'SearchResult',
    'graph_lifespan',
    'parse_agtype',
    'set_on_startup',
]
