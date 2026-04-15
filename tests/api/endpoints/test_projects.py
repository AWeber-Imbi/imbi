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
                    'outbound_count': 0,
                    'inbound_count': 0,
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
                    'outbound_count': 0,
                    'inbound_count': 0,
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
                    'environments': {'production': {}},
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
                'outbound_count': 3,
                'inbound_count': 0,
            },
            {
                'project': self._project_data(
                    id='def456nanoid',
                    name='My Consumer',
                    slug='my-consumer',
                ),
                'outbound_count': 0,
                'inbound_count': 0,
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
        self.assertEqual(rels['outbound_count'], 3)
        self.assertEqual(rels['inbound_count'], 0)

    # -- Get -----------------------------------------------------------

    def test_get_success(self) -> None:
        """Test retrieving a single project."""
        self.mock_db.execute.return_value = [
            {
                'project': self._project_data(),
                'outbound_count': 5,
                'inbound_count': 2,
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
        self.assertEqual(data['relationships']['outbound_count'], 5)
        self.assertEqual(data['relationships']['inbound_count'], 2)

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
                    'outbound_count': 0,
                    'inbound_count': 0,
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
                    'outbound_count': 0,
                    'inbound_count': 0,
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
                    'outbound_count': 0,
                    'inbound_count': 0,
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
                json={'environments': {'staging': {}}},
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

    # -- Patch ---------------------------------------------------------

    def test_patch_project_name(self) -> None:
        """Test patching only the project name."""
        existing = self._project_data()
        updated = self._project_data(name='New Name')

        self.mock_db.execute.side_effect = [
            # fetch (get_project / _RETURN_FRAGMENT style)
            [
                {
                    'project': existing,
                    'outbound_count': 0,
                    'inbound_count': 0,
                },
            ],
            # team slug validation (always runs since team_slug is
            # populated from existing project)
            [{'slug': 'platform'}],
            # project type validation (always runs when types present)
            [{'pt_slug': 'api-service', 'found': True}],
            # SET update
            [
                {
                    'project': updated,
                    'outbound_count': 0,
                    'inbound_count': 0,
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

            response = self.client.patch(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json=[
                    {'op': 'replace', 'path': '/name', 'value': 'New Name'},
                ],
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'New Name')
        self.assertIn('relationships', data)

    def test_patch_project_not_found(self) -> None:
        """Test patching non-existent project returns 404."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/nonexistent',
                json=[
                    {'op': 'replace', 'path': '/name', 'value': 'X'},
                ],
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_patch_project_with_environments(self) -> None:
        """Test patching a project that has existing environments."""
        existing = self._project_data(
            environments=[
                {
                    'slug': 'staging',
                    'name': 'Staging',
                    'id': 'env-1',
                    'created_at': '2026-01-01T00:00:00Z',
                    'updated_at': '2026-01-01T00:00:00Z',
                }
            ]
        )
        updated = self._project_data(name='New Name')

        self.mock_db.execute.side_effect = [
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            [{'slug': 'platform'}],
            [{'pt_slug': 'api-service', 'found': True}],
            [{'env_slug': 'staging', 'found': True}],  # env slug validation
            [{'project': updated, 'outbound_count': 0, 'inbound_count': 0}],
        ]

        with (
            mock.patch('imbi_common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            mock_get_model.return_value = models.Project
            response = self.client.patch(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json=[{'op': 'replace', 'path': '/name', 'value': 'New Name'}],
            )

        self.assertEqual(response.status_code, 200)

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


class _RelationshipsTestBase(unittest.TestCase):
    """Shared setup for relationship endpoint tests."""

    _permissions: typing.ClassVar[set[str]] = set()

    def setUp(self) -> None:
        from imbi_api.auth import permissions

        self.test_app = app.create_app()

        self.test_user = models.User(
            email='user@example.com',
            display_name='Test User',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=self._permissions,
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

    def _url(self, pid: str = PROJECT_ID) -> str:
        return f'/organizations/engineering/projects/{pid}/relationships'

    def _summary(self, **overrides: typing.Any) -> dict:
        data = {
            'id': 'dep1',
            'name': 'Dep One',
            'slug': 'dep-one',
            'namespace': 'engineering',
            'project_type': 'api-service',
            'project_type_icon': 'aws-lambda',
        }
        data.update(overrides)
        return data


class ProjectRelationshipsEndpointTestCase(_RelationshipsTestBase):
    """Tests for GET /projects/{id}/relationships."""

    _permissions: typing.ClassVar[set[str]] = {'project:read'}

    def test_empty(self) -> None:
        """Returns an empty list when the project has no edges."""
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [{'direction': None, 'other': None}],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                f'/organizations/engineering/projects/{PROJECT_ID}'
                '/relationships'
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'relationships': []})

    def test_mixed_directions(self) -> None:
        """Returns inbound and outbound rows, inbound sorted first."""
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {
                    'direction': 'inbound',
                    'other': self._summary(id='in1', name='Inbound A'),
                },
                {
                    'direction': 'inbound',
                    'other': self._summary(id='in2', name='Inbound B'),
                },
                {
                    'direction': 'outbound',
                    'other': self._summary(id='out1', name='Outbound A'),
                },
            ],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                f'/organizations/engineering/projects/{PROJECT_ID}'
                '/relationships'
            )

        self.assertEqual(response.status_code, 200)
        rels = response.json()['relationships']
        self.assertEqual(len(rels), 3)
        self.assertEqual(rels[0]['direction'], 'inbound')
        self.assertEqual(rels[0]['project']['id'], 'in1')
        self.assertEqual(rels[1]['direction'], 'inbound')
        self.assertEqual(rels[1]['project']['id'], 'in2')
        self.assertEqual(rels[2]['direction'], 'outbound')
        self.assertEqual(rels[2]['project']['id'], 'out1')
        for entry in rels:
            self.assertEqual(entry['type'], 'depends_on')
            self.assertEqual(entry['project']['project_type'], 'api-service')
            self.assertEqual(entry['project']['namespace'], 'engineering')

        self.assertEqual(
            rels[0]['project']['project_type_icon'],
            'aws-lambda',
        )

    def test_not_found(self) -> None:
        """Returns 404 when the project does not exist."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/projects/missing/relationships'
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_order_by_has_stable_tiebreaker(self) -> None:
        """ORDER BY must include a unique tie-breaker after other.name so
        sibling projects that share a name across namespaces sort
        deterministically across repeated requests.
        """
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [{'direction': None, 'other': None}],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                f'/organizations/engineering/projects/{PROJECT_ID}'
                '/relationships'
            )

        self.assertEqual(response.status_code, 200)
        # Fetch query is the second call (first is exists check)
        query = self.mock_db.execute.call_args_list[1].args[0]
        normalized = ' '.join(query.split())
        self.assertIn(
            'ORDER BY CASE direction',
            normalized,
            'expected relationships query to sort by direction first',
        )
        self.assertIn(
            'other.name, other.id',
            normalized,
            'expected other.id tie-breaker after other.name in ORDER BY '
            'so ordering is stable when multiple related projects share a '
            'name across namespaces',
        )


class SetProjectRelationshipsTestCase(_RelationshipsTestBase):
    """Tests for PUT /projects/{id}/relationships."""

    _permissions: typing.ClassVar[set[str]] = {'project:write'}

    def test_set_depends_on(self) -> None:
        """Replaces outbound edges and returns updated list."""
        # exists, validate, mutate (delete+create), fetch
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [{'tid': 'target1', 'found': True}],
            [],
            [
                {
                    'direction': 'outbound',
                    'other': self._summary(id='target1', name='Target One'),
                },
            ],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                self._url(),
                json={'depends_on': ['target1']},
            )

        self.assertEqual(response.status_code, 200)
        rels = response.json()['relationships']
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0]['direction'], 'outbound')
        self.assertEqual(rels[0]['project']['id'], 'target1')
        self.assertEqual(rels[0]['type'], 'depends_on')

    def test_clear_depends_on(self) -> None:
        """Empty list removes all outbound edges."""
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [],
            [{'direction': None, 'other': None}],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                self._url(),
                json={'depends_on': []},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'relationships': []})

    def test_project_not_found(self) -> None:
        """Returns 404 when source project does not exist."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                self._url('missing'),
                json={'depends_on': ['target1']},
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_target_not_found(self) -> None:
        """Returns 422 when a target project ID does not exist."""
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {'tid': 'good', 'found': True},
                {'tid': 'bad', 'found': False},
            ],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                self._url(),
                json={'depends_on': ['good', 'bad']},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn('bad', response.json()['detail'])

    def test_self_reference_ignored(self) -> None:
        """Self-references are silently dropped."""
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [],
            [{'direction': None, 'other': None}],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                self._url(),
                json={'depends_on': [PROJECT_ID]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'relationships': []})

    def test_duplicates_deduplicated(self) -> None:
        """Duplicate IDs in depends_on are collapsed."""
        # exists, validate, mutate (delete+create), fetch
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [{'tid': 'dup', 'found': True}],
            [],
            [
                {
                    'direction': 'outbound',
                    'other': self._summary(id='dup', name='Dup'),
                },
            ],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                self._url(),
                json={'depends_on': ['dup', 'dup', 'dup']},
            )

        self.assertEqual(response.status_code, 200)
        # Validate only unique targets were sent to the DB
        validate_call = self.mock_db.execute.call_args_list[1]
        validate_params = validate_call.args[1]
        self.assertEqual(validate_params['target_ids'], ['dup'])
