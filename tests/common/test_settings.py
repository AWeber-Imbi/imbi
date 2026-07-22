"""Unit tests for settings module."""

import os
import pathlib
import ssl
import tempfile
import unittest
import unittest.mock

import pydantic

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
            self.assertIn(
                str(config.url),
                (
                    'clickhouse+http://localhost:8123',
                    'clickhouse+http://localhost:8123/',
                ),
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

    def test_production_requires_secrets(self) -> None:
        """Non-dev ENVIRONMENT refuses to boot with unset secrets."""
        with unittest.mock.patch.dict(
            os.environ, {'ENVIRONMENT': 'production'}, clear=True
        ):
            with self.assertRaises(pydantic.ValidationError):
                settings.Auth(_env_file=None)

    def test_production_requires_both_secrets(self) -> None:
        """A non-dev env still refuses when only jwt_secret is provided."""
        with unittest.mock.patch.dict(
            os.environ, {'ENVIRONMENT': 'production'}, clear=True
        ):
            with self.assertRaises(pydantic.ValidationError):
                settings.Auth(_env_file=None, jwt_secret='x' * 32)

    def test_production_accepts_explicit_secrets(self) -> None:
        """Explicitly-provided secrets satisfy the non-dev guard."""
        with unittest.mock.patch.dict(
            os.environ, {'ENVIRONMENT': 'production'}, clear=True
        ):
            config = settings.Auth(
                _env_file=None,
                jwt_secret='x' * 32,
                encryption_key='k' * 32,
            )
        self.assertEqual(config.jwt_secret, 'x' * 32)
        self.assertEqual(config.encryption_key, 'k' * 32)

    def test_development_auto_generates_when_unset(self) -> None:
        """Development (the default) still auto-generates both secrets."""
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            config = settings.Auth(_env_file=None)
        self.assertTrue(config.jwt_secret)
        self.assertTrue(config.encryption_key)


class ConfigSecretsSettingsTestCase(unittest.TestCase):
    """Test config-secret encryption settings configuration."""

    def setUp(self) -> None:
        super().setUp()
        settings._config_settings = None

    def tearDown(self) -> None:
        settings._config_settings = None
        super().tearDown()

    def test_development_auto_generates_key(self) -> None:
        """Development (the default) auto-generates the encryption key."""
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            config = settings.ConfigSecrets(_env_file=None)
        self.assertIsNotNone(config.encryption_key)
        self.assertGreater(len(config.encryption_key), 0)

    def test_production_requires_key(self) -> None:
        """Non-dev ENVIRONMENT refuses to boot with an unset key."""
        with unittest.mock.patch.dict(
            os.environ, {'ENVIRONMENT': 'production'}, clear=True
        ):
            with self.assertRaises(pydantic.ValidationError):
                settings.ConfigSecrets(_env_file=None)

    def test_production_accepts_explicit_key(self) -> None:
        """An explicitly-provided key satisfies the non-dev guard."""
        with unittest.mock.patch.dict(
            os.environ, {'ENVIRONMENT': 'production'}, clear=True
        ):
            config = settings.ConfigSecrets(
                _env_file=None, encryption_key='k' * 32
            )
        self.assertEqual(config.encryption_key, 'k' * 32)

    def test_env_prefix(self) -> None:
        """IMBI_CONFIG_ENCRYPTION_KEY populates the key field."""
        with unittest.mock.patch.dict(
            os.environ,
            {'IMBI_CONFIG_ENCRYPTION_KEY': 'k' * 32},
            clear=True,
        ):
            config = settings.ConfigSecrets(_env_file=None)
        self.assertEqual(config.encryption_key, 'k' * 32)

    def test_get_config_settings_is_singleton(self) -> None:
        """get_config_settings returns a stable singleton instance."""
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            first = settings.get_config_settings()
            second = settings.get_config_settings()
        self.assertIs(first, second)
        self.assertIsNotNone(first.encryption_key)


class ReleasesSettingsTestCase(unittest.TestCase):
    """Test cases for Releases settings."""

    def test_default_version_format(self) -> None:
        """Default version_format is semver."""
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            releases = settings.Releases(_env_file=None)
        self.assertEqual(releases.version_format, 'semver')

    def test_env_override(self) -> None:
        """IMBI_RELEASES_VERSION_FORMAT overrides the default."""
        with unittest.mock.patch.dict(
            os.environ,
            {'IMBI_RELEASES_VERSION_FORMAT': 'commitish'},
            clear=True,
        ):
            releases = settings.Releases(_env_file=None)
        self.assertEqual(releases.version_format, 'commitish')

    def test_invalid_value_rejected(self) -> None:
        """An unknown format raises."""
        with unittest.mock.patch.dict(
            os.environ,
            {'IMBI_RELEASES_VERSION_FORMAT': 'calver'},
            clear=True,
        ):
            with self.assertRaises(pydantic.ValidationError):
                settings.Releases(_env_file=None)


class ConfigurationTestCase(unittest.TestCase):
    """Test cases for Configuration class."""

    def test_configuration_defaults(self) -> None:
        """Test Configuration with default values."""
        config = settings.Configuration()

        self.assertIsInstance(config.clickhouse, settings.Clickhouse)
        self.assertIsInstance(config.postgres, settings.Postgres)
        self.assertIsInstance(config.auth, settings.Auth)
        self.assertIsInstance(config.releases, settings.Releases)

    def test_releases_from_dict(self) -> None:
        """Test Releases is constructed from config dict."""
        config = settings.Configuration.model_validate(
            {'releases': {'version_format': 'commitish'}},
        )
        self.assertEqual(config.releases.version_format, 'commitish')

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


class SSLSettingsTestCase(unittest.TestCase):
    """Test cases for SSL settings."""

    def setUp(self) -> None:
        super().setUp()
        self._orig_create = ssl.create_default_context
        self._orig_https = ssl._create_default_https_context  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        ssl.create_default_context = self._orig_create
        ssl._create_default_https_context = self._orig_https  # type: ignore[attr-defined]
        super().tearDown()

    def test_default_cert_dir_is_none(self) -> None:
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            ssl_settings = settings.SSL(_env_file=None)
        self.assertIsNone(ssl_settings.cert_dir)

    def test_cert_dir_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with unittest.mock.patch.dict(
                os.environ, {'SSL_CERT_DIR': tmpdir}, clear=True
            ):
                ssl_settings = settings.SSL(_env_file=None)
            self.assertEqual(ssl_settings.cert_dir, pathlib.Path(tmpdir))

    def test_configure_does_nothing_when_cert_dir_is_none(self) -> None:
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            ssl_settings = settings.SSL(_env_file=None)
        ssl_settings.configure()
        self.assertIs(ssl.create_default_context, self._orig_create)

    def test_configure_patches_ssl_context_when_cert_dir_is_set(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ssl_settings = settings.SSL(cert_dir=pathlib.Path(tmpdir))
            # verify patching happens (load_verify_locations raises for an
            # empty dir, so we stub it out)
            with unittest.mock.patch.object(
                ssl.SSLContext, 'load_verify_locations'
            ) as mock_load:
                ssl_settings.configure()
                self.assertIsNot(ssl.create_default_context, self._orig_create)
                self.assertIsNot(
                    ssl._create_default_https_context,  # type: ignore[attr-defined]
                    self._orig_https,
                )
                # patched call must invoke load_verify_locations
                ssl.create_default_context()
                mock_load.assert_called_once_with(capath=tmpdir)


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
