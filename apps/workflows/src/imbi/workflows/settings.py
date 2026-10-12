"""imbi-workflows settings, prefixed ``IMBI_WORKFLOWS_``.

Postgres and the graph come from :mod:`imbi.common.settings`.
"""

import urllib.parse

import pydantic
import pydantic_settings

from imbi.common import settings as common_settings


class Workflows(pydantic_settings.BaseSettings):
    model_config = common_settings.base_settings_config(
        env_prefix='IMBI_WORKFLOWS_'
    )

    api_url: str = pydantic.Field(
        default='http://localhost:8000',
        validation_alias='IMBI_INTERNAL_API_URL',
        description='In-cluster origin of imbi-api',
    )
    api_public_url: str = pydantic.Field(
        default='',
        validation_alias='IMBI_API_URL',
        description="imbi-api's public URL, whose path is its route prefix",
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

    @property
    def api_base_url(self) -> str:
        """Return the imbi-api base URL with its route prefix."""
        prefix = urllib.parse.urlparse(self.api_public_url).path.rstrip('/')
        return self.api_url.rstrip('/') + prefix
