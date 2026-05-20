"""Tests for scoring history, rollup, and rescore endpoints."""

from __future__ import annotations

import datetime
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from imbi_common import graph

from imbi_api import app, models
from imbi_api import scoring as scoring_di


class ScoringEndpointsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        from imbi_api.auth import permissions

        self.test_app = app.create_app()

        self.user = models.User(
            email='admin@example.com',
            display_name='Admin',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth = permissions.AuthContext(
            user=self.user,
            session_id='s',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_user() -> permissions.AuthContext:
            return self.auth

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.mock_valkey = mock.AsyncMock()
        self.mock_valkey.set = mock.AsyncMock(return_value=True)
        self.mock_valkey.xadd = mock.AsyncMock()

        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )
        self.test_app.dependency_overrides[
            scoring_di._inject_optional_client
        ] = lambda: self.mock_valkey
        self.client = TestClient(self.test_app)

    def test_history_raw(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[{'id': 'p1'}])
        with mock.patch(
            'imbi_api.endpoints.scoring.clickhouse.query',
            mock.AsyncMock(
                return_value=[
                    {
                        'timestamp': '2026-04-01T00:00:00',
                        'score': 80.0,
                        'previous_score': 70.0,
                        'change_reason': 'attribute_change',
                    }
                ]
            ),
        ):
            response = self.client.get(
                '/organizations/eng/projects/p1/score/history',
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['granularity'], 'raw')
        self.assertEqual(len(body['points']), 1)

    def test_history_404(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        response = self.client.get(
            '/organizations/eng/projects/missing/score/history',
        )
        self.assertEqual(response.status_code, 404)

    def test_rollup(self) -> None:
        # db.execute returns project→team mappings from AGE
        self.mock_db.execute = mock.AsyncMock(
            return_value=[
                {'project_id': 'p1', 'dim_key': 'platform'},
                {'project_id': 'p2', 'dim_key': 'platform'},
            ]
        )
        with (
            mock.patch(
                'imbi_api.endpoints.scoring.clickhouse.query',
                mock.AsyncMock(
                    return_value=[
                        {
                            'project_id': 'p1',
                            'latest_score': 90.0,
                            'last_updated': '2026-04-01',
                        },
                        {
                            'project_id': 'p2',
                            'latest_score': 80.0,
                            'last_updated': '2026-03-01',
                        },
                    ]
                ),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.get(
                '/scores/rollup', params={'dimension': 'team'}
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['key'], 'platform')
        self.assertAlmostEqual(body[0]['avg_score'], 85.0)
        self.assertEqual(body[0]['latest_score'], 90.0)

    def test_rollup_empty_when_no_projects(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        response = self.client.get(
            '/scores/rollup', params={'dimension': 'team'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    def test_rescore_all(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            return_value=[{'id': 'p1'}, {'id': 'p2'}]
        )
        response = self.client.post('/scoring/rescore', json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['enqueued'], 2)
        self.assertEqual(self.mock_valkey.xadd.await_count, 2)

    def test_rescore_debounce_blocks_duplicate(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            return_value=[{'id': 'p1'}, {'id': 'p1'}]
        )
        self.mock_valkey.set = mock.AsyncMock(side_effect=[True, False])
        response = self.client.post('/scoring/rescore', json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['enqueued'], 1)

    def test_history_with_date_filters(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[{'id': 'p1'}])
        with mock.patch(
            'imbi_api.endpoints.scoring.clickhouse.query',
            mock.AsyncMock(return_value=[]),
        ):
            response = self.client.get(
                '/organizations/eng/projects/p1/score/history',
                params={
                    'from': '2026-01-01T00:00:00',
                    'to': '2026-04-01T00:00:00',
                },
            )
        self.assertEqual(response.status_code, 200, response.text)

    def test_history_hourly_granularity(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[{'id': 'p1'}])
        with mock.patch(
            'imbi_api.endpoints.scoring.clickhouse.query',
            mock.AsyncMock(
                return_value=[{'ts': '2026-04-01T00:00:00', 'score': 85.0}]
            ),
        ):
            response = self.client.get(
                '/organizations/eng/projects/p1/score/history',
                params={'granularity': 'hour'},
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['granularity'], 'hour')
        self.assertEqual(len(body['points']), 1)

    def test_rescore_by_blueprint_slug(self) -> None:
        blueprint_raw = {
            'id': 'bp1',
            'slug': 'my-blueprint',
            'name': 'My Blueprint',
            'type': 'Project',
            'filter': None,
        }
        self.mock_db.execute = mock.AsyncMock(
            side_effect=[
                [{'b': blueprint_raw}],  # blueprint lookup
                [{'id': 'p1'}, {'id': 'p2'}],  # all_project_ids
            ]
        )
        response = self.client.post(
            '/scoring/rescore', json={'blueprint_slug': 'my-blueprint'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['enqueued'], 2)

    def test_rescore_by_blueprint_slug_not_found(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        response = self.client.post(
            '/scoring/rescore', json={'blueprint_slug': 'missing-blueprint'}
        )
        self.assertEqual(response.status_code, 404)

    def test_rescore_by_policy_slug_not_found(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        response = self.client.post(
            '/scoring/rescore', json={'policy_slug': 'missing-policy'}
        )
        self.assertEqual(response.status_code, 404)

    def test_rescore_by_policy_slug(self) -> None:
        policy_props = {
            'id': 'p1id',
            'name': 'Python Version',
            'slug': 'python-version',
            'category': 'attribute',
            'attribute_name': 'programming_language',
            'weight': 50,
            'enabled': True,
            'priority': 0,
            'description': None,
            'value_score_map': '{"Python 3.12": 100}',
            'range_score_map': None,
        }
        self.mock_db.execute = mock.AsyncMock(
            return_value=[{'sp': policy_props, 'targets': []}]
        )
        with mock.patch(
            'imbi_api.endpoints.scoring.score_queue.affected_projects',
            mock.AsyncMock(return_value=['p1']),
        ):
            response = self.client.post(
                '/scoring/rescore', json={'policy_slug': 'python-version'}
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['enqueued'], 1)

    def test_rescore_by_project_id(self) -> None:
        response = self.client.post(
            '/scoring/rescore', json={'project_id': 'proj-abc'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['enqueued'], 1)
        args = self.mock_valkey.xadd.call_args.args
        self.assertEqual(args[1]['project_id'], 'proj-abc')

    def test_rescore_single_project_requires_only_rescore_perm(self) -> None:
        """Non-admin with ``scoring_policy:rescore`` can rescore one project.

        The wider permission ``scoring_policy:rescore_all`` is not
        required for the single-project case.
        """
        self.auth.user = self.user.model_copy(update={'is_admin': False})
        self.auth.permissions = {'scoring_policy:rescore'}
        response = self.client.post(
            '/scoring/rescore', json={'project_id': 'proj-abc'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['enqueued'], 1)

    def test_rescore_single_project_rejects_without_perm(self) -> None:
        """Non-admin with neither rescore permission is rejected (403)."""
        self.auth.user = self.user.model_copy(update={'is_admin': False})
        self.auth.permissions = set()
        response = self.client.post(
            '/scoring/rescore', json={'project_id': 'proj-abc'}
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn('scoring_policy:rescore', response.json()['detail'])

    def test_rescore_wider_scope_requires_rescore_all(self) -> None:
        """``rescore`` alone is not enough for blueprint / policy scope."""
        self.auth.user = self.user.model_copy(update={'is_admin': False})
        self.auth.permissions = {'scoring_policy:rescore'}
        response = self.client.post(
            '/scoring/rescore', json={'policy_slug': 'python-version'}
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn('scoring_policy:rescore_all', response.json()['detail'])

    def test_rescore_all_requires_rescore_all_for_non_admin(self) -> None:
        """A non-admin with ``rescore_all`` runs the empty-body bulk path."""
        self.auth.user = self.user.model_copy(update={'is_admin': False})
        self.auth.permissions = {'scoring_policy:rescore_all'}
        self.mock_db.execute = mock.AsyncMock(
            return_value=[{'id': 'p1'}, {'id': 'p2'}]
        )
        response = self.client.post('/scoring/rescore', json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['enqueued'], 2)

    def test_score_trend_returns_delta(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            return_value=[{'score': 90.0}],
        )
        with (
            mock.patch(
                'imbi_api.endpoints.scoring.clickhouse.query',
                mock.AsyncMock(return_value=[{'score': 80.0}]),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.get(
                '/organizations/eng/projects/p1/score/trend',
                params={'days': 30},
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['current'], 90.0)
        self.assertEqual(body['previous'], 80.0)
        self.assertEqual(body['delta'], 10.0)
        self.assertEqual(body['period_days'], 30)

    def test_score_trend_handles_missing_history(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            return_value=[{'score': 90.0}],
        )
        with (
            mock.patch(
                'imbi_api.endpoints.scoring.clickhouse.query',
                mock.AsyncMock(return_value=[]),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.get(
                '/organizations/eng/projects/p1/score/trend',
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIsNone(body['previous'])
        self.assertIsNone(body['delta'])

    def test_score_trend_404_when_project_missing(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        response = self.client.get(
            '/organizations/eng/projects/missing/score/trend',
        )
        self.assertEqual(response.status_code, 404)

    def test_monthly_improvement_returns_current_month_rows(self) -> None:
        # p1 and p2 are in "platform", p3 is in "data" (current month only)
        # p4 is in "legacy" but only scored in the previous month
        self.mock_db.execute = mock.AsyncMock(
            return_value=[
                {'project_id': 'p1', 'dim_key': 'platform'},
                {'project_id': 'p2', 'dim_key': 'platform'},
                {'project_id': 'p3', 'dim_key': 'data'},
                {'project_id': 'p4', 'dim_key': 'legacy'},
            ]
        )
        # asyncio.gather calls clickhouse.query twice: cur then prev
        with (
            mock.patch(
                'imbi_api.endpoints.scoring.clickhouse.query',
                mock.AsyncMock(
                    side_effect=[
                        # current-month scores: p1, p2, p3 scored; p4 not
                        [
                            {'project_id': 'p1', 'score': 80.0},
                            {'project_id': 'p2', 'score': 60.0},
                            {'project_id': 'p3', 'score': 90.0},
                        ],
                        # previous-month scores: p1, p2, p4 scored; p3 not
                        [
                            {'project_id': 'p1', 'score': 70.0},
                            {'project_id': 'p2', 'score': 50.0},
                            {'project_id': 'p4', 'score': 85.0},
                        ],
                    ]
                ),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.get(
                '/scores/monthly-improvement',
                params={'year': 2026, 'month': 4, 'dimension': 'team'},
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        keys = {row['key'] for row in body}
        # Only keys present in current month
        self.assertIn('platform', keys)
        self.assertIn('data', keys)
        # "legacy" only existed in prev month; must NOT appear
        self.assertNotIn('legacy', keys)

        platform_row = next(r for r in body if r['key'] == 'platform')
        self.assertAlmostEqual(platform_row['current_avg_score'], 70.0)
        self.assertAlmostEqual(platform_row['previous_avg_score'], 60.0)
        self.assertAlmostEqual(platform_row['improvement'], 10.0)
        self.assertEqual(platform_row['project_count'], 2)

        data_row = next(r for r in body if r['key'] == 'data')
        self.assertAlmostEqual(data_row['current_avg_score'], 90.0)
        self.assertIsNone(data_row['previous_avg_score'])
        self.assertIsNone(data_row['improvement'])
        self.assertEqual(data_row['project_count'], 1)

    def test_monthly_improvement_empty_when_no_projects(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        response = self.client.get(
            '/scores/monthly-improvement',
            params={'year': 2026, 'month': 4, 'dimension': 'team'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    def test_history_by_team_empty_when_no_projects(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        response = self.client.get('/scores/history-by-team')
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['granularity'], 'day')
        self.assertEqual(body['teams'], [])

    def test_history_by_team_returns_aggregated_series(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            return_value=[
                {'project_id': 'p1', 'dim_key': 'platform'},
                {'project_id': 'p2', 'dim_key': 'platform'},
                {'project_id': 'p3', 'dim_key': 'data'},
            ]
        )
        with (
            mock.patch(
                'imbi_api.endpoints.scoring.clickhouse.query',
                mock.AsyncMock(
                    return_value=[
                        {
                            'ts': '2026-04-01',
                            'project_id': 'p1',
                            'score': 80.0,
                        },
                        {
                            'ts': '2026-04-01',
                            'project_id': 'p2',
                            'score': 60.0,
                        },
                        {
                            'ts': '2026-04-01',
                            'project_id': 'p3',
                            'score': 90.0,
                        },
                    ]
                ),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.get('/scores/history-by-team')
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['granularity'], 'day')
        teams = {t['key']: t['points'] for t in body['teams']}
        self.assertIn('platform', teams)
        self.assertIn('data', teams)
        platform_score = teams['platform'][0]['score']
        self.assertAlmostEqual(platform_score, 70.0)
        self.assertAlmostEqual(teams['data'][0]['score'], 90.0)

    def test_history_by_team_hourly_with_date_filters(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            return_value=[{'project_id': 'p1', 'dim_key': 'eng'}]
        )
        with (
            mock.patch(
                'imbi_api.endpoints.scoring.clickhouse.query',
                mock.AsyncMock(return_value=[]),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.get(
                '/scores/history-by-team',
                params={
                    'granularity': 'hour',
                    'from': '2026-01-01T00:00:00',
                    'to': '2026-04-01T00:00:00',
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['granularity'], 'hour')
        self.assertEqual(body['teams'], [])

    def test_history_feed_empty_when_no_projects(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        response = self.client.get('/scores/history-feed')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    def test_history_feed_returns_events(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            return_value=[
                {
                    'project_id': 'p1',
                    'project_name': 'My Project',
                    'team_slug': 'platform',
                },
            ]
        )
        with (
            mock.patch(
                'imbi_api.endpoints.scoring.clickhouse.query',
                mock.AsyncMock(
                    return_value=[
                        {
                            'timestamp': '2026-04-01T12:00:00',
                            'project_id': 'p1',
                            'score': 85.0,
                            'previous_score': 75.0,
                            'change_reason': 'attribute_change',
                        }
                    ]
                ),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.get('/scores/history-feed')
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body), 1)
        event = body[0]
        self.assertEqual(event['project_id'], 'p1')
        self.assertEqual(event['project_name'], 'My Project')
        self.assertEqual(event['team_key'], 'platform')
        self.assertAlmostEqual(event['score'], 85.0)
        self.assertAlmostEqual(event['previous_score'], 75.0)
        self.assertEqual(event['change_reason'], 'attribute_change')

    def test_history_feed_with_date_filters_and_limit(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            return_value=[
                {
                    'project_id': 'p1',
                    'project_name': 'Proj',
                    'team_slug': 'eng',
                },
            ]
        )
        with (
            mock.patch(
                'imbi_api.endpoints.scoring.clickhouse.query',
                mock.AsyncMock(return_value=[]),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.get(
                '/scores/history-feed',
                params={
                    'from': '2026-01-01T00:00:00',
                    'to': '2026-04-01T00:00:00',
                    'limit': 50,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    def test_history_feed_handles_null_previous_score(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            return_value=[
                {
                    'project_id': 'p1',
                    'project_name': 'Proj',
                    'team_slug': 'eng',
                },
            ]
        )
        with (
            mock.patch(
                'imbi_api.endpoints.scoring.clickhouse.query',
                mock.AsyncMock(
                    return_value=[
                        {
                            'timestamp': '2026-04-01T12:00:00',
                            'project_id': 'p1',
                            'score': 70.0,
                            'previous_score': None,
                            'change_reason': 'initial',
                        }
                    ]
                ),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.get('/scores/history-feed')
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertIsNone(body[0]['previous_score'])
        self.assertEqual(body[0]['change_reason'], 'initial')
