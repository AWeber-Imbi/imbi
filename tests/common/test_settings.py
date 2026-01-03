"""Unit tests for settings module."""

import os
import pathlib
import tempfile
import unittest

from imbi_common import settings


class TestNeo4jSettings(unittest.TestCase):
    """Test Neo4j settings configuration."""

    def test_default_url(self):
        """Test default Neo4j URL."""
        config = settings.Neo4j()
        self.assertEqual(str(config.url), 'neo4j://localhost:7687')

    def test_default_database(self):
        """Test default database name."""
        config = settings.Neo4j()
        self.assertEqual(config.database, 'neo4j')

    def test_default_keep_alive(self):
        """Test default keep_alive setting."""
        config = settings.Neo4j()
        self.assertTrue(config.keep_alive)

    def test_credential_extraction_from_url(self):
        """Test extracting credentials from URL."""
        config = settings.Neo4j(
            url='neo4j://testuser:testpass@testhost:7687'
        )
        self.assertEqual(config.user, 'testuser')
        self.assertEqual(config.password, 'testpass')

    def test_url_encoded_credentials(self):
        """Test URL-encoded credentials are decoded."""
        config = settings.Neo4j(
            url='neo4j://user%40example:p%40ssw0rd@host:7687'
        )
        self.assertEqual(config.user, 'user@example')
        self.assertEqual(config.password, 'p@ssw0rd')


class TestClickHouseSettings(unittest.TestCase):
    """Test ClickHouse settings configuration."""

    def test_default_url(self):
        """Test default ClickHouse URL."""
        config = settings.Clickhouse()
        self.assertEqual(str(config.url), 'http://localhost:8123')


class TestAuthSettings(unittest.TestCase):
    """Test authentication settings configuration."""

    def test_default_jwt_algorithm(self):
        """Test default JWT algorithm."""
        config = settings.Auth()
        self.assertEqual(config.jwt_algorithm, 'HS256')

    def test_default_access_token_expire(self):
        """Test default access token expiration."""
        config = settings.Auth()
        self.assertEqual(config.access_token_expire_seconds, 3600)

    def test_default_refresh_token_expire(self):
        """Test default refresh token expiration."""
        config = settings.Auth()
        self.assertEqual(config.refresh_token_expire_seconds, 2592000)

    def test_default_password_min_length(self):
        """Test default minimum password length."""
        config = settings.Auth()
        self.assertEqual(config.password_min_length, 12)

    def test_default_password_requirements(self):
        """Test default password requirements."""
        config = settings.Auth()
        self.assertTrue(config.password_require_uppercase)
        self.assertTrue(config.password_require_lowercase)
        self.assertTrue(config.password_require_digit)
        self.assertTrue(config.password_require_special)

    def test_auto_generated_jwt_secret(self):
        """Test JWT secret is auto-generated if not provided."""
        config = settings.Auth()
        self.assertIsNotNone(config.jwt_secret)
        self.assertGreater(len(config.jwt_secret), 0)

    def test_auto_generated_encryption_key(self):
        """Test encryption key is auto-generated if not provided."""
        config = settings.Auth()
        self.assertIsNotNone(config.encryption_key)
        self.assertGreater(len(config.encryption_key), 0)


class TestServerConfig(unittest.TestCase):
    """Test server configuration settings."""

    def test_default_environment(self):
        """Test default environment name."""
        config = settings.ServerConfig()
        self.assertEqual(config.environment, 'development')

    def test_default_host(self):
        """Test default bind address."""
        config = settings.ServerConfig()
        self.assertEqual(config.host, 'localhost')

    def test_default_port(self):
        """Test default listen port."""
        config = settings.ServerConfig()
        self.assertEqual(config.port, 8000)


class TestLoadConfig(unittest.TestCase):
    """Test configuration loading from files and environment."""

    def test_load_config_returns_configuration(self):
        """Test load_config returns Configuration instance."""
        config = settings.load_config()
        self.assertIsInstance(config, settings.Configuration)

    def test_load_config_from_toml_file(self):
        """Test loading configuration from TOML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = pathlib.Path(tmpdir) / 'config.toml'
            config_file.write_text("""
[neo4j]
database = "test_database"

[server]
environment = "testing"
port = 9000
            """)

            # Change working directory to temp dir
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                config = settings.load_config()
                self.assertEqual(config.neo4j.database, 'test_database')
                self.assertEqual(config.server.environment, 'testing')
                self.assertEqual(config.server.port, 9000)
            finally:
                os.chdir(original_cwd)


if __name__ == '__main__':
    unittest.main()
