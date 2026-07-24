import datetime
import unittest
from unittest import mock

import typer.testing

from imbi.api import entrypoint, models


class SetupTestCase(unittest.TestCase):
    """Test cases for setup command.

    Uses regular TestCase (not IsolatedAsyncioTestCase) because the
    setup command calls asyncio.run() which creates its own event loop.
    That would fail inside an already-running loop.
    """

    def setUp(self) -> None:
        super().setUp()
        self.runner = typer.testing.CliRunner()
        self.admin_user = models.User(
            email='admin@example.com',
            display_name='Administrator',
            password_hash='hashed',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.seed_result = {
            'organization': True,
            'permissions': 5,
            'roles': 3,
        }

        # Graph database lifecycle
        self.mock_graph = mock.MagicMock()
        self.mock_graph.open = mock.AsyncMock()
        self.mock_graph.close = mock.AsyncMock()
        self.mock_graph.execute = mock.AsyncMock(return_value=[])
        self.mock_graph.merge = mock.AsyncMock(return_value=[])
        self.mock_graph_cls = self.enterContext(
            mock.patch.object(
                entrypoint.graph,
                'Graph',
                return_value=self.mock_graph,
            )
        )

        # ClickHouse lifecycle
        self.mock_ch_init = self.enterContext(
            mock.patch.object(
                entrypoint.clickhouse,
                'initialize',
                new_callable=mock.AsyncMock,
            )
        )
        self.mock_ch_close = self.enterContext(
            mock.patch.object(
                entrypoint.clickhouse,
                'aclose',
                new_callable=mock.AsyncMock,
            )
        )
        self.mock_ch_schema = self.enterContext(
            mock.patch.object(
                entrypoint.clickhouse,
                'setup_schema',
                new_callable=mock.AsyncMock,
            )
        )

        # Seed and admin checks
        self.mock_check_seeded = self.enterContext(
            mock.patch.object(
                entrypoint.seed,
                'check_if_seeded',
                new_callable=mock.AsyncMock,
                return_value=False,
            )
        )
        self.mock_check_admin = self.enterContext(
            mock.patch.object(
                entrypoint,
                '_check_admin_exists',
                new_callable=mock.AsyncMock,
                return_value=False,
            )
        )
        self.mock_bootstrap = self.enterContext(
            mock.patch.object(
                entrypoint.seed,
                'bootstrap_auth_system',
                new_callable=mock.AsyncMock,
            )
        )
        self.mock_bootstrap.return_value = self.seed_result

        # Admin user creation
        self.mock_create_admin = self.enterContext(
            mock.patch.object(
                entrypoint,
                '_create_admin_user',
                new_callable=mock.AsyncMock,
            )
        )
        self.mock_create_admin.return_value = self.admin_user

        # Password input (getpass reads /dev/tty, not stdin)
        self.mock_getpass = self.enterContext(
            mock.patch.object(
                entrypoint.getpass,
                'getpass',
                return_value='s3cret',
            )
        )

    def test_setup_fresh_install(self) -> None:
        """Test setup on a fresh system with defaults."""
        result = self.runner.invoke(
            entrypoint.main, ['setup'], input='\n\n\n\n'
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn('Setup complete', result.output)
        self.assertIn('Created organization: AWeber (aweber)', result.output)
        self.assertIn('Created 5 permissions and 3 roles', result.output)
        self.assertIn('Created admin user: admin@example.com', result.output)
        self.assertIn('ClickHouse schema created', result.output)

        self.mock_create_admin.assert_awaited_once_with(
            mock.ANY,
            email='admin@example.com',
            display_name='Administrator',
            password='s3cret',
            org_slug='aweber',
        )
        self.mock_graph.close.assert_awaited_once()
        self.mock_ch_close.assert_awaited_once()

    def test_setup_custom_email_and_display_name(self) -> None:
        """Test setup with user-provided email and display name."""
        result = self.runner.invoke(
            entrypoint.main,
            ['setup'],
            input='\n\ndave@example.com\nDave\n',
        )

        self.assertEqual(result.exit_code, 0)
        self.mock_create_admin.assert_awaited_once_with(
            mock.ANY,
            email='dave@example.com',
            display_name='Dave',
            password='s3cret',
            org_slug='aweber',
        )

    def test_setup_already_seeded_continue(self) -> None:
        """Test setup when already seeded and user confirms."""
        self.mock_check_seeded.return_value = True
        self.mock_check_admin.return_value = True

        result = self.runner.invoke(
            entrypoint.main, ['setup'], input='y\n\n\n\n\n'
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn('already set up', result.output)
        self.assertIn('Setup complete', result.output)
        self.mock_bootstrap.assert_awaited_once()

    def test_setup_already_seeded_cancel(self) -> None:
        """Test setup when already seeded and user declines."""
        self.mock_check_seeded.return_value = True
        self.mock_check_admin.return_value = True

        result = self.runner.invoke(entrypoint.main, ['setup'], input='n\n')

        self.assertEqual(result.exit_code, 0)
        self.assertIn('Setup cancelled', result.output)
        self.mock_bootstrap.assert_not_awaited()
        self.mock_graph.close.assert_awaited_once()
        self.mock_ch_close.assert_awaited_once()

    def test_setup_existing_entities_no_new(self) -> None:
        """Test output when permissions and roles already exist."""
        self.seed_result.update(organization=False, permissions=0, roles=0)

        result = self.runner.invoke(
            entrypoint.main, ['setup'], input='\n\n\n\n'
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn('Organization already exists: aweber', result.output)
        self.assertIn('already exist', result.output)

    def test_setup_graph_connection_failure(self) -> None:
        """Test setup when PostgreSQL/Graph connection fails."""
        self.mock_graph.open.side_effect = ConnectionError('refused')

        result = self.runner.invoke(entrypoint.main, ['setup'])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Failed to connect to PostgreSQL', result.output)
        self.mock_ch_init.assert_not_awaited()

    def test_setup_clickhouse_connection_failure(self) -> None:
        """Test setup when ClickHouse connection fails."""
        self.mock_ch_init.side_effect = ConnectionError('refused')

        result = self.runner.invoke(entrypoint.main, ['setup'])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Failed to connect to ClickHouse', result.output)
        self.mock_graph.close.assert_awaited_once()

    def test_setup_empty_password(self) -> None:
        """Test setup rejects empty password."""
        self.mock_getpass.return_value = ''

        result = self.runner.invoke(
            entrypoint.main, ['setup'], input='\n\n\n\n'
        )

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Password cannot be empty', result.output)
        self.mock_create_admin.assert_not_awaited()

    def test_setup_password_mismatch(self) -> None:
        """Test setup rejects mismatched passwords."""
        self.mock_getpass.side_effect = ['s3cret', 'different']

        result = self.runner.invoke(
            entrypoint.main, ['setup'], input='\n\n\n\n'
        )

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Passwords do not match', result.output)
        self.mock_create_admin.assert_not_awaited()

    def test_setup_admin_creation_failure(self) -> None:
        """Test setup when admin user creation fails."""
        self.mock_create_admin.side_effect = RuntimeError('db error')

        result = self.runner.invoke(
            entrypoint.main, ['setup'], input='\n\n\n\n'
        )

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Failed to create admin user', result.output)
        self.mock_graph.close.assert_awaited_once()
        self.mock_ch_close.assert_awaited_once()

    def test_setup_clickhouse_schema_failure(self) -> None:
        """Test setup when ClickHouse schema creation fails."""
        self.mock_ch_schema.side_effect = RuntimeError('schema error')

        result = self.runner.invoke(
            entrypoint.main, ['setup'], input='\n\n\n\n'
        )

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Failed to set up ClickHouse schema', result.output)
        self.mock_graph.close.assert_awaited_once()
        self.mock_ch_close.assert_awaited_once()


class SetupClickhouseTestCase(unittest.TestCase):
    """Test cases for the ``setup-clickhouse`` command.

    Uses regular TestCase because the command calls asyncio.run() which
    creates its own event loop.
    """

    def setUp(self) -> None:
        super().setUp()
        self.runner = typer.testing.CliRunner()
        self.mock_graph_cls = self.enterContext(
            mock.patch.object(entrypoint.graph, 'Graph')
        )
        self.mock_ch_init = self.enterContext(
            mock.patch.object(
                entrypoint.clickhouse,
                'initialize',
                new_callable=mock.AsyncMock,
            )
        )
        self.mock_ch_close = self.enterContext(
            mock.patch.object(
                entrypoint.clickhouse, 'aclose', new_callable=mock.AsyncMock
            )
        )
        self.mock_ch_schema = self.enterContext(
            mock.patch.object(
                entrypoint.clickhouse,
                'setup_schema',
                new_callable=mock.AsyncMock,
            )
        )

    def test_applies_schema(self) -> None:
        """The schema is applied and the connection closed."""
        result = self.runner.invoke(entrypoint.main, ['setup-clickhouse'])

        self.assertEqual(result.exit_code, 0)
        self.assertIn('ClickHouse schema created', result.output)
        self.mock_ch_schema.assert_awaited_once()
        self.mock_ch_close.assert_awaited_once()

    def test_does_not_touch_postgres_or_prompt(self) -> None:
        """No graph connection is opened and no input is requested."""
        result = self.runner.invoke(entrypoint.main, ['setup-clickhouse'])

        self.assertEqual(result.exit_code, 0)
        self.mock_graph_cls.assert_not_called()

    def test_connection_failure(self) -> None:
        """A ClickHouse connection failure exits non-zero."""
        self.mock_ch_init.side_effect = ConnectionError('refused')

        result = self.runner.invoke(entrypoint.main, ['setup-clickhouse'])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Failed to connect to ClickHouse', result.output)
        self.mock_ch_schema.assert_not_awaited()

    def test_schema_failure_closes_connection(self) -> None:
        """A schema failure exits non-zero and still closes the client."""
        self.mock_ch_schema.side_effect = RuntimeError('schema error')

        result = self.runner.invoke(entrypoint.main, ['setup-clickhouse'])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Failed to set up ClickHouse schema', result.output)
        self.mock_ch_close.assert_awaited_once()


class SetupPermissionsTestCase(unittest.TestCase):
    """Test cases for the ``setup-permissions`` command.

    Uses regular TestCase because the command calls asyncio.run() which
    creates its own event loop.
    """

    def setUp(self) -> None:
        super().setUp()
        self.runner = typer.testing.CliRunner()
        self.mock_graph = mock.MagicMock()
        self.mock_graph.open = mock.AsyncMock()
        self.mock_graph.close = mock.AsyncMock()
        self.enterContext(
            mock.patch.object(
                entrypoint.graph, 'Graph', return_value=self.mock_graph
            )
        )
        self.mock_ch_init = self.enterContext(
            mock.patch.object(
                entrypoint.clickhouse,
                'initialize',
                new_callable=mock.AsyncMock,
            )
        )
        self.mock_seed = self.enterContext(
            mock.patch.object(
                entrypoint.seed,
                'seed_permissions_and_roles',
                new_callable=mock.AsyncMock,
                return_value={'retired': 0, 'permissions': 4, 'roles': 3},
            )
        )

    def test_seeds_permissions_and_roles(self) -> None:
        """Permissions and roles are seeded and the connection closed."""
        result = self.runner.invoke(entrypoint.main, ['setup-permissions'])

        self.assertEqual(result.exit_code, 0)
        self.assertIn('Created 4 permission(s) and 3 role(s)', result.output)
        self.assertIn('up to date', result.output)
        self.mock_seed.assert_awaited_once_with(self.mock_graph)
        self.mock_graph.close.assert_awaited_once()

    def test_reports_retired_permissions(self) -> None:
        """Retired permissions are reported when any were removed."""
        self.mock_seed.return_value = {
            'retired': 2,
            'permissions': 0,
            'roles': 0,
        }

        result = self.runner.invoke(entrypoint.main, ['setup-permissions'])

        self.assertEqual(result.exit_code, 0)
        self.assertIn('Removed 2 retired permission(s)', result.output)

    def test_does_not_touch_clickhouse_or_prompt(self) -> None:
        """No ClickHouse connection is opened and no input is requested."""
        result = self.runner.invoke(entrypoint.main, ['setup-permissions'])

        self.assertEqual(result.exit_code, 0)
        self.mock_ch_init.assert_not_awaited()

    def test_graph_connection_failure(self) -> None:
        """A PostgreSQL connection failure exits non-zero."""
        self.mock_graph.open.side_effect = ConnectionError('refused')

        result = self.runner.invoke(entrypoint.main, ['setup-permissions'])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Failed to connect to PostgreSQL', result.output)
        self.mock_seed.assert_not_awaited()

    def test_seed_failure_closes_connection(self) -> None:
        """A seeding failure exits non-zero and still closes the graph."""
        self.mock_seed.side_effect = RuntimeError('boom')

        result = self.runner.invoke(entrypoint.main, ['setup-permissions'])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Failed to seed permissions and roles', result.output)
        self.mock_graph.close.assert_awaited_once()


class BackfillNodeIdsTestCase(unittest.TestCase):
    """Test cases for the ``backfill-node-ids`` command (#291).

    Uses regular TestCase because the command calls asyncio.run() which
    creates its own event loop.
    """

    def setUp(self) -> None:
        super().setUp()
        self.runner = typer.testing.CliRunner()

        self.mock_graph = mock.MagicMock()
        self.mock_graph.open = mock.AsyncMock()
        self.mock_graph.close = mock.AsyncMock()
        self.mock_graph.execute = mock.AsyncMock(return_value=[])
        self.enterContext(
            mock.patch.object(
                entrypoint.graph,
                'Graph',
                return_value=self.mock_graph,
            )
        )
        self.enterContext(
            mock.patch.object(
                entrypoint.graph,
                'parse_agtype',
                side_effect=lambda v: v,
            )
        )

    def test_backfill_empty_database(self) -> None:
        """No rows missing id → no SET queries are emitted."""
        result = self.runner.invoke(entrypoint.main, ['backfill-node-ids'])

        self.assertEqual(result.exit_code, 0)
        self.assertIn('Integration: assigned id to 0', result.output)
        # Only the one SELECT; no UPDATEs.
        self.assertEqual(self.mock_graph.execute.await_count, 1)
        self.mock_graph.close.assert_awaited_once()

    def test_backfill_assigns_ids(self) -> None:
        """Each missing-id row triggers a SET query with a nanoid."""
        self.mock_graph.execute.side_effect = [
            # SELECT: Integration missing id.
            [{'org_slug': 'eng', 'slug': 'stripe'}],
            # SET on the Integration.
            [{'id': 'generated'}],
        ]

        result = self.runner.invoke(entrypoint.main, ['backfill-node-ids'])

        self.assertEqual(result.exit_code, 0)
        self.assertIn('Integration: assigned id to 1', result.output)
        self.assertEqual(self.mock_graph.execute.await_count, 2)
        # Verify the SET carries a fresh id.
        set_params = self.mock_graph.execute.await_args_list[1].args[1]
        self.assertIn('new_id', set_params)
        self.assertTrue(set_params['new_id'])
        self.assertEqual(set_params['slug'], 'stripe')
        self.assertEqual(set_params['org_slug'], 'eng')

    def test_backfill_skips_updates_that_match_no_rows(self) -> None:
        """When SET ... WHERE id IS NULL matches nothing, don't count it."""
        self.mock_graph.execute.side_effect = [
            # SELECT: Integration missing id.
            [{'org_slug': 'eng', 'slug': 'stripe'}],
            # SET on the Integration returns no rows (e.g. concurrent
            # backfill).
            [],
        ]

        result = self.runner.invoke(entrypoint.main, ['backfill-node-ids'])

        self.assertEqual(result.exit_code, 0)
        self.assertIn('Integration: assigned id to 0', result.output)

    def test_backfill_graph_connection_failure(self) -> None:
        """When the graph pool fails to open, exit non-zero."""
        self.mock_graph.open.side_effect = ConnectionError('refused')

        result = self.runner.invoke(entrypoint.main, ['backfill-node-ids'])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Failed to connect to PostgreSQL', result.output)
        # Should not have attempted any queries.
        self.mock_graph.execute.assert_not_awaited()


class CreateAdminUserTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for the _create_admin_user helper."""

    def _make_db(
        self, *, user_rows: list[dict], membership_rows: list[dict]
    ) -> mock.AsyncMock:
        db = mock.AsyncMock()
        db.execute.side_effect = [user_rows, membership_rows]
        return db

    async def test_user_create_failure_raises(self) -> None:
        db = self._make_db(user_rows=[], membership_rows=[])
        with self.assertRaises(RuntimeError) as ctx:
            await entrypoint._create_admin_user(
                db,
                email='admin@example.com',
                display_name='Admin',
                password='s3cret',
                org_slug='default',
            )
        self.assertIn('Failed to create user', str(ctx.exception))
        # MERGE for the user fired, membership query never ran.
        self.assertEqual(db.execute.await_count, 1)

    async def test_membership_failure_raises(self) -> None:
        db = self._make_db(
            user_rows=[{'n': 'user-row'}],
            membership_rows=[],
        )
        with self.assertRaises(RuntimeError) as ctx:
            await entrypoint._create_admin_user(
                db,
                email='admin@example.com',
                display_name='Admin',
                password='s3cret',
                org_slug='missing',
            )
        msg = str(ctx.exception)
        self.assertIn("'admin@example.com'", msg)
        self.assertIn("'missing'", msg)
        self.assertIn('organization not found', msg)
        self.assertEqual(db.execute.await_count, 2)

    async def test_happy_path_returns_user(self) -> None:
        db = self._make_db(
            user_rows=[{'n': 'user-row'}],
            membership_rows=[{'m': 'edge-row'}],
        )
        user = await entrypoint._create_admin_user(
            db,
            email='admin@example.com',
            display_name='Admin',
            password='s3cret',
            org_slug='default',
        )
        self.assertEqual(user.email, 'admin@example.com')
        self.assertTrue(user.is_admin)
        self.assertEqual(db.execute.await_count, 2)
