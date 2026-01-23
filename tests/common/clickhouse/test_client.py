import unittest
from unittest import mock

from clickhouse_connect.driver import exceptions

from imbi_common.clickhouse import client


class SchemataQueryTestCase(unittest.TestCase):
    def test_schemata_query_with_defaults(self) -> None:
        """Test SchemataQuery with default enabled value."""
        query = client.SchemataQuery(name='test_query', query='SELECT 1')
        self.assertEqual(query.name, 'test_query')
        self.assertEqual(query.query, 'SELECT 1')
        self.assertTrue(query.enabled)

    def test_schemata_query_with_explicit_values(self) -> None:
        """Test SchemataQuery with explicit enabled value."""
        query = client.SchemataQuery(
            name='test_query', query='SELECT 1', enabled=False
        )
        self.assertEqual(query.name, 'test_query')
        self.assertEqual(query.query, 'SELECT 1')
        self.assertFalse(query.enabled)


class ClickhouseClientTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()

        # Clear the singleton instance
        client.Clickhouse._instance = None

        # Create mock client
        self.mock_client = mock.AsyncMock()
        self.mock_client.close = mock.AsyncMock()
        self.mock_client.insert = mock.AsyncMock()
        self.mock_client.query = mock.AsyncMock()

        # Patch the async client creation
        self.mock_create_client = self.enterContext(
            mock.patch(
                'clickhouse_connect.driver.create_async_client',
                return_value=self.mock_client,
            )
        )

    async def test_singleton(self) -> None:
        """Test that Clickhouse uses singleton pattern."""
        instance1 = client.Clickhouse.get_instance()
        instance2 = client.Clickhouse.get_instance()
        self.assertIs(instance1, instance2)

    async def test_initialize(self) -> None:
        """Test clickhouse initialization."""
        ch = client.Clickhouse.get_instance()

        # Mock the schemata loading to avoid file I/O
        with mock.patch.object(
            ch, '_execute_schemata_queries', return_value=None
        ):
            result = await ch.initialize()

        self.assertTrue(result)
        self.mock_create_client.assert_called_once()
        self.assertIsNotNone(ch._clickhouse)

    async def test_setup_schema_executes_enabled_queries(self) -> None:
        """Test setup_schema executes enabled schemata queries."""
        ch = client.Clickhouse.get_instance()

        mock_queries = [
            client.SchemataQuery(
                name='query1', query='CREATE TABLE test1', enabled=True
            ),
            client.SchemataQuery(
                name='query2', query='CREATE TABLE test2', enabled=False
            ),
            client.SchemataQuery(
                name='query3', query='CREATE TABLE test3', enabled=True
            ),
        ]

        with mock.patch.object(
            ch, '_load_schemata_queries', return_value=mock_queries
        ):
            with mock.patch.object(ch, 'query', return_value=[]) as mock_query:
                await ch.setup_schema()

                # Only enabled queries should be executed
                self.assertEqual(mock_query.call_count, 2)
                mock_query.assert_any_call('CREATE TABLE test1')
                mock_query.assert_any_call('CREATE TABLE test3')

    async def test_initialize_connection_failure(self) -> None:
        """Test initialization with connection failure after retries."""
        ch = client.Clickhouse.get_instance()

        # Mock _connect to return None after retries
        with mock.patch.object(ch, '_connect', return_value=None):
            with mock.patch.object(
                ch, '_execute_schemata_queries', return_value=None
            ) as mock_exec:
                result = await ch.initialize()

                # Schemata queries should not be executed when connection fails
                mock_exec.assert_not_called()

        self.assertFalse(result)
        self.assertIsNone(ch._clickhouse)

    async def test_aclose(self) -> None:
        """Test closing clickhouse connection."""
        ch = client.Clickhouse.get_instance()

        with mock.patch.object(
            ch, '_execute_schemata_queries', return_value=None
        ):
            await ch.initialize()

        await ch.aclose()
        self.mock_client.close.assert_called_once()
        self.assertIsNone(ch._clickhouse)

    async def test_aclose_without_initialize(self) -> None:
        """Test closing without initialization doesn't error."""
        ch = client.Clickhouse.get_instance()
        await ch.aclose()
        self.mock_client.close.assert_not_called()

    async def test_insert(self) -> None:
        """Test insert operation."""
        ch = client.Clickhouse.get_instance()

        mock_summary = mock.MagicMock()
        self.mock_client.insert.return_value = mock_summary

        with mock.patch.object(
            ch, '_execute_schemata_queries', return_value=None
        ):
            await ch.initialize()

        result = await ch.insert(
            'test_table',
            [['value1', 'value2'], ['value3', 'value4']],
            ['column1', 'column2'],
        )

        self.assertEqual(result, mock_summary)
        self.mock_client.insert.assert_called_once_with(
            'test_table',
            [['value1', 'value2'], ['value3', 'value4']],
            column_names=['column1', 'column2'],
        )

    async def test_insert_without_initialize(self) -> None:
        """Test insert auto-initializes if not initialized."""
        ch = client.Clickhouse.get_instance()

        mock_summary = mock.MagicMock()
        self.mock_client.insert.return_value = mock_summary

        with mock.patch.object(
            ch, '_execute_schemata_queries', return_value=None
        ):
            result = await ch.insert('test_table', [['value1']], ['column1'])

        self.assertEqual(result, mock_summary)
        self.assertIsNotNone(ch._clickhouse)

    async def test_insert_database_error(self) -> None:
        """Test insert with database error."""
        ch = client.Clickhouse.get_instance()

        self.mock_client.insert.side_effect = exceptions.DatabaseError(
            'Insert failed'
        )

        with mock.patch.object(
            ch, '_execute_schemata_queries', return_value=None
        ):
            await ch.initialize()

        with self.assertRaises(client.DatabaseError) as cm:
            await ch.insert('test_table', [['value1']], ['column1'])

        self.assertIn('Insert failed', str(cm.exception))

    async def test_insert_database_error_with_sentry(self) -> None:
        """Test insert with database error when sentry is available."""
        ch = client.Clickhouse.get_instance()

        self.mock_client.insert.side_effect = exceptions.DatabaseError(
            'Insert failed'
        )

        mock_sentry = mock.MagicMock()
        with mock.patch.object(
            ch, '_execute_schemata_queries', return_value=None
        ):
            await ch.initialize()

        with mock.patch(
            'imbi_common.clickhouse.client.sentry_sdk', mock_sentry
        ):
            with self.assertRaises(client.DatabaseError):
                await ch.insert('test_table', [['value1']], ['column1'])

        mock_sentry.capture_exception.assert_called_once()

    async def test_query(self) -> None:
        """Test query operation."""
        ch = client.Clickhouse.get_instance()

        mock_result = mock.MagicMock()
        mock_result.result_rows = [
            ('value1', 'value2'),
            ('value3', 'value4'),
        ]
        mock_result.column_names = ['column1', 'column2']
        self.mock_client.query.return_value = mock_result

        with mock.patch.object(
            ch, '_execute_schemata_queries', return_value=None
        ):
            await ch.initialize()

        result = await ch.query(
            'SELECT * FROM test WHERE id = {id}', {'id': 123}
        )

        expected = [
            {'column1': 'value1', 'column2': 'value2'},
            {'column1': 'value3', 'column2': 'value4'},
        ]
        self.assertEqual(result, expected)
        self.mock_client.query.assert_called_once_with(
            'SELECT * FROM test WHERE id = {id}', parameters={'id': 123}
        )

    async def test_query_without_parameters(self) -> None:
        """Test query without parameters."""
        ch = client.Clickhouse.get_instance()

        mock_result = mock.MagicMock()
        mock_result.result_rows = [('value1',)]
        mock_result.column_names = ['column1']
        self.mock_client.query.return_value = mock_result

        with mock.patch.object(
            ch, '_execute_schemata_queries', return_value=None
        ):
            await ch.initialize()

        result = await ch.query('SELECT 1')

        self.assertEqual(result, [{'column1': 'value1'}])
        self.mock_client.query.assert_called_once_with(
            'SELECT 1', parameters={}
        )

    async def test_query_without_initialize(self) -> None:
        """Test query auto-initializes if not initialized."""
        ch = client.Clickhouse.get_instance()

        mock_result = mock.MagicMock()
        mock_result.result_rows = [('value1',)]
        mock_result.column_names = ['column1']
        self.mock_client.query.return_value = mock_result

        with mock.patch.object(
            ch, '_execute_schemata_queries', return_value=None
        ):
            result = await ch.query('SELECT 1')

        self.assertEqual(result, [{'column1': 'value1'}])
        self.assertIsNotNone(ch._clickhouse)

    async def test_query_database_error(self) -> None:
        """Test query with database error."""
        ch = client.Clickhouse.get_instance()

        self.mock_client.query.side_effect = exceptions.DatabaseError(
            'Query failed'
        )

        with mock.patch.object(
            ch, '_execute_schemata_queries', return_value=None
        ):
            await ch.initialize()

        with self.assertRaises(client.DatabaseError) as cm:
            await ch.query('SELECT 1')

        self.assertIn('Query failed', str(cm.exception))

    async def test_query_database_error_with_sentry(self) -> None:
        """Test query with database error when sentry is available."""
        ch = client.Clickhouse.get_instance()

        self.mock_client.query.side_effect = exceptions.DatabaseError(
            'Query failed'
        )

        mock_sentry = mock.MagicMock()
        with mock.patch.object(
            ch, '_execute_schemata_queries', return_value=None
        ):
            await ch.initialize()

        with mock.patch(
            'imbi_common.clickhouse.client.sentry_sdk', mock_sentry
        ):
            with self.assertRaises(client.DatabaseError):
                await ch.query('SELECT 1')

        mock_sentry.capture_exception.assert_called_once()

    async def test_connect_success(self) -> None:
        """Test successful connection."""
        ch = client.Clickhouse.get_instance()

        result = await ch._connect()

        self.assertEqual(result, self.mock_client)
        self.mock_create_client.assert_called_once()

    async def test_connect_retry_on_operational_error(self) -> None:
        """Test connection retries on operational error."""
        ch = client.Clickhouse.get_instance()

        # Fail twice, succeed third time
        self.mock_create_client.side_effect = [
            exceptions.OperationalError('Connection refused'),
            exceptions.OperationalError('Connection refused'),
            self.mock_client,
        ]

        result = await ch._connect(delay=0.01)

        self.assertEqual(result, self.mock_client)
        self.assertEqual(self.mock_create_client.call_count, 3)

    async def test_connect_max_retries_exceeded(self) -> None:
        """Test connection fails after max retries."""
        ch = client.Clickhouse.get_instance()
        ch._settings.max_connect_attempts = 3

        self.mock_create_client.side_effect = exceptions.OperationalError(
            'Connection refused'
        )

        result = await ch._connect(delay=0.01)

        self.assertIsNone(result)
        self.assertEqual(
            self.mock_create_client.call_count,
            ch._settings.max_connect_attempts,
        )

    async def test_load_schemata_queries_success(self) -> None:
        """Test loading schemata queries from TOML file."""
        ch = client.Clickhouse.get_instance()

        mock_toml_data = {
            'query1': {'query': 'SELECT 1', 'enabled': True},
            'query2': {'query': 'SELECT 2', 'enabled': False},
            'query3': {'query': 'SELECT 3'},  # Uses default enabled=True
        }

        with mock.patch('pathlib.Path.exists', return_value=True):
            with mock.patch('pathlib.Path.open', mock.mock_open()):
                with mock.patch('tomllib.load', return_value=mock_toml_data):
                    queries = ch._load_schemata_queries()

        self.assertEqual(len(queries), 3)
        self.assertEqual(queries[0].name, 'query1')
        self.assertEqual(queries[0].query, 'SELECT 1')
        self.assertTrue(queries[0].enabled)
        self.assertEqual(queries[1].name, 'query2')
        self.assertFalse(queries[1].enabled)
        self.assertEqual(queries[2].name, 'query3')
        self.assertTrue(queries[2].enabled)

    async def test_load_schemata_queries_file_not_found(self) -> None:
        """Test loading schemata queries when file doesn't exist."""
        ch = client.Clickhouse.get_instance()

        with mock.patch('pathlib.Path.exists', return_value=False):
            queries = ch._load_schemata_queries()

        self.assertEqual(queries, [])

    async def test_load_schemata_queries_invalid_entry(self) -> None:
        """Test loading schemata queries with invalid entry."""
        ch = client.Clickhouse.get_instance()

        mock_toml_data = {
            'valid_query': {'query': 'SELECT 1'},
            'invalid_query': {'query': 123},  # Invalid type for query field
        }

        with mock.patch('pathlib.Path.exists', return_value=True):
            with mock.patch('pathlib.Path.open', mock.mock_open()):
                with mock.patch('tomllib.load', return_value=mock_toml_data):
                    queries = ch._load_schemata_queries()

        # Only valid query should be loaded
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0].name, 'valid_query')

    async def test_execute_schemata_queries_success(self) -> None:
        """Test executing schemata queries."""
        ch = client.Clickhouse.get_instance()

        mock_queries = [
            client.SchemataQuery(
                name='query1', query='SELECT 1', enabled=True
            ),
            client.SchemataQuery(
                name='query2', query='SELECT 2', enabled=False
            ),
            client.SchemataQuery(
                name='query3', query='SELECT 3', enabled=True
            ),
        ]

        with mock.patch.object(
            ch, '_load_schemata_queries', return_value=mock_queries
        ):
            with mock.patch.object(ch, 'query', return_value=[]) as mock_query:
                await ch._execute_schemata_queries()

                # Only enabled queries should be executed
                self.assertEqual(mock_query.call_count, 2)
                mock_query.assert_any_call('SELECT 1')
                mock_query.assert_any_call('SELECT 3')

    async def test_execute_schemata_queries_with_error(self) -> None:
        """Test executing schemata queries continues on error."""
        ch = client.Clickhouse.get_instance()

        mock_queries = [
            client.SchemataQuery(
                name='query1', query='SELECT 1', enabled=True
            ),
            client.SchemataQuery(
                name='query2', query='INVALID SQL', enabled=True
            ),
            client.SchemataQuery(
                name='query3', query='SELECT 3', enabled=True
            ),
        ]

        with mock.patch.object(
            ch, '_load_schemata_queries', return_value=mock_queries
        ):
            with mock.patch.object(ch, 'query') as mock_query:
                # Second query fails
                mock_query.side_effect = [
                    [],
                    client.DatabaseError('SQL error'),
                    [],
                ]

                # Should not raise, should continue with remaining queries
                await ch._execute_schemata_queries()

                self.assertEqual(mock_query.call_count, 3)

    async def test_execute_schemata_queries_with_error_and_sentry(
        self,
    ) -> None:
        """Test executing schemata queries with sentry when error occurs."""
        ch = client.Clickhouse.get_instance()

        mock_queries = [
            client.SchemataQuery(
                name='query1', query='INVALID SQL', enabled=True
            ),
        ]

        mock_sentry = mock.MagicMock()
        with mock.patch.object(
            ch, '_load_schemata_queries', return_value=mock_queries
        ):
            with mock.patch.object(ch, 'query') as mock_query:
                mock_query.side_effect = client.DatabaseError('SQL error')

                with mock.patch(
                    'imbi_common.clickhouse.client.sentry_sdk', mock_sentry
                ):
                    await ch._execute_schemata_queries()

                mock_sentry.capture_exception.assert_called_once()

    async def test_execute_schemata_queries_empty(self) -> None:
        """Test executing schemata queries with no queries."""
        ch = client.Clickhouse.get_instance()

        with mock.patch.object(ch, '_load_schemata_queries', return_value=[]):
            with mock.patch.object(ch, 'query') as mock_query:
                await ch._execute_schemata_queries()

                mock_query.assert_not_called()
