"""Tests for the graph module."""

import datetime
import json
import typing
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


class CypherParamTests(unittest.TestCase):
    """Tests for Graph._cypher_param()."""

    @staticmethod
    def _render(value: object) -> str:
        return client.Graph._cypher_param(value).as_string(None)

    # -- strings --

    def test_plain_string(self) -> None:
        self.assertEqual(self._render('hello'), "'hello'")

    def test_empty_string(self) -> None:
        self.assertEqual(self._render(''), "''")

    def test_string_with_single_quote(self) -> None:
        self.assertEqual(self._render("it's"), "'it\\'s'")

    def test_string_with_backslash(self) -> None:
        self.assertEqual(self._render('a\\b'), "'a\\\\b'")

    def test_string_with_dollar_quote(self) -> None:
        self.assertEqual(self._render('a$$b'), "'a$$b'")

    def test_string_mixed_apostrophe_and_backslash(self) -> None:
        # ``O'Brien\back`` — backslash must be doubled *first*
        # then the apostrophe escaped, so the emitted literal
        # survives Cypher parsing unchanged.
        self.assertEqual(
            self._render("O'Brien\\back"),
            "'O\\'Brien\\\\back'",
        )

    def test_string_with_embedded_double_dollar(self) -> None:
        # ``$$`` is only meaningful to PostgreSQL dollar quoting;
        # Cypher escaping leaves it untouched.
        self.assertEqual(
            self._render('pre$$post'),
            "'pre$$post'",
        )

    def test_string_with_only_backslashes(self) -> None:
        self.assertEqual(
            self._render('\\\\'),
            "'\\\\\\\\'",
        )

    # -- lists --

    def test_empty_list(self) -> None:
        self.assertEqual(self._render([]), '[]')

    def test_string_list(self) -> None:
        self.assertEqual(self._render(['a', 'b']), '["a", "b"]')

    def test_nested_list_of_dicts(self) -> None:
        val = [{'k': 'v'}, {'k2': 'v2'}]
        self.assertEqual(self._render(val), json.dumps(val))

    # -- dicts --

    def test_empty_dict(self) -> None:
        self.assertEqual(self._render({}), "'{}'")

    def test_dict_with_apostrophe(self) -> None:
        result = self._render({'d': "it's"})
        self.assertIn("\\'", result)
        self.assertNotIn("''", result)

    # -- None / bool --

    def test_none(self) -> None:
        self.assertEqual(self._render(None), 'null')

    def test_true(self) -> None:
        self.assertEqual(self._render(True), 'true')

    def test_false(self) -> None:
        self.assertEqual(self._render(False), 'false')

    # -- numbers --

    def test_integer(self) -> None:
        self.assertEqual(self._render(42), '42')

    def test_float(self) -> None:
        self.assertEqual(self._render(3.14), '3.14')

    # -- passthrough --

    def test_composable_passthrough(self) -> None:
        from psycopg import sql as psql

        frag = psql.SQL('raw')
        self.assertIs(client.Graph._cypher_param(frag), frag)


class DollarQuoteTagTests(unittest.TestCase):
    """Tests for _dollar_quote_tag()."""

    def test_default_when_safe(self) -> None:
        self.assertEqual(
            client._dollar_quote_tag('MATCH (n) RETURN n'),
            '$$',
        )

    def test_avoids_dollar_dollar(self) -> None:
        tag = client._dollar_quote_tag('foo$$bar')
        self.assertEqual(tag, '$q0$')
        self.assertNotIn(tag, 'foo$$bar')

    def test_avoids_multiple_tags(self) -> None:
        body = 'foo$$bar$q0$baz'
        tag = client._dollar_quote_tag(body)
        self.assertEqual(tag, '$q1$')
        self.assertNotIn(tag, body)


