"""Tests for project type CRUD endpoints."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from neo4j import exceptions

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

        self.client = testclient.TestClient(self.test_app)

    def _mock_neo4j_run(self, data=None):
        """Create a mock for neo4j.run returning data."""
        mock_result = mock.AsyncMock()
        if data is not None:
            mock_result.data.return_value = [
                {'project_type': data},
            ]
        else:
            mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None
        return mock_result

    def _mock_neo4j_run_with_count(
        self,
        data=None,
        project_count=0,
    ):
        """Create a mock for neo4j.run with count."""
        mock_result = mock.AsyncMock()
        if data is not None:
            mock_result.data.return_value = [
                {
                    'project_type': data,
                    'project_count': project_count,
                },
            ]
        else:
            mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None
        return mock_result

    def test_create_project_type_success(self) -> None:
        """Test successful project type creation."""
        pt_data = {
            'name': 'API Service',
            'slug': 'api-service',
            'description': 'REST API service',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        mock_result = self._mock_neo4j_run(pt_data)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=mock_result,
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
        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=exceptions.ConstraintError(),
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
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'project_type': {
                    'name': 'API Service',
                    'slug': 'api-service',
                    'organization': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                },
                'project_count': 15,
            },
            {
                'project_type': {
                    'name': 'Consumer',
                    'slug': 'consumer',
                    'organization': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                },
                'project_count': 8,
            },
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
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
        pt_data = {
            'name': 'API Service',
            'slug': 'api-service',
            'description': 'REST API service',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        mock_result = self._mock_neo4j_run_with_count(
            pt_data,
            project_count=42,
        )

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
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
        mock_result = self._mock_neo4j_run_with_count(None)

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.get(
                '/organizations/engineering/project-types/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_update_project_type(self) -> None:
        """Test updating a project type."""
        existing_data = {
            'name': 'API Service',
            'slug': 'api-service',
            'description': 'REST API service',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        updated_data = {
            'name': 'REST API Service',
            'slug': 'api-service',
            'description': 'Updated description',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        fetch_result = self._mock_neo4j_run(existing_data)
        update_result = self._mock_neo4j_run_with_count(
            updated_data,
            project_count=5,
        )

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[fetch_result, update_result],
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
        existing_data = {
            'name': 'API Service',
            'slug': 'api-service',
            'description': 'REST API service',
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
            mock_get_model.return_value = models.ProjectType

            response = self.client.put(
                '/organizations/engineering/project-types/api-service',
                json={'name': 123},
            )

        self.assertEqual(response.status_code, 400)

    def test_update_project_type_slug_conflict(self) -> None:
        """Test updating project type with conflicting slug."""
        existing_data = {
            'name': 'API Service',
            'slug': 'api-service',
            'description': 'REST API service',
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
        existing_data = {
            'name': 'API Service',
            'slug': 'api-service',
            'description': 'REST API service',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        fetch_result = self._mock_neo4j_run(existing_data)
        empty_result = self._mock_neo4j_run_with_count(None)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[fetch_result, empty_result],
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
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'deleted': 1}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.delete(
                '/organizations/engineering/project-types/api-service',
            )

        self.assertEqual(response.status_code, 204)

    def test_delete_project_type_not_found(self) -> None:
        """Test deleting nonexistent project type."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'deleted': 0}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.delete(
                '/organizations/engineering/project-types/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])
