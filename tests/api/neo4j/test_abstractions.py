import unittest
from unittest import mock

from imbi import neo4j
from imbi.neo4j import client


class Neo4jAbstrationsTestCase(unittest.IsolatedAsyncioTestCase):
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

    async def test_initialize_function(self) -> None:
        """Test module-level initialize function."""
        await neo4j.initialize()
        self.mock_driver.session.assert_called()

    async def test_aclose_function(self) -> None:
        """Test module-level aclose function."""
        await neo4j.aclose()
        self.mock_driver.close.assert_called()

    async def test_session_context_manager(self) -> None:
        """Test session context manager."""
        async with neo4j.session() as sess:
            self.assertEqual(sess, self.mock_session)

    async def test_run_context_manager(self) -> None:
        """Test run context manager with query."""
        self.mock_session.run.return_value = self.mock_result

        async with neo4j.run(
            'MATCH (n) RETURN n', test_param='value'
        ) as result:
            self.assertEqual(result, self.mock_result)

        self.mock_session.run.assert_called_once_with(
            'MATCH (n) RETURN n', test_param='value'
        )

    def test_cypher_property_params(self) -> None:
        """Test cypher property parameter generation."""
        params = {'id': '123', 'name': 'test'}
        result = neo4j.cypher_property_params(params)
        self.assertEqual(result, 'id: $id, name: $name')

        # Test empty params
        self.assertEqual(neo4j.cypher_property_params({}), '')
        self.assertEqual(neo4j.cypher_property_params(None), '')

    async def test_upsert_node(self) -> None:
        """Test upserting a node."""
        import pydantic

        class TestNode(pydantic.BaseModel):
            id: str
            name: str

        # Mock the result for the main upsert
        mock_single_result = {'nodeId': 'element123'}
        self.mock_result.single.return_value = mock_single_result
        self.mock_session.run.return_value = self.mock_result

        test_node = TestNode(id='123', name='Test Node')
        result = await neo4j.upsert(test_node, {'id': '123'})

        # Verify the result
        self.assertEqual(result, 'element123')

        # Verify session.run was called
        self.mock_session.run.assert_called_once()
        call_args = self.mock_session.run.call_args
        query = call_args[0][0]  # First positional argument

        # Verify query contains MERGE, ON CREATE SET, ON MATCH SET
        self.assertIn('MERGE', query)
        self.assertIn('ON CREATE SET', query)
        self.assertIn('ON MATCH SET', query)
        self.assertIn('RETURN elementId(node) AS nodeId', query)

        # Verify constraint was used in query
        self.assertIn('id: $id', query)


