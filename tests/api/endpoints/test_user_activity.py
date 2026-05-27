"""Tests for user-profile activity endpoints."""

from __future__ import annotations

import collections.abc
import datetime
import typing
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import graph

from imbi_api import app
from imbi_api import models as api_models
from imbi_api.auth import permissions as api_permissions
from imbi_api.endpoints import user_activity


def _make_auth(
    *,
    perms: collections.abc.Iterable[str] = ('user:read',),
    is_admin: bool = True,
) -> api_permissions.AuthContext:
    user = api_models.User(
        email='alice@example.com',
        display_name='Alice',
        is_active=True,
        is_admin=is_admin,
        is_service_account=False,
        created_at=datetime.datetime.now(datetime.UTC),
    )
    return api_permissions.AuthContext(
        user=user,
        session_id='test',
        auth_method='jwt',
        permissions=set(perms),
    )


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.test_app = app.create_app()
        self.auth = _make_auth()

        async def _current_user() -> api_permissions.AuthContext:
            return self.auth

        self.test_app.dependency_overrides[
            api_permissions.get_current_user
        ] = _current_user

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

        self.query_patcher = mock.patch(
            'imbi_common.clickhouse.query',
            new_callable=mock.AsyncMock,
        )
        self.mock_query = self.query_patcher.start()
        self.addCleanup(self.query_patcher.stop)

        self.parse_patcher = mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda v: v,
        )
        self.parse_patcher.start()
        self.addCleanup(self.parse_patcher.stop)

        # Also patch the alias imported by the module under test.
        self.parse_patcher_local = mock.patch(
            'imbi_api.endpoints.user_activity.graph.parse_agtype',
            side_effect=lambda v: v,
        )
        self.parse_patcher_local.start()
        self.addCleanup(self.parse_patcher_local.stop)

        self.client = testclient.TestClient(self.test_app)
        self.addCleanup(self.client.close)

    def _execute_returns(
        self, payloads: list[list[dict[str, typing.Any]]]
    ) -> None:
        """Set ``mock_db.execute`` to return ``payloads`` in order."""
        self.mock_db.execute.side_effect = list(payloads)


class WindowAndCursorTests(unittest.TestCase):
    def test_resolve_window_default(self) -> None:
        start, end = user_activity._resolve_window(None, None)
        self.assertGreater(end, start)
        self.assertAlmostEqual(
            (end - start).days,
            user_activity.DEFAULT_WINDOW_DAYS,
            delta=1,
        )

    def test_resolve_window_invalid_iso(self) -> None:
        import fastapi

        with self.assertRaises(fastapi.HTTPException):
            user_activity._resolve_window('not-a-date', None)

    def test_resolve_window_inverted(self) -> None:
        import fastapi

        with self.assertRaises(fastapi.HTTPException):
            user_activity._resolve_window(
                '2026-01-02T00:00:00Z', '2026-01-01T00:00:00Z'
            )

    def test_cursor_round_trip(self) -> None:
        ts = datetime.datetime(2026, 4, 1, 12, 0, tzinfo=datetime.UTC)
        encoded = user_activity.encode_cursor(ts, 'evt-1')
        decoded = user_activity.decode_cursor(encoded)
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertEqual(decoded[0], ts)
        self.assertEqual(decoded[1], 'evt-1')

    def test_cursor_decode_invalid(self) -> None:
        self.assertIsNone(user_activity.decode_cursor(''))
        self.assertIsNone(user_activity.decode_cursor('not-base64-!@#$'))

    def test_resolve_tz_valid(self) -> None:
        zone = user_activity._resolve_tz('UTC')
        self.assertEqual(str(zone), 'UTC')
        zone = user_activity._resolve_tz('America/New_York')
        self.assertEqual(str(zone), 'America/New_York')

    def test_resolve_tz_invalid(self) -> None:
        import fastapi

        with self.assertRaises(fastapi.HTTPException) as ctx:
            user_activity._resolve_tz('Not/A_Zone')
        self.assertEqual(ctx.exception.status_code, 400)


