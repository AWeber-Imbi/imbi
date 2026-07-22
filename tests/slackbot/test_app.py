import datetime
from unittest import mock

import fastapi
import fastapi.testclient

import imbi.slackbot
import imbi.slackbot.app
from tests.slackbot import helpers


class AppTests(helpers.TestCase):
    def test_create_app(self) -> None:
        app_instance = imbi.slackbot.app.create_app()
        self.assertIsInstance(app_instance, fastapi.FastAPI)

    @mock.patch('imbi.slackbot.links.initialize')
    @mock.patch('imbi.slackbot.slack_handler.aclose')
    @mock.patch('imbi.slackbot.slack_handler.initialize')
    @mock.patch('imbi.slackbot.mcp.aclose')
    @mock.patch('imbi.slackbot.mcp.initialize')
    @mock.patch('imbi.slackbot.client.aclose')
    @mock.patch('imbi.slackbot.client.initialize')
    @mock.patch('imbi.common.graph.graph_lifespan')
    def test_status_endpoint(
        self,
        _graph_lifespan: mock.MagicMock,
        _client_init: mock.AsyncMock,
        _client_close: mock.AsyncMock,
        _mcp_init: mock.AsyncMock,
        _mcp_close: mock.AsyncMock,
        _slack_init: mock.AsyncMock,
        _slack_close: mock.AsyncMock,
        _links_init: mock.AsyncMock,
    ) -> None:
        start_time = datetime.datetime.now(datetime.UTC)
        with fastapi.testclient.TestClient(
            imbi.slackbot.app.create_app()
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
        self.assertEqual(imbi.slackbot.version, body['version'])
