"""Link existing MCP servers to an organization.

An ``MCPServer`` now ``BELONGS_TO`` one organization and has a copy of
its id in ``org_id``. Servers made before that change have neither.
imbi-api runs :func:`backfill` when its graph pool opens; a server that
has ``org_id`` is never read again.

When the install has exactly one organization, each unlinked server
goes to it. Otherwise each one stays unlinked and is logged: no
organization shows it, and an administrator creates it again in the
right organization.
"""

import logging
import typing

from imbi.common import graph

LOGGER = logging.getLogger(__name__)

_CANDIDATES: typing.LiteralString = """
MATCH (s:MCPServer)
WHERE s.org_id IS NULL
RETURN s.slug AS slug
"""
_ORGS: typing.LiteralString = """
MATCH (o:Organization)
WHERE o.id IS NOT NULL
RETURN o.id AS id
"""
_LINK: typing.LiteralString = """
MATCH (s:MCPServer), (o:Organization {{id: {org}}})
WHERE s.org_id IS NULL
MERGE (s)-[:BELONGS_TO]->(o)
SET s.org_id = o.id
RETURN s.id AS id
"""


async def backfill(db: graph.Graph) -> int:
    """Link each MCP server without an organization; return the count
    of servers linked."""
    records = await db.execute(_CANDIDATES, {}, ['slug'])
    if not records:
        return 0
    orgs = [
        str(graph.parse_agtype(r['id']))
        for r in await db.execute(_ORGS, {}, ['id'])
    ]
    if len(orgs) != 1:
        for record in records:
            LOGGER.warning(
                'MCP server %r has no organization and the install has %d '
                'organizations: no organization shows it',
                graph.parse_agtype(record['slug']),
                len(orgs),
            )
        return 0
    linked = await db.execute(_LINK, {'org': orgs[0]}, ['id'])
    LOGGER.info('Linked %d MCP servers to the organization', len(linked))
    return len(linked)
