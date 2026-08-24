"""Tests for project CRUD endpoints."""

import datetime
import typing
import unittest
from unittest import mock

import psycopg.errors
from fastapi.testclient import TestClient

from apps.api.tests import support
from imbi.api import models
from imbi.common import graph

PROJECT_ID = 'abc123nanoid'


class ProjectEndpointsTestCase(support.SharedAppTestCase):
    """Test cases for project CRUD endpoints."""

    def setUp(self) -> None:
        """Set up test app with admin authentication."""
        from imbi.api.auth import permissions

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
            'imbi.api.endpoints.projects.dispatch_lifecycle',
            new=mock.AsyncMock(return_value=[]),
        )
        self._dispatch_patcher.start()
        self.addCleanup(self._dispatch_patcher.stop)

        # ``delete_project`` reads the lifecycle context bundle before
        # the DETACH DELETE; stub it so test fixtures don't need to
        # provide three extra ``db.execute`` side-effects for the
        # lookups.
        self._bundle_patcher = mock.patch(
            'imbi.api.endpoints.projects.build_lifecycle_context_bundle',
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

        # ``delete_project`` resolves the bound lifecycle capabilities
        # before the DETACH DELETE (so they survive the write); stub it
        # so CRUD tests don't need to seed the binding-resolution
        # ``db.execute`` side-effects. Dispatch tests override locally.
        self._resolve_patcher = mock.patch(
            'imbi.api.endpoints.projects.resolve_all_capabilities',
            new=mock.AsyncMock(return_value=[]),
        )
        self._resolve_patcher.start()
        self.addCleanup(self._resolve_patcher.stop)

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
                'imbi.common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.nanoid.generate',
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
                'imbi.common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.nanoid.generate',
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
            'imbi.common.blueprints.get_model',
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
                'imbi.common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.nanoid.generate',
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
                'imbi.common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.nanoid.generate',
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
                'imbi.common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.nanoid.generate',
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
            'imbi.common.graph.parse_agtype',
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
            'imbi.common.graph.parse_agtype',
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
        self.assertEqual(
            set(pt.keys()), {'name', 'slug', 'deployable', 'releasable'}
        )
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
            'imbi.common.graph.parse_agtype',
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
            'imbi.common.graph.parse_agtype',
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
            'imbi.common.graph.parse_agtype',
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
                'imbi.common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype',
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

    def test_patch_project_enqueues_dependents(self) -> None:
        """A patched attribute re-scores the project's dependents."""
        existing = self._project_data()
        updated = self._project_data(name='New Name')

        self.mock_db.execute.side_effect = [
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            [{'slug': 'platform'}],
            [{'pt_slug': 'api-service', 'found': True}],
            [{'project': updated, 'outbound_count': 0, 'inbound_count': 0}],
        ]

        with (
            mock.patch(
                'imbi.common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.score_queue.enqueue_dependents',
                mock.AsyncMock(return_value=0),
            ) as enqueue_dependents,
        ):
            mock_get_model.return_value = models.Project
            response = self.client.patch(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json=[
                    {'op': 'replace', 'path': '/name', 'value': 'New Name'},
                ],
            )

        self.assertEqual(response.status_code, 200)
        enqueue_dependents.assert_awaited_once()
        self.assertEqual(enqueue_dependents.await_args.args[2], PROJECT_ID)

    def test_patch_project_not_found(self) -> None:
        """Test patching non-existent project returns 404."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi.common.graph.parse_agtype',
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
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            mock_get_model.return_value = models.Project
            response = self.client.patch(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json=[{'op': 'replace', 'path': '/name', 'value': 'New Name'}],
            )

        self.assertEqual(response.status_code, 200)

    def test_patch_project_keeps_set_clause_join_free(self) -> None:
        """No statement mixes a property SET with a join.

        Apache AGE aborts a query whose Cypher SET clause ends up under
        a nested-loop join ("cypher SET clause cannot be rescanned"),
        and the planner's choice of join method depends on table
        statistics -- so a combined statement fails on some databases
        and not others.  The property SET therefore runs alone, and the
        relationship changes and the read-back run as their own
        statements.
        """
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
            [{'env_slug': 'testing', 'found': True}],
            [{'project': updated, 'outbound_count': 0, 'inbound_count': 0}],
        ]

        with (
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            mock_get_model.return_value = models.Project
            response = self.client.patch(
                f'/organizations/engineering/projects/{PROJECT_ID}',
                json=[
                    {'op': 'replace', 'path': '/name', 'value': 'Renamed API'},
                    {
                        'op': 'add',
                        'path': '/environments',
                        'value': {'testing': {'url': 'postgresql://db'}},
                    },
                ],
            )

        self.assertEqual(response.status_code, 200)

        statements = self.mock_db._execute_batch.call_args.args[0]
        set_statements = [s for s in statements if 'SET p.' in s.cypher]
        self.assertEqual(len(set_statements), 1)
        set_cypher = set_statements[0].cypher
        for join in ('UNWIND', 'OPTIONAL MATCH', 'MERGE', 'DELETE'):
            self.assertNotIn(join, set_cypher)
        self.assertTrue(set_cypher.rstrip().endswith('RETURN p'))

        # The read-back is a plain read -- it must not carry the SET.
        read_query = self.mock_db.execute.call_args.args[0]
        self.assertIn('OPTIONAL MATCH', read_query)
        self.assertNotIn('SET p.', read_query)

    def test_patch_project_environments_uses_inline_create(self) -> None:
        """Env edges are re-created with inline props (not SET r = {map}).

        Some Apache AGE builds silently no-op a full-property
        ``SET r = {map}`` on a relationship, dropping every edge
        attribute. The update path deletes the old DEPLOYED_IN edges
        and re-creates them with inline properties, matching the
        create path, so edge attributes persist reliably.
        """
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
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
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

        # The relationship changes run as their own batched statement,
        # separate from the property SET (AGE cannot rescan a SET that
        # ends up under a nested-loop join).
        statements = self.mock_db._execute_batch.call_args.args[0]
        update_query = next(
            stmt.cypher
            for stmt in statements
            if 'old_env:DEPLOYED_IN' in stmt.cypher
        )
        self.assertIn('CREATE (p)-[:DEPLOYED_IN', update_query)
        self.assertNotIn('MERGE (p)-[r:DEPLOYED_IN]->(e)', update_query)
        self.assertNotIn('SET r =', update_query)
        self.assertNotIn('SET p.', update_query)

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
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
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
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
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

        statements = self.mock_db._execute_batch.call_args.args[0]
        update_query = next(
            stmt.cypher
            for stmt in statements
            if 'old_own:OWNED_BY' in stmt.cypher
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
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
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
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
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
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
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
            mock.patch('imbi.api.endpoints.projects.asyncio.sleep'),
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
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
                'imbi.api.endpoints.projects.asyncio.sleep'
            ) as mock_sleep,
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
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
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
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
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
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
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                f'/organizations/engineering/projects/{PROJECT_ID}',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'lifecycle_results': []})
        # A deleted project must not linger in search results.
        self.mock_db.delete_node_embeddings.assert_awaited_once_with(
            'Project', PROJECT_ID
        )

    def test_delete_not_found(self) -> None:
        """Test deleting nonexistent project."""
        self.mock_db.execute.return_value = []

        response = self.client.delete(
            '/organizations/engineering/projects/nonexistent',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])
        self.mock_db.delete_node_embeddings.assert_not_awaited()

    def test_delete_succeeds_when_snapshot_raises(self) -> None:
        """A lifecycle snapshot failure must not abort the delete.

        ``build_lifecycle_context_bundle`` /
        ``resolve_all_capabilities`` run before the ``DETACH DELETE``;
        a transient failure there must be logged, the delete must still
        proceed, and dispatch must be skipped (no complete snapshot).
        """
        self.mock_db.execute.return_value = [{'deleted': 1}]

        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.build_lifecycle_context_bundle',
                new=mock.AsyncMock(side_effect=RuntimeError('boom')),
            ),
            mock.patch(
                'imbi.api.endpoints.projects.dispatch_lifecycle',
                new=mock.AsyncMock(return_value=[]),
            ) as mock_dispatch,
        ):
            response = self.client.delete(
                f'/organizations/engineering/projects/{PROJECT_ID}',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'lifecycle_results': []})
        mock_dispatch.assert_not_awaited()

    # -- Archive -------------------------------------------------------

    def _archived_write_params(self) -> dict[str, typing.Any]:
        """Params of the statement that wrote the archived state.

        The write and the read-back are separate statements, so the
        last ``execute`` call is the read.
        """
        return next(
            call.args[1]
            for call in self.mock_db.execute.call_args_list
            if 'SET p.archived' in call.args[0]
        )

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
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.dispatch_lifecycle',
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
        write_params = self._archived_write_params()
        self.assertIs(write_params['archived'], True)
        self.assertIsNotNone(write_params['archived_at'])

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
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.dispatch_lifecycle',
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
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.dispatch_lifecycle',
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
        write_params = self._archived_write_params()
        self.assertIs(write_params['archived'], False)
        self.assertIsNone(write_params['archived_at'])

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
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.dispatch_lifecycle',
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
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            self.client.get('/organizations/engineering/projects/')

        query = self.mock_db.execute.call_args.args[0]
        self.assertIn('coalesce(p.archived, false) = false', query)

    def test_list_include_archived(self) -> None:
        """``include_archived=true`` drops the archive filter."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            self.client.get(
                '/organizations/engineering/projects/?include_archived=true',
            )

        query = self.mock_db.execute.call_args.args[0]
        self.assertNotIn('coalesce(p.archived, false)', query)

    # -- EXISTS_IN service filtering -----------------------------------

    def test_list_by_service_returns_matching_projects(self) -> None:
        """``integration_slug`` + ``identifier`` restrict to the
        EXISTS_IN edge carrying that external identifier."""
        self.mock_db.execute.return_value = [
            {
                'project': self._project_data(),
                'outbound_count': 0,
                'inbound_count': 0,
            },
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/projects/'
                '?integration_slug=github&identifier=octo/api',
            )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'my-api')

        # The list query is the first execute call; later calls fetch
        # release/PR data once a project row comes back.
        query = self.mock_db.execute.call_args_list[0].args[0]
        params = self.mock_db.execute.call_args_list[0].args[1]
        self.assertIn('-[ei:EXISTS_IN]->', query)
        self.assertIn('Integration {{slug: {integration_slug}}}', query)
        self.assertIn('-[:BELONGS_TO]->(o)', query)
        self.assertIn('WHERE ei.identifier = {identifier}', query)
        self.assertEqual(params['integration_slug'], 'github')
        self.assertEqual(params['identifier'], 'octo/api')

    def test_list_by_service_slug_only_omits_identifier(self) -> None:
        """``integration_slug`` alone matches every project in
        the service without an identifier predicate."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/projects/?integration_slug=github',
            )

        self.assertEqual(response.status_code, 200)
        query = self.mock_db.execute.call_args.args[0]
        params = self.mock_db.execute.call_args.args[1]
        self.assertIn('-[ei:EXISTS_IN]->', query)
        self.assertNotIn('WHERE ei.identifier', query)
        self.assertEqual(params['integration_slug'], 'github')
        self.assertIsNone(params['identifier'])

    def test_list_identifier_without_service_rejected(self) -> None:
        """``identifier`` is meaningless without a service slug."""
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/projects/?identifier=octo/api',
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn('integration_slug', response.json()['detail'])
        self.mock_db.execute.assert_not_called()

    def test_list_unknown_service_returns_empty(self) -> None:
        """An unknown service slug matches nothing (no 404, no extra
        lookup query)."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/projects/'
                '?integration_slug=does-not-exist',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        self.assertEqual(self.mock_db.execute.call_count, 1)

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
                        'deprecated': {'type': 'boolean'},
                        'coverage': {'type': 'number'},
                        'replica_count': {'type': 'integer'},
                    },
                }
            ),
        )

    def _list_with_filter(self, query_string: str) -> typing.Any:
        self.mock_db.match.return_value = [self._framework_blueprint()]
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi.common.graph.parse_agtype',
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

    def test_filter_boolean_value_bound_as_boolean(self) -> None:
        """Boolean attributes bind ``true``/``false``, not strings."""
        response = self._list_with_filter('filter=deprecated:eq:true')
        self.assertEqual(response.status_code, 200)
        params = self.mock_db.execute.call_args.args[1]
        self.assertIs(params['f0_0'], True)

        response = self._list_with_filter('filter=deprecated:ne:false')
        self.assertEqual(response.status_code, 200)
        params = self.mock_db.execute.call_args.args[1]
        self.assertIs(params['f0_0'], False)

    def test_filter_boolean_invalid_value_rejected(self) -> None:
        response = self._list_with_filter('filter=deprecated:eq:maybe')
        self.assertEqual(response.status_code, 400)
        self.assertIn('true/false', response.json()['detail'])

    def test_filter_number_value_bound_as_number(self) -> None:
        """Number attributes bind ints/floats, not strings."""
        response = self._list_with_filter('filter=coverage:eq:97.5')
        self.assertEqual(response.status_code, 200)
        params = self.mock_db.execute.call_args.args[1]
        self.assertEqual(params['f0_0'], 97.5)
        self.assertIsInstance(params['f0_0'], float)

        response = self._list_with_filter('filter=coverage:eq:100')
        self.assertEqual(response.status_code, 200)
        params = self.mock_db.execute.call_args.args[1]
        self.assertEqual(params['f0_0'], 100)
        self.assertIsInstance(params['f0_0'], int)

    def test_filter_integer_in_values_coerced(self) -> None:
        """Each value in an ``in`` list is coerced independently."""
        response = self._list_with_filter('filter=replica_count:in:1,2,3')
        self.assertEqual(response.status_code, 200)
        params = self.mock_db.execute.call_args.args[1]
        self.assertEqual(
            [params['f0_0'], params['f0_1'], params['f0_2']], [1, 2, 3]
        )

    def test_filter_number_invalid_value_rejected(self) -> None:
        response = self._list_with_filter('filter=coverage:eq:lots')
        self.assertEqual(response.status_code, 400)
        self.assertIn('numeric', response.json()['detail'])

    def test_filter_integer_fractional_value_rejected(self) -> None:
        response = self._list_with_filter('filter=replica_count:eq:1.5')
        self.assertEqual(response.status_code, 400)
        self.assertIn('integer', response.json()['detail'])

    def test_filter_number_non_finite_values_rejected(self) -> None:
        """agtype has no NaN/Infinity literal, so reject them."""
        for value in ('nan', 'inf', '-inf', 'Infinity'):
            with self.subTest(value=value):
                response = self._list_with_filter(
                    f'filter=coverage:eq:{value}'
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn('finite', response.json()['detail'])

    def test_filter_string_value_unchanged(self) -> None:
        """String attributes still bind the raw string."""
        response = self._list_with_filter('filter=framework:eq:FastAPI')
        self.assertEqual(response.status_code, 200)
        params = self.mock_db.execute.call_args.args[1]
        self.assertEqual(params['f0_0'], 'FastAPI')

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
                'imbi.common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.nanoid.generate',
                return_value=PROJECT_ID,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.dispatch_lifecycle',
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
                'imbi.common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.dispatch_lifecycle',
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
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi.api.endpoints.projects.dispatch_lifecycle',
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
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi.api.endpoints.projects.dispatch_lifecycle',
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

    def test_patch_dispatches_relocated_on_team_change(self) -> None:
        """A team reassignment relocates, with no transfer flag needed.

        Team-keyed lifecycle plugins (e.g. PagerDuty) repoint on an
        owning-team change, so a bare ``/team_slug`` patch dispatches
        ``relocated`` carrying ``previous_team_slug`` -- and does so
        without ``?transfer_repository=true`` and without a type change.
        """
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
            [{'project': existing, 'outbound_count': 0, 'inbound_count': 0}],
            [{'slug': 'backend'}],
            [{'pt_slug': 'api-service', 'found': True}],
            [{'project': updated, 'outbound_count': 0, 'inbound_count': 0}],
        ]
        self._dispatch_patcher.stop()
        with (
            mock.patch('imbi.common.blueprints.get_model') as mock_get_model,
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi.api.endpoints.projects.dispatch_lifecycle',
                new=mock.AsyncMock(return_value=[]),
            ) as mock_dispatch,
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
        mock_dispatch.assert_awaited_once()
        call = mock_dispatch.await_args
        self.assertEqual(call.args[3], 'relocated')
        self.assertEqual(call.kwargs['previous_team_slug'], 'platform')

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
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.dispatch_lifecycle',
                new=mock.AsyncMock(return_value=[]),
            ) as mock_dispatch,
            mock.patch(
                'imbi.api.endpoints.projects.build_lifecycle_context_bundle',
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

    def test_delete_resolves_bindings_before_delete(self) -> None:
        """Lifecycle bindings resolve *before* the DETACH DELETE.

        Regression for IMBI-3T: resolving the project's plugin bindings
        after the node was deleted raised ``LookupError`` -> a spurious
        "Project not found" logged from the dispatcher. The endpoint must
        resolve them first and hand the snapshot to ``dispatch_lifecycle``
        so no post-delete lookup happens.
        """
        from imbi.api.plugins.resolution import ResolvedCapability

        resolved = ResolvedCapability(
            integration_id='p-a',
            integration_slug='gh-a',
            plugin_slug='gh-a',
            kind='lifecycle',
            entry=mock.MagicMock(),
            capability_cls=lambda: mock.AsyncMock(),  # type: ignore[arg-type]
            integration={},
            integration_options={},
            capability_options={},
            encrypted_credentials={},
        )

        order: list[str] = []

        async def _resolve(
            *_a: typing.Any, **_k: typing.Any
        ) -> list[ResolvedCapability]:
            order.append('resolve')
            return [resolved]

        async def _delete(*_a: typing.Any, **_k: typing.Any) -> list[dict]:
            order.append('delete')
            return [{'deleted': 1}]

        self.mock_db.execute.side_effect = _delete

        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.resolve_all_capabilities',
                new=mock.AsyncMock(side_effect=_resolve),
            ),
            mock.patch(
                'imbi.api.endpoints.projects.dispatch_lifecycle',
                new=mock.AsyncMock(return_value=[]),
            ) as mock_dispatch,
        ):
            response = self.client.delete(
                f'/organizations/engineering/projects/{PROJECT_ID}',
            )

        self.assertEqual(response.status_code, 200)
        # Bindings resolved before the DETACH DELETE ran.
        self.assertEqual(order, ['resolve', 'delete'])
        # ...and the pre-delete snapshot was handed to the dispatcher so
        # it never re-resolves against the deleted node.
        mock_dispatch.assert_awaited_once()
        self.assertEqual(
            mock_dispatch.await_args.kwargs['resolved_list'], [resolved]
        )

    def test_preview_returns_would_relocate_per_plugin(self) -> None:
        """``GET /lifecycle/preview`` fans out per plugin and flags diffs.

        Stubs ``resolve_all_capabilities`` with two capabilities whose
        handlers return different ``resolve_relocation_target`` outputs
        for the current vs hypothetical type set, and asserts the
        preview rows carry the expected ``would_relocate`` flags.
        """
        from imbi.api.plugins.resolution import ResolvedCapability
        from imbi.common.plugins.base import RelocationTarget

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

        plugin_a = ResolvedCapability(
            integration_id='p-a',
            integration_slug='gh-a',
            plugin_slug='gh-a',
            kind='lifecycle',
            entry=mock.MagicMock(),
            capability_cls=lambda: plugin_a_handler,  # type: ignore[arg-type]
            integration={},
            integration_options={},
            capability_options={},
            encrypted_credentials={},
        )
        plugin_b = ResolvedCapability(
            integration_id='p-b',
            integration_slug='gh-b',
            plugin_slug='gh-b',
            kind='lifecycle',
            entry=mock.MagicMock(),
            capability_cls=lambda: plugin_b_handler,  # type: ignore[arg-type]
            integration={},
            integration_options={},
            capability_options={},
            encrypted_credentials={},
        )

        self.mock_db.execute.side_effect = [[{'id': PROJECT_ID}]]
        with (
            mock.patch(
                'imbi.api.endpoints.projects.build_lifecycle_context_bundle',
                new=mock.AsyncMock(return_value=bundle_value),
            ),
            mock.patch(
                'imbi.api.endpoints.projects.resolve_all_capabilities',
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
                'imbi.api.endpoints.projects.build_lifecycle_context_bundle',
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
                'imbi.api.endpoints.projects.resolve_all_capabilities',
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
                'imbi.api.endpoints.projects.build_lifecycle_context_bundle',
                new=mock.AsyncMock(),
            ) as mock_bundle,
            mock.patch(
                'imbi.api.endpoints.projects.resolve_all_capabilities',
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
        from imbi.api.auth import permissions

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
            'imbi.common.graph.parse_agtype',
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
            'imbi.common.graph.parse_agtype',
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
            'imbi.common.graph.parse_agtype',
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
            'imbi.common.graph.parse_agtype',
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

        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.score_queue'
                '.condition_policies_exist',
                mock.AsyncMock(return_value=False),
            ),
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

        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.score_queue'
                '.condition_policies_exist',
                mock.AsyncMock(return_value=False),
            ),
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
            'imbi.common.graph.parse_agtype',
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
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(self._target_url('missing-target'))

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_self_reference_rejected(self) -> None:
        """Returns 400 when source and target are the same project."""
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(self._target_url(PROJECT_ID))

        self.assertEqual(response.status_code, 400)
        self.assertIn('itself', response.json()['detail'])
        self.mock_db.execute.assert_not_called()

    def test_create_enqueues_source_recompute(self) -> None:
        """Adding a dependency re-scores the source project."""
        self.mock_db.execute.return_value = [{'source_id': PROJECT_ID}]

        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.score_queue'
                '.condition_policies_exist',
                mock.AsyncMock(return_value=True),
            ),
            mock.patch(
                'imbi.api.endpoints.projects.score_queue.enqueue_recompute',
                mock.AsyncMock(return_value=True),
            ) as enqueue,
        ):
            response = self.client.post(self._target_url('target1'))

        self.assertEqual(response.status_code, 204)
        enqueue.assert_awaited_once()
        self.assertEqual(enqueue.await_args.args[1], PROJECT_ID)
        self.assertEqual(enqueue.await_args.args[2], 'dependency_change')

    def test_create_skips_recompute_without_condition_policy(self) -> None:
        """No re-score is enqueued when no condition policy exists."""
        self.mock_db.execute.return_value = [{'source_id': PROJECT_ID}]

        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.score_queue'
                '.condition_policies_exist',
                mock.AsyncMock(return_value=False),
            ),
            mock.patch(
                'imbi.api.endpoints.projects.score_queue.enqueue_recompute',
                mock.AsyncMock(return_value=True),
            ) as enqueue,
        ):
            response = self.client.post(self._target_url('target1'))

        self.assertEqual(response.status_code, 204)
        enqueue.assert_not_awaited()


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

        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.score_queue'
                '.condition_policies_exist',
                mock.AsyncMock(return_value=False),
            ),
        ):
            response = self.client.delete(self._target_url('target1'))

        self.assertEqual(response.status_code, 204)
        query = self.mock_db.execute.call_args.args[0]
        self.assertIn('DELETE r', query)
        self.assertIn('DEPENDS_ON', query)

    def test_delete_enqueues_source_recompute(self) -> None:
        """Removing a dependency re-scores the source project."""
        self.mock_db.execute.return_value = [{'source_id': PROJECT_ID}]

        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.score_queue'
                '.condition_policies_exist',
                mock.AsyncMock(return_value=True),
            ),
            mock.patch(
                'imbi.api.endpoints.projects.score_queue.enqueue_recompute',
                mock.AsyncMock(return_value=True),
            ) as enqueue,
        ):
            response = self.client.delete(self._target_url('target1'))

        self.assertEqual(response.status_code, 204)
        enqueue.assert_awaited_once()
        self.assertEqual(enqueue.await_args.args[1], PROJECT_ID)
        self.assertEqual(enqueue.await_args.args[2], 'dependency_change')

    def test_delete_skips_recompute_without_condition_policy(self) -> None:
        """No re-score is enqueued when no condition policy exists."""
        self.mock_db.execute.return_value = [{'source_id': PROJECT_ID}]

        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.projects.score_queue'
                '.condition_policies_exist',
                mock.AsyncMock(return_value=False),
            ),
            mock.patch(
                'imbi.api.endpoints.projects.score_queue.enqueue_recompute',
                mock.AsyncMock(return_value=True),
            ) as enqueue,
        ):
            response = self.client.delete(self._target_url('target1'))

        self.assertEqual(response.status_code, 204)
        enqueue.assert_not_awaited()

    def test_edge_missing(self) -> None:
        """Returns 404 when the edge does not exist."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(self._target_url('target1'))

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])


class EmitChangeEventsTestCase(unittest.IsolatedAsyncioTestCase):
    """Tests for the project-change events emitter."""

    async def test_no_changes_skips_clickhouse_insert(self) -> None:
        from imbi.api.endpoints import projects

        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance'
        ) as mock_get:
            await projects._emit_change_events(
                'p1', 'alice', {'name': 'A'}, {'name': 'A'}
            )
        mock_get.assert_not_called()

    async def test_emits_one_row_per_changed_field(self) -> None:
        from imbi.api.endpoints import projects

        mock_instance = mock.AsyncMock()
        mock_instance.insert = mock.AsyncMock()
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
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
        from imbi.api.endpoints import projects

        mock_instance = mock.AsyncMock()
        mock_instance.insert = mock.AsyncMock()
        with mock.patch(
            'imbi.api.endpoints.projects.ch_client.Clickhouse.get_instance',
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
        from imbi.api.endpoints import projects

        mock_instance = mock.AsyncMock()
        mock_instance.insert = mock.AsyncMock(side_effect=RuntimeError('boom'))
        with (
            mock.patch(
                'imbi.api.endpoints.projects.ch_client.Clickhouse.'
                'get_instance',
                return_value=mock_instance,
            ),
            self.assertLogs('imbi.api.endpoints.projects', level='ERROR'),
        ):
            # Must not raise even when ClickHouse insert fails
            await projects._emit_change_events(
                'p1', 'alice', {'name': 'A'}, {'name': 'B'}
            )


class ReleaseSummaryTimestampTestCase(unittest.IsolatedAsyncioTestCase):
    """The projects-list release summary must emit offset-bearing times.

    ``_fetch_release_summaries`` reads ``tagged_at``/``recorded_at`` from
    the ClickHouse ``tags`` table and ``authored_at`` from ``commits``.
    DateTime64 columns come back naive, so passing them straight into
    ``ReleaseSummary`` serialized them without an offset and the browser
    read them in its own zone — head-commit and latest-tag dates on the
    projects list drifted by that zone's offset.
    """

    # Naive on purpose: ClickHouse returns naive DateTime64 values.
    NAIVE = datetime.datetime(2026, 1, 1, 12, 0, 0)  # noqa: DTZ001

    async def _summaries(
        self, tag_row: dict[str, typing.Any] | None
    ) -> typing.Any:
        from imbi.api.endpoints import projects

        tag_rows = [tag_row] if tag_row else []
        head_rows = [
            {
                'project_id': 'p1',
                'sha': 'a' * 40,
                'short_sha': 'aaaaaaa',
                'author_name': 'Alice',
                'author_user': 'alice',
                'authored_at': self.NAIVE,
            }
        ]
        # Four queries: tags, head commit, authored times for the tagged
        # commits, then the commit counts since the tag.
        with mock.patch(
            'imbi.api.endpoints.projects.clickhouse.query',
            mock.AsyncMock(side_effect=[tag_rows, head_rows, [], []]),
        ):
            result = await projects._fetch_release_summaries(['p1'])
        return result['p1']

    def _assert_utc(self, value: datetime.datetime | None) -> None:
        self.assertIsNotNone(value)
        assert value is not None
        self.assertEqual(value.utcoffset(), datetime.timedelta(0))
        self.assertEqual(value, self.NAIVE.replace(tzinfo=datetime.UTC))

    async def test_head_authored_at_carries_utc_offset(self) -> None:
        summary = await self._summaries(None)
        self._assert_utc(summary.head_authored_at)

    async def test_latest_tag_at_carries_utc_offset(self) -> None:
        summary = await self._summaries(
            {
                'project_id': 'p1',
                'name': 'v1.0.0',
                'sha': 'b' * 40,
                'tagged_at': self.NAIVE,
                'recorded_at': None,
                'tagger_name': 'Rel Bot',
            }
        )
        self._assert_utc(summary.latest_tag_at)

    async def test_latest_tag_at_falls_back_to_recorded_at(self) -> None:
        summary = await self._summaries(
            {
                'project_id': 'p1',
                'name': 'v1.0.0',
                'sha': 'b' * 40,
                'tagged_at': None,
                'recorded_at': self.NAIVE,
                'tagger_name': '',
            }
        )
        self._assert_utc(summary.latest_tag_at)

    async def test_latest_tag_at_is_none_when_undated(self) -> None:
        summary = await self._summaries(
            {
                'project_id': 'p1',
                'name': 'v1.0.0',
                'sha': 'b' * 40,
                'tagged_at': None,
                'recorded_at': None,
                'tagger_name': '',
            }
        )
        self.assertIsNone(summary.latest_tag_at)


class ReleaseSummaryRankingTestCase(unittest.IsolatedAsyncioTestCase):
    """The projects list must name the same release as the Releases tab.

    Both rank the ClickHouse ``tags`` rows with
    ``versioning.latest_release_tag``, keyed on the tagged commit's
    authored time.  While this endpoint carried its own highest-semver
    copy of that logic, a stray high-numbered tag from an abandoned
    versioning scheme won here and lost there, so one project reported
    two different current releases (#279).
    """

    def _tags(self) -> list[dict[str, typing.Any]]:
        # Trimmed from the mcp-grafana tag set in #279: 1.0.0 is a
        # leftover on the oldest commit, 0.17.0-2 is on HEAD.
        return [
            {
                'project_id': 'p1',
                'name': '1.0.0',
                'sha': 'b' * 40,
                'tagged_at': datetime.datetime(2025, 6, 4),  # noqa: DTZ001
                'recorded_at': None,
                'tagger_name': '',
            },
            {
                'project_id': 'p1',
                'name': '0.17.0-2',
                'sha': 'c' * 40,
                'tagged_at': datetime.datetime(2026, 8, 21),  # noqa: DTZ001
                'recorded_at': None,
                'tagger_name': 'Rel Bot',
            },
        ]

    async def _latest_tag(
        self, authored_rows: list[dict[str, typing.Any]]
    ) -> typing.Any:
        from imbi.api.endpoints import projects

        head_rows = [
            {
                'project_id': 'p1',
                'sha': 'c' * 40,
                'short_sha': 'c' * 7,
                'author_name': 'Alice',
                'author_user': 'alice',
                'authored_at': datetime.datetime(2026, 8, 19),  # noqa: DTZ001
            }
        ]
        with mock.patch(
            'imbi.api.endpoints.projects.clickhouse.query',
            mock.AsyncMock(
                side_effect=[self._tags(), head_rows, authored_rows, []]
            ),
        ):
            result = await projects._fetch_release_summaries(['p1'])
        return result['p1']

    async def test_tag_on_newest_commit_wins(self) -> None:
        summary = await self._latest_tag(
            [
                {
                    'project_id': 'p1',
                    'sha': 'b' * 40,
                    'authored_at': datetime.datetime(2025, 6, 4),  # noqa: DTZ001
                },
                {
                    'project_id': 'p1',
                    'sha': 'c' * 40,
                    'authored_at': datetime.datetime(2026, 8, 19),  # noqa: DTZ001
                },
            ]
        )
        self.assertEqual(summary.latest_tag, '0.17.0-2')
        self.assertEqual(summary.latest_tag_sha, 'c' * 40)

    async def test_falls_back_to_version_order_without_commits(self) -> None:
        # The commits query answering nothing must not drop the summary;
        # it degrades to highest-version ordering.
        summary = await self._latest_tag([])
        self.assertEqual(summary.latest_tag, '1.0.0')

    async def test_commit_query_failure_is_swallowed(self) -> None:
        from imbi.api.endpoints import projects

        head_rows: list[dict[str, typing.Any]] = []
        with (
            mock.patch(
                'imbi.api.endpoints.projects.clickhouse.query',
                mock.AsyncMock(
                    side_effect=[
                        self._tags(),
                        head_rows,
                        RuntimeError('clickhouse down'),
                        [],
                    ]
                ),
            ),
            self.assertLogs('imbi.api.endpoints.projects', level='WARNING'),
        ):
            result = await projects._fetch_release_summaries(['p1'])
        # Still a summary, ranked without commit context.
        self.assertEqual(result['p1'].latest_tag, '1.0.0')


class ParamBatchTestCase(unittest.TestCase):
    """The authored-times parameters must stay under the form-field cap.

    ``clickhouse.query`` sends each bound parameter as an HTTP form
    field, which ClickHouse caps at ``http_max_field_value_size``
    (131072 bytes).  One query carrying every tagged sha in the org
    breached it -- measured at 2979 shas against production -- and the
    swallowed failure took the *whole* org's ranking back to
    highest-version order, so the projects list named 1.0.0 while the
    Releases tab named 0.17.0-2 (#281).
    """

    def _budget(self) -> int:
        from imbi.api.endpoints import projects

        return projects._PARAM_BYTE_BUDGET

    def _batches(
        self, shas_by_project: dict[str, list[str]]
    ) -> list[tuple[list[str], list[str]]]:
        from imbi.api.endpoints import projects

        return projects._param_batches(shas_by_project)

    def _assert_within_budget(
        self, batches: list[tuple[list[str], list[str]]]
    ) -> None:
        budget = self._budget()
        for pids, shas in batches:
            for values in (pids, shas):
                size = sum(len(value) + 3 for value in values)
                self.assertLessEqual(size, budget)

    def test_small_input_is_a_single_batch(self) -> None:
        # The common case must not pay for extra round trips.
        batches = self._batches({'p1': ['a' * 40, 'b' * 40]})
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0][0], ['p1'])
        self.assertEqual(batches[0][1], ['a' * 40, 'b' * 40])

    def test_org_scale_splits_and_covers_every_sha(self) -> None:
        # 200 projects x 30 tags ~= the production shape that failed.
        shas_by_project = {
            f'p{pid:03d}': [
                f'{pid:03d}{tag:03d}'.ljust(40, 'f') for tag in range(30)
            ]
            for pid in range(200)
        }
        batches = self._batches(shas_by_project)
        self.assertGreater(len(batches), 1)
        self._assert_within_budget(batches)

        expected = {
            (pid, sha) for pid, shas in shas_by_project.items() for sha in shas
        }
        seen = {
            (pid, sha)
            for pids, shas in batches
            for pid in pids
            for sha in shas
        }
        # Every pair is queryable; the batch it lands in doesn't matter
        # because results merge by (project_id, sha).
        self.assertTrue(expected <= seen)

    def test_single_oversized_project_is_split(self) -> None:
        # One project can exceed the budget on its own; it must not be
        # emitted as an unsendable batch.
        shas = [f'{n:040d}' for n in range(5000)]
        batches = self._batches({'p1': shas})
        self.assertGreater(len(batches), 1)
        self._assert_within_budget(batches)
        self.assertEqual(
            {sha for _, batch_shas in batches for sha in batch_shas},
            set(shas),
        )


class ReleaseSummaryBatchedAuthoredTestCase(unittest.IsolatedAsyncioTestCase):
    """Batching must not change the ranking, and must fail narrowly."""

    def setUp(self) -> None:
        self.authored_calls: dict[str, int] = {'n': 0}

    def _tags(self, count: int) -> list[dict[str, typing.Any]]:
        # Every project carries the #279 shape: a leftover high 1.0.0 on
        # an old commit, and the real release on the newest commit.
        rows: list[dict[str, typing.Any]] = []
        for pid in range(count):
            rows.append(
                {
                    'project_id': f'p{pid:03d}',
                    'name': '1.0.0',
                    'sha': f'{pid:03d}old'.ljust(40, 'a'),
                    'tagged_at': datetime.datetime(2025, 6, 4),  # noqa: DTZ001
                    'recorded_at': None,
                    'tagger_name': '',
                }
            )
            rows.append(
                {
                    'project_id': f'p{pid:03d}',
                    'name': '0.17.0-2',
                    'sha': f'{pid:03d}new'.ljust(40, 'b'),
                    'tagged_at': (
                        datetime.datetime(2026, 8, 21)  # noqa: DTZ001
                    ),
                    'recorded_at': None,
                    'tagger_name': 'Rel Bot',
                }
            )
        return rows

    #: Enough projects that the tagged shas exceed the byte budget and
    #: must split -- ~2000 x 2 x 43 bytes vs a 65536 budget, the same
    #: shape as the 4710 shas production carries.
    SCALE = 2000

    def _query(
        self, tag_rows: list[dict[str, typing.Any]], fail_after: int | None
    ) -> mock.AsyncMock:
        authored_calls = self.authored_calls

        async def dispatch(
            sql: str, params: dict[str, typing.Any] | None = None
        ) -> list[dict[str, typing.Any]]:
            params = params or {}
            if 'FROM tags FINAL' in sql:
                return tag_rows
            if 'SELECT project_id, sha, authored_at' in sql:
                authored_calls['n'] += 1
                if fail_after is not None and authored_calls['n'] > fail_after:
                    raise RuntimeError('Field value too long')
                wanted = set(params.get('shas') or [])
                return [
                    {
                        'project_id': row['project_id'],
                        'sha': row['sha'],
                        'authored_at': (
                            datetime.datetime(2025, 6, 4)  # noqa: DTZ001
                            if row['name'] == '1.0.0'
                            else datetime.datetime(2026, 8, 19)  # noqa: DTZ001
                        ),
                    }
                    for row in tag_rows
                    if row['sha'] in wanted
                    and row['project_id']
                    in set(params.get('project_ids') or [])
                ]
            return []

        return mock.AsyncMock(side_effect=dispatch)

    async def test_ranking_survives_org_scale(self) -> None:
        from imbi.api.endpoints import projects

        tag_rows = self._tags(self.SCALE)
        pids = sorted({str(row['project_id']) for row in tag_rows})
        with mock.patch(
            'imbi.api.endpoints.projects.clickhouse.query',
            self._query(tag_rows, fail_after=None),
        ):
            result = await projects._fetch_release_summaries(pids)
        # The batching is the point of the test, so assert it happened
        # rather than trusting the payload stayed oversized.
        self.assertGreater(self.authored_calls['n'], 1)
        # Before #281 this returned 1.0.0 for every project, because the
        # one oversized query failed and the map came back empty.
        self.assertEqual(len(result), self.SCALE)
        for pid in pids:
            self.assertEqual(result[pid].latest_tag, '0.17.0-2')

    async def test_one_failed_batch_degrades_only_its_projects(self) -> None:
        from imbi.api.endpoints import projects

        tag_rows = self._tags(self.SCALE)
        pids = sorted({str(row['project_id']) for row in tag_rows})
        with (
            mock.patch(
                'imbi.api.endpoints.projects.clickhouse.query',
                self._query(tag_rows, fail_after=1),
            ),
            self.assertLogs(
                'imbi.api.endpoints.projects', level='ERROR'
            ) as logs,
        ):
            result = await projects._fetch_release_summaries(pids)
        ranked = [s.latest_tag for s in result.values()]
        # The first batch still ranks correctly; the rest fall back.
        self.assertIn('0.17.0-2', ranked)
        self.assertIn('1.0.0', ranked)
        self.assertIn('fall back to highest-version', logs.output[0])

    async def test_partial_project_takes_the_fallback_whole(self) -> None:
        # A project straddling a batch boundary must not rank from the
        # half of its tags that happened to survive: the resolved tags
        # would outrank the unresolved ones whatever their commits, which
        # is neither correct nor the documented fallback.
        from imbi.api.endpoints import projects

        # One project big enough to span batches on its own.
        shas = [f'{n:040d}' for n in range(4000)]
        batches = projects._param_batches({'p1': shas})
        self.assertGreater(len(batches), 1, 'expected a split project')

        calls = {'n': 0}

        async def dispatch(
            sql: str, params: dict[str, typing.Any] | None = None
        ) -> list[dict[str, typing.Any]]:
            calls['n'] += 1
            if calls['n'] > 1:
                raise RuntimeError('Field value too long')
            return [
                {
                    'project_id': 'p1',
                    'sha': sha,
                    'authored_at': (
                        datetime.datetime(2026, 8, 19)  # noqa: DTZ001
                    ),
                }
                for sha in (params or {}).get('shas', [])
            ]

        with (
            mock.patch(
                'imbi.api.endpoints.projects.clickhouse.query',
                mock.AsyncMock(side_effect=dispatch),
            ),
            self.assertLogs('imbi.api.endpoints.projects', level='ERROR'),
        ):
            authored = await projects._fetch_authored_times({'p1': shas})
        # The first batch succeeded, but p1 is degraded overall, so it
        # must carry no authored times at all rather than a partial set.
        self.assertNotIn('p1', authored)


class ReleaseSummaryDelayedTagTestCase(unittest.IsolatedAsyncioTestCase):
    """A tag cut after its commit must not hide the commits between.

    ``latest_release_tag`` picks the tag by its commit's authored time,
    so the unreleased range has to start there too -- release-drift
    bounds its own range with exactly that value.  Measuring from
    ``tagged_at`` instead dropped every commit authored between the
    tagged commit and the moment the tag was pushed, so the projects
    list reported fewer unreleased commits, and a cleaner
    ``drift_detected``, than the same project's Releases tab (#279).
    """

    TAG_SHA = 'b' * 40
    # The tag names a January commit but was not pushed until February.
    COMMIT_AUTHORED = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    TAG_PUSHED = datetime.datetime(2026, 2, 1)  # noqa: DTZ001

    async def _count_params(
        self, authored_rows: list[dict[str, typing.Any]]
    ) -> dict[str, typing.Any]:
        from imbi.api.endpoints import projects

        tag_rows = [
            {
                'project_id': 'p1',
                'name': '1.0.0',
                'sha': self.TAG_SHA,
                'tagged_at': self.TAG_PUSHED,
                'recorded_at': None,
                'tagger_name': 'Rel Bot',
            }
        ]
        # tags, head commit, authored times, then the counts query whose
        # bound params carry the range boundary under test.
        query = mock.AsyncMock(side_effect=[tag_rows, [], authored_rows, []])
        with mock.patch('imbi.api.endpoints.projects.clickhouse.query', query):
            await projects._fetch_release_summaries(['p1'])
        return query.await_args_list[-1].args[1]

    async def test_cutoff_is_the_tagged_commits_authored_time(self) -> None:
        params = await self._count_params(
            [
                {
                    'project_id': 'p1',
                    'sha': self.TAG_SHA,
                    'authored_at': self.COMMIT_AUTHORED,
                }
            ]
        )
        self.assertEqual(params['cuts'], [self.COMMIT_AUTHORED])
        # Mode 1 compares ``authored_at``, the column release-drift
        # filters on, so both views bound the range identically.
        self.assertEqual(params['modes'], [1])

    async def test_cutoff_falls_back_when_tagged_commit_unsynced(self) -> None:
        # No authored time to measure from, so the tag timestamp stands
        # in and mode 0 keeps the committer-date comparison.
        params = await self._count_params([])
        self.assertEqual(
            params['cuts'], [self.TAG_PUSHED.replace(tzinfo=datetime.UTC)]
        )
        self.assertEqual(params['modes'], [0])
