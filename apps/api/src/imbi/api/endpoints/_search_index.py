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
for it before the response.
"""

import logging
import typing

from imbi.common import graph, models

LOGGER = logging.getLogger(__name__)


async def index(
    db: graph.Graph,
    node_type: type[models.GraphModel],
    node_id: str,
    *,
    raise_on_error: bool = False,
    **fields: typing.Any,
) -> None:
    """(Re)build the embeddings for one node from *fields*.

    Pass the node's embeddable fields by name (``title=``/``content=``
    for a document, ``body=`` for a comment, ...).  ``model_construct``
    skips validation because only those fields are read.

    Failures are logged and swallowed, which suits a best-effort call
    alongside a graph write; pass ``raise_on_error`` when indexing *is*
    the job (a reindex) and silent failure would look like success.
    """
    await db.embed_node(
        node_type.model_construct(id=node_id, **fields),
        raise_on_error=raise_on_error,
    )


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
