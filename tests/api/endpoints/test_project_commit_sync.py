"""Tests for the on-demand commit/tag-sync endpoints."""

import datetime
from unittest import mock

import fastapi
from fastapi import testclient

from imbi.api import models
from imbi.api.auth import password, permissions
from imbi.api.commit_sync import service
from imbi.api.endpoints import project_commit_sync
from imbi.common import graph
from tests.api import support

_BASE = '/organizations/octo/projects/p1/commits'


class CommitSyncEndpointTestCase(support.SharedAppTestCase):
    def setUp(self) -> None:
        self.user = models.User(
            email='dev@example.com',
            display_name='Dev',
            is_active=True,
            is_admin=False,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth = permissions.AuthContext(
            user=self.user,
            session_id='s',
            auth_method='jwt',
            permissions={
                'project:commits:write',
                'project:deployment:read',
            },
        )

        async def _user() -> permissions.AuthContext:
            return self.auth

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            _user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )
        from imbi.api import scoring

        self.test_app.dependency_overrides[scoring._inject_optional_client] = (
            lambda: mock.AsyncMock()
        )
        # No ``with``: instantiating the client without the context
        # manager skips app lifespan startup (no DB/Valkey connections),
        # matching the rest of the endpoint suite.
        self.client = testclient.TestClient(self.test_app)

    def test_sync_enqueues(self) -> None:
        with (
            mock.patch.object(
                project_commit_sync, 'resolve_capability', mock.AsyncMock()
            ),
            mock.patch.object(service, 'check_available', mock.AsyncMock()),
            mock.patch.object(
                project_commit_sync,
                'enqueue_commit_sync',
                mock.AsyncMock(return_value=True),
            ),
            mock.patch.object(service, 'set_status', mock.AsyncMock()) as ss,
        ):
            response = self.client.post(f'{_BASE}/sync')
        self.assertEqual(202, response.status_code)
        self.assertTrue(response.json()['enqueued'])
        self.assertEqual('queued', ss.await_args.kwargs['status'])

    def test_sync_debounced_skips_status(self) -> None:
        with (
            mock.patch.object(
                project_commit_sync, 'resolve_capability', mock.AsyncMock()
            ),
            mock.patch.object(service, 'check_available', mock.AsyncMock()),
            mock.patch.object(
                project_commit_sync,
                'enqueue_commit_sync',
                mock.AsyncMock(return_value=False),
            ),
            mock.patch.object(service, 'set_status', mock.AsyncMock()) as ss,
        ):
            response = self.client.post(f'{_BASE}/sync')
        self.assertEqual(202, response.status_code)
        self.assertFalse(response.json()['enqueued'])
        ss.assert_not_awaited()

    def test_sync_no_commit_sync_plugin_returns_400(self) -> None:
        with (
            mock.patch.object(
                project_commit_sync, 'resolve_capability', mock.AsyncMock()
            ),
            mock.patch.object(
                service,
                'check_available',
                mock.AsyncMock(
                    side_effect=service.CommitSyncUnavailable('nope')
                ),
            ),
        ):
            response = self.client.post(f'{_BASE}/sync')
        self.assertEqual(400, response.status_code)

    def test_sync_no_deployment_plugin_returns_404(self) -> None:
        with mock.patch.object(
            project_commit_sync,
            'resolve_capability',
            mock.AsyncMock(side_effect=fastapi.HTTPException(status_code=404)),
        ):
            response = self.client.post(f'{_BASE}/sync')
        self.assertEqual(404, response.status_code)

    def test_get_status(self) -> None:
        status = service.CommitSyncStatus(
            status='success', commits_synced=10, tags_synced=2
        )
        with mock.patch.object(
            service, 'read_status', mock.AsyncMock(return_value=status)
        ):
            response = self.client.get(f'{_BASE}/sync-status')
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual('success', data['status'])
        self.assertEqual(10, data['commits_synced'])