class ContributionsTests(_Base):
    def test_unknown_user_returns_404(self) -> None:
        self._execute_returns([[]])  # _ensure_user_exists -> no rows
        resp = self.client.get('/users/missing@example.com/contributions')
        self.assertEqual(resp.status_code, 404)

    def test_aggregates_all_legs(self) -> None:
        # _ensure_user_exists, _resolve_user_subjects, then 4 graph legs
        self._execute_returns(
            [
                [{'id': 'u1'}],
                [
                    {
                        'conn_subjects': ['ext-42'],
                        'oauth_subjects': ['oauth-1'],
                    }
                ],
                [
                    {
                        'ts': datetime.datetime(
                            2026, 4, 17, 10, 0, tzinfo=datetime.UTC
                        ).isoformat(),
                    },
                    {
                        'ts': datetime.datetime(
                            2026, 4, 17, 11, 0, tzinfo=datetime.UTC
                        ).isoformat(),
                    },
                ],  # documents
                [],  # releases
                [],  # uploads
                [],  # conversations
            ]
        )
        opslog_day = datetime.date(2026, 4, 16)
        events_day = datetime.date(2026, 4, 18)
        self.mock_query.side_effect = [
            [{'d': opslog_day, 'c': 5}],  # opslog buckets
            [{'d': events_day, 'c': 2}],  # events buckets
        ]
        resp = self.client.get('/users/alice@example.com/contributions')
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body['total'], 5 + 2 + 2)
        self.assertEqual(len(body['buckets']), 3)
        sources = {b['date']: b['by_source'] for b in body['buckets']}
        self.assertEqual(sources[opslog_day.isoformat()]['operations_log'], 5)
        self.assertEqual(sources[events_day.isoformat()]['events'], 2)
        self.assertEqual(sources['2026-04-17']['document'], 2)

    def test_invalid_tz_returns_400(self) -> None:
        self._execute_returns([[{'id': 'u1'}]])
        resp = self.client.get(
            '/users/alice@example.com/contributions?tz=Not/A_Zone'
        )
        self.assertEqual(resp.status_code, 400)


class StatsTests(_Base):
    def test_returns_success_rate_and_envs(self) -> None:
        self._execute_returns(
            [
                [{'id': 'u1'}],
                [{'conn_subjects': [], 'oauth_subjects': []}],
                [],  # _projects_touched -> graph
            ]
        )
        self.mock_query.side_effect = [
            [{'deployed': 50, 'rolled_back': 3}],  # totals
            [
                {'environment_slug': 'production', 'c': 30},
                {'environment_slug': 'staging', 'c': 20},
            ],  # by env
            [{'project_id': 'p1'}, {'project_id': 'p2'}],  # opslog distinct
        ]
        resp = self.client.get('/users/alice@example.com/stats')
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body['deployments']['total'], 50)
        self.assertEqual(body['deployments']['rolled_back'], 3)
        self.assertAlmostEqual(
            body['deployments']['success_rate'],
            1.0 - 3 / 50,
        )
        self.assertEqual(body['projects_touched'], 2)
        self.assertEqual(
            body['deployments_by_environment'],
            {'production': 30, 'staging': 20},
        )

    def test_zero_deployments_yields_null_success_rate(self) -> None:
        self._execute_returns(
            [
                [{'id': 'u1'}],
                [{'conn_subjects': [], 'oauth_subjects': []}],
                [],
            ]
        )
        self.mock_query.side_effect = [
            [{'deployed': 0, 'rolled_back': 0}],
            [],
            [],
        ]
        resp = self.client.get('/users/alice@example.com/stats')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()['deployments']['success_rate'])


class IdentitiesTests(_Base):
    def test_primary_is_most_recent_last_used(self) -> None:
        recent = datetime.datetime(2026, 5, 1, tzinfo=datetime.UTC)
        older = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        self._execute_returns(
            [
                [{'id': 'u1'}],  # _ensure_user_exists
                [
                    {
                        'provider': 'google',
                        'provider_user_id': '999',
                        'email': 'alice@example.com',
                        'display_name': 'Alice',
                        'linked_at': older.isoformat(),
                        'last_used': older.isoformat(),
                    },
                    {
                        'provider': 'github',
                        'provider_user_id': '42',
                        'email': 'alice@example.com',
                        'display_name': 'Alice',
                        'linked_at': older.isoformat(),
                        'last_used': recent.isoformat(),
                    },
                ],
            ]
        )
        resp = self.client.get('/users/alice@example.com/identities')
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body['primary']['provider'], 'github')
        self.assertEqual(len(body['all']), 2)


