import logging
import os
import pathlib
import secrets
import tomllib
import typing

import pydantic
import pydantic_settings

from imbi.common.versioning import VersionFormat

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


class ConfigFileSettings(pydantic_settings.BaseSettings):
    """Settings that also read one section of ``config.toml``.

    ``config_section`` names the section. The sources, from the highest
    priority to the lowest, are: constructor arguments, environment
    variables, the ``.env`` file, the ``config.toml`` section, and the
    field defaults. Thus an environment variable always overrides the
    same key in ``config.toml``.

    """

    config_section: typing.ClassVar[str]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[pydantic_settings.BaseSettings],
        init_settings: pydantic_settings.PydanticBaseSettingsSource,
        env_settings: pydantic_settings.PydanticBaseSettingsSource,
        dotenv_settings: pydantic_settings.PydanticBaseSettingsSource,
        file_secret_settings: pydantic_settings.PydanticBaseSettingsSource,
    ) -> tuple[pydantic_settings.PydanticBaseSettingsSource, ...]:
        config_file = pydantic_settings.InitSettingsSource(
            settings_cls, load_config_data().get(cls.config_section, {})
        )
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            config_file,
            file_secret_settings,
        )


class Auth(ConfigFileSettings):
    """Authentication settings shared across Imbi services.

    Contains only JWT and encryption configuration needed by any
    service that verifies tokens or handles encrypted data.

    """

    model_config = base_settings_config(env_prefix='IMBI_AUTH_')
    config_section = 'auth'

    # JWT Configuration
    jwt_secret: str = pydantic.Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        description='JWT signing secret (auto-generated if not provided)',
    )
    jwt_algorithm: str = 'HS256'
    access_token_expire_seconds: int = 3600  # 1 hour
    refresh_token_expire_seconds: int = 2592000  # 30 days

    # Throttle interval for the ``last_used`` stamp the shared API-key
    # auth path writes. Authentication runs on every request, but
    # persisting the stamp every time spikes graph write pressure for no
    # UX benefit -- the value only needs to be accurate to the nearest
    # minute or so. Set to 0 to disable throttling. Constrained rather than
    # clamped: the stamp path takes `max(0, ...)`, so a typo like `-1` would
    # otherwise silently disable throttling and write on every request.
    last_used_throttle_seconds: int = pydantic.Field(default=60, ge=0)

    # Encryption Configuration (Phase 5)
    encryption_key: str | None = pydantic.Field(
        default=None,
        description='Base64-encoded Fernet key for token encryption',
    )

    @pydantic.model_validator(mode='after')
    def validate_secrets(self) -> Auth:
        """Enforce explicit secrets outside development; auto-generate in dev.

        When ``ENVIRONMENT`` is anything other than ``development`` (the
        default), both ``IMBI_AUTH_JWT_SECRET`` and
        ``IMBI_AUTH_ENCRYPTION_KEY`` must be configured explicitly: booting
        with auto-generated per-process values would silently invalidate
        every issued token (and make every encrypted value undecryptable)
        on the next restart, so it is refused. In development the historical
        auto-generation behavior is preserved.

        ``model_fields_set`` distinguishes an explicitly-supplied value
        (env var, config file, or kwarg) from a default, and is inspected
        before the dev-mode auto-generation below mutates it.
        """
        if os.getenv('ENVIRONMENT', 'development').lower() != 'development':
            missing = sorted(
                name
                for name in ('jwt_secret', 'encryption_key')
                if name not in self.model_fields_set
            )
            if missing:
                raise ValueError(
                    'These IMBI_AUTH_ settings must be set explicitly when '
                    'ENVIRONMENT is not "development": ' + ', '.join(missing)
                )

        if self.encryption_key is None:
            from cryptography import fernet

            self.encryption_key = fernet.Fernet.generate_key().decode('ascii')
            LOGGER.warning(
                'Encryption key auto-generated. Set IMBI_AUTH_ENCRYPTION_KEY '
                'in production for stable key across restarts.'
            )
        return self


