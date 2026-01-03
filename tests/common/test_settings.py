"""Unit tests for settings module."""

import os
import pathlib
import tempfile
import unittest

import pydantic

from imbi_common import settings


class Neo4jSettingsTestCase(unittest.TestCase):
    """Test cases for Neo4j settings."""

    def test_default_settings(self) -> None:
        """Test Neo4j settings with explicit defaults."""
        # Provide explicit URL to avoid environment interference
        neo4j = settings.Neo4j(url=pydantic.AnyUrl('neo4j://localhost:7687'))
        self.assertEqual(str(neo4j.url), 'neo4j://localhost:7687')
        self.assertIsNone(neo4j.user)
        self.assertIsNone(neo4j.password)
        self.assertEqual(neo4j.database, 'neo4j')
        self.assertTrue(neo4j.keep_alive)
        self.assertEqual(neo4j.liveness_check_timeout, 60)
        self.assertEqual(neo4j.max_connection_lifetime, 300)

    def test_url_with_username_and_password(self) -> None:
        """Test extracting username and password from URL."""
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('neo4j://testuser:testpass@localhost:7687')
        )

        # Credentials should be extracted
        self.assertEqual(neo4j.user, 'testuser')
        self.assertEqual(neo4j.password, 'testpass')

        # URL should be cleaned (no credentials)
        self.assertEqual(str(neo4j.url), 'neo4j://localhost:7687')
        self.assertIsNone(neo4j.url.username)
        self.assertIsNone(neo4j.url.password)

    def test_url_with_only_username(self) -> None:
        """Test extracting only username from URL."""
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('neo4j://testuser@localhost:7687')
        )

        # Username should be extracted
        self.assertEqual(neo4j.user, 'testuser')
        self.assertIsNone(neo4j.password)

        # URL should be cleaned
        self.assertEqual(str(neo4j.url), 'neo4j://localhost:7687')

    def test_url_with_credentials_and_path(self) -> None:
        """Test URL with credentials and path component."""
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('neo4j://user:pass@localhost:7687/database')
        )

        # Credentials should be extracted
        self.assertEqual(neo4j.user, 'user')
        self.assertEqual(neo4j.password, 'pass')

        # URL should preserve path but remove credentials
        self.assertEqual(str(neo4j.url), 'neo4j://localhost:7687/database')

    def test_explicit_user_password_not_overridden(self) -> None:
        """Test that explicit user/password are not overridden by URL."""
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('neo4j://urluser:urlpass@localhost:7687'),
            user='explicituser',
            password='explicitpass',
        )

        # Explicit credentials should take precedence
        self.assertEqual(neo4j.user, 'explicituser')
        self.assertEqual(neo4j.password, 'explicitpass')

        # URL should still be cleaned
        self.assertEqual(str(neo4j.url), 'neo4j://localhost:7687')

    def test_url_without_credentials(self) -> None:
        """Test URL without embedded credentials."""
        neo4j = settings.Neo4j(url=pydantic.AnyUrl('neo4j://remotehost:7687'))

        # No credentials should be set
        self.assertIsNone(neo4j.user)
        self.assertIsNone(neo4j.password)

        # URL should remain unchanged
        self.assertEqual(str(neo4j.url), 'neo4j://remotehost:7687')

    def test_url_with_different_port(self) -> None:
        """Test URL with non-default port."""
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('neo4j://user:pass@example.com:9999')
        )

        # Credentials should be extracted
        self.assertEqual(neo4j.user, 'user')
        self.assertEqual(neo4j.password, 'pass')

        # URL should preserve custom port
        self.assertEqual(str(neo4j.url), 'neo4j://example.com:9999')

    def test_url_with_special_characters_in_password(self) -> None:
        """Test URL with special characters in password."""
        # URL-encoded password with special chars
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('neo4j://user:p%40ss%23word@localhost:7687')
        )

        # Password should be decoded
        self.assertEqual(neo4j.user, 'user')
        self.assertEqual(neo4j.password, 'p@ss#word')

        # URL should be cleaned
        self.assertEqual(str(neo4j.url), 'neo4j://localhost:7687')

    def test_bolt_scheme(self) -> None:
        """Test with bolt:// scheme."""
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('bolt://user:pass@localhost:7687')
        )

        # Credentials should be extracted
        self.assertEqual(neo4j.user, 'user')
        self.assertEqual(neo4j.password, 'pass')

        # URL should preserve bolt scheme
        self.assertEqual(str(neo4j.url), 'bolt://localhost:7687')

    def test_url_with_credentials_no_port(self) -> None:
        """Test URL with credentials but no explicit port."""
        neo4j = settings.Neo4j(
            url=pydantic.AnyUrl('neo4j://user:pass@localhost')
        )

        # Credentials should be extracted
        self.assertEqual(neo4j.user, 'user')
        self.assertEqual(neo4j.password, 'pass')

        # URL should be cleaned (may or may not include implicit port)
        self.assertIn(
            str(neo4j.url),
            (
                'neo4j://localhost',
                'neo4j://localhost:7687',
                'neo4j://localhost/',
            ),
        )


