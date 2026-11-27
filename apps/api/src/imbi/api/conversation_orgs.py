"""Put existing assistant conversations in an organization.

A ``Conversation`` now has the ``org_id`` of the organization it is in,
and the assistant shows only the conversations of the selected
organization. Conversations made before that change have no ``org_id``.
imbi-api runs :func:`backfill` when its graph pool opens; a
conversation that has ``org_id`` is never read again.

Each user's conversations go to the user's organization. A user in more
than one organization gets the first by slug: memberships have no date,
so no organization is the oldest. A user in no organization keeps them
without one, and they are logged: no organization shows them.
"""

import logging
import typing

from imbi.common import graph

LOGGER = logging.getLogger(__name__)

_USERS: typing.LiteralString = """
MATCH (c:Conversation)
WHERE c.org_id IS NULL
RETURN DISTINCT c.user_email AS email
"""
_FIRST_ORG: typing.LiteralString = """
MATCH (:User {{email: {email}}})-[:MEMBER_OF]->(o:Organization)
WHERE o.id IS NOT NULL
RETURN o.id AS id
ORDER BY o.slug
LIMIT 1
"""
_SET: typing.LiteralString = """
MATCH (c:Conversation {{user_email: {email}}})
WHERE c.org_id IS NULL
SET c.org_id = {org}
RETURN c.id AS id
"""


async def backfill(db: graph.Graph) -> int:
    """Put each conversation without an organization in one; return
    the count of conversations changed."""
    changed = 0
    for record in await db.execute(_USERS, {}, ['email']):
        email = str(graph.parse_agtype(record['email']))
        orgs = await db.execute(_FIRST_ORG, {'email': email}, ['id'])
        if not orgs:
            LOGGER.warning(
                'Conversations of %s have no organization: the user is in '
                'none, so no organization shows them',
                email,
            )
            continue
        org = str(graph.parse_agtype(orgs[0]['id']))
        changed += len(
            await db.execute(_SET, {'email': email, 'org': org}, ['id'])
        )
    if changed:
        LOGGER.info('Put %d conversations in an organization', changed)
    return changed
