"""Find the tags of an organization in the graph, by slug or by id.

The slug lookups take the organization slug, because most callers
have only the slug.
"""

import typing

import fastapi

from imbi.common import graph

_BY_SLUG_QUERY: typing.LiteralString = """
MATCH (t:Tag)-[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
WHERE t.slug IN {slugs}
RETURN t.slug AS slug, t.id AS id
"""

_BY_ID_QUERY: typing.LiteralString = """
MATCH (t:Tag)-[:BELONGS_TO]->(:Organization {{id: {org_id}}})
WHERE t.id IN {ids}
RETURN t.id AS id, t.name AS name, t.slug AS slug, t.color AS color
"""


async def ids_by_slug(
    db: graph.Graph, org_slug: str, slugs: list[str]
) -> dict[str, str]:
    """Return ``{slug: id}`` for the tags of the org with these slugs.
    A slug that is not a tag of the org is not in the result."""
    if not slugs:
        return {}
    records = await db.execute(
        _BY_SLUG_QUERY,
        {'org_slug': org_slug, 'slugs': sorted(set(slugs))},
        ['slug', 'id'],
    )
    return {
        str(graph.parse_agtype(r['slug'])): str(graph.parse_agtype(r['id']))
        for r in records
    }


async def require_ids(
    db: graph.Graph, org_slug: str, slugs: list[str]
) -> dict[str, str]:
    """Return ``{slug: id}`` for these tag slugs.

    Raises:
        422: A slug is not a tag of the org.

    """
    found = await ids_by_slug(db, org_slug, slugs)
    missing = sorted(set(slugs) - found.keys())
    if missing:
        raise fastapi.HTTPException(
            status_code=422, detail=f'Tag slug(s) not found: {missing!r}'
        )
    return found


async def by_id(
    db: graph.Graph, org_id: str, ids: list[str]
) -> dict[str, dict[str, typing.Any]]:
    """Return ``{id: {id, name, slug, color}}`` for the tags of the org
    with these ids. An id that is not a tag of the org is not in the
    result."""
    if not ids:
        return {}
    records = await db.execute(
        _BY_ID_QUERY,
        {'org_id': org_id, 'ids': sorted(set(ids))},
        ['id', 'name', 'slug', 'color'],
    )
    tags = [{k: graph.parse_agtype(v) for k, v in r.items()} for r in records]
    return {t['id']: t for t in tags}
