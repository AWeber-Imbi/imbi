"""Scheduler-specific settings.

Shared settings (Postgres, ClickHouse, auth) come from
:mod:`imbi.common.settings`; only what the scheduler adds lives here.
"""

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
    # Where the scheduler reaches imbi-api. Distinct from ``IMBI_API_URL``
    # (the API's *public* URL): this is the in-cluster address used for
    # service-to-service calls, the same var imbi-assistant and imbi-mcp read.
    api_url: str = pydantic.Field(
        default='http://localhost:8000',
        validation_alias='IMBI_INTERNAL_API_URL',
        description='imbi-api base URL for api targets and token requests',
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
    sa_client_secret: str | None = pydantic.Field(
        default=None, description='Service account client credential secret'
    )
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
        description='Consecutive no-effect runs before the owner is notified',
    )
    poll_interval: int = pydantic.Field(
        default=30,
        gt=0,
        description=(
            'Upper bound in seconds on the engine sleep. A missed NOTIFY '
            'costs latency, not a missed run, because the loop re-polls.'
        ),
    )