class ClickhouseSettingsTestCase(unittest.TestCase):
    """Test ClickHouse settings configuration."""

    def test_default_url(self) -> None:
        """Test default ClickHouse URL."""
        # Clear environment to ensure clean state
        original_url = os.environ.pop('CLICKHOUSE_URL', None)
        try:
            config = settings.Clickhouse(_env_file=None)
            # HttpUrl may add trailing slash
            self.assertIn(
                str(config.url),
                ('http://localhost:8123', 'http://localhost:8123/'),
            )
        finally:
            if original_url:
                os.environ['CLICKHOUSE_URL'] = original_url


class EmailSettingsTestCase(unittest.TestCase):
    """Test cases for Email settings."""

    def test_mailpit_detection_in_development(self) -> None:
        """Test Mailpit port detection in development environment."""
        # Set environment variables for Mailpit detection
        os.environ['IMBI_ENVIRONMENT'] = 'development'
        os.environ['MAILPIT_SMTP_PORT'] = '1025'

        try:
            email = settings.Email(smtp_host='localhost', smtp_port=587)

            # Should have detected Mailpit port
            self.assertEqual(email.smtp_port, 1025)
            self.assertFalse(email.smtp_use_tls)
        finally:
            # Clean up environment variables
            os.environ.pop('IMBI_ENVIRONMENT', None)
            os.environ.pop('MAILPIT_SMTP_PORT', None)

    def test_mailpit_detection_with_explicit_tls(self) -> None:
        """Test that explicit TLS setting is not overridden."""
        os.environ['IMBI_ENVIRONMENT'] = 'development'
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
            os.environ.pop('IMBI_ENVIRONMENT', None)
            os.environ.pop('MAILPIT_SMTP_PORT', None)
            os.environ.pop('IMBI_EMAIL_SMTP_USE_TLS', None)

    def test_no_mailpit_detection_in_production(self) -> None:
        """Test that Mailpit detection is skipped in production."""
        os.environ['IMBI_ENVIRONMENT'] = 'production'
        os.environ['MAILPIT_SMTP_PORT'] = '1025'

        try:
            email = settings.Email(
                smtp_host='localhost', smtp_port=587, smtp_use_tls=True
            )

            # Should not have detected Mailpit in production
            self.assertEqual(email.smtp_port, 587)
            self.assertTrue(email.smtp_use_tls)
        finally:
            os.environ.pop('IMBI_ENVIRONMENT', None)
            os.environ.pop('MAILPIT_SMTP_PORT', None)

    def test_no_mailpit_detection_non_localhost(self) -> None:
        """Test that Mailpit detection only applies to localhost."""
        os.environ['IMBI_ENVIRONMENT'] = 'development'
        os.environ['MAILPIT_SMTP_PORT'] = '1025'

        try:
            email = settings.Email(
                smtp_host='smtp.example.com', smtp_port=587, smtp_use_tls=True
            )

            # Should not detect Mailpit for non-localhost
            self.assertEqual(email.smtp_port, 587)
            self.assertTrue(email.smtp_use_tls)
        finally:
            os.environ.pop('IMBI_ENVIRONMENT', None)
            os.environ.pop('MAILPIT_SMTP_PORT', None)

    def test_no_mailpit_detection_different_port(self) -> None:
        """Test that Mailpit detection only applies to default port 587."""
        os.environ['IMBI_ENVIRONMENT'] = 'development'
        os.environ['MAILPIT_SMTP_PORT'] = '1025'

        try:
            email = settings.Email(smtp_host='localhost', smtp_port=2525)

            # Should not detect Mailpit for non-default port
            self.assertEqual(email.smtp_port, 2525)
        finally:
            os.environ.pop('IMBI_ENVIRONMENT', None)
            os.environ.pop('MAILPIT_SMTP_PORT', None)


