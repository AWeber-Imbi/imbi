import datetime
from unittest import mock

import fastapi.testclient

import imbi_assistant
import imbi_assistant.app
from tests import helpers


class AppTests(helpers.TestCase):
    def test_create_app(self) -> None:
        app_instance = imbi_assistant.app.create_app()
        self.assertIsInstance(app_instance, fastapi.FastAPI)

    @mock.patch('imbi_assistant.client.aclose')
    @mock.patch('imbi_assistant.client.initialize')
    @mock.patch('imbi_common.neo4j.aclose')
    @mock.patch('imbi_common.neo4j.initialize')
    def test_status_endpoint(
        self,
        _neo4j_init: mock.AsyncMock,
        _neo4j_close: mock.AsyncMock,
        _client_init: mock.AsyncMock,
        _client_close: mock.AsyncMock,
    ) -> None:
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

    @mock.patch('imbi_assistant.client.aclose')
    @mock.patch('imbi_assistant.client.initialize')
    @mock.patch('imbi_common.neo4j.aclose')
    @mock.patch('imbi_common.neo4j.initialize')
    def test_status_endpoint_in_specific_environment(
        self,
        _neo4j_init: mock.AsyncMock,
        _neo4j_close: mock.AsyncMock,
        _client_init: mock.AsyncMock,
        _client_close: mock.AsyncMock,
    ) -> None:
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
