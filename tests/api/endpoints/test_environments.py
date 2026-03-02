"""Tests for environment CRUD endpoints."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from neo4j import exceptions

from imbi_api import app, models


class EnvironmentEndpointsTestCase(unittest.TestCase):
    """Test cases for environment CRUD endpoints."""

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
                'environment:create',
                'environment:read',
                'environment:update',
                'environment:delete',
            },
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.client = testclient.TestClient(self.test_app)

    def _mock_neo4j_run(self, data=None):
        """Create a mock for neo4j.run returning data."""
        mock_result = mock.AsyncMock()
        if data is not None:
            mock_result.data.return_value = [
                {'environment': data},
            ]
        else:
            mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None
        return mock_result

    def test_create_environment_success(self) -> None:
        """Test successful environment creation."""
        env_data = {
            'name': 'Production',
            'slug': 'production',
            'description': 'Production environment',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        mock_result = self._mock_neo4j_run(env_data)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=mock_result,
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.post(
                '/environments/',
                json={
                    'name': 'Production',
                    'slug': 'production',
                    'description': 'Production environment',
                    'organization_slug': 'engineering',
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'production')
        self.assertEqual(data['name'], 'Production')

    def test_create_environment_missing_org_slug(self) -> None:
        """Test creating environment without organization_slug."""
        response = self.client.post(
            '/environments/',
            json={
                'name': 'Production',
                'slug': 'production',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'organization_slug',
            response.json()['detail'],
        )

    def test_create_environment_org_not_found(self) -> None:
        """Test creating environment with nonexistent org."""
        mock_result = self._mock_neo4j_run(None)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=mock_result,
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.post(
                '/environments/',
                json={
                    'name': 'Production',
                    'slug': 'production',
                    'organization_slug': 'nonexistent',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_environment_validation_error(self) -> None:
        """Test creating environment with invalid data."""
        with mock.patch(
            'imbi_common.blueprints.get_model',
        ) as mock_get_model:
            mock_get_model.return_value = models.Environment

            response = self.client.post(
                '/environments/',
                json={
                    'organization_slug': 'engineering',
                    # Missing required 'name' and 'slug'
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'Validation error',
            response.json()['detail'],
        )

    def test_create_environment_slug_conflict(self) -> None:
        """Test creating environment with duplicate slug."""
        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=exceptions.ConstraintError(),
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.post(
                '/environments/',
                json={
                    'name': 'Production',
                    'slug': 'production',
                    'organization_slug': 'engineering',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_list_environments(self) -> None:
        """Test listing all environments."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'environment': {
                    'name': 'Production',
                    'slug': 'production',
                    'organization': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                },
            },
            {
                'environment': {
                    'name': 'Staging',
                    'slug': 'staging',
                    'organization': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                },
            },
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.get('/environments/')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['slug'], 'production')

    def test_get_environment(self) -> None:
        """Test retrieving a single environment."""
        env_data = {
            'name': 'Production',
            'slug': 'production',
            'description': 'Production environment',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        mock_result = self._mock_neo4j_run(env_data)

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.get(
                '/environments/production',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'production')
        self.assertEqual(data['name'], 'Production')

    def test_get_environment_not_found(self) -> None:
        """Test retrieving nonexistent environment."""
        mock_result = self._mock_neo4j_run(None)

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.get(
                '/environments/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_update_environment(self) -> None:
        """Test updating an environment."""
        existing_data = {
            'name': 'Production',
            'slug': 'production',
            'description': 'Production environment',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        updated_data = {
            'name': 'Production US',
            'slug': 'production',
            'description': 'Updated description',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        fetch_result = self._mock_neo4j_run(existing_data)
        update_result = self._mock_neo4j_run(updated_data)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[fetch_result, update_result],
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.put(
                '/environments/production',
                json={
                    'name': 'Production US',
                    'slug': 'production',
                    'description': 'Updated description',
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'Production US')

    def test_update_environment_not_found(self) -> None:
        """Test updating nonexistent environment."""
        mock_run = self._mock_neo4j_run(None)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=mock_run,
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.put(
                '/environments/nonexistent',
                json={
                    'name': 'Test',
                    'slug': 'nonexistent',
                },
            )

        self.assertEqual(response.status_code, 404)

    def test_update_environment_validation_error(self) -> None:
        """Test updating environment with invalid data."""
        existing_data = {
            'name': 'Production',
            'slug': 'production',
            'description': 'Production environment',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        mock_run = self._mock_neo4j_run(existing_data)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=mock_run,
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.put(
                '/environments/production',
                json={'name': 123},
            )

        self.assertEqual(response.status_code, 400)

    def test_update_environment_slug_conflict(self) -> None:
        """Test updating environment with conflicting slug."""
        existing_data = {
            'name': 'Production',
            'slug': 'production',
            'description': 'Production environment',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        fetch_result = self._mock_neo4j_run(existing_data)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[
                    fetch_result,
                    exceptions.ConstraintError(),
                ],
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.put(
                '/environments/production',
                json={
                    'name': 'Production',
                    'slug': 'existing-slug',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_update_environment_concurrent_delete(self) -> None:
        """Test updating environment deleted between fetch and update."""
        existing_data = {
            'name': 'Production',
            'slug': 'production',
            'description': 'Production environment',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        fetch_result = self._mock_neo4j_run(existing_data)
        empty_result = self._mock_neo4j_run(None)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[fetch_result, empty_result],
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.put(
                '/environments/production',
                json={
                    'name': 'Production Updated',
                    'slug': 'production',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_delete_environment(self) -> None:
        """Test deleting an environment."""
        with mock.patch(
            'imbi_common.neo4j.delete_node',
        ) as mock_delete:
            mock_delete.return_value = True

            response = self.client.delete(
                '/environments/production',
            )

        self.assertEqual(response.status_code, 204)
        mock_delete.assert_called_once_with(
            models.Environment,
            {'slug': 'production'},
        )

    def test_delete_environment_not_found(self) -> None:
        """Test deleting nonexistent environment."""
        with mock.patch(
            'imbi_common.neo4j.delete_node',
        ) as mock_delete:
            mock_delete.return_value = False

            response = self.client.delete(
                '/environments/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])
