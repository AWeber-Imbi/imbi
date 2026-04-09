"""Tests for project type CRUD endpoints."""

import datetime
import unittest
from unittest import mock

import psycopg.errors
from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models


class ProjectTypeEndpointsTestCase(unittest.TestCase):
    """Test cases for project type CRUD endpoints."""

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
                'project_type:create',
                'project_type:read',
                'project_type:update',
                'project_type:delete',
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

    def test_create_project_type_success(self) -> None:
        """Test successful project type creation."""
        self.mock_db.execute.return_value = [
            {
                'pt': {
                    'name': 'API Service',
                    'slug': 'api-service',
                    'description': 'REST API service',
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
            mock_get_model.return_value = models.ProjectType

            response = self.client.post(
                '/organizations/engineering/project-types/',
                json={
                    'name': 'API Service',
                    'slug': 'api-service',
                    'description': 'REST API service',
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'api-service')
        self.assertEqual(data['name'], 'API Service')
        self.assertIn('relationships', data)
        rels = data['relationships']
        self.assertEqual(
            rels['projects']['count'],
            0,
        )

    def test_create_project_type_org_not_found_in_url(self) -> None:
        """Test creating project type with nonexistent org in URL."""
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
            mock_get_model.return_value = models.ProjectType

            response = self.client.post(
                '/organizations/nonexistent/project-types/',
                json={
                    'name': 'API Service',
                    'slug': 'api-service',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_project_type_org_not_found(self) -> None:
        """Test creating project type with nonexistent org."""
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
            mock_get_model.return_value = models.ProjectType

            response = self.client.post(
                '/organizations/nonexistent/project-types/',
                json={
                    'name': 'API Service',
                    'slug': 'api-service',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_project_type_validation_error(self) -> None:
        """Test creating project type with invalid data."""
        with mock.patch(
            'imbi_common.blueprints.get_model',
        ) as mock_get_model:
            mock_get_model.return_value = models.ProjectType

            response = self.client.post(
                '/organizations/engineering/project-types/',
                json={},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'Validation error',
            response.json()['detail'],
        )

    def test_create_project_type_slug_conflict(self) -> None:
        """Test creating project type with duplicate slug."""
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
            mock_get_model.return_value = models.ProjectType

            response = self.client.post(
                '/organizations/engineering/project-types/',
                json={
                    'name': 'API Service',
                    'slug': 'api-service',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    def test_list_project_types(self) -> None:
        """Test listing all project types with relationships."""
        self.mock_db.execute.return_value = [
            {
                'pt': {
                    'name': 'API Service',
                    'slug': 'api-service',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
                'project_count': 15,
            },
            {
                'pt': {
                    'name': 'Consumer',
                    'slug': 'consumer',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
                'project_count': 8,
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/project-types/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['slug'], 'api-service')
        rels = data[0]['relationships']
        self.assertEqual(
            rels['projects']['count'],
            15,
        )
        self.assertEqual(
            data[1]['relationships']['projects']['count'],
            8,
        )

    def test_get_project_type(self) -> None:
        """Test retrieving a single project type."""
        self.mock_db.execute.return_value = [
            {
                'pt': {
                    'name': 'API Service',
                    'slug': 'api-service',
                    'description': 'REST API service',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
                'project_count': 42,
            }
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/project-types/api-service',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'api-service')
        self.assertEqual(data['name'], 'API Service')
        rels = data['relationships']
        self.assertEqual(
            rels['projects']['count'],
            42,
        )

    def test_get_project_type_not_found(self) -> None:
        """Test retrieving nonexistent project type."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/project-types/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_update_project_type(self) -> None:
        """Test updating a project type."""
        fetch_records = [
            {
                'pt': {
                    'name': 'API Service',
                    'slug': 'api-service',
                    'description': 'REST API service',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
            }
        ]
        update_records = [
            {
                'pt': {
                    'name': 'REST API Service',
                    'slug': 'api-service',
                    'description': 'Updated description',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
                'project_count': 5,
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
            mock_get_model.return_value = models.ProjectType

            response = self.client.put(
                '/organizations/engineering/project-types/api-service',
                json={
                    'name': 'REST API Service',
                    'slug': 'api-service',
                    'description': 'Updated description',
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'REST API Service')
        self.assertIn('relationships', data)

    def test_update_project_type_not_found(self) -> None:
        """Test updating nonexistent project type."""
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
            mock_get_model.return_value = models.ProjectType

            response = self.client.put(
                '/organizations/engineering/project-types/nonexistent',
                json={
                    'name': 'Test',
                    'slug': 'nonexistent',
                },
            )

        self.assertEqual(response.status_code, 404)

    def test_update_project_type_validation_error(self) -> None:
        """Test updating project type with invalid data."""
        fetch_records = [
            {
                'pt': {
                    'name': 'API Service',
                    'slug': 'api-service',
                    'description': 'REST API service',
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
            mock_get_model.return_value = models.ProjectType

            response = self.client.put(
                '/organizations/engineering/project-types/api-service',
                json={'name': 123},
            )

        self.assertEqual(response.status_code, 400)

    def test_update_project_type_slug_conflict(self) -> None:
        """Test updating project type with conflicting slug."""
        fetch_records = [
            {
                'pt': {
                    'name': 'API Service',
                    'slug': 'api-service',
                    'description': 'REST API service',
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
            mock_get_model.return_value = models.ProjectType

            response = self.client.put(
                '/organizations/engineering/project-types/api-service',
                json={
                    'name': 'API Service',
                    'slug': 'existing-slug',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    def test_update_project_type_concurrent_delete(self) -> None:
        """Test updating project type deleted between fetch
        and update."""
        fetch_records = [
            {
                'pt': {
                    'name': 'API Service',
                    'slug': 'api-service',
                    'description': 'REST API service',
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
            mock_get_model.return_value = models.ProjectType

            response = self.client.put(
                '/organizations/engineering/project-types/api-service',
                json={
                    'name': 'API Service Updated',
                    'slug': 'api-service',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_delete_project_type(self) -> None:
        """Test deleting a project type."""
        self.mock_db.execute.return_value = [{'pt': True}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                '/organizations/engineering/project-types/api-service',
            )

        self.assertEqual(response.status_code, 204)

    def test_delete_project_type_not_found(self) -> None:
        """Test deleting nonexistent project type."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                '/organizations/engineering/project-types/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])
