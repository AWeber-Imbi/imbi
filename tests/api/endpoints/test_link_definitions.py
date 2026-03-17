"""Tests for link definition CRUD endpoints."""

import datetime
import typing
import unittest
from unittest import mock

from fastapi import testclient
from neo4j import exceptions

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

        self.client = testclient.TestClient(self.test_app)

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
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        data.update(overrides)
        return data

    # -- Create --------------------------------------------------------

    def test_create_success(self) -> None:
        """Test successful link definition creation."""
        record = self._link_def_data()

        with mock.patch(
            'imbi_common.neo4j.query',
            return_value=[{'link_definition': record}],
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

    def test_create_validation_error(self) -> None:
        """Test creating link definition with invalid data."""
        response = self.client.post(
            '/organizations/engineering/link-definitions/',
            json={},
        )

        self.assertEqual(response.status_code, 422)

    def test_create_org_not_found(self) -> None:
        """Test creating link definition when org does not exist."""
        with mock.patch(
            'imbi_common.neo4j.query',
            return_value=[],
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
        with mock.patch(
            'imbi_common.neo4j.query',
            side_effect=exceptions.ConstraintError(),
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
        records = [
            {'link_definition': self._link_def_data()},
            {
                'link_definition': self._link_def_data(
                    name='Grafana Dashboard',
                    slug='grafana',
                ),
            },
        ]

        with mock.patch(
            'imbi_common.neo4j.query',
            return_value=records,
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
        record = self._link_def_data()

        with mock.patch(
            'imbi_common.neo4j.query',
            return_value=[{'link_definition': record}],
        ):
            response = self.client.get(
                '/organizations/engineering/link-definitions/github-repo',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'github-repo')

    def test_get_not_found(self) -> None:
        """Test retrieving nonexistent link definition."""
        with mock.patch(
            'imbi_common.neo4j.query',
            return_value=[],
        ):
            response = self.client.get(
                '/organizations/engineering/link-definitions/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    # -- Update --------------------------------------------------------

    def test_update_success(self) -> None:
        """Test updating a link definition."""
        existing = self._link_def_data()
        updated = self._link_def_data(
            name='Updated GitHub Repo',
        )

        with mock.patch(
            'imbi_common.neo4j.query',
            side_effect=[
                [{'link_definition': existing}],
                [{'link_definition': updated}],
            ],
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
        with mock.patch(
            'imbi_common.neo4j.query',
            return_value=[],
        ):
            response = self.client.put(
                '/organizations/engineering/link-definitions/nonexistent',
                json={'name': 'Updated'},
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_update_slug_conflict(self) -> None:
        """Test updating link definition with conflicting slug."""
        existing = self._link_def_data()

        with mock.patch(
            'imbi_common.neo4j.query',
            side_effect=[
                [{'link_definition': existing}],
                exceptions.ConstraintError(),
            ],
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
        existing = self._link_def_data()

        with mock.patch(
            'imbi_common.neo4j.query',
            side_effect=[
                [{'link_definition': existing}],
                [],
            ],
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
        with mock.patch(
            'imbi_common.neo4j.query',
            return_value=[{'deleted': 1}],
        ):
            response = self.client.delete(
                '/organizations/engineering/link-definitions/github-repo',
            )

        self.assertEqual(response.status_code, 204)

    def test_delete_not_found(self) -> None:
        """Test deleting nonexistent link definition."""
        with mock.patch(
            'imbi_common.neo4j.query',
            return_value=[{'deleted': 0}],
        ):
            response = self.client.delete(
                '/organizations/engineering/link-definitions/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])
