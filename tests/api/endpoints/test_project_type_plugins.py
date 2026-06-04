"""Tests for project-type plugin assignment endpoints."""

import datetime
import json
from unittest import mock

from fastapi import testclient
from imbi_common import graph

from imbi_api import models
from imbi_api.auth import password, permissions
from tests import support


class ProjectTypePluginsEndpointTestCase(support.SharedAppTestCase):
    def setUp(self) -> None:
        self.test_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={'project_type:read', 'project_type:update'},
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

    def test_list_empty(self) -> None:
        self.mock_db.execute.return_value = []
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/project-types/web/plugins/'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_with_results(self) -> None:
        self.mock_db.execute.return_value = [
            {
                'plugin': {
                    'id': 'p1',
                    'plugin_slug': 'ssm',
                    'label': 'SSM',
                    'options': '{}',
                    'api_version': 1,
                },
                'edge': {
                    'plugin_type': 'configuration',
                    'default': True,
                    'options': '{}',
                },
            }
        ]
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/project-types/web/plugins/'
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data[0]['plugin_id'], 'p1')
        self.assertEqual(data[0]['source'], 'project_type')

    def test_replace_validation_error(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.put(
                '/organizations/myorg/project-types/web/plugins/',
                json=[
                    {
                        'plugin_id': 'p1',
                        'plugin_type': 'configuration',
                        'default': False,
                        'options': {},
                    }
                ],
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('default', response.json()['detail'])

    def test_replace_creates_assignments(self) -> None:
        plugin_record = {
            'plugin': {
                'id': 'p1',
                'plugin_slug': 'ssm',
                'label': 'SSM',
                'options': '{}',
                'api_version': 1,
            },
            'edge': {
                'plugin_type': 'configuration',
                'default': True,
                'options': '{}',
            },
        }
        self.mock_db.execute.side_effect = [
            [{'found': '1'}],  # validate plugin_ids
            [],  # fused delete + UNWIND create
            [plugin_record],  # final list call
        ]
        with testclient.TestClient(self.test_app) as client:
            response = client.put(
                '/organizations/myorg/project-types/web/plugins/',
                json=[
                    {
                        'plugin_id': 'p1',
                        'plugin_type': 'configuration',
                        'default': True,
                        'options': {},
                    }
                ],
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data[0]['plugin_id'], 'p1')

    def test_from_record_with_string_edge(self) -> None:
        # Covers the parse_agtype path for an edge that is a JSON string.
        from imbi_api.endpoints.project_type_plugins import _from_record

        rec = {
            'plugin': json.dumps(
                {
                    'id': 'p1',
                    'plugin_slug': 'ssm',
                    'label': 'SSM',
                }
            ),
            'edge': json.dumps(
                {
                    'plugin_type': 'configuration',
                    'default': True,
                    'options': '{}',
                }
            ),
        }
        resp = _from_record(rec, 'project_type')
        self.assertEqual(resp.plugin_id, 'p1')
