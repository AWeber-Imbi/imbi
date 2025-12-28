import unittest
from unittest import mock

from imbi import entrypoint, version


class RunServerTestCase(unittest.TestCase):
    """Test cases for run_server function."""

    @mock.patch('imbi.entrypoint.uvicorn.run')
    @mock.patch('imbi.entrypoint.settings.ServerConfig')
    def test_run_server_production_mode(
        self, mock_config: mock.Mock, mock_uvicorn_run: mock.Mock
    ) -> None:
        """Test run_server in production mode."""
        # Configure mock
        mock_instance = mock.Mock()
        mock_instance.environment = 'production'
        mock_instance.host = 'localhost'
        mock_instance.port = 8000
        mock_config.return_value = mock_instance

        # Call the function
        entrypoint.run_server(dev=False)

        # Verify uvicorn.run was called
        mock_uvicorn_run.assert_called_once()
        call_args = mock_uvicorn_run.call_args

        # Check the first argument is the app factory string
        self.assertEqual(call_args[0][0], 'imbi.app:create_app')

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

    @mock.patch('imbi.entrypoint.uvicorn.run')
    @mock.patch('imbi.entrypoint.settings.ServerConfig')
    def test_run_server_development_mode(
        self, mock_config: mock.Mock, mock_uvicorn_run: mock.Mock
    ) -> None:
        """Test run_server in development mode."""
        # Configure mock
        mock_instance = mock.Mock()
        mock_instance.environment = 'development'
        mock_instance.host = 'localhost'
        mock_instance.port = 8000
        mock_config.return_value = mock_instance

        # Call the function
        entrypoint.run_server(dev=False)

        # Verify uvicorn.run was called with reload parameters
        call_args = mock_uvicorn_run.call_args
        kwargs = call_args[1]

        # Development mode should have reload
        self.assertTrue(kwargs['reload'])
        self.assertIn('reload_dirs', kwargs)
        self.assertIn('reload_excludes', kwargs)
        self.assertIn('**/*.pyc', kwargs['reload_excludes'])

    @mock.patch('imbi.entrypoint.uvicorn.run')
    @mock.patch('imbi.entrypoint.settings.ServerConfig')
    def test_run_server_with_dev_flag(
        self, mock_config: mock.Mock, mock_uvicorn_run: mock.Mock
    ) -> None:
        """Test run_server with dev=True flag."""
        # Configure mock for production environment
        mock_instance = mock.Mock()
        mock_instance.environment = 'production'
        mock_instance.host = 'localhost'
        mock_instance.port = 8000
        mock_config.return_value = mock_instance

        # Call the function with dev=True
        entrypoint.run_server(dev=True)

        # Verify uvicorn.run was called with reload even in production
        call_args = mock_uvicorn_run.call_args
        kwargs = call_args[1]

        # dev=True should enable reload regardless of environment
        self.assertTrue(kwargs['reload'])
        self.assertIn('reload_dirs', kwargs)

    @mock.patch('imbi.entrypoint.uvicorn.run')
    @mock.patch('imbi.entrypoint.settings.ServerConfig')
    def test_run_server_custom_host_port(
        self, mock_config: mock.Mock, mock_uvicorn_run: mock.Mock
    ) -> None:
        """Test run_server with custom host and port."""
        # Configure mock with custom values
        mock_instance = mock.Mock()
        mock_instance.environment = 'production'
        mock_instance.host = '0.0.0.0'
        mock_instance.port = 9000
        mock_config.return_value = mock_instance

        # Call the function
        entrypoint.run_server(dev=False)

        # Verify custom host and port are used
        call_args = mock_uvicorn_run.call_args
        kwargs = call_args[1]
        self.assertEqual(kwargs['host'], '0.0.0.0')
        self.assertEqual(kwargs['port'], 9000)
