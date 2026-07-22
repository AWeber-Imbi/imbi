"""PagerDuty lifecycle capability.

Reacts to the project lifecycle by managing a PagerDuty **service** named
after the project slug, wired to the owning team's escalation policy via
the ``team_escalation_policy_mapping`` integration option, and (when a
gateway URL is configured) a per-service V3 **webhook subscription** so
incident events flow back to Imbi.

PagerDuty is cloud-only, so there is no host-flavor routing -- a single
REST API key credential and the shared ``api.pagerduty.com`` client.

The capability writes its result through ``ctx.service_writeback``: the
host persists the ``EXISTS_IN`` edge (service id + the encrypted webhook
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
from imbi_common.plugins.base import (
    LifecycleCapability,
    LifecycleResult,
    PluginContext,
    RelocationTarget,
    ServiceWriteback,
)

from imbi_plugin_pagerduty import _client, _provisioning, _services

LOGGER = logging.getLogger(__name__)


class PagerDutyLifecycle(LifecycleCapability):
    """Create / update / delete / relocate a project's PagerDuty service.

    Service creation, webhook subscription, and edge writeback live in
    :mod:`imbi_plugin_pagerduty._provisioning` so the doctor capability
    shares exactly this create path.
    """

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
            filt = _provisioning.as_dict(subscription.get('filter'))
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
        policy_id = _provisioning.escalation_policy_id(ctx, ctx.team_slug)
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
                _provisioning.build_writeback(ctx, existing)
                return LifecycleResult(
                    status='skipped',
                    message=f'PagerDuty service {ctx.project_slug!r} exists',
                    artifacts={'service_id': str(existing.get('id') or '')},
                )
            service = await _provisioning.provision_service(
                client, ctx, policy_id
            )
            service_id = str(service.get('id') or '')
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
            _provisioning.build_writeback(ctx, payload.get('service') or {})
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
        new_policy = _provisioning.escalation_policy_id(ctx, ctx.team_slug)
        old_policy = _provisioning.escalation_policy_id(
            ctx, ctx.previous_team_slug
        )
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
            _provisioning.build_writeback(ctx, payload.get('service') or {})
        return LifecycleResult(
            status='ok',
            message=f'Repointed PagerDuty service {service_id}',
            artifacts={'service_id': service_id},
        )

    async def resolve_relocation_target(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> RelocationTarget | None:
        del credentials
        policy_id = _provisioning.escalation_policy_id(ctx, ctx.team_slug)
        if not policy_id:
            return None
        return RelocationTarget(
            link_key=_services.SERVICE_LINK_KEY,
            identifier=f'{policy_id}/{ctx.project_slug}',
            display=f'{ctx.project_slug} -> {policy_id}',
        )
