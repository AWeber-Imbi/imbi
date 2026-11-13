"""imbi-workflows settings, prefixed ``IMBI_WORKFLOWS_``.

Postgres and the graph come from :mod:`imbi.common.settings`.
"""

import pydantic

from imbi.common import settings as common_settings


class Workflows(common_settings.InternalApi):
    model_config = common_settings.base_settings_config(
        env_prefix='IMBI_WORKFLOWS_'
    )

    sa_client_id: str | None = None
    sa_client_secret: pydantic.SecretStr | None = None
    workers: int = pydantic.Field(
        default=10, gt=0, description='Runs worked on at the same time'
    )
    poll_interval: float = pydantic.Field(
        default=10.0,
        gt=0,
        description='Upper bound in seconds on the sleep between polls. '
        'A lost NOTIFY costs latency, not a run.',
    )
    lease_seconds: int = pydantic.Field(
        default=300,
        gt=30,
        description='How long a claim lasts. One step call must end '
        'inside it.',
    )
    deploy_poll_seconds: int = pydantic.Field(
        default=15, gt=0, description='Seconds between deployment polls'
    )
    agent_poll_seconds: int = pydantic.Field(
        default=30, gt=0, description='Seconds between agent task polls'
    )
    scheduler_url: str = pydantic.Field(
        default='http://localhost:8005/api',
        description="imbi-scheduler's task API, with its route prefix",
    )
    reconcile_interval: float = pydantic.Field(
        default=300.0,
        gt=0,
        description='Seconds between passes of the trigger reconciler. '
        'imbi-api also wakes it after each activation and pause.',
    )
    script_max_memory_mb: int = pydantic.Field(
        default=64, gt=0, description='Memory one script step can use, in MiB'
    )
    script_max_seconds: float = pydantic.Field(
        default=5.0,
        gt=0,
        description='Seconds one script step can run. A step timeout that '
        'is shorter wins.',
    )
