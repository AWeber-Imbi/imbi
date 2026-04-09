"""Tests for the graph module."""

import json
import unittest
from unittest import mock

import dotenv
import fastapi
import fastapi.testclient

from imbi_common import graph, lifespan, models
from imbi_common.graph import client

dotenv.load_dotenv()


class ParseAgtypeTests(unittest.TestCase):
    def test_none_passthrough(self) -> None:
        self.assertIsNone(graph.parse_agtype(None))

    def test_non_string_passthrough(self) -> None:
        self.assertEqual(42, graph.parse_agtype(42))

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
        result = graph.parse_agtype(vertex)
        self.assertEqual('Acme', result['name'])
        self.assertEqual('acme', result['slug'])

    def test_bare_json_string(self) -> None:
        self.assertEqual(
            {'key': 'val'},
            graph.parse_agtype('{"key": "val"}'),
        )

    def test_non_json_string_passthrough(self) -> None:
        self.assertEqual('hello', graph.parse_agtype('hello'))

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
        result = graph.parse_agtype(edge)
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


class GraphModelCreateDeleteTests(
    unittest.IsolatedAsyncioTestCase,
):
    """Verify create/delete accept GraphModel (non-Node)."""

    @mock.patch.object(graph.Graph, '_execute_batch')
    async def test_create_graph_model(
        self,
        mock_batch: mock.AsyncMock,
    ) -> None:
        g = graph.Graph()
        g.opened = True
        gm = models.GraphModel(id='gm-1')
        result = await g.create(gm)
        self.assertIs(result, gm)
        mock_batch.assert_awaited_once()

    @mock.patch.object(graph.Graph, '_execute_on')
    async def test_delete_graph_model(
        self,
        mock_exec: mock.AsyncMock,
    ) -> None:
        g = graph.Graph()
        g.opened = True
        mock_conn = mock.AsyncMock()
        ctx = mock.AsyncMock()
        ctx.__aenter__ = mock.AsyncMock(
            return_value=mock_conn,
        )
        ctx.__aexit__ = mock.AsyncMock(
            return_value=False,
        )
        mock_pool = mock.MagicMock()
        mock_pool.connection.return_value = ctx
        g.pool = mock_pool
        gm = models.GraphModel(id='gm-1')
        await g.delete(gm)
        mock_exec.assert_awaited_once()
        # _delete_embeddings should NOT be called for non-Node
        mock_conn.execute.assert_not_awaited()


class EmbeddableFieldsTests(unittest.TestCase):
    """Test the _embeddable_fields helper."""

    def test_embeddable_fields_returned(self) -> None:
        """Organization inherits Embeddable from Node."""
        org = models.Organization(
            name='Org',
            slug='org',
            description='Desc',
        )
        fields = client._embeddable_fields(org)
        names = [f[0] for f in fields]
        self.assertIn('name', names)
        self.assertIn('description', names)

    def test_none_values_included_as_none(self) -> None:
        """Fields with None values are returned for cleanup."""
        org = models.Organization(
            name='Org',
            slug='org',
            description=None,
        )
        fields = client._embeddable_fields(org)
        by_name = {f[0]: f[1] for f in fields}
        self.assertIn('description', by_name)
        self.assertIsNone(by_name['description'])


class AutoEmbedTests(unittest.IsolatedAsyncioTestCase):
    """Test _auto_embed with mocked embeddings module."""

    @mock.patch('imbi_common.graph.embeddings.aembed')
    @mock.patch('imbi_common.settings.Embeddings')
    async def test_disabled_skips_embedding(
        self,
        mock_settings: mock.MagicMock,
        mock_aembed: mock.MagicMock,
    ) -> None:
        mock_settings.return_value.enabled = False
        g = graph.Graph()
        org = models.Organization(name='Org', slug='org')
        await g._auto_embed(org)
        mock_aembed.assert_not_called()

    async def test_auto_embed_logs_on_failure(
        self,
    ) -> None:
        g = graph.Graph()
        g.opened = True

        mock_pool = mock.MagicMock()
        mock_pool.connection.side_effect = RuntimeError(
            'pool fail',
        )
        g.pool = mock_pool

        org = models.Organization(
            name='Org',
            slug='org',
            description='A description',
        )
        with self.assertLogs(
            'imbi_common.graph',
            level='WARNING',
        ):
            await g._auto_embed(org)


class SearchResultTests(unittest.TestCase):
    def test_search_result_creation(self) -> None:
        r = graph.SearchResult(
            node_label='Project',
            node_id='abc123',
            attribute='name',
            chunk_text='My Project',
            distance=0.15,
        )
        self.assertEqual(r.node_label, 'Project')
        self.assertEqual(r.node_id, 'abc123')
        self.assertAlmostEqual(r.distance, 0.15)

    def test_search_result_frozen(self) -> None:
        r = graph.SearchResult(
            node_label='X',
            node_id='Y',
            attribute='a',
            chunk_text='t',
            distance=0.0,
        )
        with self.assertRaises(AttributeError):
            r.distance = 1.0  # type: ignore[misc]
