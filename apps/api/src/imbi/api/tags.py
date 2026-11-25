"""Find the tags of an organization in the graph, and tag nodes.

The slug lookups take the organization slug, because most callers
have only the slug.

The tag writes take a ``MATCH`` clause that binds the tagged node to
``n`` and its organization to ``o``, so that one pair of queries serves
every label.
"""

import typing

import fastapi

from imbi.common import graph
from imbi.common.graph import cypher as graph_cypher

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


def detach_statement(
    node: typing.LiteralString, params: dict[str, typing.Any]
) -> graph_cypher.Statement:
    """Return the statement that removes every tag of the node."""
    return graph_cypher.Statement(
        node
        + """
        MATCH (n)-[r:TAGGED_WITH]->(:Tag)
        DELETE r
        RETURN count(r) AS changed
        """,
        params,
    )


def attach_statement(
    node: typing.LiteralString,
    params: dict[str, typing.Any],
    slugs: list[str],
) -> graph_cypher.Statement:
    """Return the statement that tags the node with the org tags that
    have these slugs. ``MERGE`` does not make a second edge for a tag
    that the node already has."""
    return graph_cypher.Statement(
        node
        + """
        MATCH (t:Tag)-[:BELONGS_TO]->(o)
        WHERE t.slug IN {tag_slugs}
        MERGE (n)-[:TAGGED_WITH]->(t)
        RETURN count(t) AS changed
        """,
        {**params, 'tag_slugs': slugs},
    )


async def execute(db: graph.Graph, statement: graph_cypher.Statement) -> None:
    """Run a statement of :func:`detach_statement` or
    :func:`attach_statement` on its own."""
    await db.execute(statement.cypher, statement.params, ['changed'])
