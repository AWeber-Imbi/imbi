import unittest.mock

from fastapi import testclient

from imbi_api import app, lifespans


class ApplicationLifespanTestCase(unittest.TestCase):
    """Test cases for the application lifespan."""

    def test_successful_lifespan_startup(self) -> None:
        """Test initializing lifespan by fetching status."""
        with testclient.TestClient(app.create_app()) as client:
            response = client.get('/status')
            self.assertEqual(response.status_code, 200)

    def test_clickhouse_initialization_failure(self) -> None:
        """Test initializing lifespan by fetching status."""
        with unittest.mock.patch(
            'imbi_api.lifespans.clickhouse.initialize',
            new=unittest.mock.AsyncMock(),
        ) as initialize:
            initialize.return_value = False
            with self.assertRaises(RuntimeError) as error:
                with testclient.TestClient(app.create_app()):
                    pass  # nothing to do here
        initialize.assert_called_once()
        self.assertEqual(
            str(error.exception),
            'ClickHouse initialization failed',
        )

    def test_openapi_refresh_blueprint_failure(self) -> None:
        failure = RuntimeError()
        with (
            unittest.mock.patch(
                'imbi_api.lifespans.openapi.refresh_blueprint_models',
                new=unittest.mock.AsyncMock(
                    side_effect=failure,
                ),
            ) as refresh_blueprint_models,
            self.assertLogs(
                lifespans.LOGGER,
                level='WARNING',
            ) as cm,
        ):
            with testclient.TestClient(app.create_app()):
                pass

        refresh_blueprint_models.assert_awaited_once()
        self.assertIn(
            f'WARNING:imbi_api.lifespans:'
            f'Failed to refresh blueprint'
            f' models: {failure}',
            cm.output,
        )