class BuildCypherSqlTests(unittest.IsolatedAsyncioTestCase):
    """Regression tests for _build_cypher_sql composition.

    The previous implementation round-tripped the rendered
    Cypher through ``sql.SQL(resolved_string)``, which treated
    literal ``{`` / ``}`` in user data as format placeholders
    and raised ``IndexError`` at format time.  After switching
    to ``sql.Composed``, user data containing braces passes
    through untouched.

    """

    async def test_user_value_with_literal_braces(self) -> None:
        g = graph.Graph()
        await g.open()
        try:
            async with g.pool.connection() as conn:
                built = g._build_cypher_sql(
                    conn,
                    'MATCH (n:Organization {{name: {name}}}) RETURN n',
                    {'name': 'pre{weird}post'},
                )
                rendered = built.as_string(conn)
        finally:
            await g.close()
        # The user value survives verbatim inside the Cypher
        # body — it is NOT re-interpreted as placeholders.
        self.assertIn('pre{weird}post', rendered)
        # And the Cypher property-map braces are still present.
        self.assertIn('{name: ', rendered)

    async def test_raw_cypher_map_literal(self) -> None:
        """Raw Cypher with an un-escaped map literal.

        This is the admin Graph Query workbench path: the user types
        Cypher directly, braces and all, with ``raw=True``. The
        formatter must be skipped entirely — otherwise psycopg parses
        ``{name: "RabbitMQ"}`` as a placeholder with a format spec and
        raises ``ValueError('no format specification supported by SQL')``.
        """
        g = graph.Graph()
        await g.open()
        try:
            async with g.pool.connection() as conn:
                built = g._build_cypher_sql(
                    conn,
                    'MATCH (p:Project {name: "RabbitMQ"}) RETURN p',
                    None,
                    columns=['p'],
                    raw=True,
                )
                rendered = built.as_string(conn)
        finally:
            await g.close()
        self.assertIn('{name: "RabbitMQ"}', rendered)

    async def test_templated_query_without_params_unescapes_braces(
        self,
    ) -> None:
        """Param-less templated query still runs through ``format()``.

        Internal callers double their literal braces (``a{{.*}}``) and
        may pass an empty params dict (e.g. a ``RETURN a{{.*}}`` list
        query). The formatter must still run to unescape ``{{``/``}}``
        back to single braces; skipping it leaves doubled braces that
        AGE rejects with ``syntax error at or near "{"``.
        """
        g = graph.Graph()
        await g.open()
        try:
            async with g.pool.connection() as conn:
                built = g._build_cypher_sql(
                    conn,
                    'MATCH (a:App) RETURN a{{.*}} AS app',
                    {},
                    columns=['app'],
                )
                rendered = built.as_string(conn)
        finally:
            await g.close()
        # Doubled braces collapse to single — and no doubles remain.
        self.assertIn('a{.*} AS app', rendered)
        self.assertNotIn('{{', rendered)


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