class Neo4jCypheranticWrappersTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for cypherantic wrapper functions."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()

        # Clear the singleton instance
        client.Neo4j._instance = None

        self.mock_driver = mock.AsyncMock()
        self.mock_session = mock.AsyncMock()

        # Set up session context manager
        mock_session_cm = mock.AsyncMock()
        mock_session_cm.__aenter__.return_value = self.mock_session
        mock_session_cm.__aexit__.return_value = None

        self.mock_driver.session = mock.MagicMock(return_value=mock_session_cm)
        self.mock_driver.close = mock.AsyncMock()

        # Patch the driver creation
        self.driver_patcher = mock.patch(
            'neo4j.AsyncGraphDatabase.driver', return_value=self.mock_driver
        )
        self.mock_driver_class = self.driver_patcher.start()
        self.addCleanup(self.driver_patcher.stop)

    async def test_create_node(self) -> None:
        """Test create_node wrapper function."""
        import pydantic

        class TestNode(pydantic.BaseModel):
            id: str
            name: str

        test_node = TestNode(id='123', name='Test')
        mock_neo4j_node = mock.MagicMock()

        with mock.patch(
            'cypherantic.create_node', return_value=mock_neo4j_node
        ) as mock_create:
            result = await neo4j.create_node(test_node)

            # Verify cypherantic.create_node was called with session and model
            mock_create.assert_called_once()
            call_args = mock_create.call_args
            self.assertEqual(call_args[0][1], test_node)
            self.assertEqual(result, mock_neo4j_node)

    async def test_create_relationship_with_props(self) -> None:
        """Test create_relationship with relationship properties."""
        import pydantic

        class FromNode(pydantic.BaseModel):
            id: str

        class ToNode(pydantic.BaseModel):
            id: str

        class RelProps(pydantic.BaseModel):
            since: str

        from_node = FromNode(id='1')
        to_node = ToNode(id='2')
        rel_props = RelProps(since='2024')
        mock_relationship = mock.MagicMock()

        with mock.patch(
            'cypherantic.create_relationship',
            return_value=mock_relationship,
        ) as mock_create:
            result = await neo4j.create_relationship(
                from_node, to_node, rel_props
            )

            # Verify cypherantic.create_relationship was called correctly
            mock_create.assert_called_once()
            call_args = mock_create.call_args
            self.assertEqual(call_args[0][1], from_node)
            self.assertEqual(call_args[0][2], to_node)
            self.assertEqual(call_args[0][3], rel_props)
            self.assertEqual(result, mock_relationship)

    async def test_create_relationship_with_type(self) -> None:
        """Test create_relationship with relationship type string."""
        import pydantic

        class FromNode(pydantic.BaseModel):
            id: str

        class ToNode(pydantic.BaseModel):
            id: str

        from_node = FromNode(id='1')
        to_node = ToNode(id='2')
        mock_relationship = mock.MagicMock()

        with mock.patch(
            'cypherantic.create_relationship',
            return_value=mock_relationship,
        ) as mock_create:
            result = await neo4j.create_relationship(
                from_node, to_node, rel_type='KNOWS'
            )

            # Verify cypherantic.create_relationship was called correctly
            mock_create.assert_called_once()
            call_args = mock_create.call_args
            self.assertEqual(call_args[0][1], from_node)
            self.assertEqual(call_args[0][2], to_node)
            self.assertEqual(call_args[0][3], None)
            self.assertEqual(call_args[1]['rel_type'], 'KNOWS')
            self.assertEqual(result, mock_relationship)

    async def test_refresh_relationship(self) -> None:
        """Test refresh_relationship wrapper function."""
        import pydantic

        class TestNode(pydantic.BaseModel):
            id: str
            friends: list = []

        test_node = TestNode(id='123')

        with mock.patch(
            'cypherantic.refresh_relationship', return_value=None
        ) as mock_refresh:
            await neo4j.refresh_relationship(test_node, 'friends')

            # Verify cypherantic.refresh_relationship was called correctly
            mock_refresh.assert_called_once()
            call_args = mock_refresh.call_args
            self.assertEqual(call_args[0][1], test_node)
            self.assertEqual(call_args[0][2], 'friends')

    async def test_retrieve_relationship_edges(self) -> None:
        """Test retrieve_relationship_edges wrapper function."""
        from typing import NamedTuple

        import pydantic

        class FriendNode(pydantic.BaseModel):
            id: str
            name: str

        class FriendshipProps(pydantic.BaseModel):
            since: str

        class FriendEdge(NamedTuple):
            node: FriendNode
            properties: FriendshipProps

        class TestNode(pydantic.BaseModel):
            id: str

        test_node = TestNode(id='123')
        mock_edges = [
            FriendEdge(
                node=FriendNode(id='456', name='Alice'),
                properties=FriendshipProps(since='2020'),
            )
        ]

        with mock.patch(
            'cypherantic.retrieve_relationship_edges',
            return_value=mock_edges,
        ) as mock_retrieve:
            result = await neo4j.retrieve_relationship_edges(
                test_node, 'FRIENDS_WITH', 'OUTGOING', FriendEdge
            )

            # Verify cypherantic.retrieve_relationship_edges was called
            mock_retrieve.assert_called_once()
            call_args = mock_retrieve.call_args
            self.assertEqual(call_args[0][1], test_node)
            self.assertEqual(call_args[0][2], 'FRIENDS_WITH')
            self.assertEqual(call_args[0][3], 'OUTGOING')
            self.assertEqual(call_args[0][4], FriendEdge)
            self.assertEqual(result, mock_edges)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].node.name, 'Alice')
