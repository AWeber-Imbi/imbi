import typing
import unittest
from unittest import mock

import cypherantic
import pydantic

from imbi_common import neo4j
from imbi_common.neo4j import client


class ConvertNeo4jTypesTestCase(unittest.TestCase):
    """Test cases for convert_neo4j_types."""

    def test_dict_conversion(self) -> None:
        """Test dict values are recursively converted."""
        result = neo4j.convert_neo4j_types({'a': 1, 'b': 'hello'})
        self.assertEqual(result, {'a': 1, 'b': 'hello'})

    def test_list_conversion(self) -> None:
        """Test list values are recursively converted."""
        result = neo4j.convert_neo4j_types([1, 'hello', True])
        self.assertEqual(result, [1, 'hello', True])

    def test_to_native_duck_typing(self) -> None:
        """Test objects with to_native() are converted."""
        obj = mock.MagicMock()
        obj.to_native.return_value = 42
        result = neo4j.convert_neo4j_types(obj)
        self.assertEqual(result, 42)
        obj.to_native.assert_called_once()

    def test_nested_list_in_dict(self) -> None:
        """Test nested lists in dicts are converted."""
        obj = mock.MagicMock()
        obj.to_native.return_value = 'native_val'
        result = neo4j.convert_neo4j_types({'items': [obj, 'plain']})
        self.assertEqual(result, {'items': ['native_val', 'plain']})

    def test_primitive_passthrough(self) -> None:
        """Test primitives are returned as-is."""
        self.assertEqual(neo4j.convert_neo4j_types(42), 42)
        self.assertEqual(neo4j.convert_neo4j_types('hello'), 'hello')
        self.assertIsNone(neo4j.convert_neo4j_types(None))


class PrepareNodeDataTestCase(unittest.TestCase):
    """Test cases for _prepare_node_data."""

    def test_relationship_field_with_default(self) -> None:
        """Test relationship field gets default value."""

        class MyNode(pydantic.BaseModel):
            name: str
            friends: typing.Annotated[
                list[str],
                cypherantic.Relationship(
                    rel_type='FRIENDS',
                    direction='OUTGOING',
                ),
            ] = []

        result = neo4j._prepare_node_data(MyNode, {'name': 'Alice'})
        self.assertEqual(result['name'], 'Alice')
        self.assertEqual(result['friends'], [])

    def test_relationship_field_without_default(self) -> None:
        """Test required relationship field gets None."""

        class MyNode(pydantic.BaseModel):
            name: str
            org: typing.Annotated[
                str,
                cypherantic.Relationship(
                    rel_type='BELONGS_TO',
                    direction='OUTGOING',
                ),
            ]

        result = neo4j._prepare_node_data(MyNode, {'name': 'Alice'})
        self.assertEqual(result['name'], 'Alice')
        self.assertIsNone(result['org'])

    def test_existing_data_not_overwritten(self) -> None:
        """Test existing node data is preserved."""

        class MyNode(pydantic.BaseModel):
            name: str
            friends: typing.Annotated[
                list[str],
                cypherantic.Relationship(
                    rel_type='FRIENDS',
                    direction='OUTGOING',
                ),
            ] = []

        result = neo4j._prepare_node_data(
            MyNode, {'name': 'Alice', 'friends': ['Bob']}
        )
        self.assertEqual(result['friends'], ['Bob'])


