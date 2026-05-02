"""Tests for scoring policy CRUD endpoints."""

from __future__ import annotations

import datetime
import typing
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from imbi_common import graph

from imbi_api import app, models
from imbi_api import scoring as scoring_di


class ScoringPolicyEndpointsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        from imbi_api.auth import permissions

        self.test_app = app.create_app()

        self.admin_user = models.User(
            email='admin@example.com',
            display_name='Admin',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.admin_user,
            session_id='s',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.mock_valkey = mock.AsyncMock()
        self.mock_valkey.set = mock.AsyncMock(return_value=True)
        self.mock_valkey.xadd = mock.AsyncMock(return_value=b'1-0')

        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )
        self.test_app.dependency_overrides[
            scoring_di._inject_optional_client
        ] = lambda: self.mock_valkey
        self.client = TestClient(self.test_app)

    def _policy_props(self, **kw: typing.Any) -> dict[str, typing.Any]:
        d = {
            'id': 'p1id',
            'name': 'Python Version',
            'slug': 'python-version',
            'category': 'attribute',
            'attribute_name': 'programming_language',
            'weight': 50,
            'enabled': True,
            'priority': 0,
            'description': None,
            'value_score_map': {'Python 3.12': 100, 'Python 2.7': 0},
            'range_score_map': None,
        }
        d.update(kw)
        return d

    def test_create_policy_success(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            side_effect=[
                [{'sp': self._policy_props()}],
                [{'sp': self._policy_props(), 'targets': []}],
                [],
            ]
        )
        # affected_projects -> blueprints.get_model + execute
        with mock.patch(
            'imbi_api.endpoints.scoring_policies.score_queue.'
            'affected_projects',
            mock.AsyncMock(return_value=['p1', 'p2']),
        ):
            response = self.client.post(
                '/scoring/policies/',
                json={
                    'name': 'Python Version',
                    'slug': 'python-version',
                    'attribute_name': 'programming_language',
                    'weight': 50,
                    'value_score_map': {
                        'Python 3.12': 100,
                        'Python 2.7': 0,
                    },
                },
            )
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertEqual(data['slug'], 'python-version')
        self.assertEqual(self.mock_valkey.xadd.await_count, 2)

    def test_get_policy_not_found(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        response = self.client.get('/scoring/policies/missing')
        self.assertEqual(response.status_code, 404)

    def test_get_policy_success(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            return_value=[{'sp': self._policy_props(), 'targets': ['svc']}]
        )
        response = self.client.get('/scoring/policies/python-version')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['slug'], 'python-version')

    def test_list_policies_filters(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            return_value=[{'sp': self._policy_props(), 'targets': []}]
        )
        response = self.client.get(
            '/scoring/policies/',
            params={
                'enabled': 'true',
                'attribute_name': 'programming_language',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        call = self.mock_db.execute.await_args
        params = call.args[1]
        self.assertEqual(params.get('enabled'), True)
        self.assertEqual(params.get('attribute_name'), 'programming_language')

    def test_update_policy_enqueues(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            side_effect=[
                [{'sp': self._policy_props(), 'targets': []}],
                [],
                [{'sp': self._policy_props(weight=80), 'targets': []}],
            ]
        )
        with mock.patch(
            'imbi_api.endpoints.scoring_policies.score_queue.'
            'affected_projects',
            mock.AsyncMock(return_value=['p1']),
        ):
            response = self.client.patch(
                '/scoring/policies/python-version',
                json=[{'op': 'replace', 'path': '/weight', 'value': 80}],
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertGreaterEqual(self.mock_valkey.xadd.await_count, 1)

    def test_delete_policy(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            side_effect=[
                [{'sp': self._policy_props(), 'targets': []}],
                [],
            ]
        )
        with mock.patch(
            'imbi_api.endpoints.scoring_policies.score_queue.'
            'affected_projects',
            mock.AsyncMock(return_value=['p1']),
        ):
            response = self.client.delete('/scoring/policies/python-version')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.mock_valkey.xadd.await_count, 1)

    def test_list_policies_with_category_filter(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            return_value=[{'sp': self._policy_props(), 'targets': []}]
        )
        response = self.client.get(
            '/scoring/policies/', params={'category': 'attribute'}
        )
        self.assertEqual(response.status_code, 200)
        call = self.mock_db.execute.await_args
        self.assertIn('category', call.args[1])

    def test_create_policy_with_targets(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            side_effect=[
                [{'sp': self._policy_props()}],
                [{'found': ['service']}],  # target validation
                [],  # link targets
                [{'sp': self._policy_props(), 'targets': ['service']}],
                [],
            ]
        )
        with (
            mock.patch(
                'imbi_api.endpoints.scoring_policies.score_queue.'
                'affected_projects',
                mock.AsyncMock(return_value=[]),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.post(
                '/scoring/policies/',
                json={
                    'name': 'Python Version',
                    'slug': 'python-version',
                    'attribute_name': 'programming_language',
                    'weight': 50,
                    'value_score_map': {'Python 3.12': 100},
                    'targets': ['service'],
                },
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['slug'], 'python-version')

    def test_create_policy_with_unknown_targets_returns_400(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            side_effect=[
                [{'sp': self._policy_props()}],
                [{'found': []}],  # target validation returns nothing found
            ]
        )
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/scoring/policies/',
                json={
                    'name': 'Python Version',
                    'slug': 'python-version',
                    'attribute_name': 'programming_language',
                    'weight': 50,
                    'value_score_map': {'Python 3.12': 100},
                    'targets': ['nonexistent-type'],
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Unknown project type', response.json()['detail'])

    def test_create_policy_conflict(self) -> None:
        import psycopg.errors

        self.mock_db.execute = mock.AsyncMock(
            side_effect=psycopg.errors.UniqueViolation()
        )
        response = self.client.post(
            '/scoring/policies/',
            json={
                'name': 'Python Version',
                'slug': 'python-version',
                'attribute_name': 'programming_language',
                'weight': 50,
                'value_score_map': {'Python 3.12': 100},
            },
        )
        self.assertEqual(response.status_code, 409)

    def test_update_policy_with_targets(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            side_effect=[
                [{'sp': self._policy_props(), 'targets': []}],  # load existing
                [],  # SET props
                [{'found': ['service']}],  # target validation (new)
                [],  # clear targets
                [],  # link new targets
                [
                    {'sp': self._policy_props(), 'targets': ['service']}
                ],  # reload
            ]
        )
        with (
            mock.patch(
                'imbi_api.endpoints.scoring_policies.score_queue.'
                'affected_projects',
                mock.AsyncMock(return_value=[]),
            ),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.patch(
                '/scoring/policies/python-version',
                json=[
                    {
                        'op': 'replace',
                        'path': '/targets',
                        'value': ['service'],
                    }
                ],
            )
        self.assertEqual(response.status_code, 200, response.text)

    def test_update_policy_with_unknown_targets_returns_400(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            side_effect=[
                [{'sp': self._policy_props(), 'targets': []}],  # load existing
                [],  # SET props
                [{'found': []}],  # target validation finds nothing
            ]
        )
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/scoring/policies/python-version',
                json=[
                    {
                        'op': 'replace',
                        'path': '/targets',
                        'value': ['ghost-type'],
                    }
                ],
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Unknown project type', response.json()['detail'])

    def test_update_policy_clear_targets(self) -> None:
        """PATCH with targets=[] clears all targets without validation."""
        self.mock_db.execute = mock.AsyncMock(
            side_effect=[
                [{'sp': self._policy_props(), 'targets': ['service']}],  # load
                [],  # SET props
                [],  # clear targets
                [{'sp': self._policy_props(), 'targets': []}],  # reload
            ]
        )
        with mock.patch(
            'imbi_api.endpoints.scoring_policies.score_queue.'
            'affected_projects',
            mock.AsyncMock(return_value=[]),
        ):
            response = self.client.patch(
                '/scoring/policies/python-version',
                json=[{'op': 'replace', 'path': '/targets', 'value': []}],
            )
        self.assertEqual(response.status_code, 200, response.text)

    def test_update_policy_not_found(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        response = self.client.patch(
            '/scoring/policies/missing',
            json=[{'op': 'replace', 'path': '/weight', 'value': 10}],
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_policy_not_found(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        response = self.client.delete('/scoring/policies/missing')
        self.assertEqual(response.status_code, 404)

    def test_parse_node_handles_invalid_json(self) -> None:
        """Coverage for _parse_node exception path."""
        from imbi_api.endpoints.scoring_policies import _parse_node

        raw = {
            'id': 'x',
            'name': 'test',
            'value_score_map': '{invalid json',
            'range_score_map': None,
        }
        result = _parse_node(raw)
        self.assertIsNone(result['value_score_map'])
