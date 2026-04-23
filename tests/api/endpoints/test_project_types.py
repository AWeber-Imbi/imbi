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

    def test_patch_project_type_name(self) -> None:
        """Test patching only the project type name."""
        from imbi_common import models as common_models

        existing_pt = {
            'name': 'Service',
            'slug': 'service',
            'description': None,
        }
        self.mock_db.execute.side_effect = [
            [
                {
                    'pt': existing_pt,
                    'o': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                }
            ],
            [
                {
                    'pt': {
                        'name': 'Microservice',
                        'slug': 'service',
                    },
                    'o': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                    'project_count': 10,
                }
            ],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            with mock.patch(
                'imbi_common.blueprints.get_model',
                return_value=common_models.ProjectType,
            ):
                response = self.client.patch(
                    '/organizations/engineering/project-types/service',
                    json=[
                        {
                            'op': 'replace',
                            'path': '/name',
                            'value': 'Microservice',
                        }
                    ],
                )

        self.assertEqual(response.status_code, 200)

    def test_patch_project_type_not_found(self) -> None:
        """Test patching non-existent project type returns 404."""
        from imbi_common import models as common_models

        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.blueprints.get_model',
            return_value=common_models.ProjectType,
        ):
            response = self.client.patch(
                '/organizations/engineering/project-types/nonexistent',
                json=[
                    {
                        'op': 'replace',
                        'path': '/name',
                        'value': 'X',
                    }
                ],
            )

        self.assertEqual(response.status_code, 404)

    def test_patch_project_type_slug_conflict(self) -> None:
        """Renaming slug to an existing value returns 409."""
        from imbi_common import models as common_models

        existing = {'name': 'API Service', 'slug': 'api-service'}
        self.mock_db.execute.side_effect = [
            [
                {
                    'pt': existing,
                    'o': {'name': 'Engineering', 'slug': 'engineering'},
                },
            ],
            psycopg.errors.UniqueViolation(),
        ]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi_common.blueprints.get_model',
                return_value=common_models.ProjectType,
            ),
        ):
            response = self.client.patch(
                '/organizations/engineering/project-types/api-service',
                json=[{'op': 'replace', 'path': '/slug', 'value': 'taken'}],
            )

        self.assertEqual(response.status_code, 409)

    def test_patch_project_type_concurrent_delete(self) -> None:
        """Update returning no rows yields 404."""
        from imbi_common import models as common_models

        existing = {'name': 'API Service', 'slug': 'api-service'}
        self.mock_db.execute.side_effect = [
            [
                {
                    'pt': existing,
                    'o': {'name': 'Engineering', 'slug': 'engineering'},
                },
            ],
            [],
        ]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi_common.blueprints.get_model',
                return_value=common_models.ProjectType,
            ),
        ):
            response = self.client.patch(
                '/organizations/engineering/project-types/api-service',
                json=[{'op': 'replace', 'path': '/name', 'value': 'New'}],
            )

        self.assertEqual(response.status_code, 404)
