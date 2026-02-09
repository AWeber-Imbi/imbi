import datetime

import fastapi.testclient

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

            # Verify postgres stats structure
            postgres_stats = body['postgres']
            self.assertIsInstance(postgres_stats, dict)

            # Verify expected keys are present
            self.assertIn('pool_size', postgres_stats)
            self.assertIn('pool_available', postgres_stats)
            self.assertIn('requests_waiting', postgres_stats)

            # Verify values are integers
            self.assertIsInstance(postgres_stats['pool_size'], int)
            self.assertIsInstance(postgres_stats['pool_available'], int)
            self.assertIsInstance(postgres_stats['requests_waiting'], int)
