"""Tests for link definition CRUD endpoints."""

import datetime
import typing
import unittest
from unittest import mock

import psycopg.errors
from fastapi.testclient import TestClient
from imbi_common import graph

from imbi_api import app, models


class LinkDefinitionEndpointsTestCase(unittest.TestCase):
    """Test cases for link definition CRUD endpoints."""

    def setUp(self) -> None:
        """Set up test app with admin authentication."""
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
                'link_definition:create',
                'link_definition:read',
                'link_definition:write',
                'link_definition:delete',
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

    def _link_def_data(self, **overrides: typing.Any) -> dict:
        """Return a default link definition record."""
        data: dict[str, typing.Any] = {
            'name': 'GitHub Repository',
            'slug': 'github-repo',
            'description': 'Link to GitHub repo',
            'icon': 'https://github.com/favicon.ico',
            'url_template': 'https://github.com/{org}/{repo}',
            'created_at': '2026-03-17T12:00:00Z',
            'updated_at': '2026-03-17T12:00:00Z',
        }
        data.update(overrides)
        return data

    def _org_data(self) -> dict:
        """Return a default organization record."""
        return {
            'name': 'Engineering',
            'slug': 'engineering',
        }

    # -- Create --------------------------------------------------------

    def test_create_success(self) -> None:
        """Test successful link definition creation."""
        self.mock_db.execute.return_value = [
            {
                'ld': self._link_def_data(),
                'o': self._org_data(),
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/organizations/engineering/link-definitions/',
                json={
                    'name': 'GitHub Repository',
                    'slug': 'github-repo',
                    'description': 'Link to GitHub repo',
                    'url_template': ('https://github.com/{org}/{repo}'),
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'github-repo')
        self.assertEqual(data['name'], 'GitHub Repository')
        self.assertIn('relationships', data)
        self.assertEqual(
            data['relationships']['projects']['count'],
            0,
        )

    def test_create_validation_error(self) -> None:
        """Test creating link definition with invalid data."""
        response = self.client.post(
            '/organizations/engineering/link-definitions/',
            json={},
        )

        self.assertEqual(response.status_code, 422)

    def test_create_org_not_found(self) -> None:
        """Test creating link definition when org does not exist."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/organizations/nonexistent/link-definitions/',
                json={
                    'name': 'GitHub Repository',
                    'slug': 'github-repo',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_slug_conflict(self) -> None:
        """Test creating link definition with duplicate slug."""
        self.mock_db.execute.side_effect = psycopg.errors.UniqueViolation()

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/organizations/engineering/link-definitions/',
                json={
                    'name': 'GitHub Repository',
                    'slug': 'github-repo',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    # -- List ----------------------------------------------------------

    def test_list_success(self) -> None:
        """Test listing link definitions."""
        self.mock_db.execute.return_value = [
            {
                'ld': self._link_def_data(),
                'o': self._org_data(),
                'project_count': 5,
            },
            {
                'ld': self._link_def_data(
                    name='Grafana Dashboard',
                    slug='grafana',
                ),
                'o': self._org_data(),
                'project_count': 0,
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/link-definitions/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['slug'], 'github-repo')

    # -- Get -----------------------------------------------------------

    def test_get_success(self) -> None:
        """Test retrieving a single link definition."""
        self.mock_db.execute.return_value = [
            {
                'ld': self._link_def_data(),
                'o': self._org_data(),
                'project_count': 3,
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/link-definitions/github-repo',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'github-repo')
        self.assertIn('relationships', data)
        self.assertEqual(data['relationships']['projects']['count'], 3)

    def test_get_not_found(self) -> None:
        """Test retrieving nonexistent link definition."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/link-definitions/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    # -- Update --------------------------------------------------------

    def test_update_success(self) -> None:
        """Test updating a link definition."""
        fetch_records = [
            {
                'ld': self._link_def_data(),
                'o': self._org_data(),
            },
        ]
        update_records = [
            {
                'ld': self._link_def_data(
                    name='Updated GitHub Repo',
                ),
                'o': self._org_data(),
                'project_count': 2,
            },
        ]
        self.mock_db.execute.side_effect = [
            fetch_records,
            update_records,
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                '/organizations/engineering/link-definitions/github-repo',
                json={'name': 'Updated GitHub Repo'},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'Updated GitHub Repo')

    def test_update_not_found(self) -> None:
        """Test updating nonexistent link definition."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                '/organizations/engineering/link-definitions/nonexistent',
                json={'name': 'Updated'},
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_update_slug_conflict(self) -> None:
        """Test updating link definition with conflicting slug."""
        fetch_records = [
            {
                'ld': self._link_def_data(),
                'o': self._org_data(),
            },
        ]
        self.mock_db.execute.side_effect = [
            fetch_records,
            psycopg.errors.UniqueViolation(),
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                '/organizations/engineering/link-definitions/github-repo',
                json={
                    'name': 'GitHub Repository',
                    'slug': 'existing-slug',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    def test_update_concurrent_delete(self) -> None:
        """Test updating link definition deleted between
        fetch and update."""
        fetch_records = [
            {
                'ld': self._link_def_data(),
                'o': self._org_data(),
            },
        ]
        self.mock_db.execute.side_effect = [
            fetch_records,
            [],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                '/organizations/engineering/link-definitions/github-repo',
                json={'name': 'Updated'},
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    # -- Delete --------------------------------------------------------

    def test_delete_success(self) -> None:
        """Test deleting a link definition."""
        self.mock_db.execute.return_value = [{'ld': True}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                '/organizations/engineering/link-definitions/github-repo',
            )

        self.assertEqual(response.status_code, 204)

    def test_delete_not_found(self) -> None:
        """Test deleting nonexistent link definition."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                '/organizations/engineering/link-definitions/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])
