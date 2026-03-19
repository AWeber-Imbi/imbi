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


class ConfigurationTestCase(unittest.TestCase):
    """Test cases for Configuration class."""

    def test_configuration_defaults(self) -> None:
        """Test Configuration with default values."""
        config = settings.Configuration()

        self.assertIsInstance(config.clickhouse, settings.Clickhouse)
        self.assertIsInstance(config.neo4j, settings.Neo4j)
        self.assertIsInstance(config.auth, settings.Auth)

    def test_configuration_from_dict(self) -> None:
        """Test Configuration from dictionary data."""
        data = {
            'neo4j': {'url': 'neo4j://neo4j-prod:7687'},
        }

        config = settings.Configuration.model_validate(data)

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
                config = settings.load_config()

                self.assertIsInstance(config, settings.Configuration)
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
[neo4j]
database = "test-db"

[auth]
access_token_expire_seconds = 7200
"""
                )

                os.chdir(tmpdir)
                config = settings.load_config()

                self.assertEqual(config.neo4j.database, 'test-db')
                self.assertEqual(config.auth.access_token_expire_seconds, 7200)
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
