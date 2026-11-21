"""Find the teams of an organization in the graph, by slug or by id."""

import typing

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
