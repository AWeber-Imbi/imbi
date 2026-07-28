import datetime
import unittest.mock

import fastapi.testclient

import imbi.scheduler.app
from apps.scheduler.tests import helpers
from imbi.scheduler import lifespans, store


class AppTests(helpers.TestCase):
    def test_create_app(self) -> None:
        app_instance = imbi.scheduler.app.create_app()
        self.assertIsInstance(app_instance, fastapi.FastAPI)

    def test_the_trigger_loop_is_registered(self) -> None:
        # Without this hook the service answers /status and fires nothing.
        # Order matters too: the engine borrows the store's pool.
        with unittest.mock.patch.object(
            imbi.scheduler.app.lifespan, 'Lifespan'
        ) as composed:
            imbi.scheduler.app.create_app()
        self.assertEqual(
            (
                lifespans.clickhouse_hook,
                store.store_lifespan,
                lifespans.engine_hook,
            ),
            composed.call_args.args,
        )

    def test_status_endpoint(self) -> None:
        start_time = datetime.datetime.now(datetime.UTC)
        with fastapi.testclient.TestClient(
            imbi.scheduler.app.create_app()
        ) as client:
            response = client.get('/status')
            self.assertEqual(200, response.status_code)

        body = response.json()
        self.assertEqual('development', body['environment'])
        self.assertEqual('imbi-scheduler', body['service'])
        self.assertGreaterEqual(
            datetime.datetime.fromisoformat(body['started_at']), start_time
        )
        self.assertEqual('ok', body['status'])
        self.assertEqual(imbi.scheduler.version, body['version'])

    def test_status_endpoint_in_specific_environment(self) -> None:
        with (
            self.override_environment(ENVIRONMENT='testing'),
            fastapi.testclient.TestClient(
                imbi.scheduler.app.create_app()
            ) as client,
        ):
            response = client.get('/status')
            self.assertEqual(200, response.status_code)

        body = response.json()
        self.assertEqual('testing', body['environment'])
