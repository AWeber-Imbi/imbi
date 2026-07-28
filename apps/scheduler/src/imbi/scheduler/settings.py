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
    gateway_url: pydantic.HttpUrl | None = pydantic.Field(
        default=None,
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
    default_timeout: int = pydantic.Field(
        default=120, gt=0, description='Default per-run timeout in seconds'
    )
    default_misfire_grace_time: int = pydantic.Field(
        default=300, gt=0, description='Default misfire grace in seconds'
    )
    run_retention_days: int = pydantic.Field(
        default=90, gt=0, description='ClickHouse TTL for run history'
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
