"""One-shot backfill: generate embeddings for all existing nodes.

Run with::

    uv run python -m imbi_api.backfill_embeddings

Iterates every embeddable node type and calls ``_auto_embed`` for each
instance.  By default skips any node that already has an embedding row
in ``public.embeddings`` so the script is safely resumable -- pass
``--force`` to re-embed everything.  Per-type batches fan out
concurrently up to ``--concurrency`` so a backfill against a remote
embedding provider isn't bottlenecked on serial round-trips, while the
bound prevents a runaway from exhausting the provider's rate limit.
"""

import argparse
import asyncio
import logging
import typing

import psycopg
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
# match() still works via model_construct fallback; _auto_embed embeds any
# GraphModel that declares Embeddable fields.
_GRAPH_MODEL_TYPES: list[type[models.GraphModel]] = [
    models.Document,
    models.Release,
    models.Comment,
    models.Component,
]

_DEFAULT_CONCURRENCY = 4


async def _already_embedded_ids(
    db: graph.Graph,
    node_label: str,
) -> set[str]:
    """Return the set of node ids that already have embedding rows."""
    async with db.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'SELECT DISTINCT node_id FROM public.embeddings'
                ' WHERE node_label = %(label)s',
                {'label': node_label},
            )
            rows = typing.cast(
                'list[tuple[str]]',
                await cur.fetchall(),
            )
    return {row[0] for row in rows}


async def _embed_type(
    db: graph.Graph,
    node_type: type[models.GraphModel],
    *,
    semaphore: asyncio.Semaphore,
    force: bool,
) -> int:
    nodes = await db.match(node_type)  # type: ignore[arg-type]
    label = node_type.__name__
    skip_ids: set[str] = (
        set() if force else await _already_embedded_ids(db, label)
    )

    async def _embed_one(node: models.GraphModel) -> int:
        if not _embeddable_fields(node):  # type: ignore[arg-type]
            return 0
        if node.id in skip_ids:
            return 0
        async with semaphore:
            try:
                await db._auto_embed(node)  # type: ignore[arg-type]
            except psycopg.Error:
                LOGGER.exception('Failed to embed %s id=%s', label, node.id)
                return 0
        return 1

    results = await asyncio.gather(*(_embed_one(n) for n in nodes))
    return sum(results)


async def run(*, concurrency: int, force: bool) -> None:
    db = graph.Graph()
    await db.open()
    semaphore = asyncio.Semaphore(concurrency)
    try:
        total = 0
        for node_type in [*_NODE_TYPES, *_GRAPH_MODEL_TYPES]:
            label = node_type.__name__
            LOGGER.info(
                'Embedding %s nodes (concurrency=%d, force=%s)...',
                label,
                concurrency,
                force,
            )
            n = await _embed_type(
                db, node_type, semaphore=semaphore, force=force
            )
            LOGGER.info('  %s: %d nodes embedded', label, n)
            total += n
        LOGGER.info('Done. Total nodes embedded: %d', total)
    finally:
        await db.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Backfill embeddings for existing nodes.',
    )
    parser.add_argument(
        '--concurrency',
        type=int,
        default=_DEFAULT_CONCURRENCY,
        help=(
            'Max in-flight ``_auto_embed`` calls across all node types. '
            f'Default: {_DEFAULT_CONCURRENCY}.'
        ),
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help=(
            'Re-embed every node, even those that already have rows in '
            'public.embeddings. Without this flag the script is '
            'resumable.'
        ),
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = _parse_args()
    asyncio.run(run(concurrency=args.concurrency, force=args.force))
