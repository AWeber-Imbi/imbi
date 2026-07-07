"""Tests for the project-level Integration assignment endpoints."""

import datetime
import typing
from unittest import mock

from fastapi import testclient
from imbi_common import graph

from imbi_api import models
from imbi_api.auth import password, permissions
from tests import support


def _inode(enabled: bool = True, **over: typing.Any) -> dict[str, object]:
    """An Integration node as returned by the ``RETURN i`` agtype column."""
    node: dict[str, typing.Any] = {
        'id': 'int-1',
        'slug': 'logzio-prod',
        'plugin': 'logzio',
        'name': 'Logz.io Prod',
        'options': {},
        'capabilities': {'logs': {'enabled': enabled, 'options': {}}},
        'links': {},
        'identifiers': {},
        'encrypted_credentials': {},
    }
    node.update(over)
    return node


_LISTED = {
    'integration_slug': 'logzio-prod',
    'edge': {
        'capability': 'logs',
        'default': True,
        'options': {},
        'env_payloads': {},
    },
}


class ProjectIntegrationsEndpointTestCase(support.SharedAppTestCase):
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
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )
        self.client = testclient.TestClient(self.test_app)

    def test_list_project_integrations(self) -> None:
        self.mock_db.execute.return_value = [_LISTED]
        response = self.client.get(
            '/organizations/myorg/projects/proj1/integrations/'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['integration_slug'], 'logzio-prod')
        self.assertEqual(data[0]['capability'], 'logs')

    def test_list_project_integrations_with_identity(self) -> None:
        record = {
            'integration_slug': 'logzio-prod',
            'edge': {
                'capability': 'logs',
                'default': False,
                'options': {},
                'env_payloads': {},
                'identity_integration_id': 'id-2',
            },
        }
        self.mock_db.execute.side_effect = [
            [record],
            [{'slug': 'ident-int'}],
        ]
        response = self.client.get(
            '/organizations/myorg/projects/proj1/integrations/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()[0]['identity_integration_slug'], 'ident-int'
        )

    def test_replace_project_integrations(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'org_slug': 'myorg'}],  # _project_org_slug
            [],  # existing USES edges
            [{'i': _inode(enabled=True)}],  # org integrations by slug
            [_LISTED],  # final re-list
        ]
        with mock.patch(
            'imbi_api.endpoints.project_integrations'
            '.replace_capability_assignments',
            new=mock.AsyncMock(),
        ) as patched:
            response = self.client.put(
                '/organizations/myorg/projects/proj1/integrations/',
                json={
                    'assignments': [
                        {
                            'integration_slug': 'logzio-prod',
                            'capability': 'logs',
                            'default': True,
                        }
                    ]
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['integration_slug'], 'logzio-prod')
        patched.assert_awaited_once()

    def test_replace_project_integrations_project_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.put(
            '/organizations/myorg/projects/missing/integrations/',
            json={
                'assignments': [
                    {'integration_slug': 'logzio-prod', 'capability': 'logs'}
                ]
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_replace_project_integrations_unknown_slug(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'org_slug': 'myorg'}],  # _project_org_slug
            [],  # existing USES edges
            [],  # org integrations by slug -> none resolved
        ]
        response = self.client.put(
            '/organizations/myorg/projects/proj1/integrations/',
            json={
                'assignments': [
                    {'integration_slug': 'logzio-prod', 'capability': 'logs'}
                ]
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn('Unknown integration', response.json()['detail'])

    def test_replace_project_integrations_capability_not_enabled(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'org_slug': 'myorg'}],  # _project_org_slug
            [],  # existing USES edges
            [{'i': _inode(enabled=False)}],  # capability disabled
        ]
        response = self.client.put(
            '/organizations/myorg/projects/proj1/integrations/',
            json={
                'assignments': [
                    {'integration_slug': 'logzio-prod', 'capability': 'logs'}
                ]
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('does not have capability', response.json()['detail'])