class ConfigSecrets(pydantic_settings.BaseSettings):
    """Encryption settings for persisted configuration secrets.

    Provides a dedicated Fernet key, separate from :class:`Auth`, used to
    encrypt sensitive configuration values (e.g. external MCP server
    credentials) at rest. Keeping it distinct from the JWT/token encryption
    key lets the two be rotated independently.

    """

    model_config = base_settings_config(env_prefix='IMBI_CONFIG_')

    encryption_key: str | None = pydantic.Field(
        default=None,
        description='Base64-encoded Fernet key for config value encryption',
    )

    @pydantic.model_validator(mode='after')
    def validate_secrets(self) -> ConfigSecrets:
        """Enforce an explicit key outside development; auto-generate in dev.

        When ``ENVIRONMENT`` is anything other than ``development`` (the
        default), ``IMBI_CONFIG_ENCRYPTION_KEY`` must be configured
        explicitly: booting with an auto-generated per-process value would
        silently make every encrypted configuration value undecryptable on
        the next restart, so it is refused. In development the historical
        auto-generation behavior is preserved.

        ``model_fields_set`` distinguishes an explicitly-supplied value
        (env var, config file, or kwarg) from a default, and is inspected
        before the dev-mode auto-generation below mutates it.
        """
        if os.getenv('ENVIRONMENT', 'development').lower() != 'development':
            if 'encryption_key' not in self.model_fields_set:
                raise ValueError(
                    'IMBI_CONFIG_ENCRYPTION_KEY must be set explicitly when '
                    'ENVIRONMENT is not "development"'
                )

        if self.encryption_key is None:
            from cryptography import fernet

            self.encryption_key = fernet.Fernet.generate_key().decode('ascii')
            LOGGER.warning(
                'Config encryption key auto-generated. Set '
                'IMBI_CONFIG_ENCRYPTION_KEY in production for a stable key '
                'across restarts.'
            )
        return self


class Clickhouse(ConfigFileSettings):
    model_config = base_settings_config(env_prefix='CLICKHOUSE_')
    config_section = 'clickhouse'

    url: pydantic.ClickHouseDsn = pydantic.ClickHouseDsn(
        'clickhouse+http://localhost:8123'
    )
    connect_timeout: float = 10.0  # default in clickhouse client
    max_connect_attempts: int = 10
    cluster_name: str | None = None
    """Name of the ClickHouse cluster (``CLICKHOUSE_CLUSTER_NAME``).

    When set, ``setup_schema()`` injects ``ON CLUSTER <cluster_name>`` into
    the ``CREATE`` DDL statements loaded from ``schemata.toml`` so the schema
    is created across every node of the cluster. Leave unset for a
    single-node deployment.
    """


class EmbeddingModelConfig(pydantic.BaseModel):
    """Configuration for a single embedding model."""

    fastembed_id: str
    dimensions: int


class Embeddings(ConfigFileSettings):
    """Embedding generation settings."""

    model_config = base_settings_config(
        env_prefix='EMBEDDINGS_',
    )
    config_section = 'embeddings'

    enabled: bool = True
    default_model: str = 'text'
    models: dict[str, EmbeddingModelConfig] = pydantic.Field(
        default_factory=lambda: {
            'text': EmbeddingModelConfig(
                fastembed_id='BAAI/bge-small-en-v1.5',
                dimensions=384,
            ),
        },
    )


class IggyDSN(pydantic.AnyUrl):
    """Apache Iggy DSN, in the SDK's connection-string form.

    The schemes are the ones ``IggyClient.from_connection_string``
    parses: bare ``iggy`` and ``iggy+tcp`` both select the TCP
    transport, ``iggy+quic``, ``iggy+http`` and ``iggy+ws`` select the
    others. The SDK rejects a connection string carrying a path, so no
    ``default_path`` is set here.
    """

    _constraints = pydantic.UrlConstraints(
        allowed_schemes=[
            'iggy',
            'iggy+tcp',
            'iggy+quic',
            'iggy+http',
            'iggy+ws',
        ],
        default_host='localhost',
        default_port=8090,
        host_required=True,
    )


class Iggy(pydantic_settings.BaseSettings):
    """Apache Iggy connection settings."""

    model_config = base_settings_config(env_prefix='IGGY_')

    url: IggyDSN = pydantic.Field(
        default=IggyDSN('iggy+tcp://iggy:iggy@localhost:8090')
    )
    connect_timeout: float = 10.0
    max_connect_attempts: int = 10


class Plugins(ConfigFileSettings):
    """Plugin discovery settings.

    ``imbi_plugins`` (env ``IMBI_PLUGINS``) is an explicit list of dotted
    import paths (``package.module:Attr``) for plugin packages that cannot
    follow the ``imbi_plugin_*`` naming convention. The env var accepts a
    comma-separated string; config files supply a list. The registry
    unions it with the first-party and convention scans.

    ``imbi_plugins_disabled`` (env ``IMBI_PLUGINS_DISABLED``) is a list of
    plugin slugs to skip at load time. First-party plugins ship as
    ``imbi-plugin-*`` distributions and auto-load whenever they are
    installed; this setting turns individual plugins off without
    uninstalling anything.
    """

    model_config = base_settings_config(env_prefix='')
    config_section = 'plugins'

    imbi_plugins: typing.Annotated[list[str], pydantic_settings.NoDecode] = []
    imbi_plugins_disabled: typing.Annotated[
        list[str], pydantic_settings.NoDecode
    ] = []

    @pydantic.field_validator(
        'imbi_plugins', 'imbi_plugins_disabled', mode='before'
    )
    @classmethod
    def _split_paths(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(',') if part.strip()]
        return value


