import typing
import unittest

import pydantic

from imbi_api import settings


class PostgresSettingsTestCase(unittest.TestCase):
    """Test cases for Postgres settings."""

    def test_default_settings(self) -> None:
        """Test Postgres settings with explicit defaults."""
        postgres = settings.Postgres(
            url=pydantic.PostgresDsn(
                'postgresql://postgres:secret@localhost:5432/imbi'
            )
        )
        self.assertEqual(
            str(postgres.url),
            'postgresql://postgres:secret@localhost:5432/imbi',
        )
        self.assertEqual(postgres.graph_name, 'imbi')
        self.assertEqual(postgres.min_pool_size, 2)
        self.assertEqual(postgres.max_pool_size, 10)

    def test_custom_url(self) -> None:
        """Test Postgres settings with a custom URL."""
        postgres = settings.Postgres(
            url=pydantic.PostgresDsn('postgresql://user:pass@dbhost:5433/mydb')
        )
        self.assertEqual(
            str(postgres.url),
            'postgresql://user:pass@dbhost:5433/mydb',
        )

    def test_custom_graph_name(self) -> None:
        """Test Postgres settings with custom graph name."""
        postgres = settings.Postgres(graph_name='custom_graph')
        self.assertEqual(postgres.graph_name, 'custom_graph')

    def test_custom_pool_sizes(self) -> None:
        """Test Postgres settings with custom pool sizes."""
        postgres = settings.Postgres(
            min_pool_size=5,
            max_pool_size=20,
        )
        self.assertEqual(postgres.min_pool_size, 5)
        self.assertEqual(postgres.max_pool_size, 20)


class EmailSettingsTestCase(unittest.TestCase):
    """Test cases for Email settings."""

    def test_mailpit_detection_in_development(self) -> None:
        """Test Mailpit port detection in development environment."""
        import os

        # Set environment variables for Mailpit detection
        os.environ['IMBI_API_ENVIRONMENT'] = 'development'
        os.environ['MAILPIT_SMTP_PORT'] = '1025'

        try:
            email = settings.Email(smtp_host='localhost', smtp_port=587)

            # Should have detected Mailpit port
            self.assertEqual(email.smtp_port, 1025)
            self.assertFalse(email.smtp_use_tls)
        finally:
            # Clean up environment variables
            os.environ.pop('IMBI_API_ENVIRONMENT', None)
            os.environ.pop('MAILPIT_SMTP_PORT', None)

    def test_mailpit_detection_with_explicit_tls(self) -> None:
        """Test that explicit TLS setting is not overridden."""
        import os

        os.environ['IMBI_API_ENVIRONMENT'] = 'development'
        os.environ['MAILPIT_SMTP_PORT'] = '1025'
        os.environ['IMBI_EMAIL_SMTP_USE_TLS'] = 'true'

        try:
            email = settings.Email(
                smtp_host='localhost', smtp_port=587, smtp_use_tls=True
            )

            # Port should be updated but TLS should remain
            self.assertEqual(email.smtp_port, 1025)
            self.assertTrue(email.smtp_use_tls)
        finally:
            os.environ.pop('IMBI_API_ENVIRONMENT', None)
            os.environ.pop('MAILPIT_SMTP_PORT', None)
            os.environ.pop('IMBI_EMAIL_SMTP_USE_TLS', None)

    def test_no_mailpit_detection_in_production(self) -> None:
        """Test that Mailpit detection is skipped in production."""
        import os

        os.environ['IMBI_API_ENVIRONMENT'] = 'production'
        os.environ['MAILPIT_SMTP_PORT'] = '1025'

        try:
            email = settings.Email(
                smtp_host='localhost', smtp_port=587, smtp_use_tls=True
            )

            # Should not have detected Mailpit in production
            self.assertEqual(email.smtp_port, 587)
            self.assertTrue(email.smtp_use_tls)
        finally:
            os.environ.pop('IMBI_API_ENVIRONMENT', None)
            os.environ.pop('MAILPIT_SMTP_PORT', None)

    def test_no_mailpit_detection_non_localhost(self) -> None:
        """Test that Mailpit detection only applies to localhost."""
        import os

        os.environ['IMBI_API_ENVIRONMENT'] = 'development'
        os.environ['MAILPIT_SMTP_PORT'] = '1025'

        try:
            email = settings.Email(
                smtp_host='smtp.example.com',
                smtp_port=587,
                smtp_use_tls=True,
            )

            # Should not detect Mailpit for non-localhost
            self.assertEqual(email.smtp_port, 587)
            self.assertTrue(email.smtp_use_tls)
        finally:
            os.environ.pop('IMBI_API_ENVIRONMENT', None)
            os.environ.pop('MAILPIT_SMTP_PORT', None)

    def test_no_mailpit_detection_different_port(self) -> None:
        """Test that Mailpit detection only applies to default port."""
        import os

        os.environ['IMBI_API_ENVIRONMENT'] = 'development'
        os.environ['MAILPIT_SMTP_PORT'] = '1025'

        try:
            email = settings.Email(smtp_host='localhost', smtp_port=2525)

            # Should not detect Mailpit for non-default port
            self.assertEqual(email.smtp_port, 2525)
        finally:
            os.environ.pop('IMBI_API_ENVIRONMENT', None)
            os.environ.pop('MAILPIT_SMTP_PORT', None)


