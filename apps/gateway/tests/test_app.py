import datetime

import fastapi.testclient

import imbi.gateway.app
from apps.gateway.tests import helpers


class AppTests(helpers.TestCase):
    def test_create_app(self) -> None:
        app_instance = imbi.gateway.app.create_app()
        self.assertIsInstance(app_instance, fastapi.FastAPI)

    def test_metrics_returns_prometheus_text(self) -> None:
        # No `with`, so the lifespan does not run: the route needs none.
        client = fastapi.testclient.TestClient(imbi.gateway.app.create_app())
        response = client.get('/metrics')
        self.assertEqual(200, response.status_code)
        self.assertTrue(
            response.headers['content-type'].startswith('text/plain')
        )
        self.assertIn('imbi_iggy_published_total', response.text)

    def test_status_endpoint(self) -> None:
        start_time = datetime.datetime.now(datetime.UTC)
        with fastapi.testclient.TestClient(
            imbi.gateway.app.create_app()
        ) as client:
            response = client.get('/status')
            self.assertEqual(200, response.status_code)

        body = response.json()
        self.assertEqual('development', body['environment'])
        self.assertEqual('imbi-gateway', body['service'])
        self.assertGreaterEqual(
            datetime.datetime.fromisoformat(body['started_at']), start_time
        )
        self.assertEqual('ok', body['status'])
        self.assertEqual(imbi.gateway.version, body['version'])

    def test_status_endpoint_in_specific_environment(self) -> None:
        with (
            self.override_environment(ENVIRONMENT='testing'),
            fastapi.testclient.TestClient(
                imbi.gateway.app.create_app()
            ) as client,
        ):
            response = client.get('/status')
            self.assertEqual(200, response.status_code)

        body = response.json()
        self.assertEqual('testing', body['environment'])
