"""Find the teams of an organization in the graph, by slug or by id."""

import typing
from collections import abc

from imbi.api.auth import permissions
from imbi.common import graph

_BY_SLUG_QUERY: typing.LiteralString = """
MATCH (t:Team)-[:BELONGS_TO]->(:Organization {{id: {org_id}}})
WHERE t.slug IN {slugs}
RETURN t.slug AS slug, t.id AS id
"""

_BY_ID_QUERY: typing.LiteralString = """
MATCH (t:Team)-[:BELONGS_TO]->(:Organization {{id: {org_id}}})
WHERE t.id IN {ids}
RETURN t.id AS id, t.slug AS slug, t.name AS name
"""


async def ids_by_slug(
    db: graph.Graph, org_id: str, slugs: list[str]
) -> dict[str, str]:
    """Return ``{slug: id}`` for the teams of the org with these slugs.
    A slug that is not a team of the org is not in the result."""
    if not slugs:
        return {}
    records = await db.execute(
        _BY_SLUG_QUERY, {'org_id': org_id, 'slugs': slugs}, ['slug', 'id']
    )
    return {
        str(graph.parse_agtype(r['slug'])): str(graph.parse_agtype(r['id']))
        for r in records
    }


async def by_id(
    db: graph.Graph, org_id: str, ids: list[str]
) -> dict[str, dict[str, str]]:
    """Return ``{id: {id, slug, name}}`` for the teams of the org with
    these ids. An id that is not a team of the org is not in the
    result."""
    if not ids:
        return {}
    records = await db.execute(
        _BY_ID_QUERY, {'org_id': org_id, 'ids': ids}, ['id', 'slug', 'name']
    )
    teams = [
        {k: str(graph.parse_agtype(v)) for k, v in r.items()} for r in records
    ]
    return {t['id']: t for t in teams}


_TEAM_MEMBER_QUERY: typing.LiteralString = """
MATCH (u:User {{email: {email}}})-[:MEMBER_OF]->(t:Team {{id: {team}}})
RETURN t.id AS id
"""

_OWNED_AGENTS_QUERY: typing.LiteralString = """
MATCH (:User {{email: {email}}})-[:MEMBER_OF]->(:Team)<-[:OWNED_BY]-(a:Agent)
WHERE a.org_id = {org_id} AND a.id IN {ids}
RETURN DISTINCT a.id AS id
"""


async def is_member(
    db: graph.Graph, auth: permissions.AuthContext, team_id: str
) -> bool:
    """Whether the caller is a user and a member of the team."""
    return auth.user is not None and bool(
        await db.execute(
            _TEAM_MEMBER_QUERY,
            {'email': auth.user.email, 'team': team_id},
            ['id'],
        )
    )


async def owns_agents(
    db: graph.Graph,
    auth: permissions.AuthContext,
    org_id: str,
    agent_ids: abc.Iterable[str],
) -> bool:
    """Whether the caller is a user and a member of the owner team of
    every agent."""
    ids = sorted(set(agent_ids))
    if auth.user is None or not ids:
        return False
    records = await db.execute(
        _OWNED_AGENTS_QUERY,
        {'email': auth.user.email, 'org_id': org_id, 'ids': ids},
        ['id'],
    )
    return len(records) == len(ids)
