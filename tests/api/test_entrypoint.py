import unittest
from unittest import mock

from imbi_api import entrypoint, version


class ServeTestCase(unittest.TestCase):
    """Test cases for serve function."""

    @mock.patch('imbi_api.entrypoint.uvicorn.run')
    @mock.patch('imbi_api.entrypoint.settings.ServerConfig')
    def test_serve_production_mode(
        self, mock_config: mock.Mock, mock_uvicorn_run: mock.Mock
    ) -> None:
        """Test serve in production mode."""
        # Configure mock
        mock_instance = mock.Mock()
        mock_instance.environment = 'production'
        mock_instance.host = 'localhost'
        mock_instance.port = 8000
        mock_config.return_value = mock_instance

        # Call the function
        entrypoint.serve(dev=False)

        # Verify uvicorn.run was called
        mock_uvicorn_run.assert_called_once()
        call_args = mock_uvicorn_run.call_args

        # Check the first argument is the app factory string
        self.assertEqual(call_args[0][0], 'imbi_api.app:create_app')

        # Check keyword arguments
        kwargs = call_args[1]
        self.assertTrue(kwargs['factory'])
        self.assertEqual(kwargs['host'], 'localhost')
        self.assertEqual(kwargs['port'], 8000)
        self.assertIn('log_config', kwargs)
        self.assertTrue(kwargs['proxy_headers'])
        self.assertIn(('Server', f'imbi/{version}'), kwargs['headers'])
        self.assertTrue(kwargs['date_header'])
        self.assertFalse(kwargs['server_header'])
        self.assertEqual(kwargs['ws'], 'none')

        # Production mode should not have reload
        self.assertNotIn('reload', kwargs)

    @mock.patch('imbi_api.entrypoint.uvicorn.run')
    @mock.patch('imbi_api.entrypoint.settings.ServerConfig')
    def test_serve_development_mode(
        self, mock_config: mock.Mock, mock_uvicorn_run: mock.Mock
    ) -> None:
        """Test serve in development mode."""
        # Configure mock
        mock_instance = mock.Mock()
        mock_instance.environment = 'development'
        mock_instance.host = 'localhost'
        mock_instance.port = 8000
        mock_config.return_value = mock_instance

        # Call the function
        entrypoint.serve(dev=False)

        # Verify uvicorn.run was called with reload parameters
        call_args = mock_uvicorn_run.call_args
        kwargs = call_args[1]

        # Development mode should have reload
        self.assertTrue(kwargs['reload'])
        self.assertIn('reload_dirs', kwargs)
        self.assertIn('reload_excludes', kwargs)
        self.assertIn('**/*.pyc', kwargs['reload_excludes'])

    @mock.patch('imbi_api.entrypoint.uvicorn.run')
    @mock.patch('imbi_api.entrypoint.settings.ServerConfig')
    def test_serve_with_dev_flag(
        self, mock_config: mock.Mock, mock_uvicorn_run: mock.Mock
    ) -> None:
        """Test serve with dev=True flag."""
        # Configure mock for production environment
        mock_instance = mock.Mock()
        mock_instance.environment = 'production'
        mock_instance.host = 'localhost'
        mock_instance.port = 8000
        mock_config.return_value = mock_instance

        # Call the function with dev=True
        entrypoint.serve(dev=True)

        # Verify uvicorn.run was called with reload even in production
        call_args = mock_uvicorn_run.call_args
        kwargs = call_args[1]

        # dev=True should enable reload regardless of environment
        self.assertTrue(kwargs['reload'])
        self.assertIn('reload_dirs', kwargs)

    @mock.patch('imbi_api.entrypoint.uvicorn.run')
    @mock.patch('imbi_api.entrypoint.settings.ServerConfig')
    def test_serve_custom_host_port(
        self, mock_config: mock.Mock, mock_uvicorn_run: mock.Mock
    ) -> None:
        """Test serve with custom host and port."""
        # Configure mock with custom values
        mock_instance = mock.Mock()
        mock_instance.environment = 'production'
        mock_instance.host = '0.0.0.0'
        mock_instance.port = 9000
        mock_config.return_value = mock_instance

        # Call the function
        entrypoint.serve(dev=False)

        # Verify custom host and port are used
        call_args = mock_uvicorn_run.call_args
        kwargs = call_args[1]
        self.assertEqual(kwargs['host'], '0.0.0.0')
        self.assertEqual(kwargs['port'], 9000)
