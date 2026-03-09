import datetime

import fastapi.testclient

import imbi_assistant
import imbi_assistant.app
from tests import helpers


class AppTests(helpers.TestCase):
    def test_create_app(self) -> None:
        app_instance = imbi_assistant.app.create_app()
        self.assertIsInstance(app_instance, fastapi.FastAPI)

    def test_status_endpoint(self) -> None:
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

    def test_status_endpoint_in_specific_environment(self) -> None:
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
