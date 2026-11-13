"""Tests for organization CRUD endpoints."""

import datetime
import typing
import uuid
from unittest import mock

import httpx
import psycopg.errors
from fastapi import testclient

from apps.api.tests import support
from imbi.api import agent_tasks, models, secret_broker, workflows
from imbi.common import graph


class OrganizationEndpointsTestCase(support.SharedAppTestCase):
    """Test cases for organization CRUD endpoints."""

    def setUp(self) -> None:
        """Set up test app with admin authentication context."""
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
                'organization:create',
                'organization:read',
                'organization:update',
                'organization:delete',
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
        self.secret_store = mock.AsyncMock(
            spec=secret_broker.store.SecretStore
        )
        self.secret_store.list_all.return_value = []
        self.secret_store.identity_source.return_value = None
        self.test_app.dependency_overrides[secret_broker._inject_store] = (
            lambda: self.secret_store
        )
        # The delete transaction: Cypher goes to mock_db.execute, and
        # each relational count is 0.
        cursor = mock.AsyncMock()
        cursor.fetchone.return_value = (0,)
        self.mock_conn = mock.AsyncMock()
        self.mock_conn.execute.return_value = cursor

        async def locked_with_connection(
            _key: str, work: typing.Any
        ) -> typing.Any:
            return await work(self.mock_db.execute, self.mock_conn)

        self.mock_db.locked_with_connection.side_effect = (
            locked_with_connection
        )

        self.client = testclient.TestClient(self.test_app)

        self.test_org = models.Organization(
            name='Engineering',
            slug='engineering',
            description='Engineering organization',
        )

    def test_create_organization_success(self) -> None:
        """Test successful organization creation."""
        self.mock_db.create.return_value = self.test_org

        response = self.client.post(
            '/organizations/',
            json={
                'name': 'Engineering',
                'slug': 'engineering',
                'description': 'Engineering organization',
            },
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'engineering')
        self.assertEqual(data['name'], 'Engineering')
        self.assertIn('relationships', data)
        rels = data['relationships']
        self.assertIn('teams', rels)
        self.assertIn('members', rels)
        self.assertIn('projects', rels)
        self.assertEqual(
            rels['teams']['count'],
            0,
        )
        self.assertEqual(
            rels['members']['count'],
            0,
        )
        self.assertEqual(
            rels['projects']['count'],
            0,
        )

    def test_create_organization_validation_error(self) -> None:
        """Test creating organization with invalid data."""
        response = self.client.post(
            '/organizations/',
            json={
                'name': 'Engineering',
                # Missing required 'slug' field
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_create_organization_duplicate_slug(self) -> None:
        """Test creating organization with duplicate slug."""
        self.mock_db.create.side_effect = psycopg.errors.UniqueViolation(
            'Duplicate'
        )

        response = self.client.post(
            '/organizations/',
            json={
                'name': 'Engineering',
                'slug': 'engineering',
                'description': 'Engineering organization',
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    def test_create_organization_invalid_slug(self) -> None:
        """Slugs that are not identifiers are rejected with 422."""
        for value in ('Engineering', 'eng_ops', 'eng ops', '-eng', 'a' * 64):
            with self.subTest(value=value):
                response = self.client.post(
                    '/organizations/',
                    json={'name': 'Engineering', 'slug': value},
                )
                self.assertEqual(response.status_code, 422)
        self.mock_db.create.assert_not_called()

    def test_create_organization_accepts_identifier_slug(self) -> None:
        """Lower-case letters, digits, and hyphens are accepted."""
        self.mock_db.create.return_value = models.Organization(
            name='Engineering', slug='0-eng-2'
        )

        response = self.client.post(
            '/organizations/',
            json={'name': 'Engineering', 'slug': '0-eng-2'},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['slug'], '0-eng-2')

    def test_list_organizations(self) -> None:
        """Test listing all organizations.

        ``parse_agtype`` is left unmocked: the helper already returns
        non-string values unchanged, so the mocked ``execute`` returning
        Python dicts/ints round-trips through the real parser the same
        way it does in production — making this an actual exercise of
        the endpoint plus parser instead of an identity-mock no-op.
        """
        self.mock_db.execute.return_value = [
            {
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                    'description': 'Engineering organization',
                },
                'team_count': 3,
                'member_count': 10,
                'project_count': 25,
            },
        ]

        response = self.client.get('/organizations/')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'engineering')
        rels = data[0]['relationships']
        self.assertEqual(
            rels['teams']['count'],
            3,
        )
        self.assertEqual(
            rels['teams']['href'],
            '/organizations/engineering/teams',
        )
        self.assertEqual(
            rels['members']['count'],
            10,
        )
        self.assertEqual(
            rels['members']['href'],
            '/organizations/engineering/members',
        )
        self.assertEqual(
            rels['projects']['count'],
            25,
        )
        self.assertEqual(
            rels['projects']['href'],
            '/organizations/engineering/projects',
        )

    def test_get_organization(self) -> None:
        """Test retrieving single organization."""
        self.mock_db.execute.return_value = [
            {
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                    'description': 'Engineering organization',
                },
                'team_count': 2,
                'member_count': 5,
                'project_count': 12,
            },
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'engineering')
        self.assertEqual(data['name'], 'Engineering')
        rels = data['relationships']
        self.assertEqual(
            rels['teams']['count'],
            2,
        )

    def test_get_organization_not_found(self) -> None:
        """Test retrieving non-existent organization."""
        self.mock_db.execute.return_value = []

        response = self.client.get(
            '/organizations/nonexistent',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn(
            'not found',
            response.json()['detail'],
        )

    def test_delete_organization(self) -> None:
        """An empty organization is deleted."""
        # org id, contents, delete
        self.mock_db.execute.side_effect = [
            [{'id': 'org-1'}],
            [],
            [{'deleted': 1}],
        ]

        response = self.client.delete(
            '/organizations/engineering',
        )

        self.assertEqual(response.status_code, 204)
        self.secret_store.list_all.assert_awaited_once_with(
            'providers', 'org-1'
        )
        self.secret_store.identity_source.assert_awaited_once_with('org-1')
        self.assertIn(
            'DETACH DELETE o', self.mock_db.execute.await_args.args[0]
        )

    def test_delete_organization_not_empty(self) -> None:
        """Nodes or secret providers in the organization block the delete."""
        self.secret_store.list_all.return_value = [{}, {}]
        self.mock_db.execute.side_effect = [
            [{'id': 'org-1'}],
            [{'label': 'Team', 'n': 3}, {'label': 'Agent', 'n': 1}],
        ]

        response = self.client.delete(
            '/organizations/engineering',
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['detail'],
            "Organization 'engineering' is not empty: Agent (1), Team (3), "
            'secret providers (2). Delete these first.',
        )
        self.assertEqual(self.mock_db.execute.await_count, 2)

    def test_delete_organization_with_secrets_only(self) -> None:
        """An identity source alone blocks the delete."""
        self.secret_store.identity_source.return_value = {}
        self.mock_db.execute.side_effect = [[{'id': 'org-1'}], []]

        response = self.client.delete(
            '/organizations/engineering',
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn('identity sources (1)', response.json()['detail'])

    def test_delete_organization_not_found(self) -> None:
        """Test deleting non-existent organization."""
        self.mock_db.execute.return_value = []

        response = self.client.delete(
            '/organizations/nonexistent',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn(
            'not found',
            response.json()['detail'],
        )

    def test_patch_organization_name(self) -> None:
        """Test patching only the organization name."""
        self.mock_db.match.return_value = [self.test_org]
        self.mock_db.execute.side_effect = [
            [{'n': 'true'}],  # SET query
            [
                {'team_count': 1, 'member_count': 2, 'project_count': 3}
            ],  # counts
        ]

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                '/organizations/engineering',
                json=[{'op': 'replace', 'path': '/name', 'value': 'Eng Dept'}],
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'Eng Dept')
        self.assertIn('relationships', data)

    def test_patch_organization_not_found(self) -> None:
        """Test patching non-existent organization returns 404."""
        self.mock_db.match.return_value = []

        response = self.client.patch(
            '/organizations/nonexistent',
            json=[{'op': 'replace', 'path': '/name', 'value': 'Test'}],
        )

        self.assertEqual(response.status_code, 404)

    def test_patch_organization_readonly_field(self) -> None:
        """Test patching created_at returns 400."""
        self.mock_db.match.return_value = [self.test_org]

        response = self.client.patch(
            '/organizations/engineering',
            json=[
                {
                    'op': 'replace',
                    'path': '/created_at',
                    'value': '2025-01-01T00:00:00Z',
                }
            ],
        )

        self.assertEqual(response.status_code, 400)

    def test_patch_organization_slug_conflict(self) -> None:
        """Test slug rename to conflicting slug returns 409."""
        self.mock_db.match.return_value = [self.test_org]
        # First call fetches existing previous_slugs (L9), then the
        # actual SET raises the unique-violation we're testing for.
        self.mock_db.execute.side_effect = [
            [{'previous_slugs': None}],
            psycopg.errors.UniqueViolation('Duplicate'),
        ]

        response = self.client.patch(
            '/organizations/engineering',
            json=[{'op': 'replace', 'path': '/slug', 'value': 'taken-slug'}],
        )

        self.assertEqual(response.status_code, 409)

    def test_patch_organization_concurrent_delete(self) -> None:
        """Update query returning no rows yields 404."""
        self.mock_db.match.return_value = [self.test_org]
        self.mock_db.execute.side_effect = [[]]

        response = self.client.patch(
            '/organizations/engineering',
            json=[{'op': 'replace', 'path': '/name', 'value': 'Renamed'}],
        )

        self.assertEqual(response.status_code, 404)

    def test_patch_organization_validation_error(self) -> None:
        """Patch that yields invalid model returns 400."""
        self.mock_db.match.return_value = [self.test_org]

        response = self.client.patch(
            '/organizations/engineering',
            json=[{'op': 'replace', 'path': '/name', 'value': None}],
        )

        self.assertEqual(response.status_code, 400)

    def test_patch_organization_invalid_slug(self) -> None:
        """Patch to a slug that is not an identifier returns 400."""
        self.mock_db.match.return_value = [self.test_org]

        for value in ('Bad Slug', '-lead', 'a/b', 'a' * 64, ''):
            with self.subTest(value=value):
                response = self.client.patch(
                    '/organizations/engineering',
                    json=[{'op': 'replace', 'path': '/slug', 'value': value}],
                )
                self.assertEqual(response.status_code, 400)
        self.mock_db.execute.assert_not_called()

    def test_patch_organization_rename_captures_previous_slug(self) -> None:
        """L9: renaming an org appends the old slug to previous_slugs."""
        self.mock_db.match.return_value = [self.test_org]
        # 1st execute = fetch previous_slugs (none yet); 2nd execute
        # = SET; 3rd execute = the count query in _persist_organization.
        renamed_org = {
            'id': self.test_org.id,
            'name': self.test_org.name,
            'slug': 'eng',
            'description': self.test_org.description,
            'icon': self.test_org.icon,
            'created_at': self.test_org.created_at.isoformat(),
            'updated_at': self.test_org.updated_at,
            'previous_slugs': ['engineering'],
        }
        self.mock_db.execute.side_effect = [
            [{'previous_slugs': None}],
            [{'n': renamed_org}],
            [
                {
                    'team_count': 0,
                    'member_count': 0,
                    'project_count': 0,
                }
            ],
        ]

        response = self.client.patch(
            '/organizations/engineering',
            json=[{'op': 'replace', 'path': '/slug', 'value': 'eng'}],
        )

        self.assertEqual(response.status_code, 200)
        # The SET call (call_args_list[1]) should have received the
        # original slug as the new previous_slugs entry.
        set_call = self.mock_db.execute.call_args_list[1]
        params = set_call.args[1]
        self.assertEqual(params['previous_slugs'], ['engineering'])
        self.assertEqual(params['slug'], 'eng')
        self.assertEqual(params['original_slug'], 'engineering')

    def test_patch_organization_no_rename_skips_previous_slugs(
        self,
    ) -> None:
        """L9: a non-slug update does not touch previous_slugs."""
        self.mock_db.match.return_value = [self.test_org]
        renamed_org = {
            'id': self.test_org.id,
            'name': 'New Name',
            'slug': self.test_org.slug,
            'description': self.test_org.description,
            'icon': self.test_org.icon,
            'created_at': self.test_org.created_at.isoformat(),
            'updated_at': self.test_org.updated_at,
        }
        # No previous_slugs fetch on the non-rename path: just SET then
        # the count query.
        self.mock_db.execute.side_effect = [
            [{'n': renamed_org}],
            [
                {
                    'team_count': 0,
                    'member_count': 0,
                    'project_count': 0,
                }
            ],
        ]

        response = self.client.patch(
            '/organizations/engineering',
            json=[{'op': 'replace', 'path': '/name', 'value': 'New Name'}],
        )

        self.assertEqual(response.status_code, 200)
        set_call = self.mock_db.execute.call_args_list[0]
        params = set_call.args[1]
        self.assertNotIn('previous_slugs', params)

    def test_patch_organization_tag_formats(self) -> None:
        """Patching tag_formats persists the list in the SET params."""
        self.mock_db.match.return_value = [self.test_org]
        updated_org = {
            'id': self.test_org.id,
            'name': self.test_org.name,
            'slug': self.test_org.slug,
            'description': self.test_org.description,
            'icon': self.test_org.icon,
            'created_at': self.test_org.created_at.isoformat(),
            'updated_at': self.test_org.updated_at,
        }
        self.mock_db.execute.side_effect = [
            [{'n': updated_org}],
            [{'team_count': 0, 'member_count': 0, 'project_count': 0}],
        ]
        formats = [{'label': 'Semver', 'pattern': r'^v?\d+\.\d+\.\d+$'}]

        response = self.client.patch(
            '/organizations/engineering',
            json=[{'op': 'add', 'path': '/tag_formats', 'value': formats}],
        )

        self.assertEqual(response.status_code, 200)
        set_call = self.mock_db.execute.call_args_list[0]
        params = set_call.args[1]
        self.assertEqual(params['tag_formats'], formats)
        # The SET clause must include the tag_formats assignment.
        self.assertIn('n.tag_formats = {tag_formats}', set_call.args[0])

    def test_patch_organization_rejects_invalid_tag_format(self) -> None:
        """An uncompilable regex pattern is rejected with 400."""
        self.mock_db.match.return_value = [self.test_org]

        response = self.client.patch(
            '/organizations/engineering',
            json=[
                {
                    'op': 'add',
                    'path': '/tag_formats',
                    'value': [{'label': 'Bad', 'pattern': '('}],
                }
            ],
        )

        self.assertEqual(response.status_code, 400)


class OrganizationDeleteRelationalTestCase(support.SharedAppAsyncTestCase):
    """The delete against the live Postgres that ``root:services`` boots."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        from imbi.api.auth import permissions

        self.org = f'orgdel-{uuid.uuid4().hex[:10]}'
        await graph.initialize()
        await agent_tasks.initialize()
        await workflows.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.pool = agent_tasks.create_pool()
        await self.pool.open()
        self.addAsyncCleanup(self._cleanup)
        await self.graph.execute(
            'CREATE (o:Organization {{id: {org}, slug: {org}, name: {org}}})'
            ' RETURN o.id AS id',
            {'org': self.org},
            ['id'],
        )
        secrets = mock.AsyncMock(spec=secret_broker.store.SecretStore)
        secrets.list_all.return_value = []
        secrets.identity_source.return_value = None
        admin = models.User(
            email='admin@example.com',
            display_name='Admin',
            is_active=True,
            is_admin=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        async def current_user() -> permissions.AuthContext:
            return permissions.AuthContext(
                user=admin,
                session_id='test-session',
                auth_method='jwt',
                permissions={'organization:delete'},
            )

        overrides = self.test_app.dependency_overrides
        overrides[permissions.get_current_user] = current_user
        overrides[graph._inject_graph] = lambda: self.graph
        overrides[secret_broker._inject_store] = lambda: secrets
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.test_app),
            base_url='http://test',
        )

    async def _cleanup(self) -> None:
        await self.client.aclose()
        await self.graph.execute(
            'MATCH (o:Organization {{id: {org}}}) DETACH DELETE o'
            ' RETURN 1 AS ok',
            {'org': self.org},
            ['ok'],
        )
        async with self.pool.connection() as conn:
            for table in (
                'agent_runtime.task_dependencies',
                'agent_runtime.task_projects',
                'agent_runtime.tasks',
                'agent_runtime.task_id_sequences',
                'workflow_runtime.runs',
                'workflows.trigger_bindings',
                'workflows.workflows',
            ):
                await conn.execute(
                    f'DELETE FROM {table} WHERE organization_id = %s',
                    (self.org,),
                )
        await self.pool.close()
        await self.graph.close()

    async def _count(self, table: str) -> int:
        async with self.pool.connection() as conn:
            cursor = await conn.execute(
                f'SELECT count(*) FROM {table} WHERE organization_id = %s',
                (self.org,),
            )
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def _insert_task(self, conn: typing.Any, short_id: str) -> uuid.UUID:
        task_id = uuid.uuid4()
        await conn.execute(
            'INSERT INTO agent_runtime.tasks (id, organization_id, short_id,'
            ' agent_id, agent_version, service_account_id, title,'
            ' description, origin_kind, origin_id, origin, owner)'
            " VALUES (%s, %s, %s, 'a', 1, 'sa', 't', 'd', 'human', 'u',"
            " '{}', 'o')",
            (task_id, self.org, short_id),
        )
        return task_id

    async def test_task_history_and_runs_are_deleted(self) -> None:
        async with self.pool.connection() as conn:
            first = await self._insert_task(conn, 'T-1')
            second = await self._insert_task(conn, 'T-2')
            await conn.execute(
                'INSERT INTO agent_runtime.task_dependencies (organization_id,'
                ' dependent_task_id, prerequisite_task_id, created_by_kind,'
                " created_by) VALUES (%s, %s, %s, 'human', 'u')",
                (self.org, second, first),
            )
            await conn.execute(
                'INSERT INTO agent_runtime.task_projects (organization_id,'
                ' task_id, project_id, project_slug, added_by_kind,'
                " added_by) VALUES (%s, %s, 'p', 'p', 'human', 'u')",
                (self.org, first),
            )
            await conn.execute(
                'INSERT INTO agent_runtime.events (task_id, seq, event_id,'
                " type, actor_kind, channel) VALUES (%s, 1, %s, 'x', 'human',"
                " 'c')",
                (first, uuid.uuid4()),
            )
            await conn.execute(
                'INSERT INTO agent_runtime.task_id_sequences'
                ' (organization_id, last_value) VALUES (%s, 2)',
                (self.org,),
            )
            await conn.execute(
                'INSERT INTO workflow_runtime.runs (id, organization_id,'
                ' workflow_id, version, trigger_node_id, origin_kind,'
                " origin_id, activated_by) VALUES (%s, %s, %s, 1, 'n',"
                " 'human', 'u', 'u')",
                (uuid.uuid4(), self.org, uuid.uuid4()),
            )

        response = await self.client.delete(f'/organizations/{self.org}')

        self.assertEqual(response.status_code, 204, response.text)
        for table in (
            'agent_runtime.tasks',
            'agent_runtime.task_dependencies',
            'agent_runtime.task_projects',
            'agent_runtime.task_id_sequences',
            'workflow_runtime.runs',
        ):
            self.assertEqual(await self._count(table), 0, table)
        async with self.pool.connection() as conn:
            cursor = await conn.execute(
                'SELECT count(*) FROM agent_runtime.events WHERE task_id = %s',
                (first,),
            )
            self.assertEqual(await cursor.fetchone(), (0,))
        records = await self.graph.execute(
            'MATCH (o:Organization {{id: {org}}}) RETURN o.id AS id',
            {'org': self.org},
            ['id'],
        )
        self.assertEqual(records, [])

    async def test_workflows_and_bindings_block_the_delete(self) -> None:
        workflow_id = uuid.uuid4()
        async with self.pool.connection() as conn:
            await self._insert_task(conn, 'T-1')
            await conn.execute(
                'INSERT INTO workflows.workflows (id, organization_id, slug,'
                " name, owner_team_id, created_by) VALUES (%s, %s, 'w', 'W',"
                " 't', 'u')",
                (workflow_id, self.org),
            )
            await conn.execute(
                'INSERT INTO workflows.trigger_bindings (id, workflow_id,'
                ' organization_id, node_id, type, params) VALUES (%s, %s, %s,'
                " 'n', 'schedule', '{}')",
                (uuid.uuid4(), workflow_id, self.org),
            )

        response = await self.client.delete(f'/organizations/{self.org}')

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()['detail'],
            f"Organization '{self.org}' is not empty: workflow trigger"
            ' bindings (1), workflows (1). Delete these first.',
        )
        # Nothing was deleted.
        self.assertEqual(await self._count('agent_runtime.tasks'), 1)
