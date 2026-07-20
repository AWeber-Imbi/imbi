"""SonarQube project-doctor analysis capability.

Validates a project's binding to its SonarQube project component and
offers a one-click repair that **searches** SonarQube for the component
and, when none is found, **creates** it — then writes the ``EXISTS_IN``
edge so the gateway's webhook routing (which matches the component key
against ``EXISTS_IN.identifier``) resolves for future measure syncs.

The component key convention is ``<owning-team-slug>:<project-slug>``.
An existing edge's identifier wins over the derived default so a
manually-configured key is never overwritten.

Diagnosis (``analyze``) is best-effort: a missing ``service_url`` /
``api_token`` or an unreachable server degrades to ``warn`` findings
rather than raising, so opening the Project Doctor panel never hard-fails.
"""

from __future__ import annotations

import logging
import typing
import urllib.parse

from imbi_common.plugins.base import (
    AnalysisCapability,
    AnalysisResultItem,
    AnalysisResultStatus,
    PluginContext,
    RemediationOffer,
    RemediationResult,
    ServiceConnection,
    ServiceWriteback,
)

from imbi_plugin_sonarqube import client

LOGGER = logging.getLogger(__name__)

#: The destructive remediation: search SonarQube for the component and, if
#: absent, create it, then write the EXISTS_IN edge + dashboard link.
_REPAIR_EDGE = 'repair-edge'

#: The non-destructive remediation: reconcile a drifted edge / link against a
#: component analyze() already found. It must never create — if the component
#: has since vanished, it fails rather than silently creating one.
_RECONCILE_EDGE = 'reconcile-edge'

#: SonarQube's dashboard link uses the integration slug as its key (unlike
#: GitHub's bespoke ``github-repository`` key).
_LINK_KEY = 'sonarqube'


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
    return RemediationOffer(
        id=_REPAIR_EDGE,
        label='Create / link the SonarQube project',
        confirm=(
            'This searches SonarQube for the project component and creates '
            'one if none exists, then links it to the project.'
        ),
        destructive=True,
    )


def _reconcile_offer() -> RemediationOffer:
    return RemediationOffer(
        id=_RECONCILE_EDGE,
        label='Repair the SonarQube project link',
    )


def _find_connection(
    ctx: PluginContext, slug: str
) -> ServiceConnection | None:
    return next(
        (c for c in ctx.service_connections if c.integration_slug == slug),
        None,
    )


def _service_url(ctx: PluginContext) -> str | None:
    raw = ctx.integration_options.get('service_url')
    return str(raw).strip() if raw and str(raw).strip() else None


def _component_key(
    ctx: PluginContext, connection: ServiceConnection | None
) -> str | None:
    """Resolve the SonarQube component key for the project.

    An existing edge's identifier wins; otherwise fall back to the
    ``<team-slug>:<project-slug>`` convention. Returns ``None`` when
    neither is available (no edge and no team to derive from).
    """
    if connection is not None and connection.identifier:
        return connection.identifier
    if ctx.team_slug:
        return f'{ctx.team_slug}:{ctx.project_slug}'
    return None


def _canonical_url(base_url: str, key: str) -> str:
    quoted = urllib.parse.quote(key, safe='')
    return f'{base_url.rstrip("/")}/api/components/show?component={quoted}'


def _dashboard_url(base_url: str, key: str) -> str:
    quoted = urllib.parse.quote(key, safe='')
    return f'{base_url.rstrip("/")}/dashboard?id={quoted}'


