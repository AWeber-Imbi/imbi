import pydantic
import pydantic_settings

import imbi_gateway.helpers
from tests import helpers


class SimpleSettings(pydantic_settings.BaseSettings):
    database_url: str
    port: int = 5432


class PrefixedSettings(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(env_prefix='APP_')

    database_url: str
    api_key: str


class NestedSettings(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(env_prefix='SVC_')

    class DatabaseConfig(pydantic.BaseModel):
        host: str
        port: int

    database: DatabaseConfig


class ConstrainedSettings(pydantic_settings.BaseSettings):
    port: int = pydantic.Field(gt=0, lt=65536)
    timeout: float = pydantic.Field(gt=0.0)


class SettingsFromEnvironmentTests(helpers.TestCase):
    def test_rejects_non_basesettings_type(self) -> None:
        # Raises TypeError when typ is not a BaseSettings subclass.
        class NotASettings:
            pass

        with self.assertRaises(TypeError) as ctx:
            imbi_gateway.helpers.settings_from_environment(NotASettings)  # type: ignore[type-var]

        self.assertIn('NotASettings', str(ctx.exception))
        self.assertIn('not a subclass of', str(ctx.exception))
        self.assertIn('BaseSettings', str(ctx.exception))

    def test_loads_from_environment_variables(self) -> None:
        # Successfully loads settings from environment variables.
        with self.override_environment(
            DATABASE_URL='postgresql://localhost/test', PORT='8000'
        ):
            settings = imbi_gateway.helpers.settings_from_environment(
                SimpleSettings
            )

        self.assertEqual('postgresql://localhost/test', settings.database_url)
        self.assertEqual(8000, settings.port)

    def test_uses_default_values(self) -> None:
        # Uses default field values when env vars not set.
        with self.override_environment(
            DATABASE_URL='postgresql://localhost/test', PORT=None
        ):
            settings = imbi_gateway.helpers.settings_from_environment(
                SimpleSettings
            )

        self.assertEqual('postgresql://localhost/test', settings.database_url)
        self.assertEqual(5432, settings.port)

    def test_overrides_with_defaults_parameter(self) -> None:
        # Defaults parameter overrides environment variables.
        with self.override_environment(
            DATABASE_URL='postgresql://localhost/test', PORT='8000'
        ):
            settings = imbi_gateway.helpers.settings_from_environment(
                SimpleSettings,
                database_url='postgresql://override/db',
                port=9000,
            )

        self.assertEqual('postgresql://override/db', settings.database_url)
        self.assertEqual(9000, settings.port)

    def test_raises_settings_error_for_missing_variable(self) -> None:
        # Raises SettingsError when required env var is missing.
        with (
            self.override_environment(DATABASE_URL=None),
            self.assertRaises(pydantic_settings.SettingsError) as ctx,
        ):
            imbi_gateway.helpers.settings_from_environment(SimpleSettings)

        self.assertIn('Missing environment variable(s)', str(ctx.exception))
        self.assertIn('DATABASE_URL', str(ctx.exception))

    def test_raises_settings_error_for_multiple_missing_variables(
        self,
    ) -> None:
        # Raises SettingsError listing all missing env vars.
        with (
            self.override_environment(DATABASE_URL=None, API_KEY=None),
            self.assertRaises(pydantic_settings.SettingsError) as ctx,
        ):
            imbi_gateway.helpers.settings_from_environment(PrefixedSettings)

        error_message = str(ctx.exception)
        self.assertIn('Missing environment variable(s)', error_message)
        self.assertIn('APP_DATABASE_URL', error_message)
        self.assertIn('APP_API_KEY', error_message)

    def test_includes_env_prefix_in_error_message(self) -> None:
        # Error message includes env_prefix from model config.
        with (
            self.override_environment(APP_DATABASE_URL=None, APP_API_KEY=None),
            self.assertRaises(pydantic_settings.SettingsError) as ctx,
        ):
            imbi_gateway.helpers.settings_from_environment(PrefixedSettings)

        error_message = str(ctx.exception)
        self.assertIn('APP_DATABASE_URL', error_message)
        self.assertIn('APP_API_KEY', error_message)

    def test_handles_nested_field_errors(self) -> None:
        # Converts nested field paths to env var names.
        # When a nested model is missing, Pydantic reports the parent field
        with (
            self.override_environment(SVC_DATABASE=None),
            self.assertRaises(pydantic_settings.SettingsError) as ctx,
        ):
            imbi_gateway.helpers.settings_from_environment(NestedSettings)

        error_message = str(ctx.exception)
        self.assertIn('Missing environment variable(s)', error_message)
        # The parent field name with prefix
        self.assertIn('SVC_DATABASE', error_message)

    def test_reraises_non_missing_validation_errors(self) -> None:
        # Re-raises ValidationError for non-missing field errors.
        with (
            self.override_environment(PORT='invalid', TIMEOUT='2.5'),
            self.assertRaises(pydantic.ValidationError) as ctx,
        ):
            imbi_gateway.helpers.settings_from_environment(ConstrainedSettings)

        # Should be the original ValidationError, not SettingsError
        self.assertIsInstance(ctx.exception, pydantic.ValidationError)
        # Should be about type validation, not missing fields
        errors = ctx.exception.errors()
        self.assertTrue(
            any(
                error['type'] in ('int_parsing', 'int_type')
                for error in errors
            )
        )

    def test_reraises_constraint_validation_errors(self) -> None:
        # Re-raises ValidationError for constraint violations.
        with (
            self.override_environment(PORT='99999', TIMEOUT='-1.0'),
            self.assertRaises(pydantic.ValidationError) as ctx,
        ):
            imbi_gateway.helpers.settings_from_environment(ConstrainedSettings)

        # Should contain constraint validation errors
        errors = ctx.exception.errors()
        self.assertTrue(
            any(
                error['type'] in ('greater_than', 'less_than')
                for error in errors
            )
        )

    def test_successful_load_with_env_prefix(self) -> None:
        # Successfully loads prefixed settings.
        with self.override_environment(
            APP_DATABASE_URL='postgresql://localhost/app',
            APP_API_KEY='secret-key-123',
        ):
            settings = imbi_gateway.helpers.settings_from_environment(
                PrefixedSettings
            )

        self.assertEqual('postgresql://localhost/app', settings.database_url)
        self.assertEqual('secret-key-123', settings.api_key)

    def test_suppresses_original_exception_chain(self) -> None:
        # SettingsError is raised with 'from None' to suppress chain.
        with (
            self.override_environment(DATABASE_URL=None),
            self.assertRaises(pydantic_settings.SettingsError) as ctx,
        ):
            imbi_gateway.helpers.settings_from_environment(SimpleSettings)

        # Verify that __cause__ is None (raised with 'from None')
        self.assertIsNone(ctx.exception.__cause__)
