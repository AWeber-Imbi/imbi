import datetime
import unittest
import unittest.mock
from unittest import mock

import fastapi
import fastapi.testclient

import imbi.gateway.app
from apps.gateway.tests import helpers
from imbi.common import lifespan, sentry
from imbi.gateway import app_status


class AppTests(helpers.TestCase):
    def test_create_app(self) -> None:
        app_instance = imbi.gateway.app.create_app()
        self.assertIsInstance(app_instance, fastapi.FastAPI)

    def test_sentry_is_initialised_first(self) -> None:
        with unittest.mock.patch.object(
            imbi.gateway.app.lifespan, 'Lifespan'
        ) as composed:
            imbi.gateway.app.create_app()
        self.assertIs(sentry.sentry_lifespan, composed.call_args.args[0])

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


class StatusLifespanFailedTests(unittest.TestCase):
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