class SonarQubeDoctor(AnalysisCapability):
    """Validate and repair a project's SonarQube project-component binding."""

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
                    'Project binding',
                    'warn',
                    'This capability is not bound to an Integration — no '
                    'EXISTS_IN edge can be inspected.',
                )
            ]
        base_url = _service_url(ctx)
        if not base_url:
            return [
                _item(
                    'service-url',
                    'SonarQube URL',
                    'warn',
                    'The Integration has no service_url configured.',
                )
            ]
        api_token = credentials.get('api_token')
        if not api_token:
            return [
                _item(
                    'api-token',
                    'SonarQube API token',
                    'warn',
                    'No api_token credential configured; cannot inspect the '
                    'SonarQube project.',
                )
            ]

        connection = _find_connection(ctx, slug)
        key = _component_key(ctx, connection)
        if key is None:
            return [
                _item(
                    'exists-in',
                    'EXISTS_IN edge',
                    'warn',
                    'No EXISTS_IN edge and no owning team, so the SonarQube '
                    'component key (<team>:<project>) cannot be derived.',
                )
            ]

        try:
            component = await client.search_project(
                base_url=base_url, api_token=api_token, key=key
            )
        except client.SonarqubeClientError as exc:
            return [
                _item(
                    'component',
                    'SonarQube project',
                    'warn',
                    f'Could not reach SonarQube to verify component {key!r}: '
                    f'{exc}',
                )
            ]

        if connection is not None:
            return self._analyze_existing_edge(
                ctx, connection, base_url, key, component
            )
        return self._analyze_no_edge(key, component)

    def _analyze_existing_edge(
        self,
        ctx: PluginContext,
        connection: ServiceConnection,
        base_url: str,
        key: str,
        component: dict[str, typing.Any] | None,
    ) -> list[AnalysisResultItem]:
        if component is None:
            return [
                _item(
                    'component',
                    'SonarQube project',
                    'fail',
                    f'The EXISTS_IN edge names component {key!r} but it does '
                    'not exist in SonarQube. Use the Fix action to '
                    're-create or re-link it.',
                    _create_offer(),
                )
            ]
        results = [
            _item(
                'component',
                'SonarQube project',
                'pass',
                f'EXISTS_IN edge present and component {key!r} exists.',
            )
        ]
        expected = _canonical_url(base_url, key)
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
        dashboard = _dashboard_url(base_url, key)
        link = ctx.project_links.get(_LINK_KEY)
        if link == dashboard:
            results.append(
                _item(
                    'dashboard-link',
                    'Dashboard link',
                    'pass',
                    f'{_LINK_KEY} link matches the project dashboard.',
                )
            )
        else:
            results.append(
                _item(
                    'dashboard-link',
                    'Dashboard link',
                    'fail' if link else 'warn',
                    f'{_LINK_KEY} link {link!r} does not match the expected '
                    f'dashboard {dashboard!r}. Use the Fix action to set it.',
                    _reconcile_offer(),
                )
            )
        return results

    def _analyze_no_edge(
        self, key: str, component: dict[str, typing.Any] | None
    ) -> list[AnalysisResultItem]:
        if component is not None:
            return [
                _item(
                    'exists-in',
                    'EXISTS_IN edge',
                    'warn',
                    f'No EXISTS_IN edge, but SonarQube component {key!r} '
                    'exists. Use the Fix action to link it to this project.',
                    _reconcile_offer(),
                )
            ]
        return [
            _item(
                'exists-in',
                'EXISTS_IN edge',
                'fail',
                f'No EXISTS_IN edge and no SonarQube component {key!r}. Use '
                'the Fix action to create the project and link it.',
                _create_offer(),
            )
        ]

    async def remediate(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        remediation_id: str,
    ) -> RemediationResult:
        """Search for the component, create it if missing, and link it.

        Only the destructive ``_REPAIR_EDGE`` offer may create; the
        non-destructive ``_RECONCILE_EDGE`` offer fails if the component has
        vanished since ``analyze`` rather than silently creating one.

        Idempotent: returns ``noop`` when the edge already matches a live
        component. The component key is the existing edge identifier or the
        ``<team>:<project>`` default, and is written verbatim to
        ``EXISTS_IN.identifier`` so the gateway's webhook match resolves.
        """
        if remediation_id not in (_REPAIR_EDGE, _RECONCILE_EDGE):
            return await super().remediate(ctx, credentials, remediation_id)
        allow_create = remediation_id == _REPAIR_EDGE
        slug = ctx.integration_slug
        if slug is None:
            return RemediationResult(
                status='failed',
                message='Capability is not bound to an Integration.',
            )
        base_url = _service_url(ctx)
        if not base_url:
            return RemediationResult(
                status='failed',
                message='The Integration has no service_url configured.',
            )
        api_token = credentials.get('api_token')
        if not api_token:
            return RemediationResult(
                status='failed',
                message='No api_token credential configured.',
            )
        connection = _find_connection(ctx, slug)
        key = _component_key(ctx, connection)
        if key is None:
            return RemediationResult(
                status='failed',
                message=(
                    'Cannot derive the SonarQube component key: no EXISTS_IN '
                    'edge and no owning team.'
                ),
            )

        try:
            component = await client.search_project(
                base_url=base_url, api_token=api_token, key=key
            )
            created = False
            if component is None:
                if not allow_create:
                    return RemediationResult(
                        status='failed',
                        message=(
                            f'SonarQube component {key!r} no longer exists; '
                            're-run the doctor to re-create it.'
                        ),
                    )
                component = await client.create_project(
                    base_url=base_url,
                    api_token=api_token,
                    key=key,
                    name=ctx.project_name or ctx.project_slug,
                )
                created = True
        except client.SonarqubeClientError as exc:
            return RemediationResult(
                status='failed',
                message=f'SonarQube request failed: {exc}',
            )

        canonical = _canonical_url(base_url, key)
        dashboard = _dashboard_url(base_url, key)
        already = (
            not created
            and connection is not None
            and connection.identifier == key
            and connection.canonical_url == canonical
            and ctx.project_links.get(_LINK_KEY) == dashboard
        )
        if already:
            return RemediationResult(
                status='noop',
                message=f'SonarQube component {key!r} link already matches.',
            )
        ctx.service_writeback = ServiceWriteback(
            identifier=key,
            canonical_url=canonical,
            dashboard_links={_LINK_KEY: dashboard},
        )
        if created:
            verb = 'Created SonarQube project and linked'
        elif connection is not None:
            verb = 'Repaired the link for'
        else:
            verb = 'Linked'
        return RemediationResult(
            status='fixed',
            message=f'{verb} SonarQube component {key!r}.',
        )
