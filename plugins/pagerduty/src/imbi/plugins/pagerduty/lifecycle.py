"""PagerDuty lifecycle plugin.

Reacts to the project lifecycle by managing a PagerDuty **service** named
after the project slug, wired to the owning team's escalation policy via
the ``team_escalation_policy_mapping`` option, and (when a gateway URL is
configured) a per-service V3 **webhook subscription** so incident events
flow back to Imbi.

PagerDuty is cloud-only, so there is no host-flavor routing -- a single
REST API key credential and the shared ``api.pagerduty.com`` client.

The plugin writes its result through ``ctx.service_writeback``: the host
persists the ``EXISTS_IN`` edge (service id + the encrypted webhook
signing secret the gateway verifies against) and merges the
``pagerduty-service`` dashboard link into ``Project.links``. The service
id is therefore never stored as a separate link; the subscription's
signing secret is returned by PagerDuty only once, at creation, and is
encrypted before it leaves the plugin.

Open PagerDuty-API assumptions to confirm against a live tenant: the
create-subscription response exposes the signing secret at
``delivery_method.secret``, and a service's subscriptions are found by
listing ``/webhook_subscriptions`` and matching ``filter.id`` (there is
no documented server-side service filter).
"""

from __future__ import annotations

import logging
import typing

import httpx
from imbi_common.auth.encryption import TokenEncryption
from imbi_common.plugins.base import (
    CredentialField,
    LifecyclePlugin,
    LifecycleResult,
    PluginContext,
    PluginManifest,
    PluginOption,
    RelocationTarget,
    ServiceWriteback,
)

from imbi_plugin_pagerduty import _client, _services

LOGGER = logging.getLogger(__name__)


def _as_dict(value: object) -> dict[str, typing.Any]:
    """Narrow an arbitrary JSON value to a typed dict (or empty)."""
    if isinstance(value, dict):
        return typing.cast('dict[str, typing.Any]', value)
    return {}


_WEBHOOK_EVENTS = [
    'incident.triggered',
    'incident.acknowledged',
    'incident.resolved',
    'incident.escalated',
    'incident.reopened',
]

_OPTIONS: list[PluginOption] = [
    PluginOption(
        name='team_escalation_policy_mapping',
        label='Team to escalation policy',
        description=(
            'Maps an Imbi team slug to the PagerDuty escalation policy id '
            "the team's services route to. A PagerDuty service requires "
            'an escalation policy, so a project whose team is unmapped is '
            'skipped with an operator message.'
        ),
        type='mapping',
        required=True,
    ),
    PluginOption(
        name='default_escalation_policy_id',
        label='Default escalation policy id',
        description='Fallback escalation policy for unmapped teams.',
        type='string',
        required=False,
    ),
    PluginOption(
        name='gateway_webhook_url',
        label='Gateway webhook URL',
        description=(
            'Public imbi-gateway notifications URL the per-service '
            'PagerDuty webhook subscription delivers to. Leave blank to '
            'skip webhook provisioning.'
        ),
        type='string',
        required=False,
    ),
]

_CREDENTIALS: list[CredentialField] = [
    CredentialField(
        name='api_key',
        label='PagerDuty REST API key',
        description='A REST API key with write access to services.',
        required=True,
    )
]


