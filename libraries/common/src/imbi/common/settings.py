import logging
import pathlib
import secrets
import tomllib
import typing
from urllib import parse

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


class Neo4j(pydantic_settings.BaseSettings):
    model_config = base_settings_config(env_prefix='NEO4J_')
    url: pydantic.AnyUrl = pydantic.AnyUrl('neo4j://localhost:7687')
    user: str | None = None
    password: str | None = None
    database: str = 'neo4j'
    keep_alive: bool = True
    liveness_check_timeout: int = 60
    max_connection_lifetime: int = 300

    @pydantic.model_validator(mode='after')
    def extract_credentials_from_url(self) -> 'Neo4j':
        """Extract username/password from URL and strip them from the URL.

        If the URL contains embedded credentials (e.g.,
        neo4j://username:password@localhost:7687), extract them and set
        the user and password fields, then clean the URL.

        """
        if self.url.username and not self.user:
            # Decode URL-encoded username
            self.user = parse.unquote(self.url.username)

        if self.url.password and not self.password:
            # Decode URL-encoded password
            self.password = parse.unquote(self.url.password)

        # Strip credentials from URL if present
        if self.url.username or self.url.password:
            # Rebuild URL without credentials
            scheme = self.url.scheme
            host = self.url.host or 'localhost'
            path = self.url.path or ''

            # Build URL - only include port if explicitly set
            url_parts = f'{scheme}://{host}'
            if self.url.port:
                url_parts += f':{self.url.port}'
            if path:
                url_parts += path

            self.url = pydantic.AnyUrl(url_parts)

        return self


class ServerConfig(pydantic_settings.BaseSettings):
    model_config = base_settings_config(env_prefix='IMBI_')
    environment: str = 'development'
    host: str = 'localhost'
    port: int = 8000


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
        [server]
        environment = "production"
        host = "0.0.0.0"
        port = 8080

        [neo4j]
        url = "neo4j://neo4j-prod:7687"
        user = "admin"

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
            'neo4j': Neo4j,
            'server': ServerConfig,
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
    neo4j: Neo4j = pydantic.Field(default_factory=Neo4j)
    server: ServerConfig = pydantic.Field(default_factory=ServerConfig)
    auth: Auth = pydantic.Field(default_factory=Auth)


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

    return Configuration.model_validate(config_data)


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
