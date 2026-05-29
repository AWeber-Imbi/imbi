import datetime
from unittest import mock

import fastapi
import fastapi.testclient

import imbi_slackbot
import imbi_slackbot.app
from tests import helpers


class AppTests(helpers.TestCase):
    def test_create_app(self) -> None:
        app_instance = imbi_slackbot.app.create_app()
        self.assertIsInstance(app_instance, fastapi.FastAPI)

    @mock.patch('imbi_slackbot.slack_handler.aclose')
    @mock.patch('imbi_slackbot.slack_handler.initialize')
    @mock.patch('imbi_slackbot.mcp.aclose')
    @mock.patch('imbi_slackbot.mcp.initialize')
    @mock.patch('imbi_slackbot.client.aclose')
    @mock.patch('imbi_slackbot.client.initialize')
    @mock.patch('imbi_common.graph.graph_lifespan')
    def test_status_endpoint(
        self,
        _graph_lifespan: mock.MagicMock,
        _client_init: mock.AsyncMock,
        _client_close: mock.AsyncMock,
        _mcp_init: mock.AsyncMock,
        _mcp_close: mock.AsyncMock,
        _slack_init: mock.AsyncMock,
        _slack_close: mock.AsyncMock,
    ) -> None:
        start_time = datetime.datetime.now(datetime.UTC)
        with fastapi.testclient.TestClient(
            imbi_slackbot.app.create_app()
        ) as client:
            response = client.get('/status')
            self.assertEqual(200, response.status_code)

        body = response.json()
        self.assertEqual('development', body['environment'])
        self.assertEqual('imbi-slackbot', body['service'])
        self.assertGreaterEqual(
            datetime.datetime.fromisoformat(body['started_at']),
            start_time,
        )
        self.assertEqual('ok', body['status'])
        self.assertEqual(imbi_slackbot.version, body['version'])
