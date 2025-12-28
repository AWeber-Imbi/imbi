import unittest

import fastapi

from imbi import app, version


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
