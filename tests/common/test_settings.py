"""Unit tests for settings module."""

import os
import pathlib
import tempfile
import unittest
import unittest.mock

from imbi_common import settings


class PostgresSettingsTestCase(unittest.TestCase):
    """Test cases for Postgres settings."""

    def test_default_settings(self) -> None:
        """Test Postgres settings with defaults."""
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            pg = settings.Postgres(_env_file=None)
        self.assertEqual(
            str(pg.url),
            'postgresql://postgres:secret@localhost:5432/imbi',
        )
        self.assertEqual(pg.graph_name, 'imbi')
        self.assertEqual(pg.min_pool_size, 2)
        self.assertEqual(pg.max_pool_size, 10)

    def test_custom_url(self) -> None:
        """Test Postgres settings with custom URL."""
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            pg = settings.Postgres(
                url='postgresql://user:pass@dbhost:5432/mydb',
                _env_file=None,
            )
        self.assertEqual(
            str(pg.url),
            'postgresql://user:pass@dbhost:5432/mydb',
        )

    def test_custom_pool_sizes(self) -> None:
        """Test Postgres settings with custom pool sizes."""
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            pg = settings.Postgres(
                min_pool_size=5,
                max_pool_size=20,
                _env_file=None,
            )
        self.assertEqual(pg.min_pool_size, 5)
        self.assertEqual(pg.max_pool_size, 20)

    def test_custom_graph_name(self) -> None:
        """Test Postgres settings with custom graph name."""
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            pg = settings.Postgres(
                graph_name='test_graph',
                _env_file=None,
            )
        self.assertEqual(pg.graph_name, 'test_graph')


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
        self.assertIsInstance(config.postgres, settings.Postgres)
        self.assertIsInstance(config.auth, settings.Auth)

    def test_configuration_from_dict(self) -> None:
        """Test Configuration from dictionary data."""
        data = {
            'postgres': {
                'url': 'postgresql://user:pass@pg-host:5432/imbi',
            },
        }

        config = settings.Configuration.model_validate(data)

        self.assertEqual(
            str(config.postgres.url),
            'postgresql://user:pass@pg-host:5432/imbi',
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
[postgres]
graph_name = "test-graph"

[auth]
access_token_expire_seconds = 7200
"""
                )

                os.chdir(tmpdir)
                config = settings.load_config()

                self.assertEqual(
                    config.postgres.graph_name,
                    'test-graph',
                )
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
