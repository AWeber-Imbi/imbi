import datetime
import unittest
from unittest import mock

import fastapi.testclient

import imbi_assistant
import imbi_assistant.app
from imbi_assistant import external_mcp
from tests import helpers


class AppTests(helpers.TestCase):
    def test_create_app(self) -> None:
        app_instance = imbi_assistant.app.create_app()
        self.assertIsInstance(app_instance, fastapi.FastAPI)

    @mock.patch('imbi_assistant.links.initialize')
    @mock.patch('imbi_assistant.external_mcp.initialize')
    @mock.patch('imbi_assistant.app.graph.Graph')
    @mock.patch('imbi_assistant.client.aclose')
    @mock.patch('imbi_assistant.client.initialize')
    @mock.patch('imbi_common.graph.graph_lifespan')
    def test_status_endpoint(
        self,
        _graph_lifespan: mock.MagicMock,
        _client_init: mock.AsyncMock,
        _client_close: mock.AsyncMock,
        _graph_cls: mock.MagicMock,
        _ext_init: mock.AsyncMock,
        _links_init: mock.AsyncMock,
    ) -> None:
        _graph_cls.return_value = mock.AsyncMock()
        start_time = datetime.datetime.now(datetime.UTC)
        with fastapi.testclient.TestClient(
            imbi_assistant.app.create_app()
        ) as client:
            response = client.get('/status')
            self.assertEqual(200, response.status_code)

        body = response.json()
        self.assertEqual('development', body['environment'])
        self.assertEqual('imbi-assistant', body['service'])
        self.assertGreaterEqual(
            datetime.datetime.fromisoformat(body['started_at']),
            start_time,
        )
        self.assertEqual('ok', body['status'])
        self.assertEqual(imbi_assistant.version, body['version'])

    @mock.patch('imbi_assistant.links.initialize')
    @mock.patch('imbi_assistant.external_mcp.initialize')
    @mock.patch('imbi_assistant.app.graph.Graph')
    @mock.patch('imbi_assistant.client.aclose')
    @mock.patch('imbi_assistant.client.initialize')
    @mock.patch('imbi_common.graph.graph_lifespan')
    def test_status_endpoint_in_specific_environment(
        self,
        _graph_lifespan: mock.MagicMock,
        _client_init: mock.AsyncMock,
        _client_close: mock.AsyncMock,
        _graph_cls: mock.MagicMock,
        _ext_init: mock.AsyncMock,
        _links_init: mock.AsyncMock,
    ) -> None:
        _graph_cls.return_value = mock.AsyncMock()
        with (
            self.override_environment(ENVIRONMENT='testing'),
            fastapi.testclient.TestClient(
                imbi_assistant.app.create_app()
            ) as client,
        ):
            response = client.get('/status')
            self.assertEqual(200, response.status_code)

        body = response.json()
        self.assertEqual('testing', body['environment'])


class ExternalMCPLifespanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._original = external_mcp._manager
        external_mcp._manager = None

    def tearDown(self) -> None:
        external_mcp._manager = self._original

    @mock.patch('imbi_assistant.external_mcp.aclose')
    @mock.patch('imbi_assistant.external_mcp.initialize')
    @mock.patch('imbi_assistant.app.graph.Graph')
    async def test_lifespan_success(
        self,
        graph_cls: mock.MagicMock,
        ext_init: mock.AsyncMock,
        ext_close: mock.AsyncMock,
    ) -> None:
        db = mock.AsyncMock()
        graph_cls.return_value = db
        async with imbi_assistant.app._external_mcp_lifespan():
            pass
        db.open.assert_awaited_once()
        db.close.assert_awaited_once()
        ext_init.assert_awaited_once_with(db)
        ext_close.assert_awaited_once()

    @mock.patch('imbi_assistant.external_mcp.aclose')
    @mock.patch('imbi_assistant.app.graph.Graph')
    async def test_lifespan_db_failure_installs_manager(
        self,
        graph_cls: mock.MagicMock,
        ext_close: mock.AsyncMock,
    ) -> None:
        db = mock.AsyncMock()
        db.open.side_effect = RuntimeError('no db')
        graph_cls.return_value = db
        async with imbi_assistant.app._external_mcp_lifespan():
            # A manager is installed despite the DB failure.
            self.assertIsNotNone(external_mcp._manager)
        ext_close.assert_awaited_once()
