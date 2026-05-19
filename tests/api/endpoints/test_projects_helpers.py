"""Tests for project endpoint helper functions.

Covers the private helpers added in the release-committish work:
``_fetch_pr_counts``, ``_resolve_display_names``,
``_fetch_current_releases`` and ``_resolve_release_identities``.
"""

import datetime
import unittest
from unittest import mock

from imbi_api.endpoints import projects


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
            'imbi_api.endpoints.projects.ch_client.Clickhouse.get_instance',
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
            'imbi_api.endpoints.projects.ch_client.Clickhouse.get_instance',
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
            'imbi_api.endpoints.projects.ch_client.Clickhouse.get_instance',
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
            'imbi_api.endpoints.projects.graph.parse_agtype',
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
            'imbi_api.endpoints.projects.graph.parse_agtype',
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


class ResolveReleaseIdentitiesTestCase(unittest.IsolatedAsyncioTestCase):
    """Coverage for ``_resolve_release_identities``."""

    async def test_empty_pairs_short_circuits(self) -> None:
        db = mock.AsyncMock()
        result = await projects._resolve_release_identities(db, [])
        self.assertEqual(result, {})
        db.execute.assert_not_called()

    async def test_resolves_tag_and_committish(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {'project_id': 'p1', 'tag': '1.0.0', 'committish': 'abcdef0'},
            {'project_id': 'p1', 'tag': None, 'committish': '1234567'},
            {'project_id': 'p2', 'tag': '2.0.0', 'committish': 'fedcba9'},
        ]
        with mock.patch(
            'imbi_api.endpoints.projects.graph.parse_agtype',
            side_effect=lambda v: v,
        ):
            result = await projects._resolve_release_identities(
                db,
                [
                    ('p1', '1.0.0'),  # matches by tag
                    ('p1', '1234567'),  # matches by committish only
                    ('p2', 'fedcba9'),  # matches by committish (has tag too)
                    ('p2', 'not-there'),  # no match — omitted
                ],
            )
        self.assertEqual(result[('p1', '1.0.0')], ('1.0.0', 'abcdef0'))
        self.assertEqual(result[('p1', '1234567')], (None, '1234567'))
        self.assertEqual(result[('p2', 'fedcba9')], ('2.0.0', 'fedcba9'))
        self.assertNotIn(('p2', 'not-there'), result)

    async def test_tag_wins_when_version_matches_both(self) -> None:
        # A version equal to one release's tag AND another release's
        # committish must resolve to the tagged release.
        db = mock.AsyncMock()
        db.execute.return_value = [
            # Release A: has tag 'shared'
            {'project_id': 'p1', 'tag': 'shared', 'committish': 'aaaaaaa'},
            # Release B: has committish 'shared'
            {'project_id': 'p1', 'tag': '1.2.3', 'committish': 'shared'},
        ]
        with mock.patch(
            'imbi_api.endpoints.projects.graph.parse_agtype',
            side_effect=lambda v: v,
        ):
            result = await projects._resolve_release_identities(
                db, [('p1', 'shared')]
            )
        self.assertEqual(result[('p1', 'shared')], ('shared', 'aaaaaaa'))

    async def test_skips_rows_with_non_string_project_id(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {'project_id': 12345, 'tag': '1.0.0', 'committish': 'abc'},
        ]
        with mock.patch(
            'imbi_api.endpoints.projects.graph.parse_agtype',
            side_effect=lambda v: v,
        ):
            result = await projects._resolve_release_identities(
                db, [('12345', '1.0.0')]
            )
        self.assertEqual(result, {})

    async def test_swallows_db_errors(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = RuntimeError('graph down')
        result = await projects._resolve_release_identities(
            db, [('p1', '1.0.0')]
        )
        self.assertEqual(result, {})


class FetchCurrentReleasesTestCase(unittest.IsolatedAsyncioTestCase):
    """Coverage for ``_fetch_current_releases``."""

    async def test_empty_project_ids_short_circuits(self) -> None:
        db = mock.AsyncMock()
        result = await projects._fetch_current_releases(db, [])
        self.assertEqual(result, {})

    async def test_returns_release_info_per_env(self) -> None:
        deployed = datetime.datetime(2026, 4, 1, 12, 0, 0, tzinfo=datetime.UTC)
        ch_rows = [
            {
                'project_id': 'p1',
                'environment_slug': 'prod',
                'version': '1.0.0',
                'performed_by': 'alice@example.com',
                'deployed_at': deployed,
            },
            {
                'project_id': 'p1',
                'environment_slug': 'stage',
                'version': '7654321',
                'performed_by': None,
                'deployed_at': deployed,
            },
        ]
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(return_value=ch_rows)

        db = mock.AsyncMock()
        db.execute.return_value = [
            {'project_id': 'p1', 'tag': '1.0.0', 'committish': 'abcdef0'},
            {'project_id': 'p1', 'tag': None, 'committish': '7654321'},
        ]

        with (
            mock.patch(
                'imbi_api.endpoints.projects.ch_client.Clickhouse.'
                'get_instance',
                return_value=ch,
            ),
            mock.patch(
                'imbi_api.endpoints.projects.graph.parse_agtype',
                side_effect=lambda v: v,
            ),
        ):
            result = await projects._fetch_current_releases(db, ['p1'])

        prod = result['p1']['prod']
        stage = result['p1']['stage']
        self.assertEqual(prod.tag, '1.0.0')
        self.assertEqual(prod.committish, 'abcdef0')
        self.assertEqual(prod.performed_by, 'alice@example.com')
        self.assertEqual(prod.deployed_at, deployed)
        self.assertIsNone(stage.tag)
        self.assertEqual(stage.committish, '7654321')
        self.assertIsNone(stage.performed_by)

    async def test_missing_version_omits_release_identity(self) -> None:
        deployed = datetime.datetime(2026, 4, 1, 12, 0, 0, tzinfo=datetime.UTC)
        ch_rows = [
            {
                'project_id': 'p1',
                'environment_slug': 'prod',
                'version': '',
                'performed_by': 'bob@example.com',
                'deployed_at': deployed,
            },
        ]
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(return_value=ch_rows)

        db = mock.AsyncMock()
        db.execute.return_value = []

        with (
            mock.patch(
                'imbi_api.endpoints.projects.ch_client.Clickhouse.'
                'get_instance',
                return_value=ch,
            ),
            mock.patch(
                'imbi_api.endpoints.projects.graph.parse_agtype',
                side_effect=lambda v: v,
            ),
        ):
            result = await projects._fetch_current_releases(db, ['p1'])
        info = result['p1']['prod']
        self.assertIsNone(info.tag)
        self.assertIsNone(info.committish)
        self.assertEqual(info.performed_by, 'bob@example.com')

    async def test_swallows_clickhouse_errors(self) -> None:
        ch = mock.MagicMock()
        ch.query = mock.AsyncMock(side_effect=RuntimeError('boom'))
        db = mock.AsyncMock()
        with mock.patch(
            'imbi_api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=ch,
        ):
            result = await projects._fetch_current_releases(db, ['p1'])
        self.assertEqual(result, {})
