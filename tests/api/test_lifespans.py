import unittest.mock

import neo4j.exceptions
from fastapi import testclient

from imbi_api import app, lifespans, neo4j_indexes


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
            str(error.exception), 'ClickHouse initialization failed'
        )

    def test_neo4j_setup_indexes_already_exist(self) -> None:
        failure = neo4j.exceptions.ConstraintError()
        with unittest.mock.patch(
            'imbi_api.lifespans.neo4j.session',
            new=unittest.mock.Mock(),
        ) as session_func:
            session_mgr = unittest.mock.AsyncMock()
            session_func.return_value = session_mgr
            session = session_mgr.__aenter__.return_value
            session.run.side_effect = failure
            with self.assertLogs(lifespans.LOGGER, level='DEBUG') as cm:
                with testclient.TestClient(app.create_app()):
                    pass  # nothing to do here

        session_func.assert_called()
        for index in neo4j_indexes.INDEXES:
            session.run.assert_any_call(index)
            self.assertIn(
                f'DEBUG:imbi_api.lifespans:Index already exists: {failure}',
                cm.output,
            )

    def test_neo4j_setup_failures(self) -> None:
        failure = RuntimeError()
        with unittest.mock.patch(
            'imbi_api.lifespans.neo4j.session',
            new=unittest.mock.Mock(),
        ) as session_func:
            session_mgr = unittest.mock.AsyncMock()
            session_func.return_value = session_mgr
            session = session_mgr.__aenter__.return_value
            session.run.side_effect = failure
            with self.assertLogs(lifespans.LOGGER, level='ERROR') as cm:
                with self.assertRaises(RuntimeError):
                    with testclient.TestClient(app.create_app()):
                        pass  # nothing to do here

        session_func.assert_called()
        session.run.assert_called()
        self.assertTrue(
            any('Failed to create index:' in msg for msg in cm.output),
        )

    def test_openapi_refresh_blueprint_failure(self) -> None:
        failure = RuntimeError()
        with unittest.mock.patch(
            'imbi_api.lifespans.openapi.refresh_blueprint_models',
            new=unittest.mock.AsyncMock(side_effect=failure),
        ) as refresh_blueprint_models:
            with self.assertLogs(lifespans.LOGGER, level='WARNING') as cm:
                with testclient.TestClient(app.create_app()):
                    pass  # nothing to do here

        refresh_blueprint_models.assert_awaited_once()
        self.assertIn(
            f'WARNING:imbi_api.lifespans:Failed to refresh blueprint'
            f' models: {failure}',
            cm.output,
        )
