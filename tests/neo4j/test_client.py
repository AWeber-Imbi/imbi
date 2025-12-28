import unittest
from unittest import mock

from imbi.neo4j import client


class Neo4jClientTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()

        # Clear the singleton instance
        client.Neo4j._instance = None

        self.mock_driver = mock.AsyncMock()
        self.mock_session = mock.AsyncMock()
        self.mock_result = mock.AsyncMock()

        # Set up session context manager
        mock_session_cm = mock.AsyncMock()
        mock_session_cm.__aenter__.return_value = self.mock_session
        mock_session_cm.__aexit__.return_value = None

        # Make session() return a context manager, not a coroutine
        self.mock_driver.session = mock.MagicMock(return_value=mock_session_cm)
        self.mock_driver.close = mock.AsyncMock()

        # Patch the driver creation and session context
        self.driver_patcher = mock.patch(
            'neo4j.AsyncGraphDatabase.driver', return_value=self.mock_driver
        )
        self.mock_driver_class = self.driver_patcher.start()
        self.addCleanup(self.driver_patcher.stop)

    def test_graph_singleton(self) -> None:
        """Test that Graph uses singleton pattern."""
        instance1 = client.Neo4j.get_instance()
        instance2 = client.Neo4j.get_instance()
        self.assertIs(instance1, instance2)

    async def test_initialize(self) -> None:
        """Test graph initialization creates indexes."""
        graph = client.Neo4j.get_instance()
        await graph.initialize()
        self.mock_driver.session.assert_called()
        self.assertEqual(
            self.mock_session.run.call_count, len(client.constants.INDEXES)
        )

    async def test_initialize_with_constraint_error(self) -> None:
        """Test initializing indexes handles constraint errors gracefully."""
        from neo4j import exceptions

        # Mock the constants to have an index
        with mock.patch(
            'imbi.neo4j.constants.INDEXES',
            [
                'CREATE CONSTRAINT test IF NOT EXISTS FOR (n:Test) '
                'REQUIRE n.id IS UNIQUE'
            ],
        ):
            # Mock session.run to raise ConstraintError
            self.mock_session.run.side_effect = exceptions.ConstraintError(
                'Already exists'
            )

            # Should not raise, should handle the error
            graph = client.Neo4j.get_instance()
            await graph.initialize()

            # Verify session was called
            self.mock_driver.session.assert_called()

    async def test_aclose(self) -> None:
        """Test graph connection close."""
        graph = client.Neo4j.get_instance()
        await graph.aclose()
        self.mock_driver.close.assert_called_once()
