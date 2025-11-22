"""
Configuration management for Imbi using Pydantic Settings.

Supports loading from TOML files (preferred) and YAML files (for backward compatibility).
"""
from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class HttpSettings(BaseSettings):
    """HTTP server configuration."""

    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4
    reload: bool = False


class PostgresSettings(BaseSettings):
    """PostgreSQL database configuration."""

    url: Optional[str] = None
    host: str = "localhost"
    port: int = 5432
    database: str = "imbi"
    user: str = "imbi"
    password: str = ""
    min_pool_size: int = 1
    max_pool_size: int = 20
    timeout: int = 30
    log_queries: bool = False

    @field_validator("url")
    @classmethod
    def parse_url(cls, v: Optional[str]) -> Optional[str]:
        """Parse and validate PostgreSQL URL."""
        if v:
            # Validate URL format
            if not v.startswith("postgresql://"):
                raise ValueError("PostgreSQL URL must start with postgresql://")
        return v


class RedisSettings(BaseSettings):
    """Redis configuration."""

    url: str = "redis://localhost:6379/0"
    encoding: str = "utf-8"
    decode_responses: bool = True


class SessionSettings(BaseSettings):
    """Session management configuration."""

    redis: RedisSettings = Field(default_factory=RedisSettings)
    cookie_name: str = "session"
    duration: int = 7  # days
    secret_key: str = Field(..., description="Secret key for session encryption")


class StatsSettings(BaseSettings):
    """Stats collection configuration."""

    redis: RedisSettings = Field(default_factory=lambda: RedisSettings(url="redis://localhost:6379/1"))
    enabled: bool = True


class LdapSettings(BaseSettings):
    """LDAP authentication configuration."""

    enabled: bool = False
    host: str = "localhost"
    port: int = 389
    ssl: bool = False
    pool_size: int = 5
    users_dn: str = "ou=users,dc=example,dc=com"
    groups_dn: str = "ou=groups,dc=example,dc=com"
    username: Optional[str] = None
    password: Optional[str] = None


class CorsSettings(BaseSettings):
    """CORS configuration."""

    enabled: bool = True
    allowed_origins: list[str] = ["*"]
    allow_credentials: bool = True
    allowed_methods: list[str] = ["*"]
    allowed_headers: list[str] = ["*"]


class OpenSearchSettings(BaseSettings):
    """OpenSearch configuration."""

    enabled: bool = False
    hosts: list[str] = ["http://localhost:9200"]
    username: Optional[str] = None
    password: Optional[str] = None
    use_ssl: bool = False
    verify_certs: bool = True


class ClaudeSettings(BaseSettings):
    """Claude AI configuration."""

    enabled: bool = False
    api_key: str = Field(default="", description="Anthropic API key")
    model: str = "claude-sonnet-4.5"
    max_tokens: int = 4096
    temperature: float = 0.7

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Validate API key is provided when Claude is enabled."""
        if not v:
            logger.warning("Claude API key not configured")
        return v


class McpSettings(BaseSettings):
    """Model Context Protocol server configuration."""

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 3000
    api_url: str = "http://localhost:8000"
    api_token: Optional[str] = None


class SentrySettings(BaseSettings):
    """Sentry error tracking configuration."""

    enabled: bool = False
    dsn: Optional[str] = None
    environment: str = "production"
    traces_sample_rate: float = 0.1


class Config(BaseSettings):
    """Main Imbi configuration."""

    model_config = SettingsConfigDict(
        env_prefix="IMBI_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    # Core settings
    debug: bool = False
    environment: str = "production"
    encryption_key: str = Field(
        ..., description="Base64-encoded encryption key for sensitive data"
    )

    # Component settings
    http: HttpSettings = Field(default_factory=HttpSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    session: SessionSettings
    stats: StatsSettings = Field(default_factory=StatsSettings)
    ldap: LdapSettings = Field(default_factory=LdapSettings)
    cors: CorsSettings = Field(default_factory=CorsSettings)
    opensearch: OpenSearchSettings = Field(default_factory=OpenSearchSettings)
    claude: ClaudeSettings = Field(default_factory=ClaudeSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    sentry: SentrySettings = Field(default_factory=SentrySettings)

    # Application metadata
    version: str = "2.0.0"
    server_header: str = "imbi/2.0"

    @field_validator("encryption_key")
    @classmethod
    def validate_encryption_key(cls, v: str) -> str:
        """Validate encryption key is provided."""
        if not v:
            raise ValueError("encryption_key is required")
        return v


def load_config_from_toml(path: Path) -> Config:
    """
    Load configuration from a TOML file (preferred format).

    Args:
        path: Path to TOML configuration file

    Returns:
        Parsed configuration object

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is invalid
    """
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    logger.info(f"Loading configuration from TOML: {path}")

    with open(path, "rb") as f:
        data = tomllib.load(f)

    if not isinstance(data, dict):
        raise ValueError("Configuration file must contain a TOML table")

    # Handle session.secret_key default
    if "session" in data:
        session = data["session"]
        if "secret_key" not in session and "encryption_key" in data:
            session["secret_key"] = data["encryption_key"]

    try:
        config = Config(**data)
        logger.info("Configuration loaded successfully from TOML")
        return config
    except Exception as e:
        logger.error(f"Failed to parse TOML configuration: {e}")
        raise ValueError(f"Invalid configuration: {e}") from e


def load_config_from_yaml(path: Path) -> Config:
    """
    Load configuration from a YAML file (legacy format).

    Args:
        path: Path to YAML configuration file

    Returns:
        Parsed configuration object

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is invalid
    """
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    logger.info(f"Loading configuration from YAML: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError("Configuration file must contain a YAML dictionary")

    # Handle session.secret_key default
    if "session" in data:
        session = data["session"]
        if "secret_key" not in session and "encryption_key" in data:
            session["secret_key"] = data["encryption_key"]

    try:
        config = Config(**data)
        logger.info("Configuration loaded successfully from YAML")
        return config
    except Exception as e:
        logger.error(f"Failed to parse YAML configuration: {e}")
        raise ValueError(f"Invalid configuration: {e}") from e


def load_config(path: Optional[Path] = None) -> Config:
    """
    Load configuration from file or environment variables.

    Supports both TOML (preferred) and YAML (legacy) formats.
    Automatically detects format based on file extension.

    Args:
        path: Optional path to config file (.toml or .yaml)

    Returns:
        Parsed configuration object
    """
    if path:
        path = Path(path)
        suffix = path.suffix.lower()

        if suffix == ".toml":
            return load_config_from_toml(path)
        elif suffix in (".yaml", ".yml"):
            logger.warning(
                "YAML configuration is deprecated. Please migrate to TOML format."
            )
            return load_config_from_yaml(path)
        else:
            raise ValueError(
                f"Unsupported configuration format: {suffix}. "
                "Use .toml (preferred) or .yaml (legacy)"
            )

    # Load from environment variables only
    logger.info("Loading configuration from environment variables")
    return Config()
