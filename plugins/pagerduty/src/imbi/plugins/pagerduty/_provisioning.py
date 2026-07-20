"""Shared PagerDuty service provisioning primitives.

Used by **both** the lifecycle capability (project create / update /
relocate) and the doctor capability (search-and-create remediation) so the
two agree on how a service is created, how its webhook subscription is
provisioned, and how the result is written back to the ``EXISTS_IN`` edge.

Kept as free functions (rather than :class:`PagerDutyLifecycle` methods) so
the doctor can reuse them without constructing a lifecycle capability.
"""

from __future__ import annotations

import typing

import httpx
from imbi_common.auth.encryption import TokenEncryption
from imbi_common.plugins.base import PluginContext, ServiceWriteback

from imbi_plugin_pagerduty import _client, _services

#: Incident events the per-service webhook subscription delivers back to
#: the imbi-gateway notifications endpoint.
WEBHOOK_EVENTS = [
    'incident.triggered',
    'incident.acknowledged',
    'incident.resolved',
    'incident.escalated',
    'incident.reopened',
]


def as_dict(value: object) -> dict[str, typing.Any]:
    """Narrow an arbitrary JSON value to a typed dict (or empty)."""
    if isinstance(value, dict):
        return typing.cast('dict[str, typing.Any]', value)
    return {}


def escalation_policy_id(
    ctx: PluginContext, team_slug: str | None
) -> str | None:
    """Resolve the escalation policy id for ``team_slug``.

    Prefers the ``team_escalation_policy_mapping`` entry for the team,
    then the ``default_escalation_policy_id`` fallback. Returns ``None``
    when neither yields one.
    """
    options = ctx.integration_options
    mapping_raw = options.get('team_escalation_policy_mapping')
    if team_slug and isinstance(mapping_raw, dict):
        mapping = typing.cast('dict[str, typing.Any]', mapping_raw)
        value = mapping.get(team_slug)
        if isinstance(value, str) and value.strip():
            return value.strip()
    default = options.get('default_escalation_policy_id')
    if isinstance(default, str) and default.strip():
        return default.strip()
    return None


def gateway_url(ctx: PluginContext) -> str | None:
    """Return the configured gateway webhook URL, or ``None``."""
    raw = ctx.integration_options.get('gateway_webhook_url')
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def build_writeback(
    ctx: PluginContext,
    service: dict[str, typing.Any],
    *,
    webhook_secret_enc: str | None = None,
) -> None:
    """Record the ``EXISTS_IN`` edge + dashboard link for ``service``."""
    service_id = str(service.get('id') or '')
    html_url = str(service.get('html_url') or '')
    ctx.service_writeback = ServiceWriteback(
        identifier=service_id,
        canonical_url=f'{_client.API_BASE}/services/{service_id}',
        dashboard_links=(
            {_services.SERVICE_LINK_KEY: html_url} if html_url else {}
        ),
        webhook_secret_enc=webhook_secret_enc,
    )


async def create_service(
    client: httpx.AsyncClient,
    ctx: PluginContext,
    policy_id: str,
) -> dict[str, typing.Any]:
    """Create a PagerDuty service named after the project slug."""
    body = {
        'service': {
            'name': ctx.project_slug,
            'description': ctx.project_description or '',
            'escalation_policy': {
                'id': policy_id,
                'type': 'escalation_policy_reference',
            },
        }
    }
    response = await client.post('/services', json=body)
    response.raise_for_status()
    payload: dict[str, typing.Any] = response.json()
    return payload.get('service') or {}


async def provision_subscription(
    client: httpx.AsyncClient,
    *,
    service_id: str,
    gateway_webhook_url: str,
) -> str | None:
    """Create the V3 webhook subscription; return the encrypted secret.

    Returns ``None`` when PagerDuty does not surface a signing secret (in
    which case the gateway simply won't verify signatures for this
    service).
    """
    body = {
        'webhook_subscription': {
            'type': 'webhook_subscription',
            'delivery_method': {
                'type': 'http_delivery_method',
                'url': gateway_webhook_url,
            },
            'filter': {'type': 'service_reference', 'id': service_id},
            'events': WEBHOOK_EVENTS,
        }
    }
    response = await client.post('/webhook_subscriptions', json=body)
    response.raise_for_status()
    payload: dict[str, typing.Any] = response.json()
    subscription = as_dict(payload.get('webhook_subscription'))
    delivery = as_dict(subscription.get('delivery_method'))
    secret = delivery.get('secret')
    if not secret:
        return None
    return TokenEncryption.get_instance().encrypt(str(secret))


async def provision_service(
    client: httpx.AsyncClient,
    ctx: PluginContext,
    policy_id: str,
) -> dict[str, typing.Any]:
    """Create a service (+ webhook subscription) and write back its edge.

    The single find-nothing-then-create path shared by lifecycle create
    and doctor remediation: creates the service, provisions the webhook
    subscription when a gateway URL is configured, and records the
    ``EXISTS_IN`` edge + dashboard link on ``ctx``. Returns the created
    service payload.
    """
    service = await create_service(client, ctx, policy_id)
    service_id = str(service.get('id') or '')
    secret_enc: str | None = None
    url = gateway_url(ctx)
    if url and service_id:
        secret_enc = await provision_subscription(
            client, service_id=service_id, gateway_webhook_url=url
        )
    build_writeback(ctx, service, webhook_secret_enc=secret_enc)
    return service
