"""PagerDuty project-doctor analysis capability.

Validates a project's binding to its PagerDuty service and offers a
one-click repair that **searches** PagerDuty for the service and, when
none is found, **creates** it — then writes the ``EXISTS_IN`` edge so
future webhook routing and the Incidents tab resolve.

Diagnosis (``analyze``) is best-effort: auth / rate-limit / transport
failures degrade to ``warn`` findings rather than raising, so opening the
Project Doctor panel never hard-fails. The repair (``remediate``) reuses
the exact create path the lifecycle capability uses
(:mod:`imbi_plugin_pagerduty._provisioning`) so a doctor-created service is
identical to a lifecycle-created one.
"""

from __future__ import annotations

import logging
import typing

import httpx
from imbi_common.plugins.base import (
    AnalysisCapability,
    AnalysisResultItem,
    AnalysisResultStatus,
    PluginContext,
    RemediationOffer,
    RemediationResult,
    ServiceConnection,
)
from imbi_common.plugins.errors import (
    PluginAuthenticationFailed,
    PluginRateLimited,
)

from imbi_plugin_pagerduty import _client, _provisioning, _services

LOGGER = logging.getLogger(__name__)

#: The single remediation offered: search PagerDuty for the service and,
#: if absent, create it, then write the EXISTS_IN edge + dashboard link.
#: The same id also reconciles a drifted edge (identifier / canonical URL /
#: dashboard link) against a live service.
_REPAIR_EDGE = 'repair-edge'

_LINK_KEY = _services.SERVICE_LINK_KEY


def _item(
    slug: str,
    title: str,
    status: AnalysisResultStatus,
    description: str,
    remediation: RemediationOffer | None = None,
) -> AnalysisResultItem:
    return AnalysisResultItem(
        slug=slug,
        title=title,
        status=status,
        description=description,
        remediation=remediation,
    )


def _create_offer() -> RemediationOffer:
    """A confirm-gated offer that may create a PagerDuty service."""
    return RemediationOffer(
        id=_REPAIR_EDGE,
        label='Create / link the PagerDuty service',
        confirm=(
            'This searches PagerDuty for a service named after the project '
            'and creates one (routed to the mapped escalation policy) if '
            'none exists, then links it to the project.'
        ),
        destructive=True,
    )


def _reconcile_offer() -> RemediationOffer:
    """A non-destructive offer that only reconciles Imbi state."""
    return RemediationOffer(
        id=_REPAIR_EDGE,
        label='Repair the PagerDuty service link',
    )


def _find_connection(
    ctx: PluginContext, slug: str
) -> ServiceConnection | None:
    return next(
        (c for c in ctx.service_connections if c.integration_slug == slug),
        None,
    )


def _service_from_get(payload: object) -> dict[str, typing.Any] | None:
    """Extract the ``service`` object from a ``GET /services/{id}`` body."""
    if not isinstance(payload, dict):
        return None
    service = typing.cast('dict[str, typing.Any]', payload).get('service')
    if isinstance(service, dict):
        return typing.cast('dict[str, typing.Any]', service)
    return None


