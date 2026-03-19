import datetime
import unittest
from unittest import mock

import typer.testing

from imbi_api import entrypoint, models


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

        # Database lifecycle
        self.mock_neo4j_init = self.enterContext(
            mock.patch.object(
                entrypoint.neo4j, 'initialize', new_callable=mock.AsyncMock
            )
        )
        self.mock_neo4j_close = self.enterContext(
            mock.patch.object(
                entrypoint.neo4j, 'aclose', new_callable=mock.AsyncMock
            )
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
                entrypoint, '_create_admin_user', new_callable=mock.AsyncMock
            )
        )
        self.mock_create_admin.return_value = self.admin_user

        # Password input (getpass reads /dev/tty, not stdin)
        self.mock_getpass = self.enterContext(
            mock.patch.object(
                entrypoint.getpass, 'getpass', return_value='s3cret'
            )
        )

    def test_setup_fresh_install(self) -> None:
        """Test setup on a fresh system with defaults."""
        result = self.runner.invoke(entrypoint.main, ['setup'], input='\n\n')

        self.assertEqual(result.exit_code, 0)
        self.assertIn('Setup complete', result.output)
        self.assertIn('Created default organization', result.output)
        self.assertIn('Created 5 permissions and 3 roles', result.output)
        self.assertIn('Created admin user: admin@example.com', result.output)
        self.assertIn('ClickHouse schema created', result.output)

        self.mock_create_admin.assert_awaited_once_with(
            email='admin@example.com',
            display_name='Administrator',
            password='s3cret',
        )
        self.mock_neo4j_close.assert_awaited_once()
        self.mock_ch_close.assert_awaited_once()

    def test_setup_custom_email_and_display_name(self) -> None:
        """Test setup with user-provided email and display name."""
        result = self.runner.invoke(
            entrypoint.main, ['setup'], input='dave@example.com\nDave\n'
        )

        self.assertEqual(result.exit_code, 0)
        self.mock_create_admin.assert_awaited_once_with(
            email='dave@example.com',
            display_name='Dave',
            password='s3cret',
        )

    def test_setup_already_seeded_continue(self) -> None:
        """Test setup when already seeded and user confirms."""
        self.mock_check_seeded.return_value = True
        self.mock_check_admin.return_value = True

        result = self.runner.invoke(
            entrypoint.main, ['setup'], input='y\n\n\n'
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
        self.mock_neo4j_close.assert_awaited_once()
        self.mock_ch_close.assert_awaited_once()

    def test_setup_existing_entities_no_new(self) -> None:
        """Test output when permissions and roles already exist."""
        self.seed_result.update(organization=False, permissions=0, roles=0)

        result = self.runner.invoke(entrypoint.main, ['setup'], input='\n\n')

        self.assertEqual(result.exit_code, 0)
        self.assertIn('Default organization already exists', result.output)
        self.assertIn('already exist', result.output)

    def test_setup_neo4j_connection_failure(self) -> None:
        """Test setup when Neo4j connection fails."""
        self.mock_neo4j_init.side_effect = ConnectionError('refused')

        result = self.runner.invoke(entrypoint.main, ['setup'])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Failed to connect to Neo4j', result.output)
        self.mock_ch_init.assert_not_awaited()

    def test_setup_clickhouse_connection_failure(self) -> None:
        """Test setup when ClickHouse connection fails."""
        self.mock_ch_init.side_effect = ConnectionError('refused')

        result = self.runner.invoke(entrypoint.main, ['setup'])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Failed to connect to ClickHouse', result.output)
        self.mock_neo4j_close.assert_awaited_once()

    def test_setup_empty_password(self) -> None:
        """Test setup rejects empty password."""
        self.mock_getpass.return_value = ''

        result = self.runner.invoke(entrypoint.main, ['setup'], input='\n\n')

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Password cannot be empty', result.output)
        self.mock_create_admin.assert_not_awaited()

    def test_setup_password_mismatch(self) -> None:
        """Test setup rejects mismatched passwords."""
        self.mock_getpass.side_effect = ['s3cret', 'different']

        result = self.runner.invoke(entrypoint.main, ['setup'], input='\n\n')

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Passwords do not match', result.output)
        self.mock_create_admin.assert_not_awaited()

    def test_setup_admin_creation_failure(self) -> None:
        """Test setup when admin user creation fails."""
        self.mock_create_admin.side_effect = RuntimeError('db error')

        result = self.runner.invoke(entrypoint.main, ['setup'], input='\n\n')

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Failed to create admin user', result.output)
        self.mock_neo4j_close.assert_awaited_once()
        self.mock_ch_close.assert_awaited_once()

    def test_setup_clickhouse_schema_failure(self) -> None:
        """Test setup when ClickHouse schema creation fails."""
        self.mock_ch_schema.side_effect = RuntimeError('schema error')

        result = self.runner.invoke(entrypoint.main, ['setup'], input='\n\n')

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Failed to set up ClickHouse schema', result.output)
        self.mock_neo4j_close.assert_awaited_once()
        self.mock_ch_close.assert_awaited_once()
