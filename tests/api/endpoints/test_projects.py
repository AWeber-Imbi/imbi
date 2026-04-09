"""Tests for project CRUD endpoints."""

import datetime
import typing
import unittest
from unittest import mock

import psycopg.errors
from fastapi.testclient import TestClient
from imbi_common import graph

from imbi_api import app, models

PROJECT_ID = 'abc123nanoid'


class ProjectEndpointsTestCase(unittest.TestCase):
    """Test cases for project CRUD endpoints."""

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
                'project:create',
                'project:read',
                'project:write',
                'project:delete',
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

    def _project_data(self, **overrides: typing.Any) -> dict:
        """Return a default project record as returned by the
        graph."""
        data: dict[str, typing.Any] = {
            'id': PROJECT_ID,
            'name': 'My API',
            'slug': 'my-api',
            'description': 'An example API',
            'icon': None,
            'links': {},
            'identifiers': {},
            'created_at': '2026-03-17T12:00:00Z',
            'updated_at': '2026-03-17T12:00:00Z',
            'team': {
                'name': 'Platform',
                'slug': 'platform',
                'organization': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
            },
            'project_types': [
                {
                    'name': 'API Service',
                    'slug': 'api-service',
                    'organization': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                },
            ],
            'environments': [],
            'dependency_uris': [],
        }
        data.update(overrides)
        return data

    # -- Create --------------------------------------------------------

    def test_create_success(self) -> None:
        """Test successful project creation."""
        record = self._project_data()

        # Call 1: pre-validation query (type slugs exist)
        # Call 2: create query
        self.mock_db.execute.side_effect = [
            [{'pt_slug': 'api-service', 'found': True}],
            [
                {
                    'project': record,
                    'dependency_count': 0,
                },
            ],
        ]

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.projects.nanoid.generate',
                return_value=PROJECT_ID,
            ),
        ):
            mock_get_model.return_value = models.Project

            response = self.client.post(
                '/organizations/engineering/projects/',
                json={
                    'name': 'My API',
                    'slug': 'my-api',
                    'description': 'An example API',
                    'team_slug': 'platform',
                    'project_type_slugs': ['api-service'],
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'my-api')
        self.assertEqual(data['name'], 'My API')
        self.assertIn('relationships', data)

    def test_create_with_environments(self) -> None:
        """Test project creation with environment assignments."""
        record = self._project_data(
            environments=[
                {
                    'name': 'Production',
                    'slug': 'production',
                    'organization': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                },
            ],
        )

        self.mock_db.execute.side_effect = [
            # pt_slug validation
            [{'pt_slug': 'api-service', 'found': True}],
            # env_slug validation
            [
                {
                    'env_slug': 'production',
                    'found': True,
                },
            ],
            # create query
            [
                {
                    'project': record,
                    'dependency_count': 0,
                },
            ],
        ]

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.projects.nanoid.generate',
                return_value=PROJECT_ID,
            ),
        ):
            mock_get_model.return_value = models.Project

            response = self.client.post(
                '/organizations/engineering/projects/',
                json={
                    'name': 'My API',
                    'slug': 'my-api',
                    'team_slug': 'platform',
                    'project_type_slugs': ['api-service'],
                    'environments': {'production': None},
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(len(data['environments']), 1)

    def test_create_validation_error(self) -> None:
        """Test creating project with missing required fields."""
        with mock.patch(
            'imbi_common.blueprints.get_model',
        ) as mock_get_model:
            mock_get_model.return_value = models.Project

            response = self.client.post(
                '/organizations/engineering/projects/',
                json={},
            )

        self.assertEqual(response.status_code, 422)

    def test_create_org_not_found(self) -> None:
        """Test creating project when org/team/type not found."""
        self.mock_db.execute.side_effect = [
            # Pre-validation: no rows (org not found)
            [],
            # Create query: no rows
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
            mock.patch(
                'imbi_api.endpoints.projects.nanoid.generate',
                return_value=PROJECT_ID,
            ),
        ):
            mock_get_model.return_value = models.Project

            response = self.client.post(
                '/organizations/nonexistent/projects/',
                json={
                    'name': 'My API',
                    'slug': 'my-api',
                    'team_slug': 'platform',
                    'project_type_slugs': ['api-service'],
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_invalid_type_slugs(self) -> None:
        """Test creating project with invalid project type slugs."""
        self.mock_db.execute.side_effect = [
            # Pre-validation: type slug not found
            [{'pt_slug': 'nonexistent', 'found': False}],
        ]

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.projects.nanoid.generate',
                return_value=PROJECT_ID,
            ),
        ):
            mock_get_model.return_value = models.Project

            response = self.client.post(
                '/organizations/engineering/projects/',
                json={
                    'name': 'My API',
                    'slug': 'my-api',
                    'team_slug': 'platform',
                    'project_type_slugs': ['nonexistent'],
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn('not found', response.json()['detail'])

    def test_create_slug_conflict(self) -> None:
        """Test creating project with duplicate ID."""
        self.mock_db.execute.side_effect = [
            # Pre-validation: type slug exists
            [{'pt_slug': 'api-service', 'found': True}],
            # Create query: constraint error
            psycopg.errors.UniqueViolation(
                'Project already exists',
            ),
        ]

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.projects.nanoid.generate',
                return_value=PROJECT_ID,
            ),
        ):
            mock_get_model.return_value = models.Project

            response = self.client.post(
                '/organizations/engineering/projects/',
                json={
                    'name': 'My API',
                    'slug': 'my-api',
                    'team_slug': 'platform',
                    'project_type_slugs': ['api-service'],
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    # -- List ----------------------------------------------------------

    def test_list_success(self) -> None:
        """Test listing projects."""
        self.mock_db.execute.return_value = [
            {
                'project': self._project_data(),
                'dependency_count': 3,
            },
            {
                'project': self._project_data(
                    id='def456nanoid',
                    name='My Consumer',
                    slug='my-consumer',
                ),
                'dependency_count': 0,
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/projects/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['slug'], 'my-api')
        rels = data[0]['relationships']
        self.assertEqual(
            rels['dependencies']['count'],
            3,
        )

    # -- Get -----------------------------------------------------------

    def test_get_success(self) -> None:
        """Test retrieving a single project."""
        self.mock_db.execute.return_value = [
            {
                'project': self._project_data(),
                'dependency_count': 5,
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                f'/organizations/engineering/projects/{PROJECT_ID}',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'my-api')
        self.assertEqual(
            data['relationships']['dependencies']['count'],
            5,
        )

    def test_get_not_found(self) -> None:
        """Test retrieving nonexistent project."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/projects/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    # -- Update --------------------------------------------------------

    def test_update_success(self) -> None:
        """Test updating a project."""
        existing = self._project_data()
        updated = self._project_data(name='Updated API')

        self.mock_db.execute.side_effect = [
            # Fetch existing
            [
                {
                    'project': existing,
                    'current_team_slug': 'platform',
                    'current_type_slugs': ['api-service'],
                },
            ],
            # Update
            [
                {
                    'project': updated,
                    'dependency_count': 0,
                },
            ],
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
            mock_get_model.return_value = models.Project

            response = self.client.put(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json={'name': 'Updated API'},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'Updated API')
        self.assertIn('relationships', data)

    def test_update_with_team_change(self) -> None:
        """Test updating a project with team change."""
        existing = self._project_data()
        updated = self._project_data(
            team={
                'name': 'Backend',
                'slug': 'backend',
                'organization': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
            },
        )

        self.mock_db.execute.side_effect = [
            # Fetch existing project
            [
                {
                    'project': existing,
                    'current_team_slug': 'platform',
                    'current_type_slugs': ['api-service'],
                },
            ],
            # Team pre-validation
            [{'slug': 'backend'}],
            # Update query
            [
                {
                    'project': updated,
                    'dependency_count': 0,
                },
            ],
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
            mock_get_model.return_value = models.Project

            response = self.client.put(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json={'team_slug': 'backend'},
            )

        self.assertEqual(response.status_code, 200)

    def test_update_invalid_team(self) -> None:
        """Test updating a project with nonexistent team slug."""
        existing = self._project_data()

        self.mock_db.execute.side_effect = [
            # Fetch existing project
            [
                {
                    'project': existing,
                    'current_team_slug': 'platform',
                    'current_type_slugs': ['api-service'],
                },
            ],
            # Team pre-validation: not found
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
            mock_get_model.return_value = models.Project

            response = self.client.put(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json={'team_slug': 'nonexistent'},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn('not found', response.json()['detail'])

    def test_update_invalid_type_slugs(self) -> None:
        """Test updating project with invalid project type slugs."""
        existing = self._project_data()

        self.mock_db.execute.side_effect = [
            # Fetch existing project
            [
                {
                    'project': existing,
                    'current_team_slug': 'platform',
                    'current_type_slugs': ['api-service'],
                },
            ],
            # Type pre-validation: slug not found
            [{'pt_slug': 'nonexistent', 'found': False}],
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
            mock_get_model.return_value = models.Project

            response = self.client.put(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json={
                    'project_type_slugs': ['nonexistent'],
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn('not found', response.json()['detail'])

    def test_update_with_environment_change(self) -> None:
        """Test updating a project with environment change."""
        existing = self._project_data()
        updated = self._project_data(
            environments=[
                {
                    'name': 'Staging',
                    'slug': 'staging',
                    'organization': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                },
            ],
        )

        self.mock_db.execute.side_effect = [
            # fetch existing project
            [
                {
                    'project': existing,
                    'current_team_slug': 'platform',
                    'current_type_slugs': ['api-service'],
                },
            ],
            # env_slug validation
            [
                {
                    'env_slug': 'staging',
                    'found': True,
                },
            ],
            # update query
            [
                {
                    'project': updated,
                    'dependency_count': 0,
                },
            ],
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
            mock_get_model.return_value = models.Project

            response = self.client.put(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json={'environments': {'staging': None}},
            )

        self.assertEqual(response.status_code, 200)

    def test_update_not_found(self) -> None:
        """Test updating nonexistent project."""
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
            mock_get_model.return_value = models.Project

            response = self.client.put(
                '/organizations/engineering/projects/nonexistent',
                json={'name': 'Updated'},
            )

        self.assertEqual(response.status_code, 404)

    def test_update_slug_conflict(self) -> None:
        """Test updating project with conflicting slug."""
        existing = self._project_data()

        self.mock_db.execute.side_effect = [
            [
                {
                    'project': existing,
                    'current_team_slug': 'platform',
                    'current_type_slugs': ['api-service'],
                },
            ],
            psycopg.errors.UniqueViolation(
                'Project with slug "conflicting-slug" already'
                ' exists for project type "api-service"'
            ),
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
            mock_get_model.return_value = models.Project

            response = self.client.put(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json={'slug': 'conflicting-slug'},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    def test_update_concurrent_delete(self) -> None:
        """Test updating project deleted between fetch and
        update."""
        existing = self._project_data()

        self.mock_db.execute.side_effect = [
            [
                {
                    'project': existing,
                    'current_team_slug': 'platform',
                    'current_type_slugs': ['api-service'],
                },
            ],
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
            mock_get_model.return_value = models.Project

            response = self.client.put(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json={'name': 'Updated'},
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    # -- Delete --------------------------------------------------------

    def test_delete_success(self) -> None:
        """Test deleting a project."""
        self.mock_db.execute.return_value = [{'deleted': 1}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                f'/organizations/engineering/projects/{PROJECT_ID}',
            )

        self.assertEqual(response.status_code, 204)

    def test_delete_not_found(self) -> None:
        """Test deleting nonexistent project."""
        self.mock_db.execute.return_value = []

        response = self.client.delete(
            '/organizations/engineering/projects/nonexistent',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])
