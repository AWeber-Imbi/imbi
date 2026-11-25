"""Find the tags of an organization in the graph, and tag nodes.

The slug lookups take the organization slug, because most callers
have only the slug.

The tag writes take a ``MATCH`` clause that binds the tagged node to
``n``, so that one pair of queries serves every label.
"""

import typing

import fastapi
import pydantic

from imbi.common import graph
from imbi.common.graph import cypher as graph_cypher


class TagRef(pydantic.BaseModel):
    """An org tag as a response shows it."""

    name: str
    slug: str
    color: str | None = None


def parse_refs(raw: typing.Any) -> list[dict[str, typing.Any]]:
    """Return the :class:`TagRef` fields of the tag maps of a graph
    row (``tag{.name, .slug, .color}``), in order. An entry with no slug
    is left out."""
    refs: list[dict[str, typing.Any]] = []
    entries: list[typing.Any] = raw or []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tag = typing.cast('dict[str, typing.Any]', entry)
        if tag.get('slug'):
            refs.append(
                {
                    'name': str(tag.get('name', '')),
                    'slug': str(tag['slug']),
                    'color': tag.get('color'),
                }
            )
    return refs


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
    org_slug: str,
    slugs: list[str],
) -> graph_cypher.Statement:
    """Return the statement that tags the node with the tags of the org
    that have these slugs. ``MERGE`` does not make a second edge for a
    tag that the node already has."""
    return graph_cypher.Statement(
        node
        + """
        MATCH (t:Tag)-[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
        WHERE t.slug IN {tag_slugs}
        MERGE (n)-[:TAGGED_WITH]->(t)
        RETURN count(t) AS changed
        """,
        {**params, 'org_slug': org_slug, 'tag_slugs': slugs},
    )


def replace_statements(
    node: typing.LiteralString,
    params: dict[str, typing.Any],
    org_slug: str,
    slugs: list[str],
) -> list[graph_cypher.Statement]:
    """Return the statements that replace the tags of the node."""
    statements = [detach_statement(node, params)]
    if slugs:
        statements.append(attach_statement(node, params, org_slug, slugs))
    return statements


async def execute(
    db: graph.Graph, statements: list[graph_cypher.Statement]
) -> None:
    """Run tag statements one after the other, with no transaction."""
    for statement in statements:
        await db.execute(statement.cypher, statement.params, ['changed'])
