import datetime
import typing
import unittest

import psycopg

from imbi.common.db.etl import graph, ids, mapping
from libraries.common.tests.db.etl import support


class HelperTestCase(unittest.TestCase):
    def test_timestamp(self) -> None:
        self.assertEqual(
            graph.timestamp('2026-01-02T03:04:05.123456+00:00'),
            datetime.datetime(2026, 1, 2, 3, 4, 5, 123456, datetime.UTC),
        )

    def test_timestamp_without_zone_is_utc(self) -> None:
        value = graph.timestamp('2026-01-02T03:04:05')
        self.assertEqual(
            value, datetime.datetime(2026, 1, 2, 3, 4, 5, 0, datetime.UTC)
        )

    def test_timestamp_empty(self) -> None:
        self.assertIsNone(graph.timestamp(None))
        self.assertIsNone(graph.timestamp(''))

    def test_timestamp_not_a_string(self) -> None:
        with self.assertRaises(mapping.EtlError):
            graph.timestamp(12)

    def test_json_array(self) -> None:
        self.assertEqual(graph.json_array([1]), [1])
        self.assertEqual(graph.json_array('["a"]'), ['a'])
        self.assertEqual(graph.json_array(None), [])
        self.assertEqual(graph.json_array(''), [])
        with self.assertRaises(mapping.EtlError):
            graph.json_array('{"a": 1}')

    def test_json_object(self) -> None:
        self.assertEqual(graph.json_object({'a': 1}), {'a': 1})
        self.assertEqual(graph.json_object('{"a": 1}'), {'a': 1})
        self.assertEqual(graph.json_object(''), {})
        with self.assertRaises(mapping.EtlError):
            graph.json_object('[1]')


class VertexHelperTestCase(unittest.TestCase):
    def test_vertex_id(self) -> None:
        self.assertEqual(graph.vertex_id('Tag', '7', {'id': 'x'}), 'x')
        self.assertEqual(
            graph.vertex_id('Tag', '7', {'id': ''}),
            ids.derive_id('Tag', '7'),
        )
        self.assertNotEqual(
            graph.vertex_id('Tag', '7', {}), graph.vertex_id('Team', '7', {})
        )

    def test_created_at(self) -> None:
        context = mapping.Context(source=typing.cast(typing.Any, None))
        later = datetime.datetime(2026, 5, 1, tzinfo=datetime.UTC)
        self.assertEqual(
            graph.created_at(
                {'updated_at': '2026-02-01T00:00:00Z'},
                context,
                later,
                what='x',
            ),
            datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC),
        )
        self.assertEqual(
            graph.created_at({}, context, None, later, what='x'), later
        )
        with self.assertRaisesRegex(mapping.EtlError, 'x has no created_at'):
            graph.created_at({}, context, None, what='x')
        context = mapping.Context(
            source=typing.cast(typing.Any, None), missing_timestamp=later
        )
        self.assertEqual(graph.created_at({}, context, what='x'), later)

    def test_attributes(self) -> None:
        self.assertEqual(
            graph.attributes(
                {
                    'id': 'o',
                    'on': 'true',
                    'off': 'false',
                    'text': 'true',
                    'n': 1,
                },
                frozenset({'id'}),
                frozenset({'on', 'off', 'n'}),
            ),
            {'n': 1, 'off': False, 'on': True, 'text': 'true'},
        )


class FakeGraphTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.conn = await psycopg.AsyncConnection.connect(
            support.url(await support.scratch_database())
        )
        self.addAsyncCleanup(self.conn.close)
        await support.reset(self.conn, 'g')
        await support.fake_graph(
            self.conn,
            'g',
            {
                'Organization': [{'id': 'o1', 'name': 'One'}],
                'Tag': [
                    {'id': 't1', 'slug': 'a'},
                    {'id': 't2', 'slug': 'b'},
                ],
            },
            {
                'BELONGS_TO': [
                    ('Tag', 't2', 'Organization', 'o1'),
                    ('Tag', 't1', 'Organization', 'o1'),
                ]
            },
        )

    async def _labels(self, label: str) -> list[dict[str, typing.Any]]:
        return [
            vertex.properties
            async for vertex in graph.read_label(self.conn, 'g', label)
        ]

    async def test_read_label_in_graph_id_order(self) -> None:
        self.assertEqual(
            await self._labels('Tag'),
            [{'id': 't1', 'slug': 'a'}, {'id': 't2', 'slug': 'b'}],
        )

    async def test_missing_label_is_empty(self) -> None:
        self.assertEqual(await self._labels('Team'), [])

    async def test_read_edges(self) -> None:
        edges = [
            (edge.start.id, edge.end.id, edge.start.graph_id)
            async for edge in graph.read_edges(
                self.conn,
                'g',
                'BELONGS_TO',
                start_label='Tag',
                end_label='Organization',
            )
        ]
        self.assertEqual(edges, [('t2', 'o1', '3'), ('t1', 'o1', '2')])

    async def test_read_edges_other_labels(self) -> None:
        targets = await graph.edge_targets(
            self.conn,
            'g',
            'BELONGS_TO',
            start_label='Team',
            end_label='Organization',
        )
        self.assertEqual(targets, {})

    async def test_nested_reads(self) -> None:
        async with self.conn.transaction():
            pairs = [
                (tag.id, len(await self._labels('Organization')))
                async for tag in graph.read_label(self.conn, 'g', 'Tag')
            ]
        self.assertEqual(pairs, [('t1', 1), ('t2', 1)])


class AgeGraphTestCase(unittest.IsolatedAsyncioTestCase):
    """The reader on a real AGE graph: agtype text is JSON."""

    async def asyncSetUp(self) -> None:
        self.database = await support.scratch_database()
        async with await psycopg.AsyncConnection.connect(
            support.url(self.database)
        ) as conn:
            await support.reset(conn)
            await support.age_graph(
                conn,
                'imbi',
                "CREATE (:Organization {id: 'o1', name: 'O\\'Neil',"
                " tag_formats: [{label: 'semver', pattern: '^v'}],"
                ' count: 3, ratio: 1.5, flag: true, none: null})',
                "MATCH (o:Organization {id: 'o1'})"
                " CREATE (:Tag {id: 't1'})-[:BELONGS_TO {w: 1}]->(o)",
                "CREATE (:Team {slug: 'no-id'})",
            )
        self.conn = await psycopg.AsyncConnection.connect(
            support.url(self.database)
        )
        self.addAsyncCleanup(self.conn.close)

    async def test_read_label(self) -> None:
        rows = [
            vertex.properties
            async for vertex in graph.read_label(
                self.conn, 'imbi', 'Organization'
            )
        ]
        self.assertEqual(
            rows,
            [
                {
                    'id': 'o1',
                    'name': "O'Neil",
                    'tag_formats': [{'label': 'semver', 'pattern': '^v'}],
                    'count': 3,
                    'ratio': 1.5,
                    'flag': True,
                }
            ],
        )

    async def test_read_edges(self) -> None:
        edges = [
            edge
            async for edge in graph.read_edges(
                self.conn,
                'imbi',
                'BELONGS_TO',
                start_label='Tag',
                end_label='Organization',
            )
        ]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].start.properties, {'id': 't1'})
        self.assertEqual(edges[0].properties, {'w': 1})
        self.assertEqual(edges[0].end.id, 'o1')
        self.assertTrue(edges[0].graph_id.isdigit())

    async def test_vertex_without_id(self) -> None:
        [vertex] = [
            v async for v in graph.read_label(self.conn, 'imbi', 'Team')
        ]
        self.assertNotIn('id', vertex.properties)
        self.assertEqual(vertex.id, ids.derive_id('Team', vertex.graph_id))

    async def test_only_organization_id(self) -> None:
        self.assertEqual(
            await graph.only_organization_id(self.conn, 'imbi'), 'o1'
        )

    async def test_only_organization_id_needs_one(self) -> None:
        with self.assertRaisesRegex(mapping.EtlError, 'has 0'):
            await graph.only_organization_id(self.conn, 'other')