class BuildFetchQueryTestCase(unittest.TestCase):
    """Test cases for _build_fetch_query."""

    def test_simple_query(self) -> None:
        """Test basic MATCH query."""

        class MyNode(pydantic.BaseModel):
            name: str

        result = neo4j._build_fetch_query(MyNode)
        self.assertEqual(result, 'MATCH (node:MyNode) RETURN node')

    def test_query_with_parameters(self) -> None:
        """Test query with match parameters."""

        class MyNode(pydantic.BaseModel):
            name: str

        result = neo4j._build_fetch_query(MyNode, {'name': 'test'})
        self.assertIn('name: $name', result)

    def test_query_with_string_order_by(self) -> None:
        """Test query with string order_by."""
        result = neo4j._build_fetch_query('MyNode', order_by='name')
        self.assertIn('ORDER BY node.name', result)

    def test_query_with_list_order_by(self) -> None:
        """Test query with list order_by."""
        result = neo4j._build_fetch_query(
            'MyNode', order_by=['name', 'priority']
        )
        self.assertIn('ORDER BY node.name, node.priority', result)

    def test_query_with_string_model(self) -> None:
        """Test query with string model name."""
        result = neo4j._build_fetch_query('Blueprint')
        self.assertEqual(result, 'MATCH (node:Blueprint) RETURN node')


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

        # Verify constraint was used in query (namespaced params)
        self.assertIn('id: $_c_id', query)

        # Verify namespaced constraint param was passed
        params = call_args[1]
        self.assertEqual(params['_c_id'], '123')

    async def test_upsert_node_param_collision(self) -> None:
        """Test upsert raises on _c_ namespace collision."""
        import pydantic

        class BadNode(pydantic.BaseModel):
            id: str
            collision: str = pydantic.Field(alias='_c_id')

        self.mock_session.run.return_value = self.mock_result

        bad_node = BadNode(id='123', _c_id='oops')
        with self.assertRaises(ValueError) as ctx:
            await neo4j.upsert(bad_node, {'id': '123'})
        self.assertIn('_c_id', str(ctx.exception))
        self.mock_session.run.assert_not_called()

    async def test_delete_node_found(self) -> None:
        """Test deleting a node that exists."""
        import pydantic

        class TestNode(pydantic.BaseModel):
            id: str
            name: str

        # Mock result where node was found and deleted
        mock_single_result = {'deleted': 1}
        self.mock_result.single.return_value = mock_single_result
        self.mock_session.run.return_value = self.mock_result

        result = await neo4j.delete_node(TestNode, {'id': '123'})

        # Verify the result is True (node was deleted)
        self.assertTrue(result)

        # Verify session.run was called
        self.mock_session.run.assert_called_once()
        call_args = self.mock_session.run.call_args
        query = call_args[0][0]  # First positional argument

        # Verify query contains DELETE and WHERE
        self.assertIn('DELETE', query)
        self.assertIn('WHERE', query)
        self.assertIn('testnode', query.lower())
        self.assertIn('node.id = $id', query)

    async def test_delete_node_not_found(self) -> None:
        """Test deleting a node that doesn't exist."""
        import pydantic

        class TestNode(pydantic.BaseModel):
            id: str
            name: str

        # Mock result where node was not found
        mock_single_result = {'deleted': 0}
        self.mock_result.single.return_value = mock_single_result
        self.mock_session.run.return_value = self.mock_result

        result = await neo4j.delete_node(TestNode, {'id': '999'})

        # Verify the result is False (node was not found)
        self.assertFalse(result)

    async def test_delete_node_multiple_parameters(self) -> None:
        """Test deleting a node with multiple match parameters."""
        import pydantic

        class TestNode(pydantic.BaseModel):
            slug: str
            type: str

        # Mock result where node was found and deleted
        mock_single_result = {'deleted': 1}
        self.mock_result.single.return_value = mock_single_result
        self.mock_session.run.return_value = self.mock_result

        result = await neo4j.delete_node(
            TestNode, {'slug': 'test-node', 'type': 'Project'}
        )

        # Verify the result is True
        self.assertTrue(result)

        # Verify session.run was called with correct parameters
        self.mock_session.run.assert_called_once()
        call_args = self.mock_session.run.call_args
        query = call_args[0][0]  # First positional argument
        params = call_args[1]  # Keyword arguments

        # Verify both parameters are in the WHERE clause
        self.assertIn('node.slug = $slug', query)
        self.assertIn('node.type = $type', query)
        self.assertIn('AND', query)

        # Verify parameters were passed
        self.assertEqual(params['slug'], 'test-node')
        self.assertEqual(params['type'], 'Project')

    async def test_query_function(self) -> None:
        """Test the query() convenience function."""
        mock_records = [{'name': 'Alice'}, {'name': 'Bob'}]
        self.mock_result.data.return_value = mock_records
        self.mock_session.run.return_value = self.mock_result

        result = await neo4j.query('MATCH (n) RETURN n.name AS name')

        self.assertEqual(result, mock_records)
        self.mock_session.run.assert_called_once()

    async def test_upsert_with_timestamps(self) -> None:
        """Test upsert auto-manages created_at and updated_at."""
        import datetime

        class TimestampNode(pydantic.BaseModel):
            name: str
            created_at: datetime.datetime | None = None
            updated_at: datetime.datetime | None = None

        mock_single_result = {'nodeId': 'elem1'}
        self.mock_result.single.return_value = mock_single_result
        self.mock_session.run.return_value = self.mock_result

        node = TimestampNode(name='test')
        self.assertIsNone(node.created_at)
        self.assertIsNone(node.updated_at)

        await neo4j.upsert(node, {'name': 'test'})

        # Both timestamps should be set now
        self.assertIsNotNone(node.created_at)
        self.assertIsNotNone(node.updated_at)

    async def test_upsert_with_auto_increment(self) -> None:
        """Test upsert with auto_increment fields."""

        class VersionedNode(pydantic.BaseModel):
            name: str
            version: int = 0

        mock_single_result = {'nodeId': 'elem1', 'version': 3}
        self.mock_result.single.return_value = mock_single_result
        self.mock_session.run.return_value = self.mock_result

        node = VersionedNode(name='test', version=2)
        result = await neo4j.upsert(
            node, {'name': 'test'}, auto_increment=['version']
        )

        self.assertEqual(result, 'elem1')
        # Node should be updated in-place with server value
        self.assertEqual(node.version, 3)

        # Verify the query uses coalesce for auto-increment
        call_args = self.mock_session.run.call_args
        query = call_args[0][0]
        self.assertIn('coalesce(node.version, 0) + 1', query)

    async def test_upsert_returns_none_raises(self) -> None:
        """Test upsert raises when query returns no results."""

        class TestNode(pydantic.BaseModel):
            name: str

        self.mock_result.single.return_value = None
        self.mock_session.run.return_value = self.mock_result

        with self.assertRaises(ValueError, msg='no results'):
            await neo4j.upsert(TestNode(name='test'), {'name': 'test'})


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
        mock_neo4j_node = {'id': '123', 'name': 'Test'}

        with mock.patch(
            'cypherantic.create_node', return_value=mock_neo4j_node
        ) as mock_create:
            result = await neo4j.create_node(test_node)

            # Verify cypherantic.create_node was called with session and model
            mock_create.assert_called_once()
            call_args = mock_create.call_args
            self.assertEqual(call_args[0][1], test_node)
            # Verify result is the validated model with round-trip values
            self.assertIsInstance(result, TestNode)
            self.assertEqual(result.id, '123')
            self.assertEqual(result.name, 'Test')

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
            # Should be called with 3 positional args
            # (session, from_node, to_node) and rel_type as keyword argument
            self.assertEqual(len(call_args[0]), 3)
            self.assertEqual(call_args[0][1], from_node)
            self.assertEqual(call_args[0][2], to_node)
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

    async def test_create_relationship_no_props_or_type(self) -> None:
        """Test create_relationship raises without props or type."""

        class FromNode(pydantic.BaseModel):
            id: str

        class ToNode(pydantic.BaseModel):
            id: str

        with self.assertRaises(ValueError, msg='Either rel_props'):
            await neo4j.create_relationship(FromNode(id='1'), ToNode(id='2'))

    async def test_create_node_sets_timestamps(self) -> None:
        """Test create_node sets created_at and updated_at."""
        import datetime

        class TimedNode(pydantic.BaseModel):
            name: str
            created_at: datetime.datetime | None = None
            updated_at: datetime.datetime | None = None

        node = TimedNode(name='test')
        mock_neo4j_node = {
            'name': 'test',
            'created_at': None,
            'updated_at': None,
        }

        with mock.patch(
            'cypherantic.create_node', return_value=mock_neo4j_node
        ):
            result = await neo4j.create_node(node)

        self.assertIsInstance(result, TimedNode)
        # The original node should have timestamps set
        self.assertIsNotNone(node.created_at)
        self.assertIsNotNone(node.updated_at)
