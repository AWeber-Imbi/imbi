"""Print the environment variable tables of docs/api/configuration.md.

One table per service. The rows come from three sources:

- the fields of every pydantic settings class in `SECTIONS`,
- every `os.environ` / `os.getenv` read in the service's source tree,
  found with `ast`,
- the variables that `container/entrypoint.sh` (`CONTAINER`),
  `container/Caddyfile` and `ui/index.html` read.

A description comes from the row in `SECTIONS` or `CONTAINER`, then
from `DESCRIPTIONS`, then from the field. `NOTES` adds text to the end
of a description. The script writes the
names of variables that have no description to stderr. Paste the
output between the BEGIN and END GENERATED comments of the page.

    uv run python scripts/docs_env_table.py
"""

import ast
import json
import pathlib
import re
import sys
import types
import typing

import pydantic

from imbi.api import settings as api_settings
from imbi.assistant import settings as assistant_settings
from imbi.common import llm
from imbi.common import settings as common_settings
from imbi.common.api import settings as client_settings
from imbi.gateway import actions as gateway_actions
from imbi.scheduler import settings as scheduler_settings
from imbi.slackbot import settings as slackbot_settings
from imbi.workflows import settings as workflows_settings

ROOT = pathlib.Path(__file__).resolve().parent.parent

Row = tuple[str, str, str, str]

# (title, settings classes, source trees scanned for raw reads,
#  extra rows). For imbi-api, `Auth` lists only the fields it adds to
# the shared `Auth`.
SECTIONS: list[tuple[str, list[type], list[str], list[Row]]] = [
    (
        'Shared (imbi-common)',
        [
            common_settings.Auth,
            common_settings.ConfigSecrets,
            common_settings.Postgres,
            common_settings.Clickhouse,
            common_settings.Iggy,
            common_settings.Valkey,
            common_settings.Plugins,
            common_settings.Releases,
            common_settings.Embeddings,
            common_settings.SSL,
            llm.AnthropicSettings,
            client_settings.Settings,
        ],
        ['libraries/common/src'],
        [],
    ),
    (
        'imbi-api',
        [
            api_settings.ServerConfig,
            api_settings.Auth,
            api_settings.Email,
            api_settings.Storage,
            api_settings.IggyConnectors,
            api_settings.InternalServices,
        ],
        ['apps/api/src'],
        [
            (
                'IMBI_GATEWAY_API_TOKEN',
                'str',
                'none',
                '`imbi-api setup` and `setup-service-accounts` store this '
                'value as the API key of the `imbi-gateway` service account. '
                'Unset, they generate one and print it.',
            ),
            (
                'IMBI_SCHEDULER_SA_CLIENT_ID',
                'str',
                'none',
                '`setup` stores this pair as the client credential of the '
                '`imbi-scheduler` service account. Unset, it generates a '
                'pair and prints it.',
            ),
            (
                'IMBI_SCHEDULER_SA_CLIENT_SECRET',
                'str',
                'none',
                'See `IMBI_SCHEDULER_SA_CLIENT_ID`.',
            ),
            (
                'IMBI_WORKFLOWS_SA_CLIENT_ID',
                'str',
                'none',
                'The same, for the `imbi-workflows` service account.',
            ),
            (
                'IMBI_WORKFLOWS_SA_CLIENT_SECRET',
                'str',
                'none',
                'See `IMBI_WORKFLOWS_SA_CLIENT_ID`.',
            ),
        ],
    ),
    (
        'imbi-assistant',
        [assistant_settings.Assistant],
        ['apps/assistant/src'],
        [],
    ),
    (
        'imbi-gateway',
        [gateway_actions.ActionSettings],
        ['apps/gateway/src'],
        [],
    ),
    (
        'imbi-mcp',
        [],
        ['apps/mcp/src'],
        [
            (
                'IMBI_INTERNAL_API_URL',
                'str',
                '`http://localhost:8000`',
                'In-cluster origin of imbi-api (`--api-url`)',
            ),
            (
                'IMBI_MCP_PUBLIC_URL',
                'str',
                'none',
                'Public base URL of the host in front of imbi-mcp, without '
                'the `/mcp` path (`--public-url`). OAuth is on only when '
                'this and `IMBI_MCP_AUTH_SERVER_URL` are both set.',
            ),
            (
                'IMBI_MCP_AUTH_SERVER_URL',
                'str',
                'none',
                'Imbi OAuth issuer URL, for example `https://imbi.example.com`'
                ' (`--auth-server-url`)',
            ),
        ],
    ),
    (
        'imbi-scheduler',
        [scheduler_settings.Scheduler],
        ['apps/scheduler/src'],
        [],
    ),
    (
        'imbi-slackbot',
        [slackbot_settings.Slackbot],
        ['apps/slackbot/src'],
        [],
    ),
    (
        'imbi-workflows',
        [workflows_settings.Workflows],
        ['apps/workflows/src'],
        [],
    ),
    ('imbi-harness (agent runner pods)', [], ['apps/harness/src'], []),
]