class PagerDutyDoctor(AnalysisCapability):
    """Validate and repair a project's PagerDuty service binding."""

    async def analyze(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[AnalysisResultItem]:
        slug = ctx.integration_slug
        if not slug:
            return [
                _item(
                    'exists-in',
                    'Service binding',
                    'warn',
                    'This capability is not bound to an Integration — no '
                    'EXISTS_IN edge can be inspected.',
                )
            ]

        results: list[AnalysisResultItem] = []
        policy_id = _provisioning.escalation_policy_id(ctx, ctx.team_slug)
        if policy_id:
            results.append(
                _item(
                    'escalation-policy',
                    'Escalation policy',
                    'pass',
                    f'Team {ctx.team_slug!r} routes to escalation policy '
                    f'{policy_id!r}.',
                )
            )
        else:
            results.append(
                _item(
                    'escalation-policy',
                    'Escalation policy',
                    'warn',
                    f'No escalation policy mapped for team {ctx.team_slug!r}. '
                    'A PagerDuty service cannot be created until '
                    'team_escalation_policy_mapping or '
                    'default_escalation_policy_id is set.',
                )
            )

        connection = _find_connection(ctx, slug)
        try:
            async with _client.client(credentials) as client:
                results.extend(
                    await self._analyze_service(
                        ctx, client, connection, policy_id
                    )
                )
        except ValueError as exc:
            # Missing api_key credential.
            results.append(
                _item('service', 'PagerDuty service', 'warn', str(exc))
            )
        except (
            PluginAuthenticationFailed,
            PluginRateLimited,
            httpx.HTTPError,
        ) as exc:
            results.append(
                _item(
                    'service',
                    'PagerDuty service',
                    'warn',
                    f'Could not reach PagerDuty to verify the service: {exc}',
                )
            )
        return results

    async def _analyze_service(
        self,
        ctx: PluginContext,
        client: httpx.AsyncClient,
        connection: ServiceConnection | None,
        policy_id: str | None,
    ) -> list[AnalysisResultItem]:
        if connection is not None:
            return await self._analyze_existing_edge(ctx, client, connection)
        return await self._analyze_no_edge(ctx, client, policy_id)

    async def _analyze_existing_edge(
        self,
        ctx: PluginContext,
        client: httpx.AsyncClient,
        connection: ServiceConnection,
    ) -> list[AnalysisResultItem]:
        resp = await client.get(f'/services/{connection.identifier}')
        if resp.status_code == 404:
            return [
                _item(
                    'service',
                    'PagerDuty service',
                    'fail',
                    f'The EXISTS_IN edge points at service '
                    f'{connection.identifier!r} but PagerDuty returns 404. '
                    'The service was deleted or the id is stale — use the '
                    'Fix action to search by name and re-link or re-create.',
                    _create_offer(),
                )
            ]
        if not resp.is_success:
            return [
                _item(
                    'service',
                    'PagerDuty service',
                    'warn',
                    f'Unexpected HTTP {resp.status_code} fetching service '
                    f'{connection.identifier!r}.',
                )
            ]
        service = _service_from_get(resp.json())
        if service is None:
            return [
                _item(
                    'service',
                    'PagerDuty service',
                    'warn',
                    'PagerDuty returned an unexpected body for service '
                    f'{connection.identifier!r}.',
                )
            ]

        results = [
            _item(
                'service',
                'PagerDuty service',
                'pass',
                f'EXISTS_IN edge present and service '
                f'{connection.identifier!r} exists.',
            )
        ]

        expected = f'{_client.API_BASE}/services/{connection.identifier}'
        if connection.canonical_url == expected:
            results.append(
                _item(
                    'canonical-url',
                    'Canonical URL',
                    'pass',
                    f'Canonical URL matches {expected!r}.',
                )
            )
        else:
            results.append(
                _item(
                    'canonical-url',
                    'Canonical URL',
                    'fail',
                    f'Canonical URL {connection.canonical_url!r} does not '
                    f'match the expected {expected!r}.',
                    _reconcile_offer(),
                )
            )

        html_url = str(service.get('html_url') or '')
        link = ctx.project_links.get(_LINK_KEY)
        if link == html_url and html_url:
            results.append(
                _item(
                    'dashboard-link',
                    'Dashboard link',
                    'pass',
                    f'{_LINK_KEY} link matches the service html_url.',
                )
            )
        else:
            results.append(
                _item(
                    'dashboard-link',
                    'Dashboard link',
                    'fail' if link else 'warn',
                    f'{_LINK_KEY} link {link!r} does not match the PagerDuty '
                    f'html_url {html_url!r}. Use the Fix action to set it.',
                    _reconcile_offer(),
                )
            )
        return results

    async def _analyze_no_edge(
        self,
        ctx: PluginContext,
        client: httpx.AsyncClient,
        policy_id: str | None,
    ) -> list[AnalysisResultItem]:
        existing = await _services.find_service_by_name(
            client, ctx.project_slug
        )
        if existing is not None:
            return [
                _item(
                    'exists-in',
                    'EXISTS_IN edge',
                    'warn',
                    f'No EXISTS_IN edge, but a PagerDuty service named '
                    f'{ctx.project_slug!r} exists. Use the Fix action to '
                    'link it to this project.',
                    _reconcile_offer(),
                )
            ]
        if not policy_id:
            return [
                _item(
                    'exists-in',
                    'EXISTS_IN edge',
                    'fail',
                    f'No EXISTS_IN edge and no PagerDuty service named '
                    f'{ctx.project_slug!r}. Map an escalation policy for '
                    f'team {ctx.team_slug!r} before a service can be '
                    'created.',
                )
            ]
        return [
            _item(
                'exists-in',
                'EXISTS_IN edge',
                'fail',
                f'No EXISTS_IN edge and no PagerDuty service named '
                f'{ctx.project_slug!r}. Use the Fix action to create the '
                'service and link it.',
                _create_offer(),
            )
        ]

    async def remediate(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        remediation_id: str,
    ) -> RemediationResult:
        """Search for the service, create it if missing, and link it.

        Idempotent: returns ``noop`` when the edge already matches a live
        service. Reuses :func:`_provisioning.provision_service` for the
        create path so a doctor-created service matches a lifecycle one.
        """
        if remediation_id != _REPAIR_EDGE:
            return await super().remediate(ctx, credentials, remediation_id)
        slug = ctx.integration_slug
        if slug is None:
            return RemediationResult(
                status='failed',
                message='Capability is not bound to an Integration.',
            )
        try:
            async with _client.client(credentials) as client:
                return await self._remediate(ctx, client)
        except ValueError as exc:
            return RemediationResult(status='failed', message=str(exc))
        except PluginRateLimited as exc:
            return RemediationResult(
                status='failed',
                message=f'PagerDuty rate limit hit: {exc}',
            )
        except PluginAuthenticationFailed as exc:
            return RemediationResult(
                status='failed',
                message=f'PagerDuty rejected the API key: {exc}',
            )
        except httpx.HTTPError as exc:
            return RemediationResult(
                status='failed',
                message=f'PagerDuty request failed: {exc}',
            )

    async def _remediate(
        self, ctx: PluginContext, client: httpx.AsyncClient
    ) -> RemediationResult:
        connection = _find_connection(
            ctx, typing.cast(str, ctx.integration_slug)
        )

        # 1. If the edge names a live service, reconcile to it.
        service: dict[str, typing.Any] | None = None
        if connection is not None:
            resp = await client.get(f'/services/{connection.identifier}')
            if resp.is_success:
                service = _service_from_get(resp.json())
            elif resp.status_code != 404:
                return RemediationResult(
                    status='failed',
                    message=(
                        f'HTTP {resp.status_code} fetching service '
                        f'{connection.identifier!r}.'
                    ),
                )

        # 2. No live service via the edge — search by name (current + prior).
        if service is None:
            for name in (ctx.project_slug, ctx.previous_project_slug):
                if not name:
                    continue
                found = await _services.find_service_by_name(client, name)
                if found is not None:
                    service = found
                    break

        # 3. Still nothing — create it (needs a mapped escalation policy).
        if service is None:
            policy_id = _provisioning.escalation_policy_id(ctx, ctx.team_slug)
            if not policy_id:
                return RemediationResult(
                    status='failed',
                    message=(
                        f'No escalation policy mapped for team '
                        f'{ctx.team_slug!r}; cannot create a PagerDuty '
                        'service.'
                    ),
                )
            created = await _provisioning.provision_service(
                client, ctx, policy_id
            )
            return RemediationResult(
                status='fixed',
                message=(
                    f'Created PagerDuty service {ctx.project_slug!r} '
                    f'({created.get("id")}) and linked it.'
                ),
            )

        # 4. A service exists — reconcile the edge / link if drifted.
        service_id = str(service.get('id') or '')
        html_url = str(service.get('html_url') or '')
        expected = f'{_client.API_BASE}/services/{service_id}'
        already = (
            connection is not None
            and connection.identifier == service_id
            and connection.canonical_url == expected
            and ctx.project_links.get(_LINK_KEY) == html_url
        )
        if already:
            return RemediationResult(
                status='noop',
                message='PagerDuty service link already matches.',
            )
        _provisioning.build_writeback(ctx, service)
        verb = 'Repaired' if connection is not None else 'Linked'
        return RemediationResult(
            status='fixed',
            message=f'{verb} the PagerDuty service link ({service_id}).',
        )
