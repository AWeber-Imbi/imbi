"""Tests for environment CRUD endpoints."""

import datetime
import unittest
from unittest import mock

import psycopg.errors
from fastapi import testclient
from imbi_common import graph

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

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

    def test_create_environment_success(self) -> None:
        """Test successful environment creation."""
        self.mock_db.execute.return_value = [
            {
                'e': {
                    'name': 'Production',
                    'slug': 'production',
                    'description': 'Production environment',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
            }
        ]

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.post(
                '/organizations/engineering/environments/',
                json={
                    'name': 'Production',
                    'slug': 'production',
                    'description': 'Production environment',
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'production')
        self.assertEqual(data['name'], 'Production')
        self.assertIn('relationships', data)
        rels = data['relationships']
        self.assertEqual(
            rels['projects']['count'],
            0,
        )

    def test_create_environment_org_not_found_in_url(self) -> None:
        """Test creating environment with nonexistent org in URL."""
        self.mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.post(
                '/organizations/nonexistent/environments/',
                json={
                    'name': 'Production',
                    'slug': 'production',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_environment_org_not_found(self) -> None:
        """Test creating environment with nonexistent org."""
        self.mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.post(
                '/organizations/nonexistent/environments/',
                json={
                    'name': 'Production',
                    'slug': 'production',
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
                '/organizations/engineering/environments/',
                json={},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'Validation error',
            response.json()['detail'],
        )

    def test_create_environment_slug_conflict(self) -> None:
        """Test creating environment with duplicate slug."""
        self.mock_db.execute.side_effect = psycopg.errors.UniqueViolation()

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.post(
                '/organizations/engineering/environments/',
                json={
                    'name': 'Production',
                    'slug': 'production',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    def test_list_environments(self) -> None:
        """Test listing all environments with relationships."""
        self.mock_db.execute.return_value = [
            {
                'e': {
                    'name': 'Production',
                    'slug': 'production',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
                'project_count': 20,
            },
            {
                'e': {
                    'name': 'Staging',
                    'slug': 'staging',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
                'project_count': 15,
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/environments/'
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['slug'], 'production')
        rels = data[0]['relationships']
        self.assertEqual(
            rels['projects']['count'],
            20,
        )

    def test_get_environment(self) -> None:
        """Test retrieving a single environment."""
        self.mock_db.execute.return_value = [
            {
                'e': {
                    'name': 'Production',
                    'slug': 'production',
                    'description': 'Production environment',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
                'project_count': 30,
            }
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/environments/production',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'production')
        self.assertEqual(data['name'], 'Production')
        rels = data['relationships']
        self.assertEqual(
            rels['projects']['count'],
            30,
        )

    def test_get_environment_not_found(self) -> None:
        """Test retrieving nonexistent environment."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/environments/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_update_environment(self) -> None:
        """Test updating an environment."""
        fetch_records = [
            {
                'e': {
                    'name': 'Production',
                    'slug': 'production',
                    'description': 'Production environment',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
            }
        ]
        update_records = [
            {
                'e': {
                    'name': 'Production US',
                    'slug': 'production',
                    'description': 'Updated description',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
                'project_count': 10,
            }
        ]
        self.mock_db.execute.side_effect = [
            fetch_records,
            update_records,
        ]

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.put(
                '/organizations/engineering/environments/production',
                json={
                    'name': 'Production US',
                    'slug': 'production',
                    'description': 'Updated description',
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'Production US')
        self.assertIn('relationships', data)

    def test_update_environment_not_found(self) -> None:
        """Test updating nonexistent environment."""
        self.mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.put(
                '/organizations/engineering/environments/nonexistent',
                json={
                    'name': 'Test',
                    'slug': 'nonexistent',
                },
            )

        self.assertEqual(response.status_code, 404)

    def test_update_environment_validation_error(self) -> None:
        """Test updating environment with invalid data."""
        fetch_records = [
            {
                'e': {
                    'name': 'Production',
                    'slug': 'production',
                    'description': 'Production environment',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
            }
        ]
        self.mock_db.execute.return_value = fetch_records

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.put(
                '/organizations/engineering/environments/production',
                json={'name': 123},
            )

        self.assertEqual(response.status_code, 400)

    def test_update_environment_slug_conflict(self) -> None:
        """Test updating environment with conflicting slug."""
        fetch_records = [
            {
                'e': {
                    'name': 'Production',
                    'slug': 'production',
                    'description': 'Production environment',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
            }
        ]
        self.mock_db.execute.side_effect = [
            fetch_records,
            psycopg.errors.UniqueViolation(),
        ]

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.put(
                '/organizations/engineering/environments/production',
                json={
                    'name': 'Production',
                    'slug': 'existing-slug',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    def test_update_environment_concurrent_delete(self) -> None:
        """Test updating environment deleted between fetch
        and update."""
        fetch_records = [
            {
                'e': {
                    'name': 'Production',
                    'slug': 'production',
                    'description': 'Production environment',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
            }
        ]
        self.mock_db.execute.side_effect = [
            fetch_records,
            [],
        ]

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_get_model.return_value = models.Environment

            response = self.client.put(
                '/organizations/engineering/environments/production',
                json={
                    'name': 'Production Updated',
                    'slug': 'production',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_delete_environment(self) -> None:
        """Test deleting an environment."""
        self.mock_db.execute.return_value = [{'e': True}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                '/organizations/engineering/environments/production',
            )

        self.assertEqual(response.status_code, 204)

    def test_delete_environment_not_found(self) -> None:
        """Test deleting nonexistent environment."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                '/organizations/engineering/environments/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])
