"""Tests for project CRUD endpoints."""

import datetime
import typing
import unittest
from unittest import mock

import psycopg.errors
from fastapi.testclient import TestClient
from imbi_common import graph

from imbi_api import models
from tests import support

PROJECT_ID = 'abc123nanoid'


class ProjectEndpointsTestCase(support.SharedAppTestCase):
    """Test cases for project CRUD endpoints."""

    def setUp(self) -> None:
        """Set up test app with admin authentication."""
        from imbi_api.auth import permissions

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
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

        # Stub ``dispatch_lifecycle`` so tests that don't care about
        # plugin fan-out (the bulk of CRUD tests) aren't forced to seed
        # an extra db.execute side-effect for ``resolve_all_plugins``.
        # Tests that want to assert dispatch behaviour override this
        # patch locally (see the archive / unarchive cases).
        self._dispatch_patcher = mock.patch(
            'imbi_api.endpoints.projects.dispatch_lifecycle',
            new=mock.AsyncMock(return_value=[]),
        )
        self._dispatch_patcher.start()
        self.addCleanup(self._dispatch_patcher.stop)

        # ``delete_project`` reads the lifecycle context bundle before
        # the DETACH DELETE; stub it so test fixtures don't need to
        # provide three extra ``db.execute`` side-effects for the
        # lookups.
        self._bundle_patcher = mock.patch(
            'imbi_api.endpoints.projects.build_lifecycle_context_bundle',
            new=mock.AsyncMock(
                return_value=mock.MagicMock(
                    project_slug='my-api',
                    team_slug='platform',
                    project_links={},
                    project_type_slugs=['api-service'],
                ),
            ),
        )
        self._bundle_patcher.start()
        self.addCleanup(self._bundle_patcher.stop)

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

    def test_list_slim_omits_full_fields(self) -> None:
        """``slim=true`` returns the trimmed shape only.

        The slim response has no ``relationships``, no ``links`` /
        ``identifiers`` on the project, no embedded ``organization``
        on team / project_types / environments, and no
        ``outbound_count`` / ``inbound_count`` rows from the graph.
        """
        # The slim Cypher fragment returns one column (``project``)
        # and the row has only the trimmed keys.
        self.mock_db.execute.return_value = [
            {
                'project': {
                    'id': PROJECT_ID,
                    'name': 'My API',
                    'slug': 'my-api',
                    'description': 'An example API',
                    'archived': False,
                    'score': 88.5,
                    'team': {'name': 'Platform', 'slug': 'platform'},
                    'project_types': [
                        {
                            'slug': 'api-service',
                            'name': 'API Service',
                            'deployable': True,
                        }
                    ],
                    'environments': [
                        {
                            'slug': 'production',
                            'name': 'Production',
                            'label_color': '#00aa00',
                            'sort_order': 10,
                        }
                    ],
                },
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/projects/?slim=true',
            )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(len(data), 1)
        item = data[0]
        self.assertEqual(item['slug'], 'my-api')
        self.assertEqual(item['score'], 88.5)
        self.assertEqual(
            item['team'], {'name': 'Platform', 'slug': 'platform'}
        )
        # No embedded organization, links, identifiers, relationships.
        self.assertNotIn('organization', item['team'])
        self.assertNotIn('links', item)
        self.assertNotIn('identifiers', item)
        self.assertNotIn('relationships', item)
        self.assertNotIn('icon', item)
        self.assertNotIn('created_at', item)
        # project_types / environments are trimmed too.
        pt = item['project_types'][0]
        self.assertEqual(set(pt.keys()), {'name', 'slug', 'deployable'})
        env = item['environments'][0]
        self.assertEqual(
            set(env.keys()),
            {'name', 'slug', 'label_color', 'sort_order'},
        )
        # PR counts default to 0 when no rows come back from
        # ClickHouse (we don't mock the helpers here).
        self.assertEqual(item['open_pr_count'], 0)
        self.assertEqual(item['current_releases'], {})

    def test_list_slim_handles_empty_collections(self) -> None:
        """Slim mode tolerates empty project_types / environments.

        AGE's ``collect(CASE WHEN node IS NOT NULL THEN ... END)``
        pattern can yield ``[None]`` (a single null) when the
        OPTIONAL MATCH finds nothing.  The slim branch must strip
        those nulls before passing the row to
        ``ProjectListItem.model_validate``, otherwise pydantic
        raises and the endpoint 500s.
        """
        self.mock_db.execute.return_value = [
            {
                'project': {
                    'id': PROJECT_ID,
                    'name': 'Bare Project',
                    'slug': 'bare-project',
                    'description': None,
                    'archived': False,
                    'score': None,
                    'team': {'name': 'Platform', 'slug': 'platform'},
                    # AGE injects ``[None]`` for empty OPTIONAL MATCH.
                    'project_types': [None],
                    'environments': [None],
                },
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/projects/?slim=true',
            )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(len(data), 1)
        item = data[0]
        self.assertEqual(item['slug'], 'bare-project')
        self.assertEqual(item['project_types'], [])
        self.assertEqual(item['environments'], [])

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

    def test_patch_project_environments_uses_merge(self) -> None:
        """Env edges use MERGE so retries cannot duplicate them."""
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
        updated = self._project_data(name='Renamed API')

        self.mock_db.execute.side_effect = [
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            [{'slug': 'platform'}],
            [{'pt_slug': 'api-service', 'found': True}],
            [{'env_slug': 'staging', 'found': True}],
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
                    {'op': 'replace', 'path': '/name', 'value': 'Renamed API'},
                ],
            )

        self.assertEqual(response.status_code, 200)

        update_query = next(
            call.args[0]
            for call in self.mock_db.execute.call_args_list
            if 'old_env:DEPLOYED_IN' in call.args[0]
        )
        self.assertIn('MERGE (p)-[r:DEPLOYED_IN]->(e)', update_query)
        self.assertNotIn('CREATE (p)-[:DEPLOYED_IN', update_query)

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

    def test_patch_project_team_and_type_use_merge(self) -> None:
        """OWNED_BY and TYPE edges use MERGE so retries cannot duplicate."""
        existing = self._project_data()
        updated = self._project_data(name='Renamed API')

        self.mock_db.execute.side_effect = [
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            [{'slug': 'backend'}],
            [{'pt_slug': 'worker', 'found': True}],
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
                    {
                        'op': 'replace',
                        'path': '/project_type_slugs',
                        'value': ['worker'],
                    },
                ],
            )

        self.assertEqual(response.status_code, 200)

        update_query = next(
            call.args[0]
            for call in self.mock_db.execute.call_args_list
            if 'old_own:OWNED_BY' in call.args[0]
        )
        self.assertIn('MERGE (p)-[:OWNED_BY]->(new_t)', update_query)
        self.assertNotIn('CREATE (p)-[:OWNED_BY]', update_query)
        self.assertIn('MERGE (p)-[:TYPE]->(new_pt)', update_query)
        self.assertNotIn('CREATE (p)-[:TYPE]', update_query)

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

    def test_patch_project_retries_age_entity_update_error(self) -> None:
        """AGE 'Entity failed to be updated' is retried, eventually
        succeeds."""
        existing = self._project_data()
        updated_row = {
            'project': existing,
            'outbound_count': 0,
            'inbound_count': 0,
        }
        self.mock_db.execute.side_effect = [
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            [{'slug': 'platform'}],
            [{'pt_slug': 'api-service', 'found': True}],
            psycopg.errors.InternalError('Entity failed to be updated: 3'),
            [updated_row],  # retry succeeds
        ]

        with (
            mock.patch('imbi_api.endpoints.projects.asyncio.sleep'),
            mock.patch('imbi_common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            mock_get_model.return_value = models.Project

            response = self.client.patch(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json=[{'op': 'replace', 'path': '/name', 'value': 'Updated'}],
            )

        self.assertEqual(response.status_code, 200)

    def test_patch_project_age_update_error_exhausted(self) -> None:
        """AGE 'Entity failed to be updated' that persists is raised after
        three attempts."""
        existing = self._project_data()
        self.mock_db.execute.side_effect = [
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            [{'slug': 'platform'}],
            [{'pt_slug': 'api-service', 'found': True}],
            psycopg.errors.InternalError('Entity failed to be updated: 3'),
            psycopg.errors.InternalError('Entity failed to be updated: 3'),
            psycopg.errors.InternalError('Entity failed to be updated: 3'),
        ]

        with (
            mock.patch(
                'imbi_api.endpoints.projects.asyncio.sleep'
            ) as mock_sleep,
            mock.patch('imbi_common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
            self.assertRaises(psycopg.errors.InternalError),
        ):
            mock_get_model.return_value = models.Project
            self.client.patch(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json=[{'op': 'replace', 'path': '/name', 'value': 'Updated'}],
            )

        self.assertEqual(self.mock_db.execute.call_count, 6)
        self.assertEqual(mock_sleep.await_count, 2)

    def test_patch_project_other_internal_error_not_retried(self) -> None:
        """Non-AGE InternalError propagates without retry."""
        existing = self._project_data()
        self.mock_db.execute.side_effect = [
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            [{'slug': 'platform'}],
            [{'pt_slug': 'api-service', 'found': True}],
            psycopg.errors.InternalError('some other error'),
        ]

        with (
            mock.patch('imbi_common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
            self.assertRaises(psycopg.errors.InternalError),
        ):
            mock_get_model.return_value = models.Project
            self.client.patch(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json=[{'op': 'replace', 'path': '/name', 'value': 'Updated'}],
            )

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

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'lifecycle_results': []})

    def test_delete_not_found(self) -> None:
        """Test deleting nonexistent project."""
        self.mock_db.execute.return_value = []

        response = self.client.delete(
            '/organizations/engineering/projects/nonexistent',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    # -- Archive -------------------------------------------------------

    def test_archive_success(self) -> None:
        """Archiving a project marks it archived and returns it."""
        archived = self._project_data(
            archived=True,
            archived_at='2026-05-11T20:00:00Z',
        )
        self.mock_db.execute.return_value = [
            {
                'project': archived,
                'outbound_count': 0,
                'inbound_count': 0,
            },
        ]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.projects.dispatch_lifecycle',
                new=mock.AsyncMock(return_value=[]),
            ) as mock_dispatch,
        ):
            response = self.client.post(
                f'/organizations/engineering/projects/{PROJECT_ID}/archive',
            )

        self.assertEqual(response.status_code, 200)
        mock_dispatch.assert_awaited_once()
        data = response.json()
        self.assertTrue(data['archived'])
        self.assertEqual(data['archived_at'], '2026-05-11T20:00:00Z')
        self.assertEqual(data['lifecycle_results'], [])
        call_kwargs = self.mock_db.execute.call_args
        self.assertIs(call_kwargs.args[1]['archived'], True)
        self.assertIsNotNone(call_kwargs.args[1]['archived_at'])

    def test_archive_not_found(self) -> None:
        """Archiving a missing project returns 404."""
        self.mock_db.execute.return_value = []

        response = self.client.post(
            '/organizations/engineering/projects/nonexistent/archive',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_archive_succeeds_when_dispatch_raises(self) -> None:
        """Dispatch failure must not poison a committed archive."""
        archived = self._project_data(
            archived=True,
            archived_at='2026-05-11T20:00:00Z',
        )
        self.mock_db.execute.return_value = [
            {
                'project': archived,
                'outbound_count': 0,
                'inbound_count': 0,
            },
        ]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.projects.dispatch_lifecycle',
                new=mock.AsyncMock(side_effect=RuntimeError('boom')),
            ) as mock_dispatch,
        ):
            response = self.client.post(
                f'/organizations/engineering/projects/{PROJECT_ID}/archive',
            )

        self.assertEqual(response.status_code, 200)
        mock_dispatch.assert_awaited_once()
        self.assertEqual(response.json()['lifecycle_results'], [])

    def test_unarchive_success(self) -> None:
        """Unarchiving a project clears archived state."""
        restored = self._project_data(
            archived=False,
            archived_at=None,
        )
        self.mock_db.execute.return_value = [
            {
                'project': restored,
                'outbound_count': 0,
                'inbound_count': 0,
            },
        ]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.projects.dispatch_lifecycle',
                new=mock.AsyncMock(return_value=[]),
            ) as mock_dispatch,
        ):
            response = self.client.post(
                f'/organizations/engineering/projects/{PROJECT_ID}/unarchive',
            )

        self.assertEqual(response.status_code, 200)
        mock_dispatch.assert_awaited_once()
        data = response.json()
        self.assertFalse(data['archived'])
        self.assertIsNone(data['archived_at'])
        self.assertEqual(data['lifecycle_results'], [])
        call_kwargs = self.mock_db.execute.call_args
        self.assertIs(call_kwargs.args[1]['archived'], False)
        self.assertIsNone(call_kwargs.args[1]['archived_at'])

    def test_unarchive_not_found(self) -> None:
        """Unarchiving a missing project returns 404."""
        self.mock_db.execute.return_value = []

        response = self.client.post(
            '/organizations/engineering/projects/nonexistent/unarchive',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_unarchive_succeeds_when_dispatch_raises(self) -> None:
        """Dispatch failure must not poison a committed unarchive."""
        restored = self._project_data(
            archived=False,
            archived_at=None,
        )
        self.mock_db.execute.return_value = [
            {
                'project': restored,
                'outbound_count': 0,
                'inbound_count': 0,
            },
        ]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.projects.dispatch_lifecycle',
                new=mock.AsyncMock(side_effect=RuntimeError('boom')),
            ) as mock_dispatch,
        ):
            response = self.client.post(
                f'/organizations/engineering/projects/{PROJECT_ID}/unarchive',
            )

        self.assertEqual(response.status_code, 200)
        mock_dispatch.assert_awaited_once()
        self.assertEqual(response.json()['lifecycle_results'], [])

    def test_list_excludes_archived_by_default(self) -> None:
        """List query filters out archived projects by default."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            self.client.get('/organizations/engineering/projects/')

        query = self.mock_db.execute.call_args.args[0]
        self.assertIn('coalesce(p.archived, false) = false', query)

    def test_list_include_archived(self) -> None:
        """``include_archived=true`` drops the archive filter."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            self.client.get(
                '/organizations/engineering/projects/?include_archived=true',
            )

        query = self.mock_db.execute.call_args.args[0]
        self.assertNotIn('coalesce(p.archived, false)', query)

    # -- Attribute filtering -------------------------------------------

    def _framework_blueprint(self) -> models.Blueprint:
        return models.Blueprint(
            name='API Facts',
            slug='apis-facts',
            type='Project',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'framework': {
                            'type': 'string',
                            'enum': ['FastAPI', 'http-service-lib'],
                        },
                    },
                }
            ),
        )

    def _list_with_filter(self, query_string: str) -> typing.Any:
        self.mock_db.match.return_value = [self._framework_blueprint()]
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            return self.client.get(
                f'/organizations/engineering/projects/?{query_string}',
            )

    def test_filter_ne_excludes_unset(self) -> None:
        """``ne`` builds a plain inequality (unset rows excluded)."""
        response = self._list_with_filter(
            'filter=framework:ne:http-service-lib'
        )
        self.assertEqual(response.status_code, 200)
        query = self.mock_db.execute.call_args.args[0]
        params = self.mock_db.execute.call_args.args[1]
        self.assertIn('p.framework <> {f0_0}', query)
        self.assertNotIn('IS NULL', query)
        self.assertEqual(params['f0_0'], 'http-service-lib')

    def test_filter_eq_builds_equality(self) -> None:
        response = self._list_with_filter('filter=framework:eq:FastAPI')
        self.assertEqual(response.status_code, 200)
        query = self.mock_db.execute.call_args.args[0]
        self.assertIn('p.framework = {f0_0}', query)

    def test_filter_exists(self) -> None:
        response = self._list_with_filter('filter=framework:exists')
        self.assertEqual(response.status_code, 200)
        query = self.mock_db.execute.call_args.args[0]
        self.assertIn('p.framework IS NOT NULL', query)

    def test_filter_not_in_uses_and_of_inequalities(self) -> None:
        response = self._list_with_filter(
            'filter=framework:not_in:FastAPI,http-service-lib'
        )
        self.assertEqual(response.status_code, 200)
        query = self.mock_db.execute.call_args.args[0]
        self.assertIn(
            '(p.framework <> {f0_0} AND p.framework <> {f0_1})', query
        )

    def test_filter_unknown_field_rejected(self) -> None:
        response = self._list_with_filter('filter=bogus:eq:x')
        self.assertEqual(response.status_code, 400)
        self.assertIn('not filterable', response.json()['detail'])

    def test_filter_unknown_operator_rejected(self) -> None:
        response = self._list_with_filter('filter=framework:like:x')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Unknown filter operator', response.json()['detail'])

    def test_filter_malformed_rejected(self) -> None:
        response = self._list_with_filter('filter=framework')
        self.assertEqual(response.status_code, 400)

    def test_filter_exists_with_value_rejected(self) -> None:
        response = self._list_with_filter('filter=framework:exists:x')
        self.assertEqual(response.status_code, 400)
        self.assertIn('does not accept a value', response.json()['detail'])

    def test_filter_eq_without_value_rejected(self) -> None:
        response = self._list_with_filter('filter=framework:eq')
        self.assertEqual(response.status_code, 400)
        self.assertIn('requires a value', response.json()['detail'])

    def test_filter_ne_without_value_rejected(self) -> None:
        response = self._list_with_filter('filter=framework:ne')
        self.assertEqual(response.status_code, 400)
        self.assertIn('requires a value', response.json()['detail'])

    # -- Lifecycle dispatch wiring ------------------------------------

    def test_create_dispatches_lifecycle_created(self) -> None:
        """``create_project`` fans out a ``created`` lifecycle event."""
        record = self._project_data()
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
        # The setUp patcher is registered via addCleanup; nest a new
        # ``mock.patch`` on the same target so its return value wins for
        # the duration of this test without double-stopping the cleanup.
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
            mock.patch(
                'imbi_api.endpoints.projects.dispatch_lifecycle',
                new=mock.AsyncMock(return_value=[]),
            ) as mock_dispatch,
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
        mock_dispatch.assert_awaited_once()
        call = mock_dispatch.await_args
        self.assertEqual(call.args[3], 'created')
        self.assertEqual(call.kwargs['project_name'], 'My API')
        self.assertEqual(call.kwargs['project_description'], 'An example API')

    def test_patch_dispatches_lifecycle_on_slug_change(self) -> None:
        """Slug change passes ``previous_project_slug`` to dispatch."""
        existing = self._project_data()
        updated = self._project_data(slug='my-api-v2')
        self.mock_db.execute.side_effect = [
            [
                {
                    'project': existing,
                    'outbound_count': 0,
                    'inbound_count': 0,
                },
            ],
            [{'slug': 'platform'}],
            [{'pt_slug': 'api-service', 'found': True}],
            [
                {
                    'project': updated,
                    'outbound_count': 0,
                    'inbound_count': 0,
                },
            ],
        ]
        # Nest a fresh ``dispatch_lifecycle`` patch over the setUp one --
        # the inner mock.patch wins for the duration of the with-block
        # and addCleanup handles teardown of the outer patcher.
        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.projects.dispatch_lifecycle',
                new=mock.AsyncMock(return_value=[]),
            ) as mock_dispatch,
        ):
            mock_get_model.return_value = models.Project
            response = self.client.patch(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json=[
                    {
                        'op': 'replace',
                        'path': '/slug',
                        'value': 'my-api-v2',
                    },
                ],
            )

        self.assertEqual(response.status_code, 200)
        mock_dispatch.assert_awaited_once()
        call = mock_dispatch.await_args
        self.assertEqual(call.args[3], 'updated')
        self.assertEqual(call.kwargs['previous_project_slug'], 'my-api')

    def test_patch_dispatches_relocated_when_transfer_repository_set(
        self,
    ) -> None:
        """``?transfer_repository=true`` + type change → relocate dispatch.

        Asserts the dispatcher is called with ``event='relocated'`` and
        the previous types are carried through so plugins can decide
        between transfer and no-op.  The ``updated`` dispatch path is
        not exercised here (slug/description are unchanged), so the
        single dispatch await is the relocate call.
        """
        existing = self._project_data()
        updated = self._project_data(
            project_types=[
                {
                    'name': 'Worker',
                    'slug': 'worker',
                    'organization': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                },
            ],
        )
        self.mock_db.execute.side_effect = [
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            [{'slug': 'platform'}],
            [{'pt_slug': 'worker', 'found': True}],
            [{'project': updated, 'outbound_count': 0, 'inbound_count': 0}],
        ]
        self._dispatch_patcher.stop()
        with (
            mock.patch('imbi_common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi_api.endpoints.projects.dispatch_lifecycle',
                new=mock.AsyncMock(return_value=[]),
            ) as mock_dispatch,
        ):
            mock_get_model.return_value = models.Project
            response = self.client.patch(
                f'/organizations/engineering/projects/{PROJECT_ID}'
                '?transfer_repository=true',
                json=[
                    {
                        'op': 'replace',
                        'path': '/project_type_slugs',
                        'value': ['worker'],
                    },
                ],
            )

        self.assertEqual(response.status_code, 200)
        mock_dispatch.assert_awaited_once()
        call = mock_dispatch.await_args
        self.assertEqual(call.args[3], 'relocated')
        self.assertEqual(
            call.kwargs['previous_project_type_slugs'], ['api-service']
        )

    def test_patch_skips_relocate_without_transfer_repository_flag(
        self,
    ) -> None:
        """Default behaviour: type change alone never relocates.

        Without ``?transfer_repository=true`` a project-type swap is
        considered metadata-only -- plugins do not get a relocate
        event.  Guards against accidentally moving repos when an
        operator just retags a project.
        """
        existing = self._project_data()
        updated = self._project_data(
            project_types=[
                {
                    'name': 'Worker',
                    'slug': 'worker',
                    'organization': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                },
            ],
        )
        self.mock_db.execute.side_effect = [
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            [{'slug': 'platform'}],
            [{'pt_slug': 'worker', 'found': True}],
            [{'project': updated, 'outbound_count': 0, 'inbound_count': 0}],
        ]
        self._dispatch_patcher.stop()
        with (
            mock.patch('imbi_common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi_api.endpoints.projects.dispatch_lifecycle',
                new=mock.AsyncMock(return_value=[]),
            ) as mock_dispatch,
        ):
            mock_get_model.return_value = models.Project
            response = self.client.patch(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json=[
                    {
                        'op': 'replace',
                        'path': '/project_type_slugs',
                        'value': ['worker'],
                    },
                ],
            )

        self.assertEqual(response.status_code, 200)
        mock_dispatch.assert_not_awaited()

    def test_delete_with_delete_repository_false_skips_dispatch(
        self,
    ) -> None:
        """``delete_repository=false`` short-circuits the dispatch."""
        self.mock_db.execute.return_value = [{'deleted': 1}]
        # Nest fresh patches over the setUp ones -- the inner mock.patch
        # wins for the duration of the with-block; addCleanup handles
        # teardown of the outer patchers without a double-stop.
        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.projects.dispatch_lifecycle',
                new=mock.AsyncMock(return_value=[]),
            ) as mock_dispatch,
            mock.patch(
                'imbi_api.endpoints.projects.build_lifecycle_context_bundle',
                new=mock.AsyncMock(),
            ) as mock_bundle,
        ):
            response = self.client.delete(
                f'/organizations/engineering/projects/{PROJECT_ID}'
                '?delete_repository=false',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'lifecycle_results': []})
        mock_dispatch.assert_not_awaited()
        mock_bundle.assert_not_awaited()

    def test_preview_returns_would_relocate_per_plugin(self) -> None:
        """``GET /lifecycle/preview`` fans out per plugin and flags diffs.

        Stubs ``resolve_all_plugins`` with two plugins whose handlers
        return different ``resolve_relocation_target`` outputs for the
        current vs hypothetical type set, and asserts the preview rows
        carry the expected ``would_relocate`` flags.
        """
        from imbi_common.plugins.base import RelocationTarget

        self._bundle_patcher.stop()
        bundle_value = mock.MagicMock(
            project_slug='my-api',
            team_slug='platform',
            project_links={},
            project_type_slugs=['api-service'],
        )

        plugin_a_handler = mock.AsyncMock()
        plugin_a_handler.resolve_relocation_target.side_effect = [
            RelocationTarget(
                link_key='github-repository', identifier='apis/my-api'
            ),
            RelocationTarget(
                link_key='github-repository', identifier='workers/my-api'
            ),
        ]
        plugin_b_handler = mock.AsyncMock()
        plugin_b_handler.resolve_relocation_target.side_effect = [
            None,
            None,
        ]
        plugin_a_handler.manifest = mock.MagicMock(slug='gh-a')
        plugin_b_handler.manifest = mock.MagicMock(slug='gh-b')

        plugin_a = mock.MagicMock(
            plugin_id='p-a',
            plugin_slug='gh-a',
            options={},
            entry=mock.MagicMock(handler_cls=lambda: plugin_a_handler),
        )
        plugin_b = mock.MagicMock(
            plugin_id='p-b',
            plugin_slug='gh-b',
            options={},
            entry=mock.MagicMock(handler_cls=lambda: plugin_b_handler),
        )

        self.mock_db.execute.side_effect = [[{'id': PROJECT_ID}]]
        with (
            mock.patch(
                'imbi_api.endpoints.projects.build_lifecycle_context_bundle',
                new=mock.AsyncMock(return_value=bundle_value),
            ),
            mock.patch(
                'imbi_api.endpoints.projects.resolve_all_plugins',
                new=mock.AsyncMock(return_value=[plugin_a, plugin_b]),
            ),
        ):
            response = self.client.get(
                f'/organizations/engineering/projects/{PROJECT_ID}'
                '/lifecycle/preview?project_type_slugs=worker',
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body['previews']), 2)

        rows_by_plugin = {row['plugin_slug']: row for row in body['previews']}
        row_a = rows_by_plugin['gh-a']
        self.assertTrue(row_a['would_relocate'])
        self.assertEqual(row_a['current_target']['identifier'], 'apis/my-api')
        self.assertEqual(row_a['next_target']['identifier'], 'workers/my-api')
        row_b = rows_by_plugin['gh-b']
        self.assertFalse(row_b['would_relocate'])
        self.assertIsNone(row_b['current_target'])
        self.assertIsNone(row_b['next_target'])

    def test_preview_returns_empty_when_no_lifecycle_plugins(self) -> None:
        """No assigned lifecycle plugins → empty previews list."""
        self._bundle_patcher.stop()
        self.mock_db.execute.side_effect = [[{'id': PROJECT_ID}]]
        with (
            mock.patch(
                'imbi_api.endpoints.projects.build_lifecycle_context_bundle',
                new=mock.AsyncMock(
                    return_value=mock.MagicMock(
                        project_slug='my-api',
                        team_slug='platform',
                        project_links={},
                        project_type_slugs=['api-service'],
                    ),
                ),
            ),
            mock.patch(
                'imbi_api.endpoints.projects.resolve_all_plugins',
                new=mock.AsyncMock(return_value=[]),
            ),
        ):
            response = self.client.get(
                f'/organizations/engineering/projects/{PROJECT_ID}'
                '/lifecycle/preview?project_type_slugs=worker',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'previews': []})

    def test_preview_returns_404_when_project_missing(self) -> None:
        """Missing project → 404 instead of silently empty previews."""
        self._bundle_patcher.stop()
        self.mock_db.execute.side_effect = [[]]
        with (
            mock.patch(
                'imbi_api.endpoints.projects.build_lifecycle_context_bundle',
                new=mock.AsyncMock(),
            ) as mock_bundle,
            mock.patch(
                'imbi_api.endpoints.projects.resolve_all_plugins',
                new=mock.AsyncMock(return_value=[]),
            ) as mock_resolve,
        ):
            response = self.client.get(
                f'/organizations/engineering/projects/{PROJECT_ID}'
                '/lifecycle/preview?project_type_slugs=worker',
            )

        self.assertEqual(response.status_code, 404)
        mock_bundle.assert_not_awaited()
        mock_resolve.assert_not_awaited()


class _RelationshipsTestBase(support.SharedAppTestCase):
    """Shared setup for relationship endpoint tests."""

    _permissions: typing.ClassVar[set[str]] = set()

    def setUp(self) -> None:
        from imbi_api.auth import permissions

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
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
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
