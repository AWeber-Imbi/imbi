"""``tenants``: one new row (Appendix E, E2).

The graph has no tenant. The ETL creates one, and every organization
belongs to it (``organizations.py``). Its id is derived from its slug.
Its ``created_at`` is the oldest organization ``created_at``, so two runs
give the same row. With no organization, there is no tenant.
"""

import collections.abc
import datetime

from psycopg import sql

from imbi.common.db.etl import graph, ids, mapping


def tenant_id(context: mapping.Context) -> str:
    """Return the id of the one tenant."""
    return ids.derive_id('tenants', context.tenant_slug)


class _Tenants:
    table = 'tenants'
    columns = ('id', 'name', 'slug', 'created_at', 'updated_at')
    source_labels = ('Organization',)
    source_edges = ()

    async def rows(
        self, context: mapping.Context
    ) -> collections.abc.AsyncIterator[mapping.Event]:
        oldest: datetime.datetime | None = None
        async for org in graph.read_label(
            context.source, context.graph, 'Organization'
        ):
            created_at = graph.timestamp(org.get('created_at'))
            if created_at is None:
                raise mapping.EtlError(
                    f'Organization {org.get("id")!r} has no created_at'
                )
            if oldest is None or created_at < oldest:
                oldest = created_at
        if oldest is None:
            return
        yield {
            'id': tenant_id(context),
            'name': context.tenant_name,
            'slug': context.tenant_slug,
            'created_at': oldest,
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