class DeleteEmbeddingsWhereTests(
    unittest.IsolatedAsyncioTestCase,
):
    """Verify the three historical call sites compose correctly.

    ``_delete_embeddings_where`` replaces ``_delete_embeddings``,
    ``_delete_attr_embeddings``, and ``_delete_orphan_chunks``.
    Each branch below asserts the rendered SQL and parameters
    match the behaviour of the helper it collapsed.

    """

    @staticmethod
    def _captured(mock_conn: mock.AsyncMock) -> tuple[str, dict]:
        """Return the rendered SQL and params dict from the mock."""
        call = mock_conn.execute.await_args
        assert call is not None
        query_obj, params = call.args
        return query_obj.as_string(None), params

    async def test_delete_all_embeddings_for_node(self) -> None:
        mock_conn = mock.AsyncMock()
        await client.Graph._delete_embeddings_where(
            mock_conn,
            node_label='Organization',
            node_id='org-1',
        )
        sql_text, params = self._captured(mock_conn)
        self.assertIn('DELETE FROM public.embeddings', sql_text)
        self.assertIn('node_label = %(node_label)s', sql_text)
        self.assertIn('node_id = %(node_id)s', sql_text)
        self.assertNotIn('attribute', sql_text)
        self.assertNotIn('model_name', sql_text)
        self.assertNotIn('chunk_index', sql_text)
        self.assertEqual(
            params,
            {'node_label': 'Organization', 'node_id': 'org-1'},
        )

    async def test_delete_single_attribute(self) -> None:
        mock_conn = mock.AsyncMock()
        await client.Graph._delete_embeddings_where(
            mock_conn,
            node_label='Organization',
            node_id='org-1',
            attribute='description',
        )
        sql_text, params = self._captured(mock_conn)
        self.assertIn('attribute = %(attribute)s', sql_text)
        self.assertNotIn('model_name', sql_text)
        self.assertNotIn('chunk_index', sql_text)
        self.assertEqual(
            params,
            {
                'node_label': 'Organization',
                'node_id': 'org-1',
                'attribute': 'description',
            },
        )

    async def test_delete_orphan_chunks(self) -> None:
        mock_conn = mock.AsyncMock()
        await client.Graph._delete_embeddings_where(
            mock_conn,
            node_label='Organization',
            node_id='org-1',
            attribute='description',
            model_name='text',
            min_chunk_index=3,
        )
        sql_text, params = self._captured(mock_conn)
        self.assertIn('attribute = %(attribute)s', sql_text)
        self.assertIn('model_name = %(model_name)s', sql_text)
        self.assertIn(
            'chunk_index >= %(min_chunk_index)s',
            sql_text,
        )
        self.assertEqual(
            params,
            {
                'node_label': 'Organization',
                'node_id': 'org-1',
                'attribute': 'description',
                'model_name': 'text',
                'min_chunk_index': 3,
            },
        )


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


class SearchNodesDeserializationTests(
    unittest.IsolatedAsyncioTestCase,
):
    """Verify search_nodes runs field validators.

    Regression guard: earlier versions called
    ``model_construct`` directly so ISO timestamp strings
    were never coerced to ``datetime``.

    """

    async def test_search_nodes_runs_validators(self) -> None:
        g = graph.Graph()
        g.opened = True

        node_id = 'org-1'
        iso = '2026-04-22T12:34:56+00:00'
        props = {
            'id': node_id,
            'name': 'Acme',
            'slug': 'acme',
            'description': None,
            'created_at': iso,
        }
        vertex = (
            json.dumps(
                {
                    'id': 1,
                    'label': 'Organization',
                    'properties': props,
                },
            )
            + '::vertex'
        )

        async def fake_search(
            query: str,
            *,
            model_name: str = 'text',
            node_label: str | None = None,
            limit: int = 10,
            distance_threshold: float | None = None,
        ) -> list[graph.SearchResult]:
            return [
                graph.SearchResult(
                    node_label='Organization',
                    node_id=node_id,
                    attribute='name',
                    chunk_text='Acme',
                    distance=0.1,
                ),
            ]

        async def fake_execute(
            query_template: str,
            params: dict[str, object] | None = None,
            columns: list[str] | None = None,
        ) -> list[dict[str, object]]:
            return [{'n': vertex}]

        with (
            mock.patch.object(g, 'search', side_effect=fake_search),
            mock.patch.object(g, 'execute', side_effect=fake_execute),
        ):
            result = await g.search_nodes(
                models.Organization,
                'acme',
            )

        self.assertEqual(len(result), 1)
        org = result[0]
        self.assertIsInstance(org, models.Organization)
        self.assertEqual(org.id, node_id)
        # The validator coerced the ISO string to a datetime.
        self.assertIsInstance(
            org.created_at,
            datetime.datetime,
        )
        self.assertEqual(
            org.created_at,
            datetime.datetime.fromisoformat(iso),
        )


