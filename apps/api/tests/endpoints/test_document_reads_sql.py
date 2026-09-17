"""The read-analytics SQL, executed against a live ClickHouse.

Every other test in this suite mocks ClickHouse, which cannot catch a query
the server refuses to analyze. ``_SESSION_AGGREGATE_SQL`` shipped with an
inner alias shadowing the ``argMax`` ordering column, so the finalizer raised
``ILLEGAL_AGGREGATION`` on every call and ``document_read_sessions`` stayed
empty -- with the failure swallowed by the finalizer's own except/log. These
run each statement with a session id that matches nothing: both errors are
raised at analysis time, so an invalid query still fails while a valid one
writes nothing.

The same class of bug then shipped a second time, in
``document_analytics._DEDUPED_SESSIONS``: every ``argMax(x, finalized_at) AS
x`` shadowed the source column ``x``, and the filters constraining four of
them sat in the same scope, so the server read them as aggregates in WHERE.
Every analytics endpoint answered 503 and the readership UI, which hides
itself when the request fails, showed nothing at all. So the analytics
statements are executed here too, against filters that match no document.
"""

import datetime
import unittest
import uuid

from imbi.api.endpoints import _document_reads, document_analytics
from imbi.common import clickhouse
from imbi.common.clickhouse import client


class ReadAnalyticsSqlTestCase(unittest.IsolatedAsyncioTestCase):
    """Executes the finalizer and reaper SQL for real."""

    async def asyncSetUp(self) -> None:
        # ``Clickhouse`` is a process-wide singleton and its client binds to
        # the loop that opened it, while IsolatedAsyncioTestCase gives each
        # test method its own loop. An earlier test in the same session may
        # have left the singleton connected, in which case ``initialize()``
        # is a no-op and the first request here dies on that dead loop. Take
        # a private instance instead, and hand the old one back afterwards.
        self._previous = client.Clickhouse._instance
        client.Clickhouse._instance = None
        self.addAsyncCleanup(self._restore_singleton)
        await clickhouse.initialize()
        await clickhouse.setup_schema()

    async def _restore_singleton(self) -> None:
        await clickhouse.aclose()
        client.Clickhouse._instance = self._previous

    async def test_analytics_sql_is_valid(self) -> None:
        """The finalizer and reaper queries both analyze and run."""
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

    async def test_document_analytics_sql_is_valid(self) -> None:
        """Every per-document analytics statement analyzes and runs.

        Built through the same helpers the endpoints use, so a filter that
        collides with a dedup alias fails here the way it fails in
        production rather than passing against a mock.
        """
        params = {
            'org_slug': 'no-such-org',
            'document_id': 'no-such-document',
            'surface': 'web',
            'author': 'nobody@example.com',
        }
        source = document_analytics._session_source(
            document_analytics._document_filters('web', include_self=False)
        )
        # ``surface='all'`` drops the surface filter, the one shape the
        # default arguments never exercise.
        all_surfaces = document_analytics._session_source(
            document_analytics._document_filters('all', include_self=False)
        )
        trend_source = document_analytics._session_source(
            document_analytics._document_filters('web', include_self=False)
            + ' AND started_at > now() - INTERVAL {trend_days:UInt32} DAY'
        )

        summary = await clickhouse.query(
            document_analytics._SUMMARY_SQL.format(source=source), params
        )
        # An unfiltered aggregate returns its one all-zero row.
        self.assertEqual(1, len(summary))
        self.assertEqual(
            [],
            await clickhouse.query(
                document_analytics._SURFACE_SQL.format(source=all_surfaces),
                params,
            ),
        )
        self.assertEqual(
            [],
            await clickhouse.query(
                document_analytics._TREND_SQL.format(source=trend_source),
                {**params, 'trend_days': 90},
            ),
        )
        self.assertEqual(
            [],
            await clickhouse.query(
                document_analytics._READERS_SQL.format(
                    source=source, having=''
                ),
                {**params, 'row_limit': 26},
            ),
        )

    async def test_org_analytics_sql_is_valid(self) -> None:
        """The org report's statements analyze and run, every mode."""
        params = {
            'org_slug': 'no-such-org',
            'surface': 'web',
            'row_limit': 25,
            'stale_days': 90,
        }
        source = document_analytics._session_source(
            'org_slug = {org_slug:String}'
            + document_analytics._surface_filter('web')
        )
        stale_having = (
            'HAVING last_read_at < now() - INTERVAL {stale_days:UInt32} DAY'
        )
        for mode, order in document_analytics._ORG_ORDER.items():
            with self.subTest(mode=mode):
                sql = document_analytics._ORG_SQL.format(
                    source=source,
                    having=stale_having if mode == 'stale' else '',
                    order=order,
                )
                self.assertEqual([], await clickhouse.query(sql, params))
        # ``never-read`` takes a different path entirely.
        self.assertEqual(
            [],
            await clickhouse.query(
                document_analytics._READ_DOCUMENT_IDS_SQL.format(
                    surface_filter=document_analytics._surface_filter('web')
                ),
                params,
            ),
        )

    async def test_reaper_repairs_a_partial_finalization(self) -> None:
        """A finalized row short of the last beat is swept again.

        Heartbeats reach ClickHouse through Iggy, so a session finalized
        by its own final flush routinely misses the beats the sink had
        not drained yet. The reaper is what repairs that, so it has to
        select on "finalized through the last beat" rather than on "has
        a row at all" -- the latter makes the shortfall permanent.
        """
        now = datetime.datetime.now(datetime.UTC)
        last_beat = now - datetime.timedelta(minutes=10)
        started = now - datetime.timedelta(minutes=20)
        partial, covered, unfinalized = (
            f'sql-test-{uuid.uuid4()}' for _ in range(3)
        )

        await clickhouse.insert(
            'document_read_events',
            [
                _document_reads.DocumentReadEventRow(
                    org_slug='sql-test',
                    document_id='doc',
                    session_id=session_id,
                    seq=1,
                    principal='nobody@example.com',
                    surface='web',
                    project_id='',
                    document_version=1,
                    estimated_read_ms=1000,
                    session_started_at=started,
                    recorded_at=last_beat,
                    engaged_ms=1000,
                    max_scroll_pct=50,
                    clamped=0,
                    is_final=1,
                )
                for session_id in (partial, covered, unfinalized)
            ],
        )
        await clickhouse.insert(
            'document_read_sessions',
            [
                _document_reads.DocumentReadSessionRow(
                    org_slug='sql-test',
                    document_id='doc',
                    session_id=session_id,
                    principal='nobody@example.com',
                    surface='web',
                    project_id='',
                    document_version=1,
                    started_at=started,
                    ended_at=ended_at,
                    engaged_ms=1000,
                    max_scroll_pct=50,
                    is_view=1,
                    is_read=0,
                    finalized_at=now,
                )
                for session_id, ended_at in (
                    # Finalized before the last beat landed in the sink.
                    (partial, last_beat - datetime.timedelta(seconds=30)),
                    (covered, last_beat),
                )
            ],
        )

        rows = await clickhouse.query(
            _document_reads._STALE_SESSION_SQL,
            {
                'idle_seconds': _document_reads.SESSION_IDLE_TIMEOUT_SECONDS,
                'lookback_hours': _document_reads.SWEEP_LOOKBACK_HOURS,
                'batch': 10_000,
            },
        )
        swept = {row['session_id'] for row in rows}
        self.assertIn(partial, swept)
        self.assertIn(unfinalized, swept)
        self.assertNotIn(covered, swept)