class ActivityFeedTests(_Base):
    def test_merges_and_orders_descending(self) -> None:
        ts1 = datetime.datetime(2026, 4, 1, 10, tzinfo=datetime.UTC)
        ts2 = datetime.datetime(2026, 4, 2, 10, tzinfo=datetime.UTC)
        ts3 = datetime.datetime(2026, 4, 3, 10, tzinfo=datetime.UTC)

        self._execute_returns(
            [
                [{'id': 'u1'}],  # _ensure_user_exists
                [{'conn_subjects': [], 'oauth_subjects': []}],  # subjects
                # graph legs in registration order (document, release, upload,
                # conversation)
                [
                    {
                        'id': 'document-1',
                        'ts': ts2.isoformat(),
                        'title': 'A document',
                        'created_by': 'alice@example.com',
                        'updated_by': None,
                        'project_id': 'p1',
                        'project_slug': 'imbi-api',
                        'project_name': 'Imbi API',
                    }
                ],
                [],  # releases
                [],  # uploads
                [],  # conversations
            ]
        )
        self.mock_query.side_effect = [
            # opslog
            [
                {
                    'id': 'op-1',
                    'occurred_at': ts1,
                    'entry_type': 'Deployed',
                    'environment_slug': 'production',
                    'project_id': 'p1',
                    'project_slug': 'imbi-api',
                    'description': 'rolled v1.0.0',
                    'version': 'v1.0.0',
                },
                {
                    'id': 'op-2',
                    'occurred_at': ts3,
                    'entry_type': 'Rolled Back',
                    'environment_slug': 'production',
                    'project_id': 'p1',
                    'project_slug': 'imbi-api',
                    'description': 'reverted',
                    'version': 'v0.9.9',
                },
            ],
            [],  # events
        ]
        resp = self.client.get('/users/alice@example.com/activity?limit=2')
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(len(body['data']), 2)
        # Newest first: op-2 (ts3), document-1 (ts2)
        self.assertEqual(body['data'][0]['id'], 'op-2')
        self.assertEqual(body['data'][0]['source'], 'operations_log')
        self.assertEqual(body['data'][1]['id'], 'document-1')
        self.assertEqual(body['data'][1]['source'], 'document')
        # Has Link header
        self.assertIn('Link', resp.headers)

    def test_limit_validation(self) -> None:
        resp = self.client.get('/users/a@b/activity?limit=0')
        self.assertEqual(resp.status_code, 400)
        resp = self.client.get('/users/a@b/activity?limit=999')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_cursor(self) -> None:
        self._execute_returns([[{'id': 'u1'}]])
        resp = self.client.get(
            '/users/alice@example.com/activity?cursor=garbage!@#'
        )
        self.assertEqual(resp.status_code, 400)

    def test_no_next_link_when_results_match_limit_exactly(self) -> None:
        """No next cursor when fewer than limit+1 rows are available."""
        ts1 = datetime.datetime(2026, 4, 1, 10, tzinfo=datetime.UTC)
        ts2 = datetime.datetime(2026, 4, 2, 10, tzinfo=datetime.UTC)
        self._execute_returns(
            [
                [{'id': 'u1'}],  # _ensure_user_exists
                [{'conn_subjects': [], 'oauth_subjects': []}],  # subjects
                [],  # documents
                [],  # releases
                [],  # uploads
                [],  # conversations
            ]
        )
        self.mock_query.side_effect = [
            [
                {
                    'id': 'op-1',
                    'occurred_at': ts1,
                    'entry_type': 'Deployed',
                    'environment_slug': 'production',
                    'project_id': 'p1',
                    'project_slug': 'imbi-api',
                    'description': '',
                    'version': 'v1',
                },
                {
                    'id': 'op-2',
                    'occurred_at': ts2,
                    'entry_type': 'Deployed',
                    'environment_slug': 'production',
                    'project_id': 'p1',
                    'project_slug': 'imbi-api',
                    'description': '',
                    'version': 'v2',
                },
            ],
            [],  # events
        ]
        resp = self.client.get('/users/alice@example.com/activity?limit=2')
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(len(body['data']), 2)
        # Only first/self link, no rel="next" because available rows == limit
        link = resp.headers.get('Link', '')
        self.assertNotIn('rel="next"', link)


