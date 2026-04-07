import unittest
from unittest import mock

from imbi_common.age import client


class AGEClientTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()

        # Clear the singleton instance
        client.AGE._instance = None

        self.mock_pool = mock.AsyncMock()
        self.mock_conn = mock.AsyncMock()

        # Set up connection context manager
        mock_conn_cm = mock.AsyncMock()
        mock_conn_cm.__aenter__.return_value = self.mock_conn
        mock_conn_cm.__aexit__.return_value = None
        self.mock_pool.connection = mock.MagicMock(return_value=mock_conn_cm)
        self.mock_pool.close = mock.AsyncMock()
        self.mock_pool.open = mock.AsyncMock()

        # Patch pool creation where it's imported
        self.pool_patcher = mock.patch(
            'imbi_common.age.client.AsyncConnectionPool',
            return_value=self.mock_pool,
        )
        self.mock_pool_class = self.pool_patcher.start()
        self.addCleanup(self.pool_patcher.stop)

    async def test_graph_singleton(self) -> None:
        """Test that AGE uses singleton pattern."""
        instance1 = client.AGE.get_instance()
        instance2 = client.AGE.get_instance()
        self.assertIs(instance1, instance2)

    async def test_initialize(self) -> None:
        """Test AGE initialization creates extension, graph, and indexes."""
        graph = client.AGE.get_instance()
        await graph.initialize()

        # Pool should have been opened
        self.mock_pool.open.assert_called_once()

        # Connection should have been used
        self.mock_pool.connection.assert_called()

        # Should execute SETUP statements, ENSURE_GRAPH,
        # ENSURE_LABELS, and INDEXES
        expected_calls = (
            len(client.constants.SETUP)
            + 1  # ENSURE_GRAPH
            + len(client.constants.ENSURE_LABELS)
            + len(client.constants.INDEXES)
        )
        self.assertGreaterEqual(
            self.mock_conn.execute.call_count, expected_calls
        )

    async def test_initialize_handles_duplicate_index(self) -> None:
        """Test that DuplicateTable during index creation is handled."""
        import psycopg.errors

        # Make execute succeed for setup/graph/labels, then fail
        # on the first index
        setup_count = (
            len(client.constants.SETUP)
            + 1  # ENSURE_GRAPH
            + len(client.constants.ENSURE_LABELS)
        )
        side_effects: list[mock.AsyncMock | Exception] = [
            mock.AsyncMock() for _ in range(setup_count)
        ]
        side_effects.append(psycopg.errors.DuplicateTable('Already exists'))
        self.mock_conn.execute = mock.AsyncMock(side_effect=side_effects)

        graph = client.AGE.get_instance()
        # Should not raise
        await graph.initialize()

    async def test_aclose(self) -> None:
        """Test AGE connection pool close."""
        graph = client.AGE.get_instance()
        # Ensure pool is created first
        await graph._ensure_pool()
        await graph.aclose()
        self.mock_pool.close.assert_called_once()

    async def test_aclose_no_pool(self) -> None:
        """Test aclose when no pool exists does nothing."""
        graph = client.AGE.get_instance()
        # Should not raise
        await graph.aclose()
