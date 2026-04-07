import typing
import unittest
from unittest import mock

import pydantic

from imbi_common import age
from imbi_common.age import client, relationships


class ConvertNeo4jTypesTestCase(unittest.TestCase):
    """Test cases for convert_neo4j_types (AGE compatibility shim)."""

    def test_dict_conversion(self) -> None:
        """Test dict values are recursively converted."""
        result = age.convert_neo4j_types({'a': 1, 'b': 'hello'})
        self.assertEqual(result, {'a': 1, 'b': 'hello'})

    def test_list_conversion(self) -> None:
        """Test list values are recursively converted."""
        result = age.convert_neo4j_types([1, 'hello', True])
        self.assertEqual(result, [1, 'hello', True])

    def test_nested_list_in_dict(self) -> None:
        """Test nested lists in dicts are converted."""
        result = age.convert_neo4j_types({'items': ['val', 'plain']})
        self.assertEqual(result, {'items': ['val', 'plain']})

    def test_primitive_passthrough(self) -> None:
        """Test primitives are returned as-is."""
        self.assertEqual(age.convert_neo4j_types(42), 42)
        self.assertEqual(age.convert_neo4j_types('hello'), 'hello')
        self.assertIsNone(age.convert_neo4j_types(None))


class PrepareNodeDataTestCase(unittest.TestCase):
    """Test cases for _prepare_node_data."""

    def test_relationship_field_with_default(self) -> None:
        """Test relationship field gets default value."""

        class MyNode(pydantic.BaseModel):
            name: str
            friends: typing.Annotated[
                list[str],
                relationships.Relationship(
                    rel_type='FRIENDS',
                    direction='OUTGOING',
                ),
            ] = []

        result = age._prepare_node_data(MyNode, {'name': 'Alice'})
        self.assertEqual(result['name'], 'Alice')
        self.assertEqual(result['friends'], [])

    def test_relationship_field_without_default(self) -> None:
        """Test required relationship field gets None."""

        class MyNode(pydantic.BaseModel):
            name: str
            org: typing.Annotated[
                str,
                relationships.Relationship(
                    rel_type='BELONGS_TO',
                    direction='OUTGOING',
                ),
            ]

        result = age._prepare_node_data(MyNode, {'name': 'Alice'})
        self.assertEqual(result['name'], 'Alice')
        self.assertIsNone(result['org'])

    def test_existing_data_not_overwritten(self) -> None:
        """Test existing node data is preserved."""

        class MyNode(pydantic.BaseModel):
            name: str
            friends: typing.Annotated[
                list[str],
                relationships.Relationship(
                    rel_type='FRIENDS',
                    direction='OUTGOING',
                ),
            ] = []

        result = age._prepare_node_data(
            MyNode, {'name': 'Alice', 'friends': ['Bob']}
        )
        self.assertEqual(result['friends'], ['Bob'])


class BuildFetchQueryTestCase(unittest.TestCase):
    """Test cases for _build_fetch_query."""

    def test_simple_query(self) -> None:
        """Test basic MATCH query."""

        class MyNode(pydantic.BaseModel):
            name: str

        result = age._build_fetch_query(MyNode)
        self.assertEqual(result, 'MATCH (node:MyNode) RETURN node')

    def test_query_with_parameters(self) -> None:
        """Test query with match parameters."""

        class MyNode(pydantic.BaseModel):
            name: str

        result = age._build_fetch_query(MyNode, {'name': 'test'})
        self.assertIn('name: $name', result)

    def test_query_with_string_order_by(self) -> None:
        """Test query with string order_by."""
        result = age._build_fetch_query('MyNode', order_by='name')
        self.assertIn('ORDER BY node.name', result)

    def test_query_with_list_order_by(self) -> None:
        """Test query with list order_by."""
        result = age._build_fetch_query(
            'MyNode', order_by=['name', 'priority']
        )
        self.assertIn('ORDER BY node.name, node.priority', result)

    def test_query_with_string_model(self) -> None:
        """Test query with string model name."""
        result = age._build_fetch_query('Blueprint')
        self.assertEqual(result, 'MATCH (node:Blueprint) RETURN node')


class AGEAbstractionsTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()

        # Clear the singleton instance
        client.AGE._instance = None

        self.mock_pool = mock.AsyncMock()
        self.mock_conn = mock.AsyncMock()
        self.mock_cursor = mock.AsyncMock()

        # Set up connection context manager
        mock_conn_cm = mock.AsyncMock()
        mock_conn_cm.__aenter__.return_value = self.mock_conn
        mock_conn_cm.__aexit__.return_value = None
        self.mock_pool.connection = mock.MagicMock(return_value=mock_conn_cm)
        self.mock_pool.close = mock.AsyncMock()
        self.mock_pool.open = mock.AsyncMock()

        # Default: execute returns a cursor with empty results
        self.mock_conn.execute.return_value = self.mock_cursor
        self.mock_cursor.fetchall.return_value = []

        # Patch pool creation where it's imported
        self.pool_patcher = mock.patch(
            'imbi_common.age.client.AsyncConnectionPool',
            return_value=self.mock_pool,
        )
        self.mock_pool_class = self.pool_patcher.start()
        self.addCleanup(self.pool_patcher.stop)

    async def test_initialize_function(self) -> None:
        """Test module-level initialize function."""
        await age.initialize()
        # Should have opened the pool
        self.mock_pool.open.assert_called()

    async def test_aclose_function(self) -> None:
        """Test module-level aclose function."""
        # Ensure pool exists first
        instance = client.AGE.get_instance()
        await instance._ensure_pool()
        await age.aclose()
        self.mock_pool.close.assert_called()

    async def test_session_context_manager(self) -> None:
        """Test session context manager."""
        async with age.session() as conn:
            self.assertEqual(conn, self.mock_conn)

    async def test_run_context_manager(self) -> None:
        """Test run context manager with query."""
        self.mock_cursor.fetchall.return_value = [
            ('Alice',),
        ]

        async with age.run('MATCH (n) RETURN n') as result:
            data = await result.data()
            self.assertEqual(len(data), 1)

    def test_cypher_property_params(self) -> None:
        """Test cypher property parameter generation."""
        params = {'id': '123', 'name': 'test'}
        result = age.cypher_property_params(params)
        self.assertEqual(result, 'id: $id, name: $name')

        # Test empty params
        self.assertEqual(age.cypher_property_params({}), '')
        self.assertEqual(age.cypher_property_params(None), '')

    async def test_upsert_node(self) -> None:
        """Test upserting a node."""

        class TestNode(pydantic.BaseModel):
            id: str
            name: str

        # Mock AGE returning a row with nodeId
        node_id = 123
        self.mock_cursor.fetchall.return_value = [
            (str(node_id),),
        ]

        test_node = TestNode(id='123', name='Test Node')
        result = await age.upsert(test_node, {'id': '123'})

        # Verify the result (AGE returns integer vertex id as string)
        self.assertEqual(result, str(node_id))

        # Verify execute was called
        self.mock_conn.execute.assert_called()
        call_args = self.mock_conn.execute.call_args
        sql = str(call_args[0][0])

        # Verify query contains MERGE, ON CREATE SET, ON MATCH SET
        self.assertIn('MERGE', sql)
        self.assertIn('ON CREATE SET', sql)
        self.assertIn('ON MATCH SET', sql)

    async def test_delete_node_found(self) -> None:
        """Test deleting a node that exists."""

        class TestNode(pydantic.BaseModel):
            id: str
            name: str

        # Mock result where node was found and deleted
        self.mock_cursor.fetchall.return_value = [
            ('1',),
        ]

        result = await age.delete_node(TestNode, {'id': '123'})

        # Verify the result is True (node was deleted)
        self.assertTrue(result)

        # Verify execute was called
        self.mock_conn.execute.assert_called()
        sql = str(self.mock_conn.execute.call_args[0][0])

        # Verify query contains DELETE and WHERE
        self.assertIn('DELETE', sql)
        self.assertIn('WHERE', sql)
        self.assertIn('TestNode', sql)

    async def test_delete_node_not_found(self) -> None:
        """Test deleting a node that doesn't exist."""

        class TestNode(pydantic.BaseModel):
            id: str
            name: str

        # Mock result where count is 0
        self.mock_cursor.fetchall.return_value = [
            ('0',),
        ]

        result = await age.delete_node(TestNode, {'id': '999'})

        # Verify the result is False (node was not found)
        self.assertFalse(result)

    async def test_delete_node_multiple_parameters(self) -> None:
        """Test deleting a node with multiple match parameters."""

        class TestNode(pydantic.BaseModel):
            slug: str
            type: str

        # Mock result where node was found and deleted
        self.mock_cursor.fetchall.return_value = [
            ('1',),
        ]

        result = await age.delete_node(
            TestNode, {'slug': 'test-node', 'type': 'Project'}
        )

        # Verify the result is True
        self.assertTrue(result)

        # Verify execute was called with correct query
        sql = str(self.mock_conn.execute.call_args[0][0])

        # Verify both parameters are in the WHERE clause
        self.assertIn('node.slug', sql)
        self.assertIn('node.type', sql)
        self.assertIn('AND', sql)

    async def test_query_function(self) -> None:
        """Test the query() convenience function."""
        # AGE returns tuples; the first column is 'name' based
        # on RETURN clause parsing
        self.mock_cursor.fetchall.return_value = [
            ("'Alice'",),
            ("'Bob'",),
        ]

        result = await age.query('MATCH (n) RETURN n.name AS name')

        self.assertEqual(len(result), 2)
        self.mock_conn.execute.assert_called()

    async def test_upsert_with_timestamps(self) -> None:
        """Test upsert auto-manages created_at and updated_at."""
        import datetime

        class TimestampNode(pydantic.BaseModel):
            name: str
            created_at: datetime.datetime | None = None
            updated_at: datetime.datetime | None = None

        self.mock_cursor.fetchall.return_value = [
            ('42',),
        ]

        node = TimestampNode(name='test')
        self.assertIsNone(node.created_at)
        self.assertIsNone(node.updated_at)

        await age.upsert(node, {'name': 'test'})

        # Both timestamps should be set now
        self.assertIsNotNone(node.created_at)
        self.assertIsNotNone(node.updated_at)

    async def test_upsert_with_auto_increment(self) -> None:
        """Test upsert with auto_increment fields."""

        class VersionedNode(pydantic.BaseModel):
            name: str
            version: int = 0

        # Return nodeId and version from AGE
        self.mock_cursor.fetchall.return_value = [
            ('42', '3'),
        ]

        node = VersionedNode(name='test', version=2)
        result = await age.upsert(
            node, {'name': 'test'}, auto_increment=['version']
        )

        self.assertEqual(result, '42')
        # Node should be updated in-place with server value
        self.assertEqual(node.version, 3)

        # Verify the query uses coalesce for auto-increment
        sql = str(self.mock_conn.execute.call_args[0][0])
        self.assertIn('coalesce(node.version, 0) + 1', sql)

    async def test_upsert_returns_none_raises(self) -> None:
        """Test upsert raises when query returns no results."""

        class TestNode(pydantic.BaseModel):
            name: str

        self.mock_cursor.fetchall.return_value = []

        with self.assertRaises(ValueError, msg='no results'):
            await age.upsert(TestNode(name='test'), {'name': 'test'})


class AGERelationshipWrappersTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for relationship wrapper functions."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()

        # Clear the singleton instance
        client.AGE._instance = None

        self.mock_pool = mock.AsyncMock()
        self.mock_conn = mock.AsyncMock()
        self.mock_cursor = mock.AsyncMock()

        # Set up connection context manager
        mock_conn_cm = mock.AsyncMock()
        mock_conn_cm.__aenter__.return_value = self.mock_conn
        mock_conn_cm.__aexit__.return_value = None
        self.mock_pool.connection = mock.MagicMock(return_value=mock_conn_cm)
        self.mock_pool.close = mock.AsyncMock()
        self.mock_pool.open = mock.AsyncMock()

        self.mock_conn.execute.return_value = self.mock_cursor
        self.mock_cursor.fetchall.return_value = []

        # Patch pool creation where it's imported
        self.pool_patcher = mock.patch(
            'imbi_common.age.client.AsyncConnectionPool',
            return_value=self.mock_pool,
        )
        self.mock_pool_class = self.pool_patcher.start()
        self.addCleanup(self.pool_patcher.stop)

    async def test_create_node(self) -> None:
        """Test create_node wrapper function."""

        class TestNode(pydantic.BaseModel):
            id: str
            name: str

        # Mock AGE returning a vertex row
        import json

        vertex = json.dumps(
            {
                'id': 1,
                'label': 'TestNode',
                'properties': {'id': '123', 'name': 'Test'},
            }
        )
        self.mock_cursor.fetchall.return_value = [
            (f'{vertex}::vertex',),
        ]

        test_node = TestNode(id='123', name='Test')
        result = await age.create_node(test_node)

        # Verify result is the validated model
        self.assertIsInstance(result, TestNode)
        self.assertEqual(result.id, '123')
        self.assertEqual(result.name, 'Test')

    async def test_create_relationship_with_type(self) -> None:
        """Test create_relationship with relationship type string."""

        class FromNode(pydantic.BaseModel):
            id: str

        class ToNode(pydantic.BaseModel):
            id: str

        from_node = FromNode(id='1')
        to_node = ToNode(id='2')

        # Mock AGE returning an edge
        self.mock_cursor.fetchall.return_value = [
            ('{}::edge',),
        ]

        await age.create_relationship(from_node, to_node, rel_type='KNOWS')

        # Verify execute was called with a CREATE query
        sql = str(self.mock_conn.execute.call_args[0][0])
        self.assertIn('CREATE', sql)
        self.assertIn('KNOWS', sql)

    async def test_create_relationship_no_props_or_type(self) -> None:
        """Test create_relationship raises without props or type."""

        class FromNode(pydantic.BaseModel):
            id: str

        class ToNode(pydantic.BaseModel):
            id: str

        with self.assertRaises(ValueError, msg='Either rel_props'):
            await age.create_relationship(FromNode(id='1'), ToNode(id='2'))

    async def test_create_node_sets_timestamps(self) -> None:
        """Test create_node sets created_at and updated_at."""
        import datetime
        import json

        class TimedNode(pydantic.BaseModel):
            name: str
            created_at: datetime.datetime | None = None
            updated_at: datetime.datetime | None = None

        vertex = json.dumps(
            {
                'id': 1,
                'label': 'TimedNode',
                'properties': {
                    'name': 'test',
                    'created_at': None,
                    'updated_at': None,
                },
            }
        )
        self.mock_cursor.fetchall.return_value = [
            (f'{vertex}::vertex',),
        ]

        node = TimedNode(name='test')
        result = await age.create_node(node)

        self.assertIsInstance(result, TimedNode)
        # The original node should have timestamps set
        self.assertIsNotNone(node.created_at)
        self.assertIsNotNone(node.updated_at)

    async def test_create_relationship_with_rel_props(self) -> None:
        """Test create_relationship using rel_props with config."""
        import json

        class FromNode(pydantic.BaseModel):
            id: str

        class ToNode(pydantic.BaseModel):
            id: str

        class RelProps(pydantic.BaseModel):
            weight: int = 1

            class cypherantic_config:  # noqa: N801
                rel_type = 'LINKED_TO'

        from_node = FromNode(id='1')
        to_node = ToNode(id='2')

        edge = json.dumps({'id': 10, 'label': 'LINKED_TO', 'properties': {}})
        self.mock_cursor.fetchall.return_value = [
            (f'{edge}::edge',),
        ]

        result = await age.create_relationship(
            from_node, to_node, rel_props=RelProps(weight=5)
        )

        sql = str(self.mock_conn.execute.call_args[0][0])
        self.assertIn('LINKED_TO', sql)
        self.assertIn('weight', sql)
        self.assertIsInstance(result, dict)

    async def test_create_relationship_rel_props_no_config_no_type(
        self,
    ) -> None:
        """Test create_relationship with rel_props lacking config."""

        class FromNode(pydantic.BaseModel):
            id: str

        class ToNode(pydantic.BaseModel):
            id: str

        class RelProps(pydantic.BaseModel):
            weight: int = 1

        with self.assertRaises(ValueError):
            await age.create_relationship(
                FromNode(id='1'),
                ToNode(id='2'),
                rel_props=RelProps(),
            )

    async def test_create_relationship_empty_result(self) -> None:
        """Test create_relationship returns empty dict on no result."""

        class FromNode(pydantic.BaseModel):
            id: str

        class ToNode(pydantic.BaseModel):
            id: str

        self.mock_cursor.fetchall.return_value = []

        result = await age.create_relationship(
            FromNode(id='1'), ToNode(id='2'), rel_type='KNOWS'
        )
        self.assertEqual(result, {})

    async def test_refresh_relationship_outgoing(self) -> None:
        """Test refresh_relationship loads outgoing relationship."""
        import json

        class TeamNode(pydantic.BaseModel):
            slug: str
            members: typing.Annotated[
                list[typing.Any],
                relationships.Relationship(
                    rel_type='MEMBER_OF',
                    direction='OUTGOING',
                ),
            ] = []

        vertex = json.dumps(
            {
                'id': 2,
                'label': 'Person',
                'properties': {'name': 'Alice'},
            }
        )
        self.mock_cursor.fetchall.return_value = [
            (f'{vertex}::vertex',),
        ]

        node = TeamNode(slug='team-a')
        await age.refresh_relationship(node, 'members')
        self.assertEqual(len(node.members), 1)

    async def test_refresh_relationship_incoming(self) -> None:
        """Test refresh_relationship with incoming direction."""
        import json

        class OrgNode(pydantic.BaseModel):
            slug: str
            parent: typing.Annotated[
                typing.Any | None,
                relationships.Relationship(
                    rel_type='PARENT_OF',
                    direction='INCOMING',
                ),
            ] = None

        vertex = json.dumps(
            {
                'id': 3,
                'label': 'Org',
                'properties': {'name': 'ParentOrg'},
            }
        )
        self.mock_cursor.fetchall.return_value = [
            (f'{vertex}::vertex',),
        ]

        node = OrgNode(slug='child-org')
        await age.refresh_relationship(node, 'parent')
        self.assertIsNotNone(node.parent)

    async def test_refresh_relationship_undirected(self) -> None:
        """Test refresh_relationship with undirected direction."""

        class PeerNode(pydantic.BaseModel):
            slug: str
            peers: typing.Annotated[
                list[typing.Any],
                relationships.Relationship(
                    rel_type='PEERS_WITH',
                    direction='UNDIRECTED',
                ),
            ] = []

        self.mock_cursor.fetchall.return_value = []

        node = PeerNode(slug='peer-a')
        await age.refresh_relationship(node, 'peers')
        self.assertEqual(node.peers, [])

    async def test_refresh_relationship_no_field(self) -> None:
        """Test refresh_relationship raises for unknown field."""

        class SimpleNode(pydantic.BaseModel):
            slug: str

        with self.assertRaises(ValueError):
            await age.refresh_relationship(SimpleNode(slug='a'), 'nonexistent')

    async def test_refresh_relationship_no_rel_metadata(self) -> None:
        """Test refresh_relationship raises for non-relationship."""

        class SimpleNode(pydantic.BaseModel):
            slug: str
            name: str = ''

        with self.assertRaises(ValueError):
            await age.refresh_relationship(SimpleNode(slug='a'), 'name')

    async def test_retrieve_relationship_edges(self) -> None:
        """Test retrieve_relationship_edges returns typed edges."""
        import json

        class PersonNode(pydantic.BaseModel):
            name: str

        class WeightProps(pydantic.BaseModel):
            weight: int = 1

        class PersonEdge(typing.NamedTuple):
            node: PersonNode
            properties: WeightProps

        class TeamNode(pydantic.BaseModel):
            slug: str

        vertex = json.dumps(
            {
                'id': 2,
                'label': 'PersonNode',
                'properties': {'name': 'Alice'},
            }
        )
        edge = json.dumps(
            {
                'id': 10,
                'label': 'MEMBER_OF',
                'properties': {'weight': 3},
            }
        )
        self.mock_cursor.fetchall.return_value = [
            (f'{vertex}::vertex', f'{edge}::edge'),
        ]

        node = TeamNode(slug='team-a')
        edges = await age.retrieve_relationship_edges(
            node, 'MEMBER_OF', 'OUTGOING', PersonEdge
        )
        self.assertEqual(len(edges), 1)
        self.assertIsInstance(edges[0].node, PersonNode)
        self.assertEqual(edges[0].node.name, 'Alice')
        self.assertEqual(edges[0].properties.weight, 3)

    async def test_retrieve_relationship_edges_incoming(self) -> None:
        """Test retrieve_relationship_edges incoming direction."""

        class SimpleEdge(typing.NamedTuple):
            node: dict[str, typing.Any]
            properties: dict[str, typing.Any]

        class MyNode(pydantic.BaseModel):
            id: str

        self.mock_cursor.fetchall.return_value = []

        edges = await age.retrieve_relationship_edges(
            MyNode(id='1'), 'REL', 'INCOMING', SimpleEdge
        )
        self.assertEqual(edges, [])

    async def test_retrieve_relationship_edges_undirected(self) -> None:
        """Test retrieve_relationship_edges undirected."""

        class SimpleEdge(typing.NamedTuple):
            node: dict[str, typing.Any]
            properties: dict[str, typing.Any]

        class MyNode(pydantic.BaseModel):
            id: str

        self.mock_cursor.fetchall.return_value = []

        edges = await age.retrieve_relationship_edges(
            MyNode(id='1'), 'REL', 'UNDIRECTED', SimpleEdge
        )
        self.assertEqual(edges, [])

    async def test_fetch_node_found(self) -> None:
        """Test fetch_node returns model when found."""
        import json

        class TestNode(pydantic.BaseModel):
            id: str
            name: str

        vertex = json.dumps(
            {
                'id': 1,
                'label': 'TestNode',
                'properties': {'id': '123', 'name': 'Found'},
            }
        )
        self.mock_cursor.fetchall.return_value = [
            (f'{vertex}::vertex',),
        ]

        result = await age.fetch_node(TestNode, {'id': '123'})
        self.assertIsNotNone(result)
        self.assertEqual(result.name, 'Found')

    async def test_fetch_node_not_found(self) -> None:
        """Test fetch_node returns None when not found."""

        class TestNode(pydantic.BaseModel):
            id: str

        self.mock_cursor.fetchall.return_value = []
        result = await age.fetch_node(TestNode, {'id': 'nope'})
        self.assertIsNone(result)

    async def test_fetch_nodes_generator(self) -> None:
        """Test fetch_nodes yields model instances."""
        import json

        class TestNode(pydantic.BaseModel):
            id: str
            name: str

        v1 = json.dumps(
            {
                'id': 1,
                'label': 'TestNode',
                'properties': {'id': '1', 'name': 'A'},
            }
        )
        v2 = json.dumps(
            {
                'id': 2,
                'label': 'TestNode',
                'properties': {'id': '2', 'name': 'B'},
            }
        )
        self.mock_cursor.fetchall.return_value = [
            (f'{v1}::vertex',),
            (f'{v2}::vertex',),
        ]

        results = [node async for node in age.fetch_nodes(TestNode)]
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].name, 'A')
        self.assertEqual(results[1].name, 'B')

    async def test_upsert_with_relationship_fields(self) -> None:
        """Test upsert excludes relationship fields from properties."""

        class NodeWithRel(pydantic.BaseModel):
            slug: str
            name: str
            teams: typing.Annotated[
                list[typing.Any],
                relationships.Relationship(
                    rel_type='MEMBER_OF',
                    direction='OUTGOING',
                ),
            ] = []

        self.mock_cursor.fetchall.return_value = [
            ('99',),
        ]

        node = NodeWithRel(slug='test', name='Test', teams=['a'])
        result = await age.upsert(node, {'slug': 'test'})
        self.assertEqual(result, '99')

        sql = str(self.mock_conn.execute.call_args[0][0])
        self.assertNotIn('teams', sql)

    async def test_upsert_with_immutable_fields(self) -> None:
        """Test upsert omits immutable fields from ON MATCH SET."""

        class ImmutableNode(pydantic.BaseModel):
            slug: str
            name: str
            created_by: str = ''

        self.mock_cursor.fetchall.return_value = [
            ('55', "'admin'"),
        ]

        node = ImmutableNode(slug='test', name='Updated', created_by='admin')
        await age.upsert(
            node,
            {'slug': 'test'},
            immutable_fields=['created_by'],
        )

        sql = str(self.mock_conn.execute.call_args[0][0])
        self.assertIn('ON CREATE SET', sql)
        on_match_idx = sql.find('ON MATCH SET')
        return_idx = sql.find('RETURN')
        if on_match_idx != -1 and return_idx != -1:
            on_match_part = sql[on_match_idx:return_idx]
            self.assertNotIn('created_by', on_match_part)

    async def test_create_node_empty_result(self) -> None:
        """Test create_node raises RuntimeError on empty result."""

        class TestNode(pydantic.BaseModel):
            name: str

        self.mock_cursor.fetchall.return_value = []
        node = TestNode(name='orphan')
        with self.assertRaises(RuntimeError):
            await age.create_node(node)