class PagerDutyLifecyclePlugin(LifecyclePlugin):
    """Create / update / delete / relocate a project's PagerDuty service."""

    manifest = PluginManifest(
        slug='pagerduty-lifecycle',
        name='PagerDuty Lifecycle',
        description=(
            'Provision and maintain a PagerDuty service for the project, '
            "routed to the owning team's escalation policy, with a "
            'per-service webhook subscription back to Imbi.'
        ),
        plugin_type='lifecycle',
        auth_type='api_token',
        options=_OPTIONS,
        credentials=_CREDENTIALS,
        lifecycle_events=['created', 'updated', 'deleted', 'relocated'],
        supports_lifecycle_sync=True,
    )

    # -- option resolution ------------------------------------------------

    @staticmethod
    def _escalation_policy_id(
        ctx: PluginContext, team_slug: str | None
    ) -> str | None:
        """Resolve the escalation policy id for ``team_slug``.

        Prefers the team mapping, then the ``default_escalation_policy_id``
        fallback. Returns ``None`` when neither yields one.
        """
        options = ctx.assignment_options
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

    @staticmethod
    def _gateway_url(ctx: PluginContext) -> str | None:
        raw = ctx.assignment_options.get('gateway_webhook_url')
        return raw.strip() if isinstance(raw, str) and raw.strip() else None

    # -- service / subscription helpers -----------------------------------

    @staticmethod
    def _writeback(
        ctx: PluginContext,
        service: dict[str, typing.Any],
        *,
        webhook_secret_enc: str | None = None,
    ) -> None:
        """Record the EXISTS_IN edge + dashboard link for ``service``."""
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

    async def _create_service(
        self,
        client: httpx.AsyncClient,
        ctx: PluginContext,
        policy_id: str,
    ) -> dict[str, typing.Any]:
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

    async def _provision_subscription(
        self,
        client: httpx.AsyncClient,
        *,
        service_id: str,
        gateway_url: str,
    ) -> str | None:
        """Create the V3 webhook subscription; return the encrypted secret.

        Returns ``None`` when PagerDuty does not surface a signing secret
        (in which case the gateway simply won't verify signatures for this
        service).
        """
        body = {
            'webhook_subscription': {
                'type': 'webhook_subscription',
                'delivery_method': {
                    'type': 'http_delivery_method',
                    'url': gateway_url,
                },
                'filter': {'type': 'service_reference', 'id': service_id},
                'events': _WEBHOOK_EVENTS,
            }
        }
        response = await client.post('/webhook_subscriptions', json=body)
        response.raise_for_status()
        payload: dict[str, typing.Any] = response.json()
        subscription = _as_dict(payload.get('webhook_subscription'))
        delivery = _as_dict(subscription.get('delivery_method'))
        secret = delivery.get('secret')
        if not secret:
            return None
        return TokenEncryption.get_instance().encrypt(str(secret))

    async def _delete_subscriptions_for(
        self, client: httpx.AsyncClient, service_id: str
    ) -> None:
        """Delete every webhook subscription targeting ``service_id``."""
        response = await client.get('/webhook_subscriptions')
        response.raise_for_status()
        payload: dict[str, typing.Any] = response.json()
        subscriptions: list[dict[str, typing.Any]] = (
            payload.get('webhook_subscriptions') or []
        )
        for subscription in subscriptions:
            filt = _as_dict(subscription.get('filter'))
            if filt.get('id') == service_id and subscription.get('id'):
                await client.delete(
                    f'/webhook_subscriptions/{subscription["id"]}'
                )

    # -- hooks ------------------------------------------------------------

    async def on_project_archived(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        # PagerDuty has no archive concept; the required hook no-ops.
        del ctx, credentials
        return LifecycleResult(
            status='skipped', message='PagerDuty has no archive concept'
        )

    async def on_project_created(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        policy_id = self._escalation_policy_id(ctx, ctx.team_slug)
        if not policy_id:
            return LifecycleResult(
                status='skipped',
                message=(
                    f'No PagerDuty escalation policy mapped for team '
                    f'{ctx.team_slug!r}; set team_escalation_policy_mapping '
                    'or default_escalation_policy_id'
                ),
            )
        async with _client.client(credentials) as client:
            existing = await _services.find_service_by_name(
                client, ctx.project_slug
            )
            if existing is not None:
                self._writeback(ctx, existing)
                return LifecycleResult(
                    status='skipped',
                    message=f'PagerDuty service {ctx.project_slug!r} exists',
                    artifacts={'service_id': str(existing.get('id') or '')},
                )
            service = await self._create_service(client, ctx, policy_id)
            service_id = str(service.get('id') or '')
            secret_enc: str | None = None
            gateway_url = self._gateway_url(ctx)
            if gateway_url and service_id:
                secret_enc = await self._provision_subscription(
                    client, service_id=service_id, gateway_url=gateway_url
                )
            self._writeback(ctx, service, webhook_secret_enc=secret_enc)
        return LifecycleResult(
            status='ok',
            message=f'Created PagerDuty service {ctx.project_slug!r}',
            artifacts={'service_id': service_id},
        )

    async def on_project_updated(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        async with _client.client(credentials) as client:
            service_id = await _services.resolve_service_id(client, ctx)
            if service_id is None:
                # Upsert: nothing on the remote yet -> create it.
                return await self.on_project_created(ctx, credentials)
            body = {
                'service': {
                    'name': ctx.project_slug,
                    'description': ctx.project_description or '',
                }
            }
            response = await client.put(f'/services/{service_id}', json=body)
            response.raise_for_status()
            payload: dict[str, typing.Any] = response.json()
            self._writeback(ctx, payload.get('service') or {})
        return LifecycleResult(
            status='ok',
            message=f'Updated PagerDuty service {ctx.project_slug!r}',
            artifacts={'service_id': service_id},
        )

    async def on_project_deleted(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        async with _client.client(credentials) as client:
            service_id = await _services.resolve_service_id(client, ctx)
            if service_id is None:
                return LifecycleResult(
                    status='skipped',
                    message='No PagerDuty service to delete',
                )
            await self._delete_subscriptions_for(client, service_id)
            try:
                response = await client.delete(f'/services/{service_id}')
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    ctx.service_writeback = ServiceWriteback(
                        identifier=service_id,
                        canonical_url='',
                        remove=True,
                    )
                    return LifecycleResult(
                        status='skipped',
                        message='PagerDuty service already deleted',
                    )
                raise
        ctx.service_writeback = ServiceWriteback(
            identifier=service_id, canonical_url='', remove=True
        )
        return LifecycleResult(
            status='ok',
            message=f'Deleted PagerDuty service {service_id}',
        )

    async def on_project_relocated(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> LifecycleResult:
        new_policy = self._escalation_policy_id(ctx, ctx.team_slug)
        old_policy = self._escalation_policy_id(ctx, ctx.previous_team_slug)
        if new_policy is None:
            return LifecycleResult(
                status='skipped',
                message=(
                    f'No escalation policy mapped for team {ctx.team_slug!r}'
                ),
            )
        if new_policy == old_policy:
            # Routing target unchanged -> nothing to repoint. Safe to fire
            # for every relocation (the host dispatches to all lifecycle
            # plugins).
            return LifecycleResult(
                status='skipped',
                message='Escalation policy unchanged',
            )
        async with _client.client(credentials) as client:
            service_id = await _services.resolve_service_id(client, ctx)
            if service_id is None:
                return await self.on_project_created(ctx, credentials)
            body = {
                'service': {
                    'escalation_policy': {
                        'id': new_policy,
                        'type': 'escalation_policy_reference',
                    }
                }
            }
            response = await client.put(f'/services/{service_id}', json=body)
            response.raise_for_status()
            payload: dict[str, typing.Any] = response.json()
            self._writeback(ctx, payload.get('service') or {})
        return LifecycleResult(
            status='ok',
            message=f'Repointed PagerDuty service {service_id}',
            artifacts={'service_id': service_id},
        )

    async def resolve_relocation_target(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> RelocationTarget | None:
        del credentials
        policy_id = self._escalation_policy_id(ctx, ctx.team_slug)
        if not policy_id:
            return None
        return RelocationTarget(
            link_key=_services.SERVICE_LINK_KEY,
            identifier=f'{policy_id}/{ctx.project_slug}',
            display=f'{ctx.project_slug} -> {policy_id}',
        )