class AuthSettingsTestCase(unittest.TestCase):
    """Test authentication settings configuration."""

    def test_default_jwt_algorithm(self) -> None:
        """Test default JWT algorithm."""
        config = settings.Auth()
        self.assertEqual(config.jwt_algorithm, 'HS256')

    def test_default_access_token_expire(self) -> None:
        """Test default access token expiration."""
        config = settings.Auth()
        self.assertEqual(config.access_token_expire_seconds, 3600)

    def test_default_refresh_token_expire(self) -> None:
        """Test default refresh token expiration."""
        config = settings.Auth()
        self.assertEqual(config.refresh_token_expire_seconds, 2592000)

    def test_default_password_min_length(self) -> None:
        """Test default minimum password length."""
        config = settings.Auth()
        self.assertEqual(config.password_min_length, 12)

    def test_default_password_requirements(self) -> None:
        """Test default password requirements."""
        config = settings.Auth()
        self.assertTrue(config.password_require_uppercase)
        self.assertTrue(config.password_require_lowercase)
        self.assertTrue(config.password_require_digit)
        self.assertTrue(config.password_require_special)

    def test_auto_generated_jwt_secret(self) -> None:
        """Test JWT secret is auto-generated if not provided."""
        config = settings.Auth()
        self.assertIsNotNone(config.jwt_secret)
        self.assertGreater(len(config.jwt_secret), 0)

    def test_auto_generated_encryption_key(self) -> None:
        """Test encryption key is auto-generated if not provided."""
        config = settings.Auth()
        self.assertIsNotNone(config.encryption_key)
        self.assertGreater(len(config.encryption_key), 0)


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
        config = settings.Configuration()

        self.assertIsInstance(config.clickhouse, settings.Clickhouse)
        self.assertIsInstance(config.neo4j, settings.Neo4j)
        self.assertIsInstance(config.server, settings.ServerConfig)
        self.assertIsInstance(config.auth, settings.Auth)
        self.assertIsInstance(config.email, settings.Email)

    def test_configuration_from_dict(self) -> None:
        """Test Configuration from dictionary data."""
        data = {
            'server': {'environment': 'production', 'host': '0.0.0.0'},
            'neo4j': {'url': 'neo4j://neo4j-prod:7687'},
        }

        config = settings.Configuration.model_validate(data)

        self.assertEqual(config.server.environment, 'production')
        self.assertEqual(config.server.host, '0.0.0.0')
        # URL may or may not have trailing slash depending on pydantic version
        self.assertIn(
            str(config.neo4j.url),
            ('neo4j://neo4j-prod:7687', 'neo4j://neo4j-prod:7687/'),
        )

    def test_load_config_no_file(self) -> None:
        """Test load_config when no config file exists."""
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

[neo4j]
database = "test-db"

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
                self.assertEqual(config.neo4j.database, 'test-db')
                self.assertEqual(config.auth.access_token_expire_seconds, 7200)
        finally:
            os.chdir(original_cwd)

    def test_configuration_toml_values_used(self) -> None:
        """Test that config.toml values are loaded correctly.

        Note: Environment variables DO override TOML values in
        pydantic-settings, but only if they're set BEFORE the BaseSettings
        class is instantiated. When we pass TOML data as constructor kwargs
        (as done in the model_validator), those kwargs take precedence per
        pydantic-settings design.

        For production use, set environment variables before starting the app
        and they will properly override config.toml values.
        """
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
        config = settings.base_settings_config()

        self.assertEqual(config['case_sensitive'], False)
        self.assertEqual(config['env_file'], '.env')
        self.assertEqual(config['env_file_encoding'], 'utf-8')
        self.assertEqual(config['extra'], 'ignore')

    def test_base_settings_config_with_prefix(self) -> None:
        """Test base_settings_config with additional kwargs."""
        config = settings.base_settings_config(env_prefix='TEST_')

        self.assertEqual(config['case_sensitive'], False)
        self.assertEqual(config['env_file'], '.env')
        self.assertEqual(config['env_file_encoding'], 'utf-8')
        self.assertEqual(config['extra'], 'ignore')
        self.assertEqual(config['env_prefix'], 'TEST_')


if __name__ == '__main__':
    unittest.main()