# What container/entrypoint.sh reads. The Caddyfile and ui/index.html
# rows are parsed from the files.
CONTAINER: list[Row] = [
    (
        'IMBI_SERVICE',
        'str',
        '`all`',
        'Service the image runs: `all`, `api`, `assistant`, `gateway`, '
        '`mcp`, `scheduler`, `slackbot`, `ui`, `workflows`',
    ),
    (
        'SENTRY_AUTH_TOKEN',
        'str',
        'none',
        'With `SENTRY_ORG` and `SENTRY_PROJECT`, the `all` and `ui` modes '
        'upload the UI source maps to Sentry at start',
    ),
    ('SENTRY_ORG', 'str', 'none', 'Sentry organization for the upload'),
    ('SENTRY_PROJECT', 'str', 'none', 'Sentry project for the upload'),
    ('SENTRY_RELEASE', 'str', 'none', 'Sentry release for the upload'),
    ('SENTRY_URL', 'str', 'none', 'Sentry server URL for the upload'),
]

DESCRIPTIONS: dict[str, str] = {
    # Shared
    'CLICKHOUSE_CLUSTER_NAME': 'Cluster name. When set, `setup-clickhouse` '
    'creates the schema `ON CLUSTER <name>` with `Replicated` table '
    'engines. Leave unset for one node.',
    'IMBI_AUTH_JWT_SECRET': 'Secret that signs access and refresh tokens. '
    'Required when `ENVIRONMENT` is not `development`.',
    'IMBI_AUTH_JWT_ALGORITHM': 'JWT signing algorithm',
    'IMBI_AUTH_ACCESS_TOKEN_EXPIRE_SECONDS': 'Access token lifetime',
    'IMBI_AUTH_REFRESH_TOKEN_EXPIRE_SECONDS': 'Refresh token lifetime. '
    'Refresh tokens rotate on each use.',
    'IMBI_AUTH_LAST_USED_THROTTLE_SECONDS': 'Minimum seconds between two '
    'writes of the `last_used` time of an API key. `0` writes on each '
    'request.',
    'IMBI_AUTH_ENCRYPTION_KEY': 'Fernet key that encrypts OAuth tokens and '
    'client secrets. Required when `ENVIRONMENT` is not `development`; '
    'generated per process in development.',
    'IMBI_CONFIG_ENCRYPTION_KEY': 'Fernet key that encrypts configuration '
    'secrets, for example AI provider keys and MCP server credentials. '
    'Required when `ENVIRONMENT` is not `development`; generated per '
    'process in development.',
    'POSTGRES_URL': 'PostgreSQL DSN',
    'POSTGRES_GRAPH_NAME': 'Apache AGE graph name',
    'POSTGRES_MIN_POOL_SIZE': 'Minimum connection pool size',
    'POSTGRES_MAX_POOL_SIZE': 'Maximum connection pool size',
    'CLICKHOUSE_URL': 'ClickHouse DSN. Credentials in the URL are used.',
    'CLICKHOUSE_CONNECT_TIMEOUT': 'Connection timeout in seconds',
    'CLICKHOUSE_MAX_CONNECT_ATTEMPTS': 'Connection attempts at startup',
    'IGGY_URL': 'Apache Iggy connection string. The scheme selects the '
    'transport: `iggy`, `iggy+tcp`, `iggy+quic`, `iggy+http`, `iggy+ws`.',
    'IGGY_CONNECT_TIMEOUT': 'Connection timeout in seconds',
    'IGGY_MAX_CONNECT_ATTEMPTS': 'Connection attempts at startup',
    'VALKEY_URL': 'Valkey DSN',
    'IMBI_PLUGINS': 'Comma-separated `package.module:Attr` paths of plugins '
    'that do not use the `imbi_plugin_*` package name',
    'IMBI_PLUGINS_DISABLED': 'Comma-separated plugin slugs not to load',
    'IMBI_RELEASES_VERSION_FORMAT': 'Version format that `Release.version` '
    'must match',
    'EMBEDDINGS_ENABLED': 'Generate embeddings for vector search',
    'EMBEDDINGS_DEFAULT_MODEL': 'Key in `EMBEDDINGS_MODELS` to use',
    'EMBEDDINGS_MODELS': 'JSON map of model key to '
    '`{fastembed_id, dimensions}`',
    'SSL_CERT_DIR': 'Directory of CA certificates that every TLS context '
    'loads, in addition to the defaults',
    'ANTHROPIC_API_KEY': 'Anthropic API key',
    'IMBI_ANTHROPIC_DEFAULT_MODEL': 'Model for structured completions, for '
    'example release-note drafts',
    'IMBI_ANTHROPIC_TIMEOUT': 'Request timeout in seconds',
    'IMBI_ANTHROPIC_MAX_RETRIES': 'Retries for each request',
    'IMBI_CLIENT_API_BASE_URL': 'Imbi API URL for the `imbi.common.api` '
    'client',
    'IMBI_CLIENT_API_TOKEN': 'Bearer token for the `imbi.common.api` client',
    'IMBI_CLIENT_USER_AGENT': '`User-Agent` for the `imbi.common.api` '
    'client. Unset: `imbi-common/<version>`.',
    'ENVIRONMENT': 'Anything other than `development` makes the auth and '
    'config encryption keys required and turns off the Mailpit '
    'auto-configuration. The status pages show it.',
    'SENTRY_DSN': 'Sentry DSN. Unset: Sentry is off.',
    'SENTRY_TRACES_SAMPLE_RATE': 'Trace sample rate, `0.0` to `1.0`. '
    '`/status` requests are never sampled.',
    'SERVICE': 'Server name sent to Sentry',
    'IMBI_PROMPT_WORKERS': 'Prompt render worker processes per service '
    'process',
    'IMBI_PROMPT_WORKER_MAX_RENDERS': 'Renders before a worker is replaced',
    'IMBI_PROMPT_WORKER_MEMORY_MB': 'Address space in MiB that a worker can '
    'add after it starts. Linux only.',
    'IMBI_PROMPT_RENDER_INPROCESS': '`true` renders in the service process. '
    'For debugging only: it removes the isolation.',
    'IMBI_RELOAD_DIRS': 'Extra directories to watch with `serve --dev`, '
    'separated by the OS path separator',
    # imbi-api
    'IMBI_API_ENVIRONMENT': 'Anything other than `development` sets the '
    '`Secure` flag on the auth cookies',
    'IMBI_API_HOST': 'Host of the fallback public URL when `IMBI_API_URL` '
    'is unset. It does not set the bind address: use `serve --host`.',
    'IMBI_API_PORT': 'Port of the fallback public URL. A `tcp://ip:port` '
    'value from Kubernetes service discovery is read as its port.',
    'IMBI_API_CORS_ALLOWED_ORIGINS': 'JSON array of allowed CORS origins. '
    'Also the trusted hosts for per-request OAuth URLs.',
    'IMBI_API_FORWARDED_ALLOW_IPS': 'Comma-separated proxy IPs (or `*`) '
    'whose `X-Forwarded-*` headers are trusted. Empty: off.',
    'IMBI_API_URL': 'Public imbi-api URL with its path prefix, for example '
    '`https://imbi.example.com/api`. The path is the API route prefix.',
    'IMBI_UI_URL': 'Public UI URL, no path. Used for deep links.',
    'IMBI_AUTH_PASSWORD_MIN_LENGTH': 'Minimum password length',
    'IMBI_AUTH_PASSWORD_REQUIRE_UPPERCASE': 'Require an uppercase letter',
    'IMBI_AUTH_PASSWORD_REQUIRE_LOWERCASE': 'Require a lowercase letter',
    'IMBI_AUTH_PASSWORD_REQUIRE_DIGIT': 'Require a digit',
    'IMBI_AUTH_PASSWORD_REQUIRE_SPECIAL': 'Require a special character',
    'IMBI_AUTH_API_KEY_MAX_LIFETIME_DAYS': 'Maximum lifetime of an API key or '
    'client credential',
    'IMBI_AUTH_MFA_ISSUER_NAME': 'Issuer name in authenticator apps',
    'IMBI_AUTH_MFA_TOTP_PERIOD': 'TOTP time step in seconds',
    'IMBI_AUTH_MFA_TOTP_DIGITS': 'TOTP code length',
    'IMBI_AUTH_RATE_LIMIT_LOGIN': 'Password login rate',
    'IMBI_AUTH_RATE_LIMIT_TOKEN_REFRESH': 'Token refresh rate',
    'IMBI_AUTH_RATE_LIMIT_OAUTH_INIT': 'OAuth flow start rate',
    'IMBI_AUTH_RATE_LIMIT_API_KEY': 'API key request rate',
    'IMBI_AUTH_OAUTH_AUTO_LINK_BY_EMAIL': 'Link an SSO sign-in to the user '
    'with the same email',
    'IMBI_AUTH_OAUTH_AUTO_CREATE_USERS': 'Create a user at the first SSO '
    'sign-in',
    'IMBI_AUTH_DCR_ENABLED': 'Let OAuth clients register at '
    '`/auth/register` (RFC 7591)',
    'IMBI_EMAIL_ENABLED': 'Send email. `false` stops all email.',
    'IMBI_EMAIL_DRY_RUN': 'Log messages, do not send them',
    'IMBI_EMAIL_SMTP_HOST': 'SMTP host',
    'IMBI_EMAIL_SMTP_PORT': 'SMTP port',
    'IMBI_EMAIL_SMTP_USE_TLS': 'Use STARTTLS',
    'IMBI_EMAIL_SMTP_USE_SSL': 'Use implicit TLS (usually port 465)',
    'IMBI_EMAIL_SMTP_USERNAME': 'SMTP user name',
    'IMBI_EMAIL_SMTP_PASSWORD': 'SMTP password',
    'IMBI_EMAIL_SMTP_TIMEOUT': 'SMTP timeout in seconds',
    'IMBI_EMAIL_FROM_EMAIL': 'Sender address',
    'IMBI_EMAIL_FROM_NAME': 'Sender name',
    'IMBI_EMAIL_REPLY_TO': '`Reply-To` address',
    'IMBI_EMAIL_MAX_RETRIES': 'Send attempts after the first',
    'IMBI_EMAIL_INITIAL_RETRY_DELAY': 'First retry delay in seconds',
    'IMBI_EMAIL_MAX_RETRY_DELAY': 'Maximum retry delay in seconds',
    'IMBI_EMAIL_RETRY_BACKOFF_FACTOR': 'Retry delay multiplier',
    'MAILPIT_SMTP_PORT': 'In development, with the default SMTP host and '
    'port, use this port and no TLS (Mailpit)',
    'S3_ENDPOINT_URL': 'S3-compatible endpoint. Unset: AWS S3.',
    'S3_ACCESS_KEY': 'Access key ID. Unset: the default AWS credential chain.',
    'S3_SECRET_KEY': 'Secret access key',
    'S3_BUCKET': 'Bucket name',
    'S3_REGION': 'AWS region',
    'S3_CREATE_BUCKET_ON_INIT': 'Create the bucket at startup if it does not '
    'exist',
    'S3_MAX_FILE_SIZE': 'Upload size limit in bytes',
    'S3_ALLOWED_CONTENT_TYPES': 'JSON array of MIME types accepted for upload',
    'S3_THUMBNAIL_MAX_SIZE': 'Largest thumbnail side in pixels',
    'S3_THUMBNAIL_QUALITY': 'WEBP quality of thumbnails, 0 to 100',
    'IMBI_IGGY_CONNECTORS_API_KEYS': 'Comma-separated bearer keys of the '
    'iggy-connect runtime. Empty: the connector config endpoint answers '
    '503.',
    'IMBI_INTERNAL_ASSISTANT_URL': 'Internal URL of imbi-assistant, for the '
    'status dashboard. Empty: not probed.',
    'IMBI_INTERNAL_GATEWAY_URL': 'Internal URL of imbi-gateway, for the '
    'status dashboard',
    'IMBI_INTERNAL_MCP_URL': 'Internal URL of imbi-mcp, for the status '
    'dashboard',
    'IMBI_INTERNAL_SCHEDULER_URL': 'Internal URL of imbi-scheduler, for the '
    'status dashboard',
    'IMBI_INTERNAL_SLACKBOT_URL': 'Internal URL of imbi-slackbot, for the '
    'status dashboard',
    'IMBI_INTERNAL_WORKFLOWS_URL': 'Internal URL of imbi-workflows, for the '
    'status dashboard',
    'IMBI_SECRETS_AWS_ENDPOINT_URL': 'AWS endpoint of the secrets broker, '
    'for LocalStack. Unset: AWS.',
    'IMBI_SECRETS_GITHUB_GHES_HOSTS': 'Comma-separated GitHub Enterprise '
    'Server hosts that a GitHub App binding can use',
    'IMBI_PLUGIN_CACHE_TTL': 'Seconds that Valkey keeps the configuration '
    'key list of a project',
    'IMBI_PLUGIN_TIMEOUT_SECONDS': 'Timeout of one plugin call in seconds',
    'IMBI_PLUGINS_INSTALL_ENABLED': '`false` turns off plugin install at '
    'runtime',
    'IMBI_PLUGINS_INSTALL_TIMEOUT': 'Timeout of one plugin install in seconds',
    'IMBI_PLUGINS_INDEX_URL': 'Package index for plugin installs',
    'IMBI_OAUTH_ALLOW_INSECURE_URLS': '`true` allows `http://localhost` '
    'OAuth provider URLs. Development only.',
    # Other services
    'IMBI_INTERNAL_API_URL': 'In-cluster origin of imbi-api',
    'IMBI_INTERNAL_UI_URL': 'In-cluster UI URL for `llms.txt`. Unset: '
    '`IMBI_UI_URL`.',
    'IMBI_ASSISTANT_URL': 'Public assistant URL. Its path is the route '
    'prefix.',
    'IMBI_ASSISTANT_ENABLED': 'Turn the assistant on. `ANTHROPIC_API_KEY` '
    'turns it on too.',
    'IMBI_ASSISTANT_MODEL': 'Claude model',
    'IMBI_ASSISTANT_MAX_TOKENS': 'Maximum response tokens',
    'IMBI_ASSISTANT_MAX_CONVERSATION_TURNS': 'Maximum turns in one '
    'conversation',
    'IMBI_ASSISTANT_MAX_TOOL_ROUNDS': 'Maximum tool rounds for one message',
    'IMBI_ASSISTANT_MAX_TOOL_RESULT_CHARS': 'Longer tool results are cut',
    'IMBI_ASSISTANT_SYSTEM_PROMPT': 'Jinja system prompt that replaces the '
    'CMS and packaged prompts',
    'IMBI_ASSISTANT_PROMPT_REF': 'Prompt CMS reference of the system prompt',
    'IMBI_GATEWAY_API_TOKEN': 'API key of the `imbi-gateway` service '
    'account. Required.',
    'IMBI_SCHEDULER_SCHEMA': 'Postgres schema of the task tables',
    'IMBI_SCHEDULER_API_PREFIX': 'Route prefix of the task and run routes',
    'IMBI_SCHEDULER_GATEWAY_URL': 'imbi-gateway URL for gateway targets',
    'IMBI_SCHEDULER_SA_SLUG': 'Slug of the scheduler service account',
    'IMBI_SCHEDULER_SA_CLIENT_ID': 'Client ID of the scheduler service '
    'account',
    'IMBI_SCHEDULER_SA_CLIENT_SECRET': 'Its client secret',
    'IMBI_SCHEDULER_MAX_CONCURRENT_RUNS': 'Active runs per process',
    'IMBI_SCHEDULER_CONSECUTIVE_SKIPS_LIMIT': 'Skipped runs in a row before '
    'a task is disabled',
    'IMBI_SCHEDULER_CONSECUTIVE_NO_EFFECT_LIMIT': 'No-effect runs in a row '
    'before a warning',
    'IMBI_SCHEDULER_POLL_INTERVAL': 'Maximum seconds between polls',
    'IMBI_SLACKBOT_ENABLED': 'Turn the bot on. `ANTHROPIC_API_KEY` and both '
    'Slack tokens turn it on too.',
    'IMBI_SLACKBOT_MODEL': 'Claude model',
    'IMBI_SLACKBOT_MAX_TOKENS': 'Maximum response tokens',
    'IMBI_SLACKBOT_MAX_TOOL_ROUNDS': 'Maximum tool rounds for one message',
    'IMBI_SLACKBOT_MAX_TOOL_RESULT_CHARS': 'Longer tool results are '
    'replaced with an error',
    'IMBI_SLACKBOT_MAX_THREAD_MESSAGES': 'Thread messages sent to Claude as '
    'context',
    'IMBI_SLACKBOT_PROGRESS_UPDATES': 'Post and update a status message '
    'while a request runs',
    'IMBI_SLACKBOT_STATUS_EMOJI': 'Reaction emoji while a request runs',
    'IMBI_SLACKBOT_IDENTITY_CACHE_TTL': 'Seconds to cache a Slack user to '
    'Imbi user match',
    'IMBI_SLACKBOT_SYSTEM_PROMPT': 'Jinja system prompt that replaces the '
    'CMS and packaged prompts',
    'IMBI_SLACKBOT_PROMPT_REF': 'Prompt CMS reference of the system prompt',
    'SLACK_BOT_TOKEN': 'Slack bot token (`xoxb-`)',
    'SLACK_APP_TOKEN': 'Slack app-level token for Socket Mode (`xapp-`)',
    'IMBI_WORKFLOWS_SA_CLIENT_ID': 'Client ID of the `imbi-workflows` '
    'service account. Deploy and rollback steps fail without it.',
    'IMBI_WORKFLOWS_SA_CLIENT_SECRET': 'Its client secret',
    'IMBI_HARNESS_EXTRA_CA': 'PEM file of extra CA certificates',
    'IMBI_HARNESS_POOL': 'Runner pool name',
    'IMBI_HARNESS_MODEL': 'Model override for the runner',
    'IMBI_HARNESS_MCP_URL': 'imbi-mcp URL that agents use',
    'IMBI_HARNESS_END_OF_CHAIN': '`delete_pod` or `exit` at the end of a '
    'chain',
    'IMBI_HARNESS_IDLE_EXIT_SECONDS': 'Exit after this many idle seconds. '
    'Empty or `0`: never.',
    'HOSTNAME': 'Runner instance name',
    'POD_NAME': 'Pod name, from the Kubernetes downward API',
    'POD_NAMESPACE': 'Pod namespace, from the Kubernetes downward API',
    # Container
    'IMBI_API_UPSTREAM': 'Caddy upstream of imbi-api (`ui` mode)',
    'IMBI_ASSISTANT_UPSTREAM': 'Caddy upstream of imbi-assistant',
    'IMBI_GATEWAY_UPSTREAM': 'Caddy upstream of imbi-gateway',
    'IMBI_SCHEDULER_UPSTREAM': 'Caddy upstream of imbi-scheduler',
    'IMBI_MCP_UPSTREAM': 'Caddy upstream of imbi-mcp',
    'SERVE_SOURCE_MAPS': '`true` serves the UI `*.map` files. Otherwise '
    'Caddy answers 404.',
    'VITE_API_URL': 'API URL that Caddy writes into `index.html` at request '
    'time. The UI does not start without it.',
    'VITE_SENTRY_DSN': 'Sentry DSN of the UI, written into `index.html`',
}

