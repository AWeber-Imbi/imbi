"""``tags``: one row for each ``Tag`` vertex with an organization.

``organization_id`` comes from the ``BELONGS_TO`` edge to an
``Organization``. A tag with no such edge is skipped
(``no-organization``): ``tags.organization_id`` is NOT NULL, and plan O2
does not assign tags to the one organization. A tag with edges to two
organizations stops the ETL, because no rule chooses one. ``Tag.icon``
is not loaded; a value that is not NULL is logged (Appendix E, E35).
"""

import collections.abc

from psycopg import sql

from imbi.common.db.etl import graph, mapping

NO_ORGANIZATION = 'no-organization'


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
    source_labels = ('Tag', 'Organization')
    source_edges = ('BELONGS_TO',)

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
        async for tag in graph.read_label(
            context.source, context.graph, 'Tag'
        ):
            tag_id = str(tag.get('id'))
            organizations = owners.get(tag_id, set())
            if not organizations:
                yield mapping.Skip(NO_ORGANIZATION, tag_id)
                continue
            if len(organizations) > 1:
                raise mapping.EtlError(
                    f'Tag {tag_id!r} belongs to {len(organizations)}'
                    ' organizations'
                )
            if tag.get('icon') is not None:
                yield mapping.Change('E35', tag_id, 'icon not loaded')
            yield {
                'id': tag_id,
                'organization_id': next(iter(organizations)),
                'name': tag.get('name'),
                'slug': tag.get('slug'),
                'description': tag.get('description'),
                'created_at': graph.timestamp(tag.get('created_at')),
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
                'SELECT properties::text::jsonb ->> {key}, {owned}'
                ' FROM {tag} AS t'
            ).format(
                key=sql.Literal('id'),
                owned=owned,
                tag=sql.Identifier(context.graph, 'Tag'),
            )
        )
        count = 0
        skipped: set[str] = set()
        for tag_id, is_owned in await cursor.fetchall():
            if is_owned:
                count += 1
            else:
                skipped.add(str(tag_id))
        return mapping.Expected(
            count=count, skipped={NO_ORGANIZATION: frozenset(skipped)}
        )


MAPPING: mapping.Mapping = _Tags()
