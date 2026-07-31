"""The read-analytics SQL, executed against a live ClickHouse.

Every other test in this suite mocks ClickHouse, which cannot catch a query
the server refuses to analyze. ``_SESSION_AGGREGATE_SQL`` shipped with an
inner alias shadowing the ``argMax`` ordering column, so the finalizer raised
``ILLEGAL_AGGREGATION`` on every call and ``document_read_sessions`` stayed
empty -- with the failure swallowed by the finalizer's own except/log. These
run each statement with a session id that matches nothing: both errors are
raised at analysis time, so an invalid query still fails while a valid one
writes nothing.
"""

import unittest

from imbi.api.endpoints import _document_reads
from imbi.common import clickhouse


class ReadAnalyticsSqlTestCase(unittest.IsolatedAsyncioTestCase):
    """Executes the finalizer and reaper SQL for real."""

    async def asyncSetUp(self) -> None:
        await clickhouse.initialize()
        await clickhouse.setup_schema()

    async def asyncTearDown(self) -> None:
        # The client singleton binds to the loop that created it, and
        # IsolatedAsyncioTestCase gives each test method its own. Left open,
        # the next test to touch it fails with "Event loop is closed".
        await clickhouse.aclose()

    async def test_analytics_sql_is_valid(self) -> None:
        """The finalizer and reaper queries both analyze and run.

        One test rather than two: see ``asyncTearDown``.
        """
        aggregates = await clickhouse.query(
            _document_reads._SESSION_AGGREGATE_SQL,
            {'session_ids': ['no-such-session']},
        )
        self.assertEqual([], aggregates)
        stale = await clickhouse.query(
            _document_reads._STALE_SESSION_SQL,
            {
                'idle_seconds': _document_reads.SESSION_IDLE_TIMEOUT_SECONDS,
                'lookback_hours': _document_reads.SWEEP_LOOKBACK_HOURS,
                'batch': 1,
            },
        )
        self.assertIsInstance(stale, list)
