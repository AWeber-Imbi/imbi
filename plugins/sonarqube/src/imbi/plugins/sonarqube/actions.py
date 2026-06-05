"""Webhook action implementations dispatched from :class:`SonarqubePlugin`."""

import logging
import typing

import httpx
import pydantic
import pydantic_settings
from imbi_common import json_pointer
from imbi_common.plugins import base as plugin_base

from imbi_plugin_sonarqube import client

LOGGER = logging.getLogger(__name__)


class _ImbiSettings(pydantic_settings.BaseSettings):
    """Imbi API connection settings.

    Names mirror :class:`imbi_gateway.actions.ActionSettings` so the
    same operator-managed environment variables drive both the gateway
    handlers and this plugin's handler.
    """

    model_config = {'env_prefix': 'ACTIONS_'}

    imbi_url: pydantic.HttpUrl = pydantic.HttpUrl('http://imbi-api:8000')
    imbi_token: str


class MetricMapping(pydantic.BaseModel):
    """One row of ``WebhookRule.handler_config``.

    ``metric`` is the SonarQube measure metric key
    (e.g. ``'coverage'``, ``'ncloc'``).  ``path`` is the JSON Pointer
    target on the Imbi project that receives the metric value.
    """

    metric: str = pydantic.Field(
        description='SonarQube measure metric key (e.g. coverage, ncloc).',
    )
    path: json_pointer.JsonPointer = pydantic.Field(
        description=(
            'JSON Pointer on the Imbi project that receives this metric.'
        ),
    )


class MetricMappings(pydantic.RootModel[list[MetricMapping]]):
    """``WebhookRule.handler_config`` for ``update_project_from_webhook``.

    A list of metric -> JSON Pointer mappings. The action fetches each
    metric from SonarQube's ``/api/measures/component`` endpoint and
    patches the resolved value to the matching path on the Imbi
    project.
    """

    root: list[MetricMapping] = pydantic.Field(
        default_factory=list,
        description='Ordered list of metric -> JSON Pointer mappings.',
    )


def _index_measures(
    response: dict[str, typing.Any],
) -> dict[str, str]:
    """Return ``{metric_name: value_str}`` from a measures response."""
    component_obj: object = response.get('component') or {}
    if not isinstance(component_obj, dict):
        return {}
    measures_obj: object = typing.cast(
        'dict[str, typing.Any]', component_obj
    ).get('measures', [])
    if not isinstance(measures_obj, list):
        return {}
    indexed: dict[str, str] = {}
    for measure_obj in typing.cast('list[object]', measures_obj):
        if not isinstance(measure_obj, dict):
            continue
        measure = typing.cast('dict[str, typing.Any]', measure_obj)
        metric = measure.get('metric')
        value = measure.get('value')
        if isinstance(metric, str) and value is not None:
            indexed[metric] = str(value)
    return indexed


async def update_project_from_webhook(
    *,
    ctx: plugin_base.PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: MetricMappings,
    event: object,
) -> None:
    """Patch Imbi project facts from a SonarQube webhook delivery.

    The webhook ``event`` is not consulted; the SonarQube component
    key arrives via ``external_identifier`` (resolved by the gateway
    from ``IMPLEMENTED_BY.identifier_selector``). Resolves the
    SonarQube base URL from ``ctx.assignment_options['service_endpoint']``
    (the gateway stashes the ``ThirdPartyService.api_endpoint`` there
    before dispatch). Skips silently with a warning when the endpoint
    or API token is missing so a misconfiguration does not 5xx the
    webhook. ``action_config`` is a pre-validated :class:`MetricMappings`
    instance -- the host validates the JSON blob before calling.
    """
    del event
    mappings = action_config.root
    if not mappings:
        LOGGER.debug('No metric mappings configured; nothing to do')
        return

    api_token = credentials.get('api_token')
    if not api_token:
        LOGGER.warning(
            'SonarQube api_token credential is missing; skipping project '
            '%s/%s update',
            ctx.org_slug,
            ctx.project_id,
        )
        return
    raw_endpoint = ctx.assignment_options.get('service_endpoint')
    service_endpoint = str(raw_endpoint) if raw_endpoint else None
    if not service_endpoint:
        LOGGER.warning(
            'ThirdPartyService has no api_endpoint configured; skipping '
            'project %s/%s update',
            ctx.org_slug,
            ctx.project_id,
        )
        return

    metric_keys = [mapping.metric for mapping in mappings]
    try:
        response = await client.fetch_component_measures(
            base_url=service_endpoint,
            api_token=api_token,
            component=external_identifier,
            metric_keys=metric_keys,
        )
    except client.SonarqubeClientError:
        LOGGER.exception(
            'Failed to fetch SonarQube measures for component %r',
            external_identifier,
        )
        return

    measures = _index_measures(response)
    patch: list[dict[str, typing.Any]] = []
    for mapping in mappings:
        value = measures.get(mapping.metric)
        if value is None:
            LOGGER.warning(
                'SonarQube measure %r missing for component %r; '
                'skipping patch %s',
                mapping.metric,
                external_identifier,
                str(mapping.path),
            )
            continue
        patch.append({'op': 'add', 'path': str(mapping.path), 'value': value})

    if not patch:
        LOGGER.info(
            'No SonarQube measures resolved for component %r; project %s/%s '
            'left unchanged',
            external_identifier,
            ctx.org_slug,
            ctx.project_id,
        )
        return

    await _patch_imbi_project(ctx.org_slug, ctx.project_id, patch)


async def _patch_imbi_project(
    org_slug: str,
    project_id: str,
    patch: list[dict[str, typing.Any]],
) -> None:
    """PATCH the Imbi project's facts.

    Reads connection settings from the ``ACTIONS_IMBI_URL`` and
    ``ACTIONS_IMBI_TOKEN`` environment variables (matching the
    gateway's own :class:`imbi_gateway.actions.ActionSettings`) so the
    plugin requires no additional configuration.
    """
    settings = _ImbiSettings()  # type: ignore[call-arg]
    url = (
        str(settings.imbi_url).rstrip('/')
        + f'/organizations/{org_slug}/projects/{project_id}'
    )
    headers = {
        'Authorization': f'Bearer {settings.imbi_token}',
        'Content-Type': 'application/json',
    }
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        response = await http_client.patch(url, headers=headers, json=patch)
    if response.is_error:
        LOGGER.warning(
            'Failed to patch Imbi project %s/%s: %s %s',
            org_slug,
            project_id,
            response.status_code,
            response.text,
        )
