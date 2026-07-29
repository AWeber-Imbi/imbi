import datetime
import unittest.mock

import fastapi.testclient

import imbi.scheduler.app
from apps.scheduler.tests import helpers
from imbi.common import graph
from imbi.scheduler import lifespans, store


class AppTests(helpers.TestCase):
    def test_create_app(self) -> None:
        app_instance = imbi.scheduler.app.create_app()
        self.assertIsInstance(app_instance, fastapi.FastAPI)

    def test_the_trigger_loop_is_registered(self) -> None:
        # Without the engine hook the service answers /status and fires
        # nothing. Order matters too: the engine borrows the store's pool,
        # and the graph hook has to be open before an endpoint can resolve
        # a caller's permissions.
        with unittest.mock.patch.object(
            imbi.scheduler.app.lifespan, 'Lifespan'
        ) as composed:
            imbi.scheduler.app.create_app()
        self.assertEqual(
            (
                lifespans.clickhouse_hook,
                graph.graph_lifespan,
                store.store_lifespan,
                lifespans.engine_hook,
            ),
            composed.call_args.args,
        )

    def test_every_prd_route_is_mounted(self) -> None:
        # The PRD's section 10 table, minus the /credentials rows ADR 0002
        # removed. A route silently missing its prefix is the failure this
        # catches: the Caddyfile strips /scheduler, so what a caller reaches
        # is exactly what is registered here.
        app_instance = imbi.scheduler.app.create_app()
        mounted = {
            (method, route.path)
            for route in app_instance.routes
            for method in getattr(route, 'methods', set())
        }
        for method, path in [
            ('GET', '/api/tasks'),
            ('POST', '/api/tasks'),
            ('GET', '/api/tasks/{slug}'),
            ('PATCH', '/api/tasks/{slug}'),
            ('DELETE', '/api/tasks/{slug}'),
            ('POST', '/api/tasks/{slug}/pause'),
            ('POST', '/api/tasks/{slug}/resume'),
            ('POST', '/api/tasks/{slug}/run'),
            ('POST', '/api/tasks/{slug}/dry-run'),
            ('GET', '/api/tasks/{slug}/runs'),
            ('GET', '/api/runs/{run_id}'),
            ('POST', '/api/runs/{run_id}/cancel'),
        ]:
            with self.subTest(route=f'{method} {path}'):
                self.assertIn((method, path), mounted)

    def test_no_credentials_routes_exist(self) -> None:
        # ADR 0002 removed the credential store; a route managing one would
        # be an endpoint with nothing behind it.
        app_instance = imbi.scheduler.app.create_app()
        self.assertEqual(
            [],
            [
                route.path
                for route in app_instance.routes
                if 'credential' in route.path
            ],
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
