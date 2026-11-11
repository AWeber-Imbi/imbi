"""Webhook action: sync the project's Sentry issue-count facts."""

import logging
import typing
import urllib.parse

import pydantic
import pydantic_settings

from imbi.common.api import client as api_client
from imbi.common.plugins import base as plugin_base
from imbi.plugins.sentry import client

LOGGER = logging.getLogger(__name__)


class _ImbiSettings(pydantic_settings.BaseSettings):
    """Imbi API connection settings, the same environment variables the
    gateway's own actions read (see the SonarQube plugin)."""

    model_config = {'env_prefix': 'IMBI_GATEWAY_'}

    imbi_url: pydantic.HttpUrl = pydantic.Field(
        default=pydantic.HttpUrl('http://localhost:8000'),
        validation_alias='IMBI_INTERNAL_API_URL',
    )
    # imbi-api mounts its routers under the path of its public URL.
    api_public_url: str = pydantic.Field(
        default='', validation_alias='IMBI_API_URL'
    )
    api_token: str

    @property
    def api_base_url(self) -> str:
        prefix = urllib.parse.urlparse(self.api_public_url).path.rstrip('/')
        return str(self.imbi_url).rstrip('/') + prefix


class SyncIssueCountsConfig(pydantic.BaseModel):
    """No settings: the facts and searches are Integration options."""


async def sync_issue_counts(
    *,
    ctx: plugin_base.PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: SyncIssueCountsConfig,
    event: object,
) -> None:
    """Re-count the project's Sentry issues and patch the facts.

    ``external_identifier`` is the Sentry project slug the gateway
    matched against ``EXISTS_IN.identifier``. The count is read from
    Sentry, not derived from the event, so a missed delivery cannot make
    the fact drift.
    """
    del action_config, event
    try:
        s = client.settings(ctx, credentials)
        project = await client.get_project(s, external_identifier)
        if project is None:
            LOGGER.warning(
                'Sentry project %r not found; skipping', external_identifier
            )
            return
        counts = await client.count_all(ctx, s, project)
    except client.SentryClientError:
        LOGGER.exception(
            'Failed to count Sentry issues for %r', external_identifier
        )
        return
    await _patch_imbi_project(
        ctx.org_slug,
        ctx.project_id,
        [
            {'op': 'add', 'path': f'/{fact}', 'value': count}
            for fact, count in counts.items()
        ],
    )


async def _patch_imbi_project(
    org_slug: str, project_id: str, patch: list[dict[str, typing.Any]]
) -> None:
    settings = _ImbiSettings()  # type: ignore[call-arg]
    async with api_client.Imbi(
        base_url=settings.api_base_url, token=settings.api_token, timeout=30.0
    ) as imbi:
        await imbi.patch_project(org_slug, project_id, patch)
