import logging
import pathlib
import secrets
import tomllib
import typing

import pydantic
import pydantic_settings

LOGGER = logging.getLogger(__name__)


def base_settings_config(
    *,
    env_prefix: str = '',
) -> pydantic_settings.SettingsConfigDict:
    """Create a base SettingsConfigDict with common defaults.

    Args:
        env_prefix: Environment variable prefix

    Returns:
        SettingsConfigDict with base settings

    """
    return pydantic_settings.SettingsConfigDict(
        case_sensitive=False,
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore',
        env_prefix=env_prefix,
    )


class Clickhouse(pydantic_settings.BaseSettings):
    model_config = base_settings_config(env_prefix='CLICKHOUSE_')

    url: pydantic.HttpUrl = pydantic.HttpUrl('http://localhost:8123')
    connect_timeout: float = 10.0  # default in clickhouse client
    max_connect_attempts: int = 10


class AGE(pydantic_settings.BaseSettings):
    """Apache AGE (PostgreSQL extension) connection settings."""

    model_config = base_settings_config(env_prefix='AGE_')
    url: str = 'postgresql://postgres:secret@localhost:5432/imbi'
    graph_name: str = 'imbi'
    min_pool_size: int = 2
    max_pool_size: int = 10


class Auth(pydantic_settings.BaseSettings):
    """Authentication settings shared across Imbi services.

    Contains only JWT and encryption configuration needed by any
    service that verifies tokens or handles encrypted data.

    """

    model_config = base_settings_config(env_prefix='IMBI_AUTH_')

    # JWT Configuration
    jwt_secret: str = pydantic.Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        description='JWT signing secret (auto-generated if not provided)',
    )
    jwt_algorithm: str = 'HS256'
    access_token_expire_seconds: int = 3600  # 1 hour
    refresh_token_expire_seconds: int = 2592000  # 30 days

    # Encryption Configuration (Phase 5)
    encryption_key: str | None = pydantic.Field(
        default=None,
        description='Base64-encoded Fernet key for token encryption',
    )

    @pydantic.model_validator(mode='after')
    def generate_encryption_key_if_missing(self) -> 'Auth':
        """Generate encryption key if not provided (Phase 5).

        Auto-generates a Fernet encryption key if IMBI_AUTH_ENCRYPTION_KEY
        is not set in the environment. Logs a warning since this key should
        be stable across restarts in production.
        """
        if self.encryption_key is None:
            from cryptography import fernet

            self.encryption_key = fernet.Fernet.generate_key().decode('ascii')
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                'Encryption key auto-generated. Set IMBI_AUTH_ENCRYPTION_KEY '
                'in production for stable key across restarts.'
            )
        return self


class Configuration(pydantic.BaseModel):
    """Root configuration combining all shared settings sections.

    Supports loading from config.toml files with environment variable
    overrides. Config files are checked in this priority order:
    1. ./config.toml (project root)
    2. ~/.config/imbi/config.toml (user config)
    3. /etc/imbi/config.toml (system config)

    Environment variables always take precedence over config file values.

    Example config.toml:
        [age]
        url = "postgresql://postgres:secret@db-prod:5432/imbi"

        [auth]
        jwt_secret = "your-secret-here"
        access_token_expire_seconds = 7200
    """

    @pydantic.model_validator(mode='before')
    @classmethod
    def merge_env_with_config(
        cls, data: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        """Merge environment variables with config file data.

        For each BaseSettings submodel, instantiate it with the config file
        data as kwargs. This allows BaseSettings to use environment variables
        as defaults for any fields not provided in the config file.

        Args:
            data: Raw config data from TOML file

        Returns:
            Config data with BaseSettings instances properly constructed

        """
        settings_fields: dict[str, type[pydantic_settings.BaseSettings]] = {
            'clickhouse': Clickhouse,
            'age': AGE,
            'auth': Auth,
        }
        for field, settings_cls in settings_fields.items():
            if field in data and data[field] is not None:
                # Skip if already an instance (e.g., from direct construction)
                if isinstance(data[field], settings_cls):
                    continue
                data[field] = settings_cls(**data[field])
        return data

    clickhouse: Clickhouse = pydantic.Field(default_factory=Clickhouse)
    age: AGE = pydantic.Field(default_factory=AGE)
    auth: Auth = pydantic.Field(default_factory=Auth)


def load_config_data() -> dict[str, typing.Any]:
    """Load raw configuration data from config.toml files.

    Checks for config files in priority order:
    1. ./config.toml (project root)
    2. ~/.config/imbi/config.toml (user config)
    3. /etc/imbi/config.toml (system config)

    Returns the merged dictionary without validation so that callers
    can validate against their own Configuration subclass.

    Returns:
        Merged configuration dictionary

    """
    config_paths = [
        pathlib.Path.cwd() / 'config.toml',
        pathlib.Path.home() / '.config' / 'imbi' / 'config.toml',
        pathlib.Path('/etc/imbi/config.toml'),
    ]

    config_data: dict[str, typing.Any] = {}

    for config_path in config_paths:
        if config_path.exists():
            LOGGER.info('Loading configuration from %s', config_path)
            try:
                with config_path.open('rb') as f:
                    file_data = tomllib.load(f)
                    # Merge with priority to earlier files (first found wins)
                    for key, value in file_data.items():
                        if key not in config_data:
                            config_data[key] = value
                        elif isinstance(value, dict) and isinstance(
                            config_data[key], dict
                        ):
                            # Merge nested dicts
                            config_data[key] = {**value, **config_data[key]}
            except (tomllib.TOMLDecodeError, OSError) as e:
                LOGGER.warning('Failed to load %s: %s', config_path, e)
                continue

    return config_data


def load_config() -> Configuration:
    """Load configuration from config.toml files with environment overrides.

    Checks for config files in priority order:
    1. ./config.toml (project root)
    2. ~/.config/imbi/config.toml (user config)
    3. /etc/imbi/config.toml (system config)

    Environment variables always override config file values.

    Returns:
        Configuration object with merged settings

    """
    return Configuration.model_validate(load_config_data())


# Module-level singleton for Auth settings to ensure stable JWT secret
_auth_settings: Auth | None = None


def get_auth_settings() -> Auth:
    """Get the singleton Auth settings instance.

    This ensures the JWT secret remains stable across requests when
    auto-generated (i.e., when IMBI_AUTH_JWT_SECRET is not set in env).

    Returns:
        The singleton Auth settings instance.

    """
    global _auth_settings
    if _auth_settings is None:
        _auth_settings = Auth()
    return _auth_settings
