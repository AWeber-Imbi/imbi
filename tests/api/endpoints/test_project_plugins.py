"""Tests for project plugin assignment endpoints."""

import datetime
import json
from unittest import mock

from fastapi import testclient
from imbi_common import graph

from imbi_api import models
from imbi_api.auth import password, permissions
from tests import support


class ProjectPluginsEndpointTestCase(support.SharedAppTestCase):
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
            permissions={'project:read', 'project:write'},
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

    def test_get_project_plugins_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/plugins/'
            )
        self.assertEqual(response.status_code, 404)

    def test_get_project_plugins_merged_view(self) -> None:
        plugin_a = {
            'id': 'pa',
            'plugin_slug': 'ssm',
            'label': 'PT default',
            'options': '{}',
            'api_version': 1,
        }
        plugin_b = {
            'id': 'pb',
            'plugin_slug': 'logzio',
            'label': 'Project log override',
            'options': '{}',
            'api_version': 1,
        }
        self.mock_db.execute.return_value = [
            {
                'pt_rows': json.dumps(
                    [
                        {
                            'plugin': plugin_a,
                            'edge': {
                                'tab': 'configuration',
                                'default': True,
                                'options': '{}',
                            },
                            'src': 'project_type',
                        }
                    ]
                ),
                'proj_rows': json.dumps(
                    [
                        {
                            'plugin': plugin_b,
                            'edge': {
                                'tab': 'logs',
                                'default': True,
                                'options': '{}',
                            },
                            'src': 'project',
                        }
                    ]
                ),
            }
        ]
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/plugins/'
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        ids = {r['plugin_id']: r for r in data}
        self.assertEqual(ids['pa']['source'], 'project_type')
        self.assertEqual(ids['pb']['source'], 'project')

    def test_replace_project_plugins_validation_error(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.put(
                '/organizations/myorg/projects/proj1/plugins/',
                json=[
                    {
                        'plugin_id': 'p1',
                        'tab': 'configuration',
                        'default': True,
                        'options': {},
                    },
                    {
                        'plugin_id': 'p2',
                        'tab': 'configuration',
                        'default': True,
                        'options': {},
                    },
                ],
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('default', response.json()['detail'])

    def test_replace_project_plugins_empty_list_ok(self) -> None:
        # No assignments == clear all. Skips validation, runs delete only.
        self.mock_db.execute.side_effect = [
            [{'deleted': '0'}],  # delete query
            [
                {  # the post-mutation get_project_plugins read
                    'pt_rows': '[]',
                    'proj_rows': '[]',
                }
            ],
        ]
        with testclient.TestClient(self.test_app) as client:
            response = client.put(
                '/organizations/myorg/projects/proj1/plugins/',
                json=[],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_replace_project_plugins_creates_each(self) -> None:
        plugin_raw = {
            'id': 'p1',
            'plugin_slug': 'ssm',
            'label': 'SSM',
            'options': '{}',
            'api_version': 1,
        }
        # validate plugin_ids + fused delete+create + final read
        self.mock_db.execute.side_effect = [
            [{'found': '1'}],  # validate
            [],  # fused delete + UNWIND create
            [
                {
                    'pt_rows': '[]',
                    'proj_rows': json.dumps(
                        [
                            {
                                'plugin': plugin_raw,
                                'edge': {
                                    'tab': 'configuration',
                                    'default': True,
                                    'options': '{}',
                                },
                                'src': 'project',
                            }
                        ]
                    ),
                }
            ],
        ]
        with testclient.TestClient(self.test_app) as client:
            response = client.put(
                '/organizations/myorg/projects/proj1/plugins/',
                json=[
                    {
                        'plugin_id': 'p1',
                        'tab': 'configuration',
                        'default': True,
                        'options': {},
                    }
                ],
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['plugin_id'], 'p1')