_NOT_READ = '. Defined but not read yet ([#463](https://github.com/AWeber-Imbi/imbi/issues/463)).'
NOTES: dict[str, str] = dict.fromkeys(
    (
        'IMBI_AUTH_PASSWORD_MIN_LENGTH',
        'IMBI_AUTH_PASSWORD_REQUIRE_UPPERCASE',
        'IMBI_AUTH_PASSWORD_REQUIRE_LOWERCASE',
        'IMBI_AUTH_PASSWORD_REQUIRE_DIGIT',
        'IMBI_AUTH_PASSWORD_REQUIRE_SPECIAL',
        'IMBI_AUTH_RATE_LIMIT_LOGIN',
        'IMBI_AUTH_RATE_LIMIT_TOKEN_REFRESH',
        'IMBI_AUTH_RATE_LIMIT_OAUTH_INIT',
        'IMBI_AUTH_RATE_LIMIT_API_KEY',
    ),
    _NOT_READ,
)

_missing: list[str] = []


def _fmt_default(value: object) -> str:
    if value is None:
        return 'none'
    if isinstance(value, pydantic.BaseModel):
        value = value.model_dump()
    if isinstance(value, (dict, list)):
        value = json.dumps(value, default=lambda v: v.model_dump())
    if isinstance(value, bool):
        value = str(value).lower()
    if isinstance(value, pydantic.SecretStr):
        value = value.get_secret_value()
    text = str(value) if not isinstance(value, str) else value
    return f'`{text}`' if text else "`''`"


