"""Tests for organization CRUD endpoints."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from neo4j import exceptions

from imbi_api import app, models


class OrganizationEndpointsTestCase(unittest.TestCase):
    """Test cases for organization CRUD endpoints."""

    def setUp(self) -> None:
        """Set up test app with admin authentication context."""
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
                'organization:create',
                'organization:read',
                'organization:update',
                'organization:delete',
            },
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.client = testclient.TestClient(self.test_app)

        self.test_org = models.Organization(
            name='Engineering',
            slug='engineering',
            description='Engineering organization',
        )

    def test_create_organization_success(self) -> None:
        """Test successful organization creation."""
        with mock.patch(
            'imbi_common.neo4j.create_node',
        ) as mock_create:
            mock_create.return_value = self.test_org

            response = self.client.post(
                '/organizations/',
                json={
                    'name': 'Engineering',
                    'slug': 'engineering',
                    'description': 'Engineering organization',
                },
            )

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertEqual(data['slug'], 'engineering')
            self.assertEqual(data['name'], 'Engineering')

    def test_create_organization_validation_error(self) -> None:
        """Test creating organization with invalid data."""
        response = self.client.post(
            '/organizations/',
            json={
                'name': 'Engineering',
                # Missing required 'slug' field
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_create_organization_duplicate_slug(self) -> None:
        """Test creating organization with duplicate slug."""
        with mock.patch(
            'imbi_common.neo4j.create_node',
        ) as mock_create:
            mock_create.side_effect = exceptions.ConstraintError(
                'Duplicate',
            )

            response = self.client.post(
                '/organizations/',
                json={
                    'name': 'Engineering',
                    'slug': 'engineering',
                    'description': 'Engineering organization',
                },
            )

            self.assertEqual(response.status_code, 409)
            self.assertIn(
                'already exists',
                response.json()['detail'],
            )

    def test_list_organizations(self) -> None:
        """Test listing all organizations."""

        async def mock_fetch_nodes(*args, **kwargs):
            yield self.test_org

        with mock.patch(
            'imbi_common.neo4j.fetch_nodes',
            new=mock_fetch_nodes,
        ):
            response = self.client.get('/organizations/')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['slug'], 'engineering')

    def test_get_organization(self) -> None:
        """Test retrieving single organization."""
        with mock.patch(
            'imbi_common.neo4j.fetch_node',
        ) as mock_fetch:
            mock_fetch.return_value = self.test_org

            response = self.client.get(
                '/organizations/engineering',
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['slug'], 'engineering')
            self.assertEqual(data['name'], 'Engineering')

    def test_get_organization_not_found(self) -> None:
        """Test retrieving non-existent organization."""
        with mock.patch(
            'imbi_common.neo4j.fetch_node',
        ) as mock_fetch:
            mock_fetch.return_value = None

            response = self.client.get(
                '/organizations/nonexistent',
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not found',
                response.json()['detail'],
            )

    def test_update_organization(self) -> None:
        """Test updating organization."""
        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
            ) as mock_fetch,
            mock.patch(
                'imbi_common.neo4j.upsert',
            ) as mock_upsert,
        ):
            mock_fetch.return_value = self.test_org

            response = self.client.put(
                '/organizations/engineering',
                json={
                    'name': 'Engineering Department',
                    'slug': 'engineering',
                    'description': 'Updated description',
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(
                data['name'],
                'Engineering Department',
            )
            mock_upsert.assert_called_once()

    def test_update_organization_slug_rename(self) -> None:
        """Test updating with different slug renames it."""
        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
            ) as mock_fetch,
            mock.patch(
                'imbi_common.neo4j.upsert',
            ) as mock_upsert,
        ):
            mock_fetch.return_value = self.test_org

            response = self.client.put(
                '/organizations/engineering',
                json={
                    'name': 'Engineering',
                    'slug': 'new-slug',
                    'description': 'Test',
                },
            )

            self.assertEqual(response.status_code, 200)
            mock_upsert.assert_called_once()
            self.assertEqual(
                mock_upsert.call_args[0][1],
                {'slug': 'engineering'},
            )

    def test_update_organization_slug_conflict(self) -> None:
        """Test slug rename conflict returns 409."""
        with (
            mock.patch(
                'imbi_common.neo4j.fetch_node',
            ) as mock_fetch,
            mock.patch(
                'imbi_common.neo4j.upsert',
            ) as mock_upsert,
        ):
            mock_fetch.return_value = self.test_org
            mock_upsert.side_effect = exceptions.ConstraintError(
                'Duplicate',
            )

            response = self.client.put(
                '/organizations/engineering',
                json={
                    'name': 'Engineering',
                    'slug': 'existing-slug',
                    'description': 'Test',
                },
            )

            self.assertEqual(response.status_code, 409)
            self.assertIn(
                'already exists',
                response.json()['detail'],
            )

    def test_update_organization_not_found(self) -> None:
        """Test updating non-existent organization."""
        with mock.patch(
            'imbi_common.neo4j.fetch_node',
        ) as mock_fetch:
            mock_fetch.return_value = None

            response = self.client.put(
                '/organizations/nonexistent',
                json={
                    'name': 'Test',
                    'slug': 'nonexistent',
                    'description': 'Test',
                },
            )

            self.assertEqual(response.status_code, 404)

    def test_delete_organization(self) -> None:
        """Test deleting organization."""
        with mock.patch(
            'imbi_common.neo4j.delete_node',
        ) as mock_delete:
            mock_delete.return_value = True

            response = self.client.delete(
                '/organizations/engineering',
            )

            self.assertEqual(response.status_code, 204)
            mock_delete.assert_called_once_with(
                models.Organization,
                {'slug': 'engineering'},
            )

    def test_delete_organization_not_found(self) -> None:
        """Test deleting non-existent organization."""
        with mock.patch(
            'imbi_common.neo4j.delete_node',
        ) as mock_delete:
            mock_delete.return_value = False

            response = self.client.delete(
                '/organizations/nonexistent',
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn(
                'not found',
                response.json()['detail'],
            )
