"""Tests for the graph module."""

import json
import unittest

import dotenv
import fastapi
import fastapi.testclient

from imbi_common import graph, lifespan

dotenv.load_dotenv()


class ParseAgtypeTests(unittest.TestCase):
    def test_none_passthrough(self) -> None:
        self.assertIsNone(graph._parse_agtype(None))

    def test_non_string_passthrough(self) -> None:
        self.assertEqual(42, graph._parse_agtype(42))

    def test_vertex_extracts_properties(self) -> None:
        vertex = (
            json.dumps(
                {
                    'id': 1,
                    'label': 'Organization',
                    'properties': {'name': 'Acme', 'slug': 'acme'},
                }
            )
            + '::vertex'
        )
        result = graph._parse_agtype(vertex)
        self.assertEqual('Acme', result['name'])
        self.assertEqual('acme', result['slug'])

    def test_bare_json_string(self) -> None:
        self.assertEqual(
            {'key': 'val'},
            graph._parse_agtype('{"key": "val"}'),
        )

    def test_non_json_string_passthrough(self) -> None:
        self.assertEqual('hello', graph._parse_agtype('hello'))

    def test_edge_suffix_stripped(self) -> None:
        edge = (
            json.dumps(
                {
                    'id': 1,
                    'start_id': 2,
                    'end_id': 3,
                    'label': 'BELONGS_TO',
                    'properties': {},
                }
            )
            + '::edge'
        )
        result = graph._parse_agtype(edge)
        self.assertIsInstance(result, dict)


class GraphInitTests(unittest.TestCase):
    def test_pool_not_opened_on_init(self) -> None:
        g = graph.Graph()
        self.assertFalse(g.opened)

    def test_settings_loaded(self) -> None:
        g = graph.Graph()
        self.assertIsNotNone(g.settings)
        self.assertIsNotNone(g.settings.url)

    def test_pool_created(self) -> None:
        g = graph.Graph()
        self.assertIsNotNone(g.pool)


class GraphOpenCloseTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_sets_opened(self) -> None:
        g = graph.Graph()
        await g.open()
        try:
            self.assertTrue(g.opened)
        finally:
            await g.close()

    async def test_close_after_open(self) -> None:
        g = graph.Graph()
        await g.open()
        await g.close()
        # Pool is closed; opening a new one should still work
        g2 = graph.Graph()
        await g2.open()
        self.assertTrue(g2.opened)
        await g2.close()


class GraphExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_raises_when_not_opened(self) -> None:
        g = graph.Graph()
        with self.assertRaises(RuntimeError):
            await g.execute('MATCH (n) RETURN n')

    async def test_execute_succeeds_when_opened(self) -> None:
        g = graph.Graph()
        await g.open()
        try:
            result = await g.execute('MATCH (n) RETURN n')
            self.assertIsInstance(result, list)
        finally:
            await g.close()


class GraphLifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_yields_opened_graph(self) -> None:
        async with graph.graph_lifespan() as g:
            self.assertIsInstance(g, graph.Graph)
            self.assertTrue(g.opened)

    async def test_graph_usable_inside_context(self) -> None:
        async with graph.graph_lifespan() as g:
            result = await g.execute('MATCH (n) RETURN n')
            self.assertIsInstance(result, list)


class GraphDependencyInjectionTests(unittest.TestCase):
    def test_pool_injected_into_route(self) -> None:
        app = fastapi.FastAPI(
            lifespan=lifespan.Lifespan(graph.graph_lifespan),
        )

        @app.get('/test')
        def handler(*, pool: graph.Pool) -> dict[str, bool]:
            return {'opened': pool.opened}

        with fastapi.testclient.TestClient(app) as client:
            response = client.get('/test')
            self.assertEqual(200, response.status_code)
            self.assertTrue(response.json()['opened'])
