"""Tests for project endpoint helper functions.

Covers the private helpers added in the release-committish work:
``_fetch_pr_counts``, ``_resolve_display_names``,
``_fetch_current_releases`` and ``lookup_ops_log_performed_by``.
"""

import datetime
import json
import unittest
from unittest import mock

from imbi.api.endpoints import projects


class FetchPrCountsTestCase(unittest.IsolatedAsyncioTestCase):
    """Coverage for ``_fetch_pr_counts``."""

    async def test_empty_project_ids_short_circuits(self) -> None:
        self.assertEqual(await projects._fetch_pr_counts([]), {})

    async def test_returns_counts_without_viewer(self) -> None:
        rows = [
            {
                'project_id': 'p1',
                'open_count': 3,
                'closed_count': 1,
                'viewer_open_count': 0,
                'viewer_closed_count': 0,
            }
        ]
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(return_value=rows)
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            result = await projects._fetch_pr_counts(['p1'])
        self.assertEqual(result, {'p1': (3, 1, 0, 0)})
        # No viewer param when viewer is None
        called_sql, called_params = ch.query.call_args.args
        self.assertNotIn('viewer', called_params)
        self.assertIn('0 AS viewer_open_count', called_sql)

    async def test_returns_counts_with_viewer(self) -> None:
        rows = [
            {
                'project_id': 'p1',
                'open_count': 5,
                'closed_count': 4,
                'viewer_open_count': 2,
                'viewer_closed_count': 1,
            }
        ]
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(return_value=rows)
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            result = await projects._fetch_pr_counts(
                ['p1'], viewer='alice@example.com'
            )
        self.assertEqual(result, {'p1': (5, 4, 2, 1)})
        called_sql, called_params = ch.query.call_args.args
        self.assertEqual(called_params['viewer'], 'alice@example.com')
        self.assertIn('viewer_open_count', called_sql)

    async def test_swallows_clickhouse_errors(self) -> None:
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(side_effect=RuntimeError('boom'))
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            result = await projects._fetch_pr_counts(['p1'])
        self.assertEqual(result, {})


