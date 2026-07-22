import os
import typing
import unittest
import unittest.mock

import fastapi

from imbi.api import app, settings, version
from imbi.common import access_log


class CreateAppTestCase(unittest.TestCase):
    """Test cases for create_app function."""

    def test_create_app_returns_fastapi_instance(self) -> None:
        """Test that create_app returns a FastAPI instance."""
        application = app.create_app()
        self.assertIsInstance(application, fastapi.FastAPI)

    def test_create_app_has_correct_title(self) -> None:
        """Test that the app has the correct title."""
        application = app.create_app()
        self.assertEqual(application.title, 'Imbi')

    def test_create_app_has_correct_version(self) -> None:
        """Test that the app has the correct version."""
        application = app.create_app()
        self.assertEqual(application.version, version)

    def test_create_app_includes_routers(self) -> None:
        """Test that the app includes all routers."""
        application = app.create_app()
        # Check that the app has routes from our routers
        # At minimum, we should have the /status endpoint
        routes = [route.path for route in application.routes]
        self.assertIn('/status', routes)

    def test_create_app_has_lifespan(self) -> None:
        """Test that the app has a lifespan context manager configured."""
        application = app.create_app()
        self.assertIsNotNone(application.router.lifespan_context)

    def test_access_log_middleware_quiets_status_routes(self) -> None:
        """``/status`` and ``/api/status`` are silenced on success."""
        application = app.create_app()
        access_log_mw = next(
            (
                mw
                for mw in application.user_middleware
                if mw.cls is access_log.AccessLogMiddleware
            ),
            None,
        )
        self.assertIsNotNone(
            access_log_mw, 'AccessLogMiddleware was not installed'
        )
        assert access_log_mw is not None  # narrow for basedpyright
        quiet_paths = typing.cast(
            'set[str]', access_log_mw.kwargs['quiet_paths']
        )
        self.assertEqual(set(quiet_paths), {'/status', '/api/status'})


class ApiPrefixTestCase(unittest.TestCase):
    """Test cases for prefix derivation from IMBI_API_URL."""

    def test_prefix_applies_to_routes_but_not_docs(self) -> None:
        with unittest.mock.patch.dict(
            os.environ,
            {'IMBI_API_URL': 'https://imbi.example.com/api'},
        ):
            application = app.create_app()
            paths = {route.path for route in application.routes}
        self.assertIn('/api/status', paths)
        self.assertNotIn('/status', paths)
        self.assertIn('/api/uploads/', paths)
        self.assertNotIn('/uploads/', paths)
        self.assertIn('/openapi.json', paths)
        self.assertIn('/docs', paths)

    def test_no_url_serves_at_root(self) -> None:
        with unittest.mock.patch.dict(os.environ, {'IMBI_API_URL': ''}):
            application = app.create_app()
            paths = {route.path for route in application.routes}
        self.assertIn('/status', paths)
        self.assertIn('/uploads/', paths)

    def test_url_with_trailing_slash_in_path_is_normalized(self) -> None:
        with unittest.mock.patch.dict(
            os.environ,
            {'IMBI_API_URL': 'https://imbi.example.com/api/'},
        ):
            self.assertEqual(settings.ServerConfig().api_prefix, '/api')