def _fmt_type(annotation: object) -> str:
    if typing.get_origin(annotation) is typing.Literal:
        return ' or '.join(f'`{a}`' for a in typing.get_args(annotation))
    if isinstance(annotation, type) and not typing.get_args(annotation):
        return annotation.__name__
    if isinstance(annotation, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return ' \\| '.join(_fmt_type(a) for a in args)
    text = str(annotation).replace('typing.', '')
    return re.sub(r'[\w.]+\.(\w+)', r'\1', text)


def _row(name: str, type_: str, default: str, text: str) -> str:
    if not text:
        _missing.append(name)
    text += NOTES.get(name, '')
    return f'| `{name}` | {type_} | {default} | {text} |'


def _env_name(cls: type[pydantic.BaseModel], name: str, field: object) -> str:
    alias = field.validation_alias or field.alias  # type: ignore[attr-defined]
    if isinstance(alias, str):
        return alias.upper()
    return (cls.model_config.get('env_prefix', '') + name).upper()


def _settings_rows(cls: type[pydantic.BaseModel], skip: set[str]) -> list:
    rows = []
    for name, field in cls.model_fields.items():
        if name in skip:
            continue
        if field.is_required():
            default = 'required'
        elif field.default_factory is not None:
            first, second = field.default_factory(), field.default_factory()
            default = 'generated' if first != second else _fmt_default(first)
        else:
            default = _fmt_default(field.default)
        env = _env_name(cls, name, field)
        text = DESCRIPTIONS.get(env) or field.description or ''
        rows.append((env, _fmt_type(field.annotation), default, text))
    return rows


_ENV_FUNCS = {'_int_setting', '_seconds'}
_ENV_NAME = re.compile(r'^[A-Z][A-Z0-9_]+$')


def _is_environ(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == 'environ'
        and isinstance(node.value, ast.Name)
        and node.value.id == 'os'
    )


def _env_reads(tree: ast.Module) -> list[tuple[str, object]]:
    """Return (name, default) for each environment read in *tree*."""
    consts = {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    def value(node: ast.AST | None) -> object:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return consts.get(node.id)
        return None

    reads = []
    for node in ast.walk(tree):
        args: list[ast.expr] = []
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and (
                    (func.attr == 'get' and _is_environ(func.value))
                    or (
                        func.attr == 'getenv'
                        and isinstance(func.value, ast.Name)
                        and func.value.id == 'os'
                    )
                )
            ) or (isinstance(func, ast.Name) and func.id in _ENV_FUNCS):
                args = node.args
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Load)
            and _is_environ(node.value)
        ):
            args = [node.slice]
        if not args:
            continue
        name = value(args[0])
        if isinstance(name, str) and _ENV_NAME.match(name):
            reads.append((name, value(args[1]) if len(args) > 1 else None))
    return reads


