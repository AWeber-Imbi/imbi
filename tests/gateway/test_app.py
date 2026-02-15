import datetime

import fastapi.testclient
import yarl

import imbi_gateway.app
from tests import helpers


class AppTests(helpers.TestCase):
    def test_create_app(self) -> None:
        app_instance = imbi_gateway.app.create_app()
        self.assertIsInstance(app_instance, fastapi.FastAPI)

    def test_status_endpoint(self) -> None:
        start_time = datetime.datetime.now(datetime.UTC)
        with fastapi.testclient.TestClient(
            imbi_gateway.app.create_app()
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
        self.assertEqual(imbi_gateway.version, body['version'])

    def test_status_endpoint_in_specific_environment(self) -> None:
        with (
            self.override_environment(ENVIRONMENT='testing'),
            fastapi.testclient.TestClient(
                imbi_gateway.app.create_app()
            ) as client,
        ):
            response = client.get('/status')
            self.assertEqual(200, response.status_code)

        body = response.json()
        self.assertEqual('testing', body['environment'])

    def test_status_endpoint_includes_postgres_stats(self) -> None:
        """Status endpoint includes PostgreSQL pool statistics."""
        # Uses real PostgreSQL connection from compose environment.
        # POSTGRES_URL must be set in environment (e.g., from .env).
        with fastapi.testclient.TestClient(
            imbi_gateway.app.create_app()
        ) as client:
            response = client.get('/status')
            self.assertEqual(200, response.status_code)
            body = response.json()
            self.assertIn('postgres', body)

            postgres_status = body['postgres']
            self.assertIsInstance(postgres_status, dict)

            # Verify top-level keys
            self.assertIn('url', postgres_status)
            url = yarl.URL(postgres_status['url'])
            self.assertEqual('***', url.password)

            # Verify postgres stats structure
            self.assertIn('pool_stats', postgres_status)
            stats = postgres_status['pool_stats']
            expected_stat_keys = {
                'connections_num',
                'connections_ms',
                'pool_max',
                'pool_min',
                'pool_size',
                'pool_available',
                'requests_waiting',
            }
            self.assertIsInstance(stats, dict)
            for key in expected_stat_keys:
                self.assertIn(key, stats)
                self.assertIsInstance(stats[key], int)
