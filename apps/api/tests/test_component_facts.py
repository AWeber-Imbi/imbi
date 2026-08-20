"""The SBoM component-fact reads, as SQL rather than as behaviour.

Every other test of these reads mocks ``clickhouse.query``, so it
asserts what the endpoints do with rows and never what they asked for.
Two classes of defect slip through that entirely.

The first is the batch join. A release accumulates a batch per ingest
and per backfill, and only one of them is current; a read of
``release_components`` without the ``argMax`` join returns every
snapshot the release has ever had, superseded ones included. The
inverse tuple order is worse and quieter -- with ``recorded_at``
leading, a backfill written after an ingest displaces it, which is the
defect this migration already shipped once and caught in review on the
writer. Both are invisible against a mock, because a mocked query
returns the same rows whatever the SQL says.

The second is a query the server refuses to analyze. The reads are
composed from fragments rather than written out, so a malformed
``WHERE`` reaches production intact -- the same shape as the analytics
SQL bugs ``test_document_reads_sql`` exists to stop.
"""

import unittest
from unittest import mock

from imbi.api import component_facts
from imbi.common import clickhouse
from imbi.common.clickhouse import client

#: Every read in the module, with arguments that reach ClickHouse.
#: Each entry is exercised twice: once against a mock to inspect the
#: SQL, once against a live server to prove it analyzes.
READS: tuple[tuple[str, tuple[object, ...]], ...] = (
    ('component_ids_in_org', (['proj-1'],)),
    ('component_ids_in_org', (['proj-1'], ['cmp-1'])),
    ('component_in_org', (['proj-1'], 'cmp-1')),
    ('component_release_in_org', (['proj-1'], 'cmp-1', 'crel-1')),
    ('search_counts', (['proj-1'], ['cmp-1'])),
    ('ecosystem_totals', (['proj-1'],)),
    ('component_usage', (['rel-1'], 'cmp-1')),
    ('governed_usage', (['rel-1'], ['crel-1'])),
    ('release_components', ('rel-1',)),
)


class BatchJoinTestCase(unittest.IsolatedAsyncioTestCase):
    """No read may reach the fact table without resolving a batch."""

    async def asyncSetUp(self) -> None:
        self.query = mock.AsyncMock(return_value=[])
        patcher = mock.patch('imbi.common.clickhouse.query', self.query)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _statements(self) -> list[str]:
        for name, args in READS:
            await getattr(component_facts, name)(*args)
        self.assertEqual(len(READS), self.query.await_count)
        return [call.args[0] for call in self.query.await_args_list]

    async def test_every_read_joins_the_winning_batch(self) -> None:
        """``release_components`` is never read on its own."""
        for statement in await self._statements():
            with self.subTest(statement=statement):
                self.assertIn('imbi.release_components', statement)
                self.assertIn('imbi.release_component_batches', statement)
                self.assertIn(
                    'ON c.release_id = b.release_id'
                    ' AND c.batch_id = b.batch_id',
                    statement,
                )

    async def test_source_leads_the_argmax_key(self) -> None:
        """A backfill must not displace an ingest in any landing order.

        Tuple comparison orders on the first element, so this is the
        whole of that guarantee: with ``recorded_at`` first, whichever
        batch was written last wins and a backfill running beside live
        traffic silently overwrites real SBoMs.
        """
        for statement in await self._statements():
            with self.subTest(statement=statement):
                self.assertIn(
                    "argMax(batch_id, (source = 'ingest', recorded_at))",
                    statement,
                )
                self.assertNotIn(
                    "argMax(batch_id, (recorded_at, source = 'ingest'))",
                    statement,
                )


class ComponentFactsSqlTestCase(unittest.IsolatedAsyncioTestCase):
    """Executes every read for real, against filters matching nothing."""

    async def asyncSetUp(self) -> None:
        # ``Clickhouse`` is a process-wide singleton whose client binds
        # to the loop that opened it, while IsolatedAsyncioTestCase
        # gives each test its own loop. Take a private instance and
        # hand the old one back, as test_document_reads_sql does.
        self._previous = client.Clickhouse._instance
        client.Clickhouse._instance = None
        self.addAsyncCleanup(self._restore_singleton)
        await clickhouse.initialize()
        await clickhouse.setup_schema()

    async def _restore_singleton(self) -> None:
        await clickhouse.aclose()
        client.Clickhouse._instance = self._previous

    async def test_every_read_analyzes_and_runs(self) -> None:
        """Composition errors fail here rather than in production."""
        for name, args in READS:
            with self.subTest(read=name, args=args):
                self.assertFalse(await getattr(component_facts, name)(*args))