class EscapeCypherValueTestCase(unittest.TestCase):
    """Test _escape_cypher_value for uncovered branches."""

    def test_float_value(self) -> None:
        result = age._escape_cypher_value(3.14)
        self.assertEqual(result, '3.14')

    def test_date_value(self) -> None:
        import datetime

        d = datetime.date(2026, 4, 7)
        result = age._escape_cypher_value(d)
        self.assertEqual(result, "'2026-04-07'")

    def test_datetime_value(self) -> None:
        import datetime

        dt = datetime.datetime(2026, 4, 7, 12, 0, 0, tzinfo=datetime.UTC)
        result = age._escape_cypher_value(dt)
        self.assertIn('2026-04-07', result)

    def test_anyurl_value(self) -> None:
        url = pydantic.AnyUrl('https://example.com')
        result = age._escape_cypher_value(url)
        self.assertIn('example.com', result)

    def test_fallback_to_string(self) -> None:
        """Test non-standard types fall back to string."""

        class Custom:
            def __str__(self) -> str:
                return 'custom_val'

        result = age._escape_cypher_value(Custom())
        self.assertIn('custom_val', result)


class UniqueKeyPropsTestCase(unittest.TestCase):
    """Test _unique_key_props for uncovered branches."""

    def test_json_schema_extra_unique(self) -> None:
        """Test field with unique=True in json_schema_extra."""

        class UniqueNode(pydantic.BaseModel):
            slug: str = pydantic.Field(json_schema_extra={'unique': True})
            name: str = ''

        node = UniqueNode(slug='my-slug', name='My Name')
        props = age._unique_key_props(node)
        self.assertEqual(props, {'slug': 'my-slug'})

    def test_raises_when_no_unique_fields(self) -> None:
        """Test ValueError raised when no unique fields found."""

        class PlainNode(pydantic.BaseModel):
            title: str
            count: int = 0

        node = PlainNode(title='hello')
        with self.assertRaises(ValueError):
            age._unique_key_props(node)

    def test_raises_for_relationship_only_model(self) -> None:
        """Test ValueError for model with only relationship fields."""

        class RelNode(pydantic.BaseModel):
            links: typing.Annotated[
                list[str],
                relationships.Relationship(
                    rel_type='LINKS_TO',
                    direction='OUTGOING',
                ),
            ] = []
            title: str = ''

        node = RelNode(title='hi')
        with self.assertRaises(ValueError):
            age._unique_key_props(node)


class RelationshipFieldNamesTestCase(unittest.TestCase):
    """Test _relationship_field_names."""

    def test_includes_alias(self) -> None:
        """Test that field aliases are included."""

        class AliasedNode(pydantic.BaseModel):
            friends: typing.Annotated[
                list[str],
                relationships.Relationship(
                    rel_type='FRIENDS',
                    direction='OUTGOING',
                ),
            ] = pydantic.Field(default=[], alias='friendList')

        names = age._relationship_field_names(AliasedNode)
        self.assertIn('friends', names)
        self.assertIn('friendList', names)


class AGEResultTestCase(unittest.TestCase):
    """Test _AGEResult methods."""

    def test_getitem_raises_on_empty(self) -> None:
        result = age._AGEResult([], ['col'])
        with self.assertRaises(KeyError):
            _ = result['col']

    def test_contains(self) -> None:
        result = age._AGEResult([], ['col'])
        self.assertIn('col', result)
        self.assertNotIn('other', result)
