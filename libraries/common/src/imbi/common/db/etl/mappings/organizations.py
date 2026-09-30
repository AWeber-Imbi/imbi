"""``organizations``: one row for each ``Organization`` vertex.

Every organization belongs to the one tenant (Appendix E, E2). A vertex
with no ``id`` (the seeded one) gets an id derived from its graph id
(E36), and one with no ``created_at`` gets the E40 fallback. The graph
keeps blueprint values as extra vertex properties; each property that
is not a column goes into ``attributes``, with the ``'true'`` and
``'false'`` strings of a boolean blueprint field as booleans (D32).
``tag_formats`` and ``previous_slugs`` can be JSON text (E30), so they
are decoded. A missing ``document_analytics_identities`` gets the model
default.
"""

import collections.abc

from psycopg import sql

from imbi.common.db.etl import graph, mapping
from imbi.common.db.etl.mappings import _organizations

#: The vertex properties that have their own column.
PROPERTIES = frozenset(
    {
        'id',
        'name',
        'slug',
        'description',
        'icon',
        'previous_slugs',
        'tag_formats',
        'document_analytics_identities',
        'created_at',
        'updated_at',
    }
)


class _Organizations:
    table = 'organizations'
    columns = (
        'id',
        'tenant_id',
        'name',
        'slug',
        'description',
        'icon',
        'previous_slugs',
        'tag_formats',
        'document_analytics_identities',
        'attributes',
        'created_at',
        'updated_at',
    )
    source_labels = ('Organization', 'Blueprint', 'Team', 'Project', 'User')
    source_edges = ('BELONGS_TO', 'OWNED_BY', 'MEMBER_OF')

    async def rows(
        self, context: mapping.Context
    ) -> collections.abc.AsyncIterator[mapping.Event]:
        tenant_id = _organizations.tenant_id(context)
        created = await _organizations.created_at(context)
        booleans = await graph.boolean_attributes(
            context.source, context.graph, 'Organization'
        )
        async for vertex in graph.read_label(
            context.source, context.graph, 'Organization'
        ):
            org = vertex.properties
            yield {
                'id': vertex.id,
                'tenant_id': tenant_id,
                'name': org.get('name'),
                'slug': org.get('slug'),
                'description': org.get('description'),
                'icon': org.get('icon'),
                'previous_slugs': [
                    str(slug)
                    for slug in graph.json_array(org.get('previous_slugs'))
                ],
                'tag_formats': graph.json_array(org.get('tag_formats')),
                'document_analytics_identities': (
                    org.get('document_analytics_identities') or 'authors_only'
                ),
                'attributes': graph.attributes(org, PROPERTIES, booleans),
                'created_at': created[vertex.id],
                'updated_at': graph.timestamp(org.get('updated_at')),
            }

    async def expected(self, context: mapping.Context) -> mapping.Expected:
        if not await graph.label_exists(
            context.source, context.graph, 'Organization'
        ):
            return mapping.Expected(count=0)
        cursor = await context.source.execute(
            sql.SQL('SELECT count(*) FROM {}').format(
                sql.Identifier(context.graph, 'Organization')
            )
        )
        row = await cursor.fetchone()
        return mapping.Expected(count=int(row[0]) if row else 0)


MAPPING: mapping.Mapping = _Organizations()
