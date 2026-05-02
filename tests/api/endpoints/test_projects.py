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

    def test_patch_project_team_change(self) -> None:
        """Patch a project to change its team."""
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
            # fetch existing
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            # team_slug validation
            [{'slug': 'backend'}],
            # project type validation
            [{'pt_slug': 'api-service', 'found': True}],
            # SET update
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
                json=[
                    {
                        'op': 'replace',
                        'path': '/team_slug',
                        'value': 'backend',
                    },
                ],
            )

        self.assertEqual(response.status_code, 200)

    def test_patch_project_invalid_team(self) -> None:
        """Patch with a non-existent team slug returns 422."""
        existing = self._project_data()

        self.mock_db.execute.side_effect = [
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            # team_slug validation: not found
            [],
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
                json=[
                    {
                        'op': 'replace',
                        'path': '/team_slug',
                        'value': 'nonexistent',
                    },
                ],
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn('not found', response.json()['detail'])

    def test_patch_project_invalid_type_slugs(self) -> None:
        """Patch with invalid project type slugs returns 422."""
        existing = self._project_data()

        self.mock_db.execute.side_effect = [
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            # team_slug validation
            [{'slug': 'platform'}],
            # project type validation: slug not found
            [{'pt_slug': 'nonexistent', 'found': False}],
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
                json=[
                    {
                        'op': 'replace',
                        'path': '/project_type_slugs',
                        'value': ['nonexistent'],
                    },
                ],
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn('not found', response.json()['detail'])

    def test_patch_project_slug_conflict(self) -> None:
        """Patch that triggers slug conflict returns 409."""
        existing = self._project_data()

        self.mock_db.execute.side_effect = [
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            [{'slug': 'platform'}],
            [{'pt_slug': 'api-service', 'found': True}],
            psycopg.errors.UniqueViolation(
                'Project with slug "conflicting-slug" already exists'
            ),
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
                json=[
                    {
                        'op': 'replace',
                        'path': '/slug',
                        'value': 'conflicting-slug',
                    },
                ],
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_patch_project_concurrent_delete(self) -> None:
        """Patch when update query returns empty returns 404."""
        existing = self._project_data()

        self.mock_db.execute.side_effect = [
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            [{'slug': 'platform'}],
            [{'pt_slug': 'api-service', 'found': True}],
            [],  # update returns no rows
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
                json=[
                    {'op': 'replace', 'path': '/name', 'value': 'Updated'},
                ],
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


class CreateProjectRelationshipTestCase(_RelationshipsTestBase):
    """Tests for POST /projects/{id}/relationships/{target_id}."""

    _permissions: typing.ClassVar[set[str]] = {'project:write'}

    def _target_url(self, target_id: str, pid: str = PROJECT_ID) -> str:
        return (
            f'/organizations/engineering/projects/{pid}'
            f'/relationships/{target_id}'
        )

    def test_create_edge(self) -> None:
        """Creates a DEPENDS_ON edge and returns 204."""
        self.mock_db.execute.return_value = [{'source_id': PROJECT_ID}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(self._target_url('target1'))

        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.mock_db.execute.call_count, 1)
        query = self.mock_db.execute.call_args.args[0]
        self.assertIn('MERGE', query)
        self.assertIn('DEPENDS_ON', query)

    def test_create_is_idempotent(self) -> None:
        """MERGE makes repeated calls safe; still returns 204."""
        self.mock_db.execute.return_value = [{'source_id': PROJECT_ID}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            first = self.client.post(self._target_url('target1'))
            second = self.client.post(self._target_url('target1'))

        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 204)
        self.assertEqual(self.mock_db.execute.call_count, 2)
        for call in self.mock_db.execute.call_args_list:
            query = call.args[0]
            self.assertIn('MERGE', query)
            self.assertIn('DEPENDS_ON', query)

    def test_source_not_found(self) -> None:
        """Returns 404 when source project is missing."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._target_url('target1', pid='missing'),
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_target_not_found(self) -> None:
        """Returns 404 when target project is missing."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(self._target_url('missing-target'))

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_self_reference_rejected(self) -> None:
        """Returns 400 when source and target are the same project."""
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(self._target_url(PROJECT_ID))

        self.assertEqual(response.status_code, 400)
        self.assertIn('itself', response.json()['detail'])
        self.mock_db.execute.assert_not_called()


class DeleteProjectRelationshipTestCase(_RelationshipsTestBase):
    """Tests for DELETE /projects/{id}/relationships/{target_id}."""

    _permissions: typing.ClassVar[set[str]] = {'project:write'}

    def _target_url(self, target_id: str, pid: str = PROJECT_ID) -> str:
        return (
            f'/organizations/engineering/projects/{pid}'
            f'/relationships/{target_id}'
        )

    def test_delete_edge(self) -> None:
        """Removes a DEPENDS_ON edge and returns 204."""
        self.mock_db.execute.return_value = [{'source_id': PROJECT_ID}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(self._target_url('target1'))

        self.assertEqual(response.status_code, 204)
        query = self.mock_db.execute.call_args.args[0]
        self.assertIn('DELETE r', query)
        self.assertIn('DEPENDS_ON', query)

    def test_edge_missing(self) -> None:
        """Returns 404 when the edge does not exist."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(self._target_url('target1'))

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])


class EmitChangeEventsTestCase(unittest.IsolatedAsyncioTestCase):
    """Tests for the project-change events emitter."""

    async def test_no_changes_skips_clickhouse_insert(self) -> None:
        from imbi_api.endpoints import projects

        with mock.patch(
            'imbi_api.endpoints.projects.ch_client.Clickhouse.get_instance'
        ) as mock_get:
            await projects._emit_change_events(
                'p1', 'alice', {'name': 'A'}, {'name': 'A'}
            )
        mock_get.assert_not_called()

    async def test_emits_one_row_per_changed_field(self) -> None:
        from imbi_api.endpoints import projects

        mock_instance = mock.AsyncMock()
        mock_instance.insert = mock.AsyncMock()
        with mock.patch(
            'imbi_api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=mock_instance,
        ):
            await projects._emit_change_events(
                'p1',
                'alice',
                {'name': 'A', 'description': 'old', 'id': 'p1'},
                {'name': 'B', 'description': 'new', 'id': 'p1'},
            )
        mock_instance.insert.assert_awaited_once()
        args = mock_instance.insert.await_args.args
        self.assertEqual(args[0], 'events')
        rows = args[1]
        self.assertEqual(len(rows), 2)
        # `id` was in skip-list so it should not appear
        fields = {row[7]['field'] for row in rows}
        self.assertEqual(fields, {'name', 'description'})

    async def test_skip_list_excludes_score_and_relationships(self) -> None:
        from imbi_api.endpoints import projects

        mock_instance = mock.AsyncMock()
        mock_instance.insert = mock.AsyncMock()
        with mock.patch(
            'imbi_api.endpoints.projects.ch_client.Clickhouse.get_instance',
            return_value=mock_instance,
        ):
            await projects._emit_change_events(
                'p1',
                'alice',
                {'score': 10, 'relationships': []},
                {'score': 20, 'relationships': [{'a': 1}]},
            )
        # All changes filtered out — no insert call
        mock_instance.insert.assert_not_awaited()

    async def test_clickhouse_failure_is_logged_not_raised(self) -> None:
        from imbi_api.endpoints import projects

        mock_instance = mock.AsyncMock()
        mock_instance.insert = mock.AsyncMock(side_effect=RuntimeError('boom'))
        with (
            mock.patch(
                'imbi_api.endpoints.projects.ch_client.Clickhouse.'
                'get_instance',
                return_value=mock_instance,
            ),
            self.assertLogs('imbi_api.endpoints.projects', level='ERROR'),
        ):
            # Must not raise even when ClickHouse insert fails
            await projects._emit_change_events(
                'p1', 'alice', {'name': 'A'}, {'name': 'B'}
            )
