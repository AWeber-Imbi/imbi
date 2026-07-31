"""Keep vector-search embeddings in step with raw-Cypher writes.

The graph client embeds a node's ``Embeddable`` fields automatically
when it is written through ``db.create``/``db.merge`` and clears them on
``db.delete``.  Endpoints in this package write their nodes as raw
Cypher through ``db.execute`` instead -- there is no model for the
client to inspect, so nothing is embedded.  Any such write of a node
type with ``Embeddable`` fields (``Document``, ``Comment``, ``Release``,
``Project``) must call :func:`index` after a create/update and
:func:`drop` after a delete, or the node silently falls out of search
until the next reindex.

Embedding chunks and runs a local model, so callers on a request path
should schedule :func:`index` as a background task rather than paying
for it before the response.  It re-reads the node when it runs, so the
caller only has to name the node, not hand over the values it wrote.
"""

import logging

from imbi.common import graph, models

LOGGER = logging.getLogger(__name__)


async def index(
    db: graph.Graph,
    node_type: type[models.GraphModel],
    node_id: str,
    *,
    raise_on_error: bool = False,
) -> bool:
    """(Re)build the embeddings for one node from its persisted state.

    The node is re-read here rather than embedded from the values the
    caller wrote, because nothing orders the background tasks two
    concurrent edits schedule.  Embedding the queued payload lets the
    older task run last and leave the vector index holding stale text;
    re-reading means whichever task runs last embeds the row as it
    actually stands, which is correct either way round.

    A node that was deleted between the write and this task is skipped
    -- ``drop`` has already cleared its rows.  Returns whether the node
    was found and embedded, which the reindex operation reports as
    ``succeeded`` vs ``skipped``.

    Failures are logged and swallowed, which suits a best-effort call
    alongside a graph write; pass ``raise_on_error`` when indexing *is*
    the job (a reindex) and silent failure would look like success.
    """
    nodes = await db.match(node_type, {'id': node_id})
    if not nodes:
        LOGGER.debug(
            'Skipping index of %s id=%s; the node is gone',
            node_type.__name__,
            node_id,
        )
        return False
    await db.embed_node(nodes[0], raise_on_error=raise_on_error)
    return True


async def drop(
    db: graph.Graph,
    node_type: type[models.GraphModel],
    node_id: str,
) -> None:
    """Delete every embedding row for a node that was just deleted.

    Best-effort like :func:`index`: the node itself is already gone by
    the time this runs, so a failure here must not turn a successful
    delete into a 500.  The orphaned rows are cleaned up by the next
    ``search-reindex``.
    """
    try:
        await db.delete_node_embeddings(node_type.__name__, node_id)
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Failed to drop embeddings for %s id=%s; a search-reindex '
            'will clean this up',
            node_type.__name__,
            node_id,
            exc_info=True,
        )
