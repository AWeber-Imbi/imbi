import unittest
from unittest import mock

from imbi_common.neo4j import client


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
            'neo4j.AsyncGraphDatabase.driver',
            return_value=self.mock_driver,
        )
        self.mock_driver_class = self.driver_patcher.start()
        self.addCleanup(self.driver_patcher.stop)

    async def test_graph_singleton(self) -> None:
        """Test that Graph uses singleton pattern."""
        instance1 = client.Neo4j.get_instance()
        instance2 = client.Neo4j.get_instance()
        self.assertIs(instance1, instance2)

    async def test_initialize(self) -> None:
        """Test graph initialization creates indexes."""
        graph = client.Neo4j.get_instance()
        await graph.initialize()
        self.mock_driver.session.assert_called()
        expected_calls = len(client.constants.INDEXES) + len(
            client.constants.TRIGGERS
        )
        self.assertEqual(self.mock_session.run.call_count, expected_calls)

    async def test_initialize_with_constraint_error(self) -> None:
        """Test that ConstraintError during index creation is
        handled."""
        from neo4j import exceptions

        with (
            mock.patch(
                'imbi_common.neo4j.constants.INDEXES',
                [
                    'CREATE CONSTRAINT test IF NOT EXISTS '
                    'FOR (n:Test) REQUIRE n.id IS UNIQUE'
                ],
            ),
            mock.patch('imbi_common.neo4j.constants.TRIGGERS', []),
        ):
            self.mock_session.run.side_effect = exceptions.ConstraintError(
                'Already exists'
            )

            graph = client.Neo4j.get_instance()
            await graph.initialize()

            self.mock_driver.session.assert_called()

    async def test_initialize_trigger_apoc_not_available(
        self,
    ) -> None:
        """Test that ProcedureNotFound skips the trigger."""
        from neo4j import exceptions

        apoc_err = exceptions.Neo4jError._hydrate_neo4j(
            code='Neo.ClientError.Procedure.ProcedureNotFound',
            message='APOC not installed',
        )

        with (
            mock.patch('imbi_common.neo4j.constants.INDEXES', []),
            mock.patch(
                'imbi_common.neo4j.constants.TRIGGERS',
                [
                    {
                        'name': 'test_trigger',
                        'query': 'RETURN null',
                        'selector': {'phase': 'before'},
                    }
                ],
            ),
        ):
            self.mock_session.run.side_effect = apoc_err

            graph = client.Neo4j.get_instance()
            with self.assertLogs(client.LOGGER, level='WARNING') as cm:
                await graph.initialize()

            self.assertTrue(
                any('APOC not available' in msg for msg in cm.output)
            )

    async def test_initialize_trigger_other_client_error_raises(
        self,
    ) -> None:
        """Test that non-ProcedureNotFound ClientErrors propagate."""
        from neo4j import exceptions

        err = exceptions.Neo4jError._hydrate_neo4j(
            code='Neo.ClientError.Security.Forbidden',
            message='Permission denied',
        )

        with (
            mock.patch('imbi_common.neo4j.constants.INDEXES', []),
            mock.patch(
                'imbi_common.neo4j.constants.TRIGGERS',
                [
                    {
                        'name': 'test_trigger',
                        'query': 'RETURN null',
                        'selector': {'phase': 'before'},
                    }
                ],
            ),
        ):
            self.mock_session.run.side_effect = err

            graph = client.Neo4j.get_instance()
            with self.assertRaises(exceptions.ClientError):
                await graph.initialize()

    async def test_aclose(self) -> None:
        """Test graph connection close."""
        graph = client.Neo4j.get_instance()
        await graph.aclose()
        self.mock_driver.close.assert_called_once()