class ResolveDisplayNamesTestCase(unittest.IsolatedAsyncioTestCase):
    """Coverage for ``_resolve_display_names``."""

    async def test_empty_emails_short_circuits(self) -> None:
        db = mock.AsyncMock()
        self.assertEqual(await projects._resolve_display_names(db, []), {})
        db.execute.assert_not_called()

    async def test_returns_mapping(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {'email': 'a@example.com', 'display_name': 'Alice'},
            {'email': 'b@example.com', 'display_name': 'Bob'},
        ]
        with mock.patch(
            'imbi.api.endpoints.projects.graph.parse_agtype',
            side_effect=lambda v: v,
        ):
            result = await projects._resolve_display_names(
                db, ['a@example.com', 'b@example.com']
            )
        self.assertEqual(
            result,
            {'a@example.com': 'Alice', 'b@example.com': 'Bob'},
        )

    async def test_skips_rows_missing_fields(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {'email': 'a@example.com', 'display_name': None},
            {'email': None, 'display_name': 'NoEmail'},
            {'email': 'c@example.com', 'display_name': 'Carol'},
        ]
        with mock.patch(
            'imbi.api.endpoints.projects.graph.parse_agtype',
            side_effect=lambda v: v,
        ):
            result = await projects._resolve_display_names(
                db, ['a@example.com', 'c@example.com']
            )
        self.assertEqual(result, {'c@example.com': 'Carol'})

    async def test_swallows_db_errors(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = RuntimeError('graph down')
        result = await projects._resolve_display_names(db, ['a@example.com'])
        self.assertEqual(result, {})


def _event(
    timestamp: datetime.datetime,
    *,
    status: str = 'success',
    performed_by: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        'timestamp': timestamp.isoformat(),
        'status': status,
    }
    if performed_by is not None:
        payload['performed_by'] = performed_by
    return payload


def _row(
    *,
    project_id: str,
    env_slug: str,
    tag: str | None,
    committish: str | None,
    events: list[dict[str, object]],
) -> dict[str, object]:
    return {
        'project_id': project_id,
        'env_slug': env_slug,
        'tag': tag,
        'committish': committish,
        'deployments': json.dumps(events),
    }


class FetchCurrentReleasesTestCase(unittest.IsolatedAsyncioTestCase):
    """Coverage for ``_fetch_current_releases`` reading from AGE."""

    async def test_empty_project_ids_short_circuits(self) -> None:
        db = mock.AsyncMock()
        result = await projects._fetch_current_releases(db, [])
        self.assertEqual(result, {})
        db.execute.assert_not_called()

    async def test_returns_release_info_per_env(self) -> None:
        older = datetime.datetime(2026, 4, 1, 12, 0, 0, tzinfo=datetime.UTC)
        newer = datetime.datetime(2026, 4, 2, 12, 0, 0, tzinfo=datetime.UTC)
        db = mock.AsyncMock()
        db.execute.return_value = [
            # An older release also deployed to prod — must not win.
            _row(
                project_id='p1',
                env_slug='prod',
                tag='0.9.0',
                committish='abc1234',
                events=[_event(older, performed_by='legacy@example.com')],
            ),
            # The current prod release: latest event wins.
            _row(
                project_id='p1',
                env_slug='prod',
                tag='1.0.0',
                committish='abcdef0',
                events=[_event(newer, performed_by='alice@example.com')],
            ),
            # Stage release with a null performer (in-product deploy).
            _row(
                project_id='p1',
                env_slug='stage',
                tag=None,
                committish='7654321',
                events=[_event(newer)],
            ),
        ]

        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(return_value=[])

        with (
            mock.patch(
                'imbi.api.endpoints.projects.ch_client.Clickhouse.'
                'get_instance',
                return_value=ch,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.graph.parse_agtype',
                side_effect=lambda v: v,
            ),
        ):
            result = await projects._fetch_current_releases(db, ['p1'])

        prod = result['p1']['prod']
        stage = result['p1']['stage']
        self.assertEqual(prod.tag, '1.0.0')
        self.assertEqual(prod.committish, 'abcdef0')
        self.assertEqual(prod.performed_by, 'alice@example.com')
        self.assertEqual(prod.deployed_at, newer)
        self.assertIsNone(stage.tag)
        self.assertEqual(stage.committish, '7654321')
        self.assertIsNone(stage.performed_by)

    async def test_enriches_performed_by_from_ops_log(self) -> None:
        deployed = datetime.datetime(2026, 4, 1, 12, 0, 0, tzinfo=datetime.UTC)
        db = mock.AsyncMock()
        db.execute.return_value = [
            _row(
                project_id='p1',
                env_slug='prod',
                tag='1.0.0',
                committish='abcdef0',
                events=[_event(deployed)],
            ),
        ]
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(
            return_value=[
                {
                    'project_id': 'p1',
                    'environment_slug': 'prod',
                    'version': '1.0.0',
                    'performed_by': 'bob@example.com',
                },
            ]
        )

        with (
            mock.patch(
                'imbi.api.endpoints.projects.ch_client.Clickhouse.'
                'get_instance',
                return_value=ch,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.graph.parse_agtype',
                side_effect=lambda v: v,
            ),
        ):
            result = await projects._fetch_current_releases(db, ['p1'])

        self.assertEqual(result['p1']['prod'].performed_by, 'bob@example.com')

    async def test_enriches_performed_by_from_committish_when_tag_set(
        self,
    ) -> None:
        # A branch/SHA deploy records version = committish in the ops log
        # even though the release carries a tag; the backfill must probe
        # the committish key too, not just the tag.
        deployed = datetime.datetime(2026, 4, 1, 12, 0, 0, tzinfo=datetime.UTC)
        db = mock.AsyncMock()
        db.execute.return_value = [
            _row(
                project_id='p1',
                env_slug='prod',
                tag='1.0.0',
                committish='abcdef0',
                events=[_event(deployed)],
            ),
        ]
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(
            return_value=[
                {
                    'project_id': 'p1',
                    'environment_slug': 'prod',
                    'version': 'abcdef0',
                    'performed_by': 'carol@example.com',
                },
            ]
        )

        with (
            mock.patch(
                'imbi.api.endpoints.projects.ch_client.Clickhouse.'
                'get_instance',
                return_value=ch,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.graph.parse_agtype',
                side_effect=lambda v: v,
            ),
        ):
            result = await projects._fetch_current_releases(db, ['p1'])

        self.assertEqual(
            result['p1']['prod'].performed_by, 'carol@example.com'
        )

    async def test_skips_environments_with_no_events(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            _row(
                project_id='p1',
                env_slug='prod',
                tag='1.0.0',
                committish='abcdef0',
                events=[],
            ),
        ]
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(return_value=[])
        with (
            mock.patch(
                'imbi.api.endpoints.projects.ch_client.Clickhouse.'
                'get_instance',
                return_value=ch,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.graph.parse_agtype',
                side_effect=lambda v: v,
            ),
        ):
            result = await projects._fetch_current_releases(db, ['p1'])
        self.assertEqual(result, {})

    async def test_swallows_graph_errors(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = RuntimeError('graph down')
        result = await projects._fetch_current_releases(db, ['p1'])
        self.assertEqual(result, {})


class LookupOpsLogPerformedByTestCase(unittest.IsolatedAsyncioTestCase):
    """Coverage for ``lookup_ops_log_performed_by``."""

    async def test_empty_targets_short_circuits(self) -> None:
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance'
        ) as gi:
            result = await projects.lookup_ops_log_performed_by([])
        self.assertEqual(result, {})
        gi.assert_not_called()

    async def test_filters_to_requested_keys(self) -> None:
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(
            return_value=[
                {
                    'project_id': 'p1',
                    'environment_slug': 'prod',
                    'version': '1.0.0',
                    'performed_by': 'alice@example.com',
                },
                # Stale row for a version we no longer need — must be dropped.
                {
                    'project_id': 'p1',
                    'environment_slug': 'prod',
                    'version': '0.9.0',
                    'performed_by': 'legacy@example.com',
                },
            ]
        )
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            result = await projects.lookup_ops_log_performed_by(
                [('p1', 'prod', '1.0.0', None)]
            )
        self.assertEqual(result, {('p1', 'prod'): 'alice@example.com'})

    async def test_swallows_clickhouse_errors(self) -> None:
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(side_effect=RuntimeError('boom'))
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            result = await projects.lookup_ops_log_performed_by(
                [('p1', 'prod', '1.0.0', None)]
            )
        self.assertEqual(result, {})
