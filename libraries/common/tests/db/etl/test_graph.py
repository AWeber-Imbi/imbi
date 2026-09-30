import datetime
import typing
import unittest

import psycopg

from imbi.common.db.etl import graph, mapping
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


class FakeGraphTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = await support.create_database('graph')
        self.addAsyncCleanup(support.drop_database, self.database)
        self.conn = await psycopg.AsyncConnection.connect(
            support.url(self.database)
        )
        self.addAsyncCleanup(self.conn.close)
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
        return [row async for row in graph.read_label(self.conn, 'g', label)]

    async def test_read_label_in_graph_id_order(self) -> None:
        self.assertEqual(
            await self._labels('Tag'),
            [{'id': 't1', 'slug': 'a'}, {'id': 't2', 'slug': 'b'}],
        )

    async def test_missing_label_is_empty(self) -> None:
        self.assertEqual(await self._labels('Team'), [])

    async def test_read_edges(self) -> None:
        edges = [
            (start['id'], end['id'])
            async for start, _edge, end in graph.read_edges(
                self.conn,
                'g',
                'BELONGS_TO',
                start_label='Tag',
                end_label='Organization',
            )
        ]
        self.assertEqual(edges, [('t2', 'o1'), ('t1', 'o1')])

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
                (tag['id'], len(await self._labels('Organization')))
                async for tag in graph.read_label(self.conn, 'g', 'Tag')
            ]
        self.assertEqual(pairs, [('t1', 1), ('t2', 1)])


class AgeGraphTestCase(unittest.IsolatedAsyncioTestCase):
    """The reader on a real AGE graph: agtype text is JSON."""

    async def asyncSetUp(self) -> None:
        self.database = await support.create_database('age')
        self.addAsyncCleanup(support.drop_database, self.database)
        async with await psycopg.AsyncConnection.connect(
            support.url(self.database)
        ) as conn:
            await support.age_graph(
                conn,
                'imbi',
                "CREATE (:Organization {id: 'o1', name: 'O\\'Neil',"
                " tag_formats: [{label: 'semver', pattern: '^v'}],"
                ' count: 3, ratio: 1.5, flag: true, none: null})',
                "MATCH (o:Organization {id: 'o1'})"
                " CREATE (:Tag {id: 't1'})-[:BELONGS_TO {w: 1}]->(o)",
            )
        self.conn = await psycopg.AsyncConnection.connect(
            support.url(self.database)
        )
        self.addAsyncCleanup(self.conn.close)

    async def test_read_label(self) -> None:
        rows = [
            row
            async for row in graph.read_label(
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
        self.assertEqual(edges[0][0], {'id': 't1'})
        self.assertEqual(edges[0][1], {'w': 1})
        self.assertEqual(edges[0][2]['id'], 'o1')
