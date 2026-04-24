"""Tests for tag CRUD endpoints."""

import datetime
import typing
import unittest
from unittest import mock

import psycopg.errors
from fastapi.testclient import TestClient
from imbi_common import graph

from imbi_api import app, models


class TagEndpointsTestCase(unittest.TestCase):
    """Test cases for tag CRUD endpoints."""

    def setUp(self) -> None:
        from imbi_api.auth import permissions

        self.test_app = app.create_app()

        self.admin_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.admin_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={
                'tag:create',
                'tag:read',
                'tag:write',
                'tag:delete',
            },
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = TestClient(self.test_app)

    def _tag_data(self, **overrides: typing.Any) -> dict:
        data: dict[str, typing.Any] = {
            'id': 'tag-123',
            'name': 'Runbook',
            'slug': 'runbook',
            'description': None,
            'created_at': '2026-03-17T12:00:00Z',
            'updated_at': '2026-03-17T12:00:00Z',
        }
        data.update(overrides)
        return data

    def _org_data(self) -> dict:
        return {'name': 'Engineering', 'slug': 'engineering'}

    # -- Create --------------------------------------------------------

    def test_create_success(self) -> None:
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/tags/',
                json={'name': 'Runbook'},
            )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['slug'], 'runbook')
        self.assertEqual(body['relationships']['notes']['count'], 0)

    def test_create_auto_slugifies_from_name(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(name='Post Mortem', slug='post-mortem'),
                'o': self._org_data(),
            }
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/tags/',
                json={'name': 'Post Mortem'},
            )
        self.assertEqual(response.status_code, 201)
        # second positional arg of .execute call contains the params dict
        _, args, _ = self.mock_db.execute.mock_calls[0]
        self.assertEqual(args[1]['slug'], 'post-mortem')

    def test_create_slug_conflict(self) -> None:
        self.mock_db.execute.side_effect = psycopg.errors.UniqueViolation()
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/tags/',
                json={'name': 'Runbook', 'slug': 'runbook'},
            )
        self.assertEqual(response.status_code, 409)

    def test_create_org_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/ghost/tags/',
                json={'name': 'Runbook'},
            )
        self.assertEqual(response.status_code, 404)

    # -- List ----------------------------------------------------------

    def test_list_success(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(),
                'o': self._org_data(),
                'note_count': 4,
            },
            {
                't': self._tag_data(name='Alert', slug='alert'),
                'o': self._org_data(),
                'note_count': 0,
            },
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get('/organizations/engineering/tags/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['relationships']['notes']['count'], 4)

    # -- Get -----------------------------------------------------------

    def test_get_success(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(),
                'o': self._org_data(),
                'note_count': 2,
            }
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/tags/runbook'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['relationships']['notes']['count'], 2)

    def test_get_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/tags/missing'
            )
        self.assertEqual(response.status_code, 404)

    # -- Patch ---------------------------------------------------------

    def test_patch_rename(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'t': self._tag_data(), 'o': self._org_data()}],
            [
                {
                    't': self._tag_data(name='Runbooks'),
                    'o': self._org_data(),
                    'note_count': 3,
                }
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/name', 'value': 'Runbooks'}],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'Runbooks')

    def test_patch_slug_conflict(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'t': self._tag_data(), 'o': self._org_data()}],
            psycopg.errors.UniqueViolation(),
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/slug', 'value': 'alert'}],
            )
        self.assertEqual(response.status_code, 409)

    def test_patch_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.patch(
            '/organizations/engineering/tags/missing',
            json=[{'op': 'replace', 'path': '/name', 'value': 'X'}],
        )
        self.assertEqual(response.status_code, 404)

    def test_patch_readonly_path_rejected(self) -> None:
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/id', 'value': 'xxx'}],
            )
        self.assertEqual(response.status_code, 400)

    # -- Delete --------------------------------------------------------

    def test_delete_success(self) -> None:
        self.mock_db.execute.return_value = [{'t': True}]
        response = self.client.delete(
            '/organizations/engineering/tags/runbook'
        )
        self.assertEqual(response.status_code, 204)

    def test_delete_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.delete(
            '/organizations/engineering/tags/missing'
        )
        self.assertEqual(response.status_code, 404)

    def test_patch_validation_error(self) -> None:
        """Patching /name to non-string triggers a 400 validation error."""
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/name', 'value': 123}],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_concurrent_delete_returns_404(self) -> None:
        """Update returning no rows after fetch yields 404."""
        self.mock_db.execute.side_effect = [
            [{'t': self._tag_data(), 'o': self._org_data()}],
            [],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/name', 'value': 'Runbooks'}],
            )
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    unittest.main()