class GraphActivityColumnsTests(unittest.TestCase):
    """Cypher RETURN arity must match ``_GRAPH_ACTIVITY_COLUMNS``.

    AGE requires the SQL ``AS (...)`` column list passed to ``cypher()``
    to match the number of ``RETURN`` expressions, otherwise psycopg
    raises ``DatatypeMismatch: return row and column definition list do
    not match`` — which is what surfaced as a 500 on the
    ``GET /users/{email}/activity`` endpoint.
    """

    @staticmethod
    def _return_arity(template: str) -> int:
        """Count comma-separated aliases in the Cypher RETURN clause."""
        import re

        upper = template.upper()
        start = upper.index('RETURN')
        tail = template[start + len('RETURN') :]
        tail_upper = tail.upper()
        stop = len(tail)
        for kw in (' ORDER BY ', ' LIMIT ', ' WITH ', ' UNION '):
            idx = tail_upper.find(kw)
            if idx != -1 and idx < stop:
                stop = idx
        clause = tail[:stop]
        flat = re.sub(r'\s+', ' ', clause).strip()
        return len([p for p in flat.split(',') if p.strip()])

    def test_columns_match_return_arity(self) -> None:
        for label, template in user_activity._GRAPH_ACTIVITY_QUERIES.items():
            with self.subTest(label=label):
                arity = self._return_arity(template)
                self.assertEqual(
                    len(user_activity._GRAPH_ACTIVITY_COLUMNS[label]),
                    arity,
                    f'columns for {label!r} must match RETURN arity',
                )


class GraphActivityExecuteTests(_Base):
    """``_graph_activity`` must pass a columns list matching the query."""

    def test_execute_columns_match_per_label(self) -> None:
        """Regression for the 500 on /users/{email}/activity.

        AGE's ``cypher()`` wrapper requires an ``AS (...)`` column list
        whose arity matches the Cypher ``RETURN`` clause; the bug was
        that ``_graph_activity`` omitted the ``columns`` argument
        entirely, so psycopg attempted a single-column unpack of an
        N-column row and raised ``DatatypeMismatch``.
        """
        self._execute_returns(
            [
                [{'id': 'u1'}],  # _ensure_user_exists
                [{'conn_subjects': [], 'oauth_subjects': []}],  # subjects
                [],  # documents
                [],  # releases
                [],  # uploads
                [],  # conversations
            ]
        )
        self.mock_query.side_effect = [[], []]  # opslog, events
        resp = self.client.get('/users/alice@example.com/activity')
        self.assertEqual(resp.status_code, 200, resp.text)

        # First two execute calls are _ensure_user_exists + subjects; the
        # next four are the graph-activity legs in registration order.
        graph_calls = self.mock_db.execute.await_args_list[2:6]
        for call, label in zip(
            graph_calls,
            ('document', 'release', 'upload', 'conversation'),
            strict=True,
        ):
            with self.subTest(label=label):
                self.assertGreaterEqual(len(call.args), 3, call)
                columns = call.args[2]
                self.assertEqual(
                    columns,
                    user_activity._GRAPH_ACTIVITY_COLUMNS[label],
                )


class PermissionTests(unittest.TestCase):
    """Endpoints must require user:read."""

    def setUp(self) -> None:
        self.test_app = app.create_app()
        self.auth = _make_auth(perms=(), is_admin=False)  # no permissions

        async def _current_user() -> api_permissions.AuthContext:
            return self.auth

        self.test_app.dependency_overrides[
            api_permissions.get_current_user
        ] = _current_user
        # Also override graph so require_permission doesn't trip on a
        # missing pool when it short-circuits on the 403.
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )
        self.client = testclient.TestClient(self.test_app)
        self.addCleanup(self.client.close)

    def test_contributions_requires_user_read(self) -> None:
        resp = self.client.get('/users/alice@example.com/contributions')
        self.assertEqual(resp.status_code, 403)

    def test_stats_requires_user_read(self) -> None:
        resp = self.client.get('/users/alice@example.com/stats')
        self.assertEqual(resp.status_code, 403)

    def test_activity_requires_user_read(self) -> None:
        resp = self.client.get('/users/alice@example.com/activity')
        self.assertEqual(resp.status_code, 403)

    def test_identities_requires_user_read(self) -> None:
        resp = self.client.get('/users/alice@example.com/identities')
        self.assertEqual(resp.status_code, 403)
