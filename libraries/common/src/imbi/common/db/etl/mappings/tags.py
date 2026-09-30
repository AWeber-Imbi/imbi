"""``tags``: one row for each ``Tag`` vertex with an organization.

``organization_id`` comes from the ``BELONGS_TO`` edge to an
``Organization``. A tag with no such edge is skipped and counted
(Appendix E, E41): ``tags.organization_id`` is NOT NULL, and plan O2
does not assign tags to the one organization. A tag with edges to two
organizations stops the ETL, because no rule chooses one. ``Tag.icon``
is not loaded; a value that is not NULL is logged (E35). A tag with no
``created_at`` gets the E40 fallback: its ``updated_at``, else the
``created_at`` of its organization.
"""

import collections.abc

from psycopg import sql

from imbi.common.db.etl import graph, mapping
from imbi.common.db.etl.mappings import _organizations

NO_ORGANIZATION = 'E41'


class _Tags:
    table = 'tags'
    columns = (
        'id',
        'organization_id',
        'name',
        'slug',
        'description',
        'created_at',
        'updated_at',
    )
    source_labels = ('Tag', 'Organization', 'Team', 'Project', 'User')
    source_edges = ('BELONGS_TO', 'OWNED_BY', 'MEMBER_OF')

    async def rows(
        self, context: mapping.Context
    ) -> collections.abc.AsyncIterator[mapping.Event]:
        owners = await graph.edge_targets(
            context.source,
            context.graph,
            'BELONGS_TO',
            start_label='Tag',
            end_label='Organization',
        )
        organization_created = await _organizations.known_created_at(context)
        async for vertex in graph.read_label(
            context.source, context.graph, 'Tag'
        ):
            tag, tag_id = vertex.properties, vertex.id
            organizations = owners.get(tag_id, set())
            if not organizations:
                yield mapping.Skip(NO_ORGANIZATION, tag_id)
                continue
            if len(organizations) > 1:
                raise mapping.EtlError(
                    f'Tag {tag_id!r} belongs to {len(organizations)}'
                    ' organizations'
                )
            organization_id = next(iter(organizations))
            if tag.get('icon') is not None:
                yield mapping.Change('E35', tag_id, 'icon not loaded')
            yield {
                'id': tag_id,
                'organization_id': organization_id,
                'name': tag.get('name'),
                'slug': tag.get('slug'),
                'description': tag.get('description'),
                'created_at': graph.created_at(
                    tag,
                    context,
                    organization_created.get(organization_id),
                    what=f'Tag {tag_id!r}',
                ),
                'updated_at': graph.timestamp(tag.get('updated_at')),
            }

    async def expected(self, context: mapping.Context) -> mapping.Expected:
        if not await graph.label_exists(context.source, context.graph, 'Tag'):
            return mapping.Expected(count=0)
        owned: sql.Composable = sql.SQL('false')
        if await graph.label_exists(
            context.source, context.graph, 'BELONGS_TO'
        ) and await graph.label_exists(
            context.source, context.graph, 'Organization'
        ):
            eq = await graph.id_equals(
                context.source, context.graph, 'BELONGS_TO'
            )
            owned = sql.SQL(
                'EXISTS (SELECT 1 FROM {edge} AS e'
                ' JOIN {org} AS o ON o.id {eq} e.end_id'
                ' WHERE e.start_id {eq} t.id)'
            ).format(
                edge=sql.Identifier(context.graph, 'BELONGS_TO'),
                org=sql.Identifier(context.graph, 'Organization'),
                eq=eq,
            )
        cursor = await context.source.execute(
            sql.SQL(
                'SELECT t.id::text, t.properties::text::jsonb, {owned}'
                ' FROM {tag} AS t'
            ).format(
                owned=owned,
                tag=sql.Identifier(context.graph, 'Tag'),
            )
        )
        count = 0
        skipped: set[str] = set()
        for graph_id, properties, is_owned in await cursor.fetchall():
            if is_owned:
                count += 1
            else:
                skipped.add(graph.vertex_id('Tag', str(graph_id), properties))
        return mapping.Expected(
            count=count, skipped={NO_ORGANIZATION: frozenset(skipped)}
        )


MAPPING: mapping.Mapping = _Tags()
