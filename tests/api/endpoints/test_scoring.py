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