def _raw_type(default: object) -> str:
    if isinstance(default, str) and default.lower() in {'true', 'false'}:
        return 'bool'
    for cast in (int, float):
        try:
            cast(default)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            continue
        return cast.__name__
    return 'str'


def _raw_rows(trees: list[str], seen: set[str]) -> list:
    rows = []
    for tree in trees:
        for path in sorted((ROOT / tree).rglob('*.py')):
            if 'tests' in path.parts:
                continue
            module = ast.parse(path.read_text())
            for name, default in _env_reads(module):
                if name in seen:
                    continue
                seen.add(name)
                rows.append(
                    (
                        name,
                        _raw_type(default),
                        _fmt_default(default),
                        DESCRIPTIONS.get(name, ''),
                    )
                )
    return rows


def _container_rows() -> list:
    rows = list(CONTAINER)
    seen = {row[0] for row in rows}
    caddy = (ROOT / 'container' / 'Caddyfile').read_text()
    for name, default in re.findall(r'\{\$(\w+):([^}]*)\}', caddy):
        if name not in seen:
            seen.add(name)
            rows.append(
                (name, 'str', f'`{default}`', DESCRIPTIONS.get(name, ''))
            )
    for name in re.findall(r'\{env\.(\w+)\}', caddy):
        if name not in seen:
            seen.add(name)
            rows.append((name, 'str', 'none', DESCRIPTIONS.get(name, '')))
    index = (ROOT / 'ui' / 'index.html').read_text()
    for name in re.findall(r'\{\{env "(\w+)"\}\}', index):
        if name not in seen:
            seen.add(name)
            rows.append((name, 'str', 'none', DESCRIPTIONS.get(name, '')))
    return rows


def _table(title: str, rows: list) -> list[str]:
    lines = [
        f'### {title}',
        '',
        '| Variable | Type | Default | Description |',
        '|---|---|---|---|',
    ]
    lines.extend(_row(*row) for row in rows)
    lines.append('')
    return lines


def main() -> None:
    common_auth = set(common_settings.Auth.model_fields)
    shared: set[str] = set()
    lines: list[str] = []
    for title, classes, trees, extra in SECTIONS:
        rows = []
        for cls in classes:
            skip = common_auth if cls is api_settings.Auth else set()
            rows.extend(_settings_rows(cls, skip))
        seen = {row[0] for row in rows}
        rows.extend(row for row in extra if row[0] not in seen)
        seen.update(row[0] for row in extra)
        rows.extend(_raw_rows(trees, seen | shared))
        shared = shared or {row[0] for row in rows}
        lines.extend(_table(title, rows))
    lines.extend(
        _table('Container (entrypoint, Caddy, UI)', _container_rows())
    )
    sys.stdout.write('\n'.join(lines).rstrip('\n') + '\n')
    if _missing:
        sys.stderr.write('No description: ' + ', '.join(_missing) + '\n')


if __name__ == '__main__':
    main()
