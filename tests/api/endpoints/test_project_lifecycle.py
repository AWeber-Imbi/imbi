"""Tests for the project lifecycle push-sync endpoint."""

import datetime
from unittest import mock

from fastapi import testclient

from imbi.api import models
from imbi.api.auth import password, permissions
from imbi.api.plugins.lifecycle_dispatch import LifecycleInvocation
from imbi.common import graph
from tests.api import support


class ProjectLifecycleSyncEndpointTestCase(support.SharedAppTestCase):
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
            permissions={'project:write'},
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

    def test_sync_rolls_up_statuses(self) -> None:
        invocations = [
            LifecycleInvocation(
                integration_id='p1',
                plugin_slug='pagerduty-lifecycle',
                status='ok',
            ),
            LifecycleInvocation(
                integration_id='p2', plugin_slug='other', status='skipped'
            ),
            LifecycleInvocation(
                integration_id='p3',
                plugin_slug='broken',
                status='failed',
                message='boom',
            ),
        ]
        with mock.patch(
            'imbi.api.endpoints.project_lifecycle.dispatch_lifecycle',
            new=mock.AsyncMock(return_value=invocations),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.post(
                    '/organizations/myorg/projects/proj1/lifecycle/sync'
                )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['projects'], 1)
        self.assertEqual(data['synced'], 1)
        self.assertEqual(data['skipped'], 1)
        self.assertEqual(data['failed'], 1)
        self.assertEqual(len(data['errors']), 1)
        self.assertEqual(data['errors'][0]['project_id'], 'proj1')
        self.assertIn('broken', data['errors'][0]['detail'])

    def test_sync_no_plugins_returns_zero(self) -> None:
        with mock.patch(
            'imbi.api.endpoints.project_lifecycle.dispatch_lifecycle',
            new=mock.AsyncMock(return_value=[]),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.post(
                    '/organizations/myorg/projects/proj1/lifecycle/sync'
                )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['projects'], 1)
        self.assertEqual(data['synced'], 0)
        self.assertEqual(data['errors'], [])

    def test_sync_requires_write_permission(self) -> None:
        non_admin = models.User(
            email='dev@example.com',
            display_name='Dev',
            is_active=True,
            is_admin=False,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=non_admin,
            session_id='test-session',
            auth_method='jwt',
            permissions={'project:read'},
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/lifecycle/sync'
            )
        self.assertEqual(response.status_code, 403)
