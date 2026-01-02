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
    """Authentication and authorization settings."""

    model_config = base_settings_config(env_prefix='IMBI_AUTH_')

    # JWT Configuration
    jwt_secret: str = pydantic.Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        description='JWT signing secret (auto-generated if not provided)',
    )
    jwt_algorithm: str = 'HS256'
    access_token_expire_seconds: int = 3600  # 1 hour
    refresh_token_expire_seconds: int = 2592000  # 30 days

    # Password Policy
    min_password_length: int = 12
    require_password_uppercase: bool = True
    require_password_lowercase: bool = True
    require_password_digit: bool = True
    require_password_special: bool = True

    # Session Configuration
    session_timeout_seconds: int = 86400  # 24 hours
    max_concurrent_sessions: int = 5

    # API Key Configuration
    api_key_max_lifetime_days: int = 365

    # Encryption Configuration (Phase 5)
    encryption_key: str | None = pydantic.Field(
        default=None,
        description='Base64-encoded Fernet key for token encryption',
    )

    # MFA Configuration (Phase 5)
    mfa_issuer_name: str = 'Imbi'
    mfa_totp_period: int = 30  # seconds
    mfa_totp_digits: int = 6

    # Rate Limiting Configuration (Phase 5)
    rate_limit_login: str = '5/minute'
    rate_limit_token_refresh: str = '10/minute'
    rate_limit_oauth_init: str = '3/minute'
    rate_limit_api_key: str = '100/minute'

    # OAuth Provider Configurations
    oauth_google_enabled: bool = False
    oauth_google_client_id: str | None = None
    oauth_google_client_secret: str | None = None
    oauth_google_allowed_domains: list[str] = []

    oauth_github_enabled: bool = False
    oauth_github_client_id: str | None = None
    oauth_github_client_secret: str | None = None

    oauth_oidc_enabled: bool = False
    oauth_oidc_client_id: str | None = None
    oauth_oidc_client_secret: str | None = None
    oauth_oidc_issuer_url: str | None = None
    oauth_oidc_name: str = 'OIDC'  # Display name for generic OIDC

    # OAuth Behavior
    oauth_auto_link_by_email: bool = (
        False  # Auto-link OAuth to existing user by email
    )
    oauth_auto_create_users: bool = True  # Create user if doesn't exist
    oauth_callback_base_url: str = (
        'http://localhost:8000'  # Base URL for callbacks
    )

    # Local password authentication
    local_auth_enabled: bool = True

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


class Email(pydantic_settings.BaseSettings):
    """Email sending configuration."""

    model_config = base_settings_config(env_prefix='IMBI_EMAIL_')

    # Feature flags
    enabled: bool = True
    dry_run: bool = False

    # SMTP Configuration
    smtp_host: str = 'localhost'
    smtp_port: int = 587
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_timeout: int = 30

    # Sender Configuration
    from_email: pydantic.EmailStr = 'noreply@imbi.example.com'
    from_name: str = 'Imbi'
    reply_to: pydantic.EmailStr | None = None

    # Retry Configuration
    max_retries: int = 3
    initial_retry_delay: float = 1.0
    max_retry_delay: float = 60.0
    retry_backoff_factor: float = 2.0

    @pydantic.model_validator(mode='after')
    def configure_mailpit_defaults(self) -> 'Email':
        """Auto-configure for Mailpit in development.

        If running in development mode and SMTP is localhost:587 (defaults),
        check for MAILPIT_SMTP_PORT environment variable and use it if present.
        This allows automatic integration with Mailpit from bootstrap script.

        """
        import os

        if os.getenv('IMBI_ENVIRONMENT', 'development') == 'development':
            if self.smtp_host == 'localhost' and self.smtp_port == 587:
                # Check if Mailpit service is available
                mailpit_port = os.getenv('MAILPIT_SMTP_PORT')
                if mailpit_port:
                    self.smtp_port = int(mailpit_port)
                    # Only override TLS if not explicitly set
                    if not os.getenv('IMBI_EMAIL_SMTP_USE_TLS'):
                        self.smtp_use_tls = False
        return self


class Configuration(pydantic.BaseModel):
    """Root configuration combining all settings sections.

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
            'email': Email,
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
    email: Email = pydantic.Field(default_factory=Email)


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
