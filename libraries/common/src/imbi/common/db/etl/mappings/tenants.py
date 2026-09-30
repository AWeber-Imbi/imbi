"""``tenants``: one new row (Appendix E, E2).

The graph has no tenant. The ETL creates one, and every organization
belongs to it (``organizations.py``). Its id is derived from its slug.
Its ``created_at`` is the oldest organization ``created_at`` (E40 for an
organization with none), so two runs give the same row. With no
organization, there is no tenant.
"""

import collections.abc

from psycopg import sql

from imbi.common.db.etl import graph, mapping
from imbi.common.db.etl.mappings import _organizations


class _Tenants:
    table = 'tenants'
    columns = ('id', 'name', 'slug', 'created_at', 'updated_at')
    source_labels = ('Organization', 'Team', 'Project', 'User')
    source_edges = ('BELONGS_TO', 'OWNED_BY', 'MEMBER_OF')

    async def rows(
        self, context: mapping.Context
    ) -> collections.abc.AsyncIterator[mapping.Event]:
        created = await _organizations.created_at(context)
        if not created:
            return
        yield {
            'id': _organizations.tenant_id(context),
            'name': context.tenant_name,
            'slug': context.tenant_slug,
            'created_at': min(created.values()),
            'updated_at': None,
        }

    async def expected(self, context: mapping.Context) -> mapping.Expected:
        if not await graph.label_exists(
            context.source, context.graph, 'Organization'
        ):
            return mapping.Expected(count=0)
        cursor = await context.source.execute(
            sql.SQL('SELECT EXISTS (SELECT 1 FROM {})').format(
                sql.Identifier(context.graph, 'Organization')
            )
        )
        row = await cursor.fetchone()
        return mapping.Expected(count=1 if row and row[0] else 0)


MAPPING: mapping.Mapping = _Tenants()
