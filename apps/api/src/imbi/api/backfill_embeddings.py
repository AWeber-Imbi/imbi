"""One-shot backfill: generate embeddings for all existing nodes.

Run with:
    uv run python -m imbi_api.backfill_embeddings

Iterates every embeddable node type and calls _auto_embed for each
instance that doesn't already have embeddings (or re-embeds if the
stored vectors are stale).
"""

import asyncio
import logging

from imbi_common import graph, models
from imbi_common.graph.client import (
    _embeddable_fields,  # type: ignore[attr-defined]
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(name)s: %(message)s',
)
LOGGER = logging.getLogger('backfill_embeddings')

# Node subclasses — _auto_embed is called normally.
_NODE_TYPES: list[type[models.Node]] = [
    models.Organization,
    models.Blueprint,
    models.Team,
    models.Environment,
    models.ProjectType,
    models.ThirdPartyService,
    models.Tag,
    models.LinkDefinition,
    models.DocumentTemplate,
    models.Project,
]

# GraphModel types that have Embeddable fields but are not Node subclasses.
# match() still works via model_construct fallback; _auto_embed accepts any
# GraphModel even though its type annotation says Node.
_GRAPH_MODEL_TYPES: list[type[models.GraphModel]] = [
    models.Document,
]


async def _embed_type(
    db: graph.Graph,
    node_type: type[models.GraphModel],
) -> int:
    nodes = await db.match(node_type)  # type: ignore[arg-type]
    count = 0
    for node in nodes:
        if not _embeddable_fields(node):  # type: ignore[arg-type]
            continue
        await db._auto_embed(node)  # type: ignore[arg-type]
        count += 1
    return count


async def run() -> None:
    db = graph.Graph()
    await db.open()
    try:
        total = 0
        for node_type in [*_NODE_TYPES, *_GRAPH_MODEL_TYPES]:
            label = node_type.__name__
            LOGGER.info('Embedding %s nodes...', label)
            n = await _embed_type(db, node_type)
            LOGGER.info('  %s: %d nodes embedded', label, n)
            total += n
        LOGGER.info('Done. Total nodes embedded: %d', total)
    finally:
        await db.close()


if __name__ == '__main__':
    asyncio.run(run())