class SearchNodeIdScopingTests(unittest.IsolatedAsyncioTestCase):
    """Verify search() pushes node_id scoping into the SQL."""

    async def _capture_search(self, **kwargs: object) -> dict[str, object]:
        g = graph.Graph()
        g.opened = True
        captured: dict[str, object] = {}

        class FakeCursor:
            async def __aenter__(self) -> typing.Self:
                return self

            async def __aexit__(self, *exc: object) -> bool:
                return False

            async def execute(
                self, query: object, params: object = None
            ) -> None:
                captured['query'] = query
                captured['params'] = params

            async def fetchall(self) -> list[dict[str, object]]:
                return []

        class FakeConn:
            def cursor(self, *a: object, **k: object) -> FakeCursor:
                return FakeCursor()

            async def __aenter__(self) -> typing.Self:
                return self

            async def __aexit__(self, *exc: object) -> bool:
                return False

        class FakePool:
            def connection(self) -> FakeConn:
                return FakeConn()

        g.pool = FakePool()  # type: ignore[assignment]

        async def fake_embed(query: str, model_name: str) -> list[float]:
            return [0.1, 0.2, 0.3]

        with (
            mock.patch(
                'imbi_common.graph.embeddings.aembed_one',
                side_effect=fake_embed,
            ),
            mock.patch(
                'imbi_common.graph.embeddings.get_dimensions',
                return_value=3,
            ),
        ):
            await g.search('q', **kwargs)  # type: ignore[arg-type]
        return captured

    async def test_node_ids_adds_scope_clause(self) -> None:
        captured = await self._capture_search(node_ids=['a', 'b'])
        params = typing.cast('dict[str, object]', captured['params'])
        self.assertEqual(params['node_ids'], ['a', 'b'])
        rendered = typing.cast(
            'client.sql.Composed', captured['query']
        ).as_string(None)
        self.assertIn('node_id = ANY', rendered)

    async def test_no_node_ids_omits_scope_clause(self) -> None:
        captured = await self._capture_search()
        params = typing.cast('dict[str, object]', captured['params'])
        self.assertNotIn('node_ids', params)
        rendered = typing.cast(
            'client.sql.Composed', captured['query']
        ).as_string(None)
        self.assertNotIn('node_id = ANY', rendered)


class _NoRequiredEdgeNode(models.Node):
    """Test fixture: a Node with an Edge field that has a default,
    so validate is the right code path.
    """

    peers: typing.Annotated[
        list[models.Organization],
        models.Edge(rel_type='LINKED_TO', direction='OUTGOING'),
    ] = []  # noqa: RUF012 - Pydantic field default, not a class attribute


class RowToModelTests(unittest.TestCase):
    """``_row_to_model`` short-circuits when validate would be wasted."""

    def test_required_edge_field_skips_validate(self) -> None:
        """A ``Project`` row (which has a required ``team`` Edge field)
        deserializes via ``model_construct`` and emits no
        ValidationError DEBUG log — the previous behavior fired one on
        every load.
        """
        props: dict[str, typing.Any] = {
            'id': 'abc',
            'name': 'demo',
            'slug': 'demo',
        }
        with self.assertNoLogs('imbi_common.graph.client', level='DEBUG'):
            project = client.Graph._row_to_model(models.Project, props)
        self.assertEqual(project.id, 'abc')
        self.assertEqual(project.name, 'demo')

    def test_optional_edges_only_runs_validate(self) -> None:
        """A model whose Edge fields all have defaults still goes
        through ``model_validate`` so field validators run.
        """
        props: dict[str, typing.Any] = {
            'id': 'n1',
            'name': 'Demo',
            'slug': 'demo',
        }
        with mock.patch.object(
            _NoRequiredEdgeNode,
            'model_validate',
            wraps=_NoRequiredEdgeNode.model_validate,
        ) as spy:
            node = client.Graph._row_to_model(_NoRequiredEdgeNode, props)
        spy.assert_called_once()
        self.assertEqual(node.slug, 'demo')

    def test_has_required_edge_field_classification(self) -> None:
        """Project has a required Edge field; the test fixture does
        not.
        """
        self.assertTrue(client._has_required_edge_field(models.Project))
        self.assertFalse(client._has_required_edge_field(_NoRequiredEdgeNode))