class Postgres(ConfigFileSettings):
    """PostgreSQL connection settings."""

    model_config = base_settings_config(env_prefix='POSTGRES_')
    config_section = 'postgres'
    url: pydantic.PostgresDsn = pydantic.Field(
        default=pydantic.PostgresDsn(
            'postgresql://postgres:secret@localhost:5432/imbi'
        )
    )
    graph_name: str = 'imbi'
    min_pool_size: int = 2
    max_pool_size: int = 10


class Releases(ConfigFileSettings):
    """Release settings.

    Controls the active ``version_format`` used when validating
    ``Release.version`` at the endpoint boundary.  The value is
    a runtime setting rather than a model field validator so the
    same model can be reused across services with different
    policies.

    """

    model_config = base_settings_config(env_prefix='IMBI_RELEASES_')
    config_section = 'releases'

    version_format: VersionFormat = 'semver'


class SSL(ConfigFileSettings):
    """SSL configuration settings."""

    model_config = base_settings_config(env_prefix='SSL_')
    config_section = 'ssl'

    cert_dir: pathlib.Path | None = pydantic.Field(
        default=None,
        description='Path to directory containing CA certificates',
    )

    def configure(self) -> None:
        """Configure the default SSL context if cert_dir is set.

        Patches ssl.create_default_context and
        ssl._create_default_https_context to load CA certificates from
        cert_dir on every call.
        """
        if self.cert_dir is None:
            return
        import ssl

        cert_dir = str(self.cert_dir)
        _orig = ssl.create_default_context

        def _patched(*args: object, **kwargs: object) -> ssl.SSLContext:
            ctx = _orig(*args, **kwargs)  # type: ignore[arg-type]
            ctx.load_verify_locations(capath=cert_dir)
            return ctx

        ssl.create_default_context = _patched
        ssl._create_default_https_context = _patched


class ValkeyDSN(pydantic.AnyUrl):
    """Valkey DSN settings."""

    _constraints = pydantic.UrlConstraints(
        allowed_schemes=['valkey'],
        default_host='localhost',
        default_port=6379,
        default_path='/0',
        host_required=True,
    )


class Valkey(ConfigFileSettings):
    """Valkey connection settings."""

    model_config = base_settings_config(env_prefix='VALKEY_')
    config_section = 'valkey'
    url: ValkeyDSN = pydantic.Field(
        default=ValkeyDSN('valkey://localhost:6379/0')
    )


class Configuration(pydantic.BaseModel):
    """Root configuration combining all shared settings sections.

    Each section reads its own ``config.toml`` section through
    :class:`ConfigFileSettings`. Config files are checked in this
    priority order:
    1. ./config.toml (project root)
    2. ~/.config/imbi/config.toml (user config)
    3. /etc/imbi/config.toml (system config)

    An environment variable overrides the same key in a config file.

    Example config.toml:
        [postgres]
        url = "postgresql://postgres:secret@db-prod:5432/imbi"

        [auth]
        jwt_secret = "your-secret-here"
        access_token_expire_seconds = 7200
    """

    auth: Auth = pydantic.Field(default_factory=Auth)
    clickhouse: Clickhouse = pydantic.Field(
        default_factory=Clickhouse,
    )
    embeddings: Embeddings = pydantic.Field(
        default_factory=Embeddings,
    )
    plugins: Plugins = pydantic.Field(
        default_factory=Plugins,
    )
    postgres: Postgres = pydantic.Field(
        default_factory=Postgres,
    )
    releases: Releases = pydantic.Field(
        default_factory=Releases,
    )
    ssl: SSL = pydantic.Field(default_factory=SSL)
    valkey: Valkey = pydantic.Field(
        default_factory=Valkey,
    )


def load_config_data() -> dict[str, typing.Any]:
    """Load raw configuration data from config.toml files.

    Checks for config files in priority order:
    1. ./config.toml (project root)
    2. ~/.config/imbi/config.toml (user config)
    3. /etc/imbi/config.toml (system config)

    Returns the merged dictionary without validation.
    :class:`ConfigFileSettings` reads its section from it.

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
            LOGGER.debug('Loading configuration from %s', config_path)
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

    An environment variable overrides the same key in a config file.

    Returns:
        Configuration object with merged settings

    """
    return Configuration()


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


# Module-level singleton for config-secret settings to ensure a stable key
_config_settings: ConfigSecrets | None = None


def get_config_settings() -> ConfigSecrets:
    """Get the singleton ConfigSecrets settings instance.

    This ensures the config encryption key remains stable across requests
    when auto-generated (i.e., when IMBI_CONFIG_ENCRYPTION_KEY is not set in
    env).

    Returns:
        The singleton ConfigSecrets settings instance.

    """
    global _config_settings
    if _config_settings is None:
        _config_settings = ConfigSecrets()
    return _config_settings
