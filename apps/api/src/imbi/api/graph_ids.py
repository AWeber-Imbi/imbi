"""Give an ``id`` to organizations and users that have none.

Nodes made before ``GraphModel.id`` existed have no ``id`` property.
The code keys organizations by id (agent tasks, workflows, secrets,
harness pools, agent tokens) and users by id (identity connections,
agent task actors, analysis runs). A model parsed from such a node gets
a new random id on each read, so nothing that it keys matches later.

imbi-api runs :func:`backfill` when its graph pool opens, so it runs
with each deploy. It sets an id only where there is none, so it never
changes an existing id, and a second run changes nothing.

Roles, permissions, plugin registrations, webhook rules and analysis
results are matched by slug, name or edge, never by id, so they are
left as they are.
"""

import logging
import typing

import nanoid

from imbi.common import graph

LOGGER = logging.getLogger(__name__)

#: Each label, with the unique property that finds one of its nodes.
_LABELS: dict[typing.LiteralString, typing.LiteralString] = {
    'Organization': 'slug',
    'User': 'email',
}


async def backfill(db: graph.Graph) -> dict[str, int]:
    """Set an id on each organization and user without one; return the
    count for each label."""
    counts: dict[str, int] = {}
    for label, key in _LABELS.items():
        missing: typing.LiteralString = (
            f'MATCH (n:{label}) WHERE n.id IS NULL RETURN n.{key} AS key'
        )
        records = await db.execute(missing, {}, ['key'])
        counts[label] = 0
        for record in records:
            value = graph.parse_agtype(record['key'])
            if value is None:
                LOGGER.warning('A %s has no id and no %s', label, key)
                continue
            # The WHERE keeps an id that another instance set first.
            update: typing.LiteralString = (
                f'MATCH (n:{label} {{{{{key}: {{key}}}}}})'
                ' WHERE n.id IS NULL SET n.id = {id} RETURN n.id AS id'
            )
            if await db.execute(
                update, {'key': value, 'id': nanoid.generate()}, ['id']
            ):
                counts[label] += 1
        if counts[label]:
            LOGGER.info('Gave an id to %d %s nodes', counts[label], label)
    return counts
