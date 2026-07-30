"""Scheduler-specific settings.

Shared settings (Postgres, ClickHouse, auth) come from
:mod:`imbi.common.settings`; only what the scheduler adds lives here.
"""

import urllib.parse

import pydantic
import pydantic_settings

from imbi.common import settings as common_settings


class Scheduler(pydantic_settings.BaseSettings):
    """Scheduler configuration, prefixed ``IMBI_SCHEDULER_``."""

    model_config = common_settings.base_settings_config(
        env_prefix='IMBI_SCHEDULER_'
    )

    schema_name: str = pydantic.Field(
        default='scheduler',
        alias='IMBI_SCHEDULER_SCHEMA',
        description='Postgres schema holding task definitions',
    )
    # The path every route below `/status` is mounted under, per PRD §10.
    # Configurable rather than a constant so a deployment can relocate the API
    # without a code change, which is what imbi-api and imbi-assistant both
    # allow. Unlike theirs this is the prefix itself, not a public URL to
    # derive one from: the Caddyfile mounts this service with `handle_path`,
    # which strips `/scheduler` before the request arrives, so the path the
    # app serves is deliberately not the path a caller used.
    api_prefix: str = pydantic.Field(
        default='/api',
        description='Path prefix for the task and run routes',
    )
    # Where the scheduler reaches imbi-api. Distinct from ``IMBI_API_URL``
    # (the API's *public* URL): this is the in-cluster address used for
    # service-to-service calls, the same var imbi-assistant and imbi-mcp read.
    api_url: str = pydantic.Field(
        default='http://localhost:8000',
        validation_alias='IMBI_INTERNAL_API_URL',
        description='imbi-api base URL for api targets and token requests',
    )
    # imbi-api mounts every router under the path component of its *public*
    # URL (``imbi.api.settings.Server.api_prefix``), while
    # ``IMBI_INTERNAL_API_URL`` is a bare origin. The prefix therefore has to
    # be re-derived here — see :attr:`api_base_url`.
    api_public_url: str = pydantic.Field(
        default='',
        validation_alias='IMBI_API_URL',
        description="imbi-api's public URL, whose path is its route prefix",
    )
    gateway_url: str = pydantic.Field(
        default='http://localhost:8003',
        description='imbi-gateway base URL for gateway targets',
    )
    sa_slug: str = pydantic.Field(
        default='imbi-scheduler',
        description="The scheduler's own service account slug",
    )
    sa_client_id: str | None = pydantic.Field(
        default=None, description='Service account client credential id'
    )
    # `SecretStr`, so the value masks itself in `repr`, `str`, and any
    # `model_dump` that reaches a log line or an error page. Read it with
    # `.get_secret_value()` -- see `identity.ServiceAccountToken.refresh`,
    # which is the one place that has to send it.
    sa_client_secret: pydantic.SecretStr | None = pydantic.Field(
        default=None, description='Service account client credential secret'
    )
    # Deliberately unrelated to ``POSTGRES_MAX_POOL_SIZE`` (default 10, of
    # which the engine's two LISTEN connections hold one each for the life of
    # the process). A firing takes a connection only for short round trips --
    # claiming the lease, the pre-flight cancel check, releasing it -- and
    # holds none across the HTTP call itself, because neither the executor nor
    # the identity resolver touches Postgres. So 20 concurrent runs against 8
    # free connections queues briefly on checkout rather than deadlocking, and
    # capping this at the pool size would throttle throughput for no reason.
    max_concurrent_runs: int = pydantic.Field(
        default=20, gt=0, description='Per-process ceiling on active runs'
    )
    consecutive_skips_limit: int = pydantic.Field(
        default=5,
        gt=0,
        description='Consecutive skipped runs before a task is disabled',
    )
    consecutive_no_effect_limit: int = pydantic.Field(
        default=5,
        gt=0,
        description='Consecutive no-effect runs before a warning is logged',
    )
    poll_interval: int = pydantic.Field(
        default=30,
        gt=0,
        description=(
            'Upper bound in seconds on the engine sleep. A missed NOTIFY '
            'costs latency, not a missed run, because the loop re-polls.'
        ),
    )

    @pydantic.field_validator('api_prefix')
    @classmethod
    def _validate_api_prefix(cls, value: str) -> str:
        """Require an absolute path, or nothing at all.

        A prefix like ``api`` would mount the routes at ``apitasks``; failing
        at startup beats serving a route table nobody can reach.
        """
        trimmed = value.rstrip('/')
        if trimmed and not trimmed.startswith('/'):
            raise ValueError(
                f'must be an absolute path (e.g. /api); got {value!r}'
            )
        return trimmed

    @property
    def api_base_url(self) -> str:
        """Return the in-cluster imbi-api base URL, prefix included.

        Every path the scheduler builds — the token endpoint and every `api`
        target — must be joined onto this rather than onto
        :attr:`api_url`: reaching ``http://imbi-api:8000/auth/token`` when the
        deployment mounts the API at ``/api`` is a 404, which turns every run
        into a skip.
        """
        prefix = urllib.parse.urlparse(self.api_public_url).path.rstrip('/')
        return self.api_url.rstrip('/') + prefix


_settings: Scheduler | None = None


def get_settings() -> Scheduler:
    """Return the process-wide Scheduler settings.

    Constructing ``Scheduler()`` re-reads the environment and revalidates
    every field, so anything on a request path wants this instead of a fresh
    instance. Mirrors ``imbi.common.settings.get_auth_settings``.

    Not for code that reads :attr:`Scheduler.schema_name`: the store is
    constructed against whatever schema the environment names at the time, and
    a cached instance would pin the first one seen.
    """
    global _settings  # noqa: PLW0603 -- singleton, as imbi-common does it
    if _settings is None:
        _settings = Scheduler()
    return _settings
