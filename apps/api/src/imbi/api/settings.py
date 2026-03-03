"""API-specific settings extending imbi-common shared settings.

Import this module instead of imbi_common.settings in imbi-api code
to get access to the full Auth settings (with password policy, OAuth,
sessions, etc.) as well as Email and Storage settings.

Re-exports all shared settings for convenience.
"""

import os
import typing

import pydantic
import pydantic_settings
from imbi_common import settings

# Re-export shared settings
Clickhouse = settings.Clickhouse
Neo4j = settings.Neo4j
ServerConfig = settings.ServerConfig
base_settings_config = settings.base_settings_config


class Auth(settings.Auth):  # type: ignore[misc]
    """Extended authentication settings for the API service.

    Inherits JWT and encryption configuration from imbi-common's Auth
    and adds password policy, session management, API key, MFA, rate
    limiting, and OAuth provider settings.
    """

    # Password Policy
    password_min_length: int = 12
    password_require_uppercase: bool = True
    password_require_lowercase: bool = True
    password_require_digit: bool = True
    password_require_special: bool = True

    # Session Configuration
    session_timeout_seconds: int = 86400  # 24 hours
    max_concurrent_sessions: int = 5

    # API Key Configuration
    api_key_max_lifetime_days: int = 365

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
    oauth_google_allowed_domains: list[str] = []  # noqa: RUF012

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
    oauth_auto_create_users: bool = True
    oauth_callback_base_url: str = (
        'http://localhost:8000'  # Base URL for callbacks
    )

    # Local password authentication
    local_auth_enabled: bool = True


class Email(pydantic_settings.BaseSettings):
    """Email sending configuration."""

    model_config = settings.base_settings_config(env_prefix='IMBI_EMAIL_')

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
        """Auto-configure for Mailpit in development."""
        if os.getenv('IMBI_ENVIRONMENT', 'development') != 'development':
            return self
        if self.smtp_host == 'localhost' and self.smtp_port == 587:
            mailpit_port = os.getenv('MAILPIT_SMTP_PORT')
            if mailpit_port:
                self.smtp_port = int(mailpit_port)
                if not os.getenv('IMBI_EMAIL_SMTP_USE_TLS'):
                    self.smtp_use_tls = False
        return self


class Storage(pydantic_settings.BaseSettings):
    """S3-compatible object storage configuration."""

    model_config = settings.base_settings_config(env_prefix='S3_')

    endpoint_url: str | None = None  # None = real AWS S3
    access_key: str | None = None
    secret_key: str | None = None
    bucket: str = 'imbi-uploads'
    region: str = 'us-east-1'
    create_bucket_on_init: bool = True

    # Upload constraints
    max_file_size: int = 50 * 1024 * 1024  # 50 MB
    allowed_content_types: list[str] = [
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
        'image/svg+xml',
        'application/pdf',
    ]

    # Thumbnail settings
    thumbnail_max_size: int = 256
    thumbnail_quality: int = 85


# Module-level singleton for extended Auth settings
_auth_settings: Auth | None = None


def get_auth_settings() -> Auth:
    """Get the singleton extended Auth settings instance.

    Returns the API-specific Auth settings which include password
    policy, OAuth, sessions, etc. in addition to JWT configuration.

    Returns:
        The singleton Auth settings instance.

    """
    global _auth_settings
    if _auth_settings is None:
        _auth_settings = Auth()
    return _auth_settings


class APIConfiguration(settings.Configuration):  # type: ignore[misc]
    """Extended configuration for the API service.

    Adds Email and Storage settings to the shared Configuration.
    """

    @pydantic.model_validator(mode='before')
    @classmethod
    def merge_env_with_config(
        cls, data: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        """Merge environment variables with config file data."""
        settings_fields: dict[str, type[pydantic_settings.BaseSettings]] = {
            'clickhouse': settings.Clickhouse,
            'neo4j': settings.Neo4j,
            'server': settings.ServerConfig,
            'auth': Auth,
            'email': Email,
            'storage': Storage,
        }
        for field, settings_cls in settings_fields.items():
            if field in data and data[field] is not None:
                if isinstance(data[field], settings_cls):
                    continue
                data[field] = settings_cls(**data[field])
        return data

    auth: Auth = pydantic.Field(default_factory=Auth)
    email: Email = pydantic.Field(default_factory=Email)
    storage: Storage = pydantic.Field(default_factory=Storage)


# Alias so `from imbi_api import settings; settings.Configuration`
# returns the API-extended type with email/storage sections.
Configuration = APIConfiguration


def load_config() -> APIConfiguration:
    """Load configuration from config.toml files.

    Wraps the shared ``load_config`` to return an
    ``APIConfiguration`` instance with email and storage sections.

    """
    data = settings.load_config().model_dump()
    return APIConfiguration.model_validate(  # type: ignore[no-any-return]
        data
    )