class ServerConfigSettingsTestCase(unittest.TestCase):
    """Test cases for ServerConfig settings."""

    def test_default_settings(self) -> None:
        """Test ServerConfig settings with defaults."""
        config = settings.ServerConfig()
        self.assertEqual(config.environment, 'development')
        self.assertEqual(config.host, 'localhost')
        self.assertEqual(config.port, 8000)

    def test_custom_settings(self) -> None:
        """Test ServerConfig with custom values."""
        config = settings.ServerConfig(
            environment='production', host='0.0.0.0', port=9000
        )
        self.assertEqual(config.environment, 'production')
        self.assertEqual(config.host, '0.0.0.0')
        self.assertEqual(config.port, 9000)


class ConfigurationTestCase(unittest.TestCase):
    """Test cases for Configuration class."""

    def test_configuration_defaults(self) -> None:
        """Test Configuration with default values."""
        config = settings.APIConfiguration()

        self.assertIsInstance(config.clickhouse, settings.Clickhouse)
        self.assertIsInstance(config.postgres, settings.Postgres)
        self.assertIsInstance(config.server, settings.ServerConfig)
        self.assertIsInstance(config.auth, settings.Auth)
        self.assertIsInstance(config.email, settings.Email)

    def test_configuration_from_dict(self) -> None:
        """Test Configuration from dictionary data."""
        data = {
            'server': {
                'environment': 'production',
                'host': '0.0.0.0',
            },
            'postgres': {
                'url': 'postgresql://user:pass@pg-prod:5432/imbi',
            },
        }

        config = settings.Configuration.model_validate(data)

        self.assertEqual(config.server.environment, 'production')
        self.assertEqual(config.server.host, '0.0.0.0')
        self.assertIn(
            'pg-prod',
            str(config.postgres.url),
        )

    def test_load_config_no_file(self) -> None:
        """Test load_config when no config file exists."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                # Should work fine with defaults
                config = settings.load_config()

                self.assertIsInstance(config, settings.Configuration)
                self.assertEqual(config.server.environment, 'development')
            finally:
                os.chdir(original_cwd)

    def test_load_config_with_toml(self) -> None:
        """Test load_config from TOML file."""
        import os
        import pathlib
        import tempfile

        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = pathlib.Path(tmpdir) / 'config.toml'
                config_path.write_text(
                    """
[server]
environment = "testing"
host = "127.0.0.1"
port = 9000

[postgres]
graph_name = "test-graph"

[auth]
access_token_expire_seconds = 7200
"""
                )

                # Save current directory and change to temp directory
                os.chdir(tmpdir)
                config = settings.load_config()

                self.assertEqual(config.server.environment, 'testing')
                self.assertEqual(config.server.host, '127.0.0.1')
                self.assertEqual(config.server.port, 9000)
                self.assertEqual(config.postgres.graph_name, 'test-graph')
                self.assertEqual(config.auth.access_token_expire_seconds, 7200)
        finally:
            os.chdir(original_cwd)

    def test_configuration_toml_values_used(self) -> None:
        """Test that config.toml values are loaded correctly.

        Note: Environment variables DO override TOML values in
        pydantic-settings, but only if they're set BEFORE the
        BaseSettings class is instantiated. When we pass TOML data
        as constructor kwargs (as done in the model_validator),
        those kwargs take precedence per pydantic-settings design.

        For production use, set environment variables before starting
        the app and they will properly override config.toml values.
        """
        import os
        import pathlib
        import tempfile

        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = pathlib.Path(tmpdir) / 'config.toml'
                config_path.write_text(
                    """
[server]
environment = "testing"
port = 9000
host = "127.0.0.1"
"""
                )

                os.chdir(tmpdir)
                config = settings.load_config()

                # TOML values should be loaded
                self.assertEqual(config.server.environment, 'testing')
                self.assertEqual(config.server.port, 9000)
                self.assertEqual(config.server.host, '127.0.0.1')
        finally:
            os.chdir(original_cwd)


class BaseSettingsConfigTestCase(unittest.TestCase):
    """Test cases for base_settings_config helper function."""

    def test_base_settings_config_defaults(self) -> None:
        """Test base_settings_config returns correct defaults."""
        config = typing.cast(
            dict[str, typing.Any],
            settings.base_settings_config(),
        )

        self.assertEqual(config['case_sensitive'], False)
        self.assertEqual(config['env_file'], '.env')
        self.assertEqual(config['env_file_encoding'], 'utf-8')
        self.assertEqual(config['extra'], 'ignore')

    def test_base_settings_config_with_prefix(self) -> None:
        """Test base_settings_config with additional kwargs."""
        config = typing.cast(
            dict[str, typing.Any],
            settings.base_settings_config(env_prefix='TEST_'),
        )

        self.assertEqual(config['case_sensitive'], False)
        self.assertEqual(config['env_file'], '.env')
        self.assertEqual(config['env_file_encoding'], 'utf-8')
        self.assertEqual(config['extra'], 'ignore')
        self.assertEqual(config['env_prefix'], 'TEST_')
