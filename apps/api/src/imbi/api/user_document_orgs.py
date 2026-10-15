"""Link existing user documents to an organization (issue #414).

A document attached to a user is now visible only through the
organization that it ``BELONGS_TO``: a user can be a member of more
than one organization. Documents made before that change have no such
edge. imbi-api runs :func:`backfill` when its graph pool opens, so the
backfill runs with each deploy; a document that has the edge is never
read again, so later runs only see the documents that stay unlinked.

Rules, in order:

1. ``tags``: the organizations of the document's tags (a tag belongs
   to one organization, and a document gets only the tags of the
   organization that it is made through) give one organization that
   the user is a member of.
2. ``single_org``: the user is a member of one organization only.
3. ``unlinked``: otherwise the document stays without an organization,
   so no organization URL shows it. Each one is logged with its id.
"""

import collections
import logging
import typing

from imbi.common import graph

LOGGER = logging.getLogger(__name__)

_CANDIDATES: typing.LiteralString = """
MATCH (d:Document)-[:ATTACHED_TO]->(u:User)
OPTIONAL MATCH (d)-[b:BELONGS_TO]->(:Organization)
WITH d, u, b
WHERE b IS NULL
RETURN DISTINCT d.id AS id, u.email AS email
"""
_TAG_ORGS: typing.LiteralString = """
MATCH (:Document {{id: {id}}})-[:TAGGED_WITH]->(:Tag)
      -[:BELONGS_TO]->(o:Organization)
RETURN DISTINCT o.id AS id
"""
_USER_ORGS: typing.LiteralString = """
MATCH (:User {{email: {email}}})-[:MEMBER_OF]->(o:Organization)
RETURN DISTINCT o.id AS id
"""
_LINK: typing.LiteralString = """
MATCH (d:Document {{id: {id}}}), (o:Organization {{id: {org}}})
MERGE (d)-[:BELONGS_TO]->(o)
RETURN d.id AS id
"""


async def _ids(
    db: graph.Graph, query: typing.LiteralString, args: dict[str, str]
) -> set[str]:
    records = await db.execute(query, args, ['id'])
    ids = (graph.parse_agtype(r['id']) for r in records)
    # An organization without an id cannot be linked to.
    return {str(value) for value in ids if value}


def choose(tag_orgs: set[str], user_orgs: set[str]) -> tuple[str, str | None]:
    """The rule and the organization for one document."""
    from_tags = tag_orgs & user_orgs
    if len(from_tags) == 1:
        return 'tags', next(iter(from_tags))
    if len(user_orgs) == 1:
        return 'single_org', next(iter(user_orgs))
    return 'unlinked', None


async def backfill(db: graph.Graph) -> dict[str, int]:
    """Link each user document without an organization; return the
    count of each rule."""
    counts: collections.Counter[str] = collections.Counter()
    records = await db.execute(_CANDIDATES, {}, ['id', 'email'])
    for record in records:
        document = str(graph.parse_agtype(record['id']))
        email = str(graph.parse_agtype(record['email']))
        rule, org = choose(
            await _ids(db, _TAG_ORGS, {'id': document}),
            await _ids(db, _USER_ORGS, {'email': email}),
        )
        counts[rule] += 1
        if org is None:
            LOGGER.warning(
                'User document %s has no organization: no organization '
                'shows it',
                document,
            )
            continue
        await db.execute(_LINK, {'id': document, 'org': org}, ['id'])
    if records:
        LOGGER.info(
            'User document organizations: %d by tags, %d by single '
            'organization, %d unlinked',
            counts['tags'],
            counts['single_org'],
            counts['unlinked'],
        )
    return dict(counts)
