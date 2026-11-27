import datetime
from unittest import mock

import fastapi.testclient

import imbi.assistant
import imbi.assistant.app
from apps.assistant.tests import helpers
from imbi.assistant import app_status
from imbi.common import lifespan


class AppTests(helpers.TestCase):
    def test_create_app(self) -> None:
        app_instance = imbi.assistant.app.create_app()
        self.assertIsInstance(app_instance, fastapi.FastAPI)

    @mock.patch('imbi.assistant.links.initialize')
    @mock.patch('imbi.assistant.client.aclose')
    @mock.patch('imbi.assistant.client.initialize')
    @mock.patch('imbi.common.graph.graph_lifespan')
    def test_status_endpoint(
        self,
        _graph_lifespan: mock.MagicMock,
        _client_init: mock.AsyncMock,
        _client_close: mock.AsyncMock,
        _links_init: mock.AsyncMock,
    ) -> None:
        start_time = datetime.datetime.now(datetime.UTC)
        with fastapi.testclient.TestClient(
            imbi.assistant.app.create_app()
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
        self.assertEqual(imbi.assistant.version, body['version'])

    @mock.patch('imbi.assistant.links.initialize')
    @mock.patch('imbi.assistant.client.aclose')
    @mock.patch('imbi.assistant.client.initialize')
    @mock.patch('imbi.common.graph.graph_lifespan')
    def test_status_endpoint_in_specific_environment(
        self,
        _graph_lifespan: mock.MagicMock,
        _client_init: mock.AsyncMock,
        _client_close: mock.AsyncMock,
        _links_init: mock.AsyncMock,
    ) -> None:
        with (
            self.override_environment(ENVIRONMENT='testing'),
            fastapi.testclient.TestClient(
                imbi.assistant.app.create_app()
            ) as client,
        ):
            response = client.get('/status')
            self.assertEqual(200, response.status_code)

        body = response.json()
        self.assertEqual('testing', body['environment'])

    def test_status_fails_when_lifespan_failed(self) -> None:
        failed = lifespan.Lifespan()
        failed.failed = True
        request = mock.Mock()
        request.state.lifespan_data = failed
        request.app.extra = {'started_at': datetime.datetime.now(datetime.UTC)}
        request.app.version = '1.0.0'
        response = fastapi.Response()
        result = app_status.status_endpoint(request=request, response=response)
        self.assertEqual(503, response.status_code)
        self.assertEqual('failing', result.status)
