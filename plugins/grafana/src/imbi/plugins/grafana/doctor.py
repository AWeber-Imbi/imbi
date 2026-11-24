"""Grafana project doctor.

Checks that the project has an ``EXISTS_IN`` edge to the Grafana
integration, that the plugin verified it, and that the edge and the
``grafana`` link match the integration options. Warns when the edge
identifier differs from the project slug, because the alert rules must
carry that value in the label.

The plugin has no Grafana credentials, so the doctor cannot confirm
that alert rules with the label exist.
"""

from __future__ import annotations

from imbi.common.plugins.base import (
    AnalysisCapability,
    AnalysisResultItem,
    AnalysisResultStatus,
    PluginContext,
    RemediationOffer,
    RemediationResult,
    ServiceWriteback,
)
from imbi.plugins.grafana import links

#: Write the edge and link for the current identifier.
_LINK = 'link-project'
#: Rewrite the edge and link with the project slug as the identifier.
_USE_SLUG = 'use-project-slug'

_LINK_OFFER = RemediationOffer(
    id=_LINK,
    label='Link the project to Grafana',
    confirm=(
        'This writes the Grafana link of this project. The alert rules '
        'must carry the identifier in the configured label.'
    ),
    destructive=True,
)
_USE_SLUG_OFFER = RemediationOffer(
    id=_USE_SLUG,
    label='Use the project slug as the identifier',
    confirm=(
        'This changes the identifier that Grafana deliveries must carry. '
        'Alert rules labelled with the old value stop matching this '
        'project.'
    ),
    destructive=True,
)


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


class GrafanaDoctor(AnalysisCapability):
    """Validate and repair the project's Grafana edge and link."""

    async def analyze(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> list[AnalysisResultItem]:
        del credentials
        if not ctx.integration_slug:
            return [
                _item(
                    'exists-in',
                    'Grafana link',
                    'warn',
                    'This capability is not bound to an Integration.',
                )
            ]
        value = links.identifier(ctx)
        try:
            expected = links.writeback(ctx, value)
        except links.GrafanaConfigError as exc:
            return [_item('exists-in', 'Grafana link', 'warn', str(exc))]
        return [
            self._check_link(ctx, expected),
            self._check_identifier(ctx, value),
        ]

    @staticmethod
    def _check_link(
        ctx: PluginContext, expected: ServiceWriteback
    ) -> AnalysisResultItem:
        name = links.label(ctx)
        conn = links.connection(ctx)
        if links.matches(ctx, expected):
            return _item(
                'exists-in',
                'Grafana link',
                'pass',
                f'Linked to Grafana alert rules with '
                f'`{name}={expected.identifier}`.',
            )
        if conn is None:
            return _item(
                'exists-in',
                'Grafana link',
                'fail',
                'The project has no Grafana link, so the gateway cannot '
                'route Grafana deliveries to it. Use the Fix action to link '
                f'it as `{name}={expected.identifier}`.',
                _LINK_OFFER,
            )
        return _item(
            'exists-in',
            'Grafana link',
            'warn',
            f'The Grafana link `{name}={expected.identifier}` exists, but '
            'the edge or the alert rules link does not match the '
            'integration options. Use the Fix action to refresh it.',
            _LINK_OFFER,
        )

    @staticmethod
    def _check_identifier(
        ctx: PluginContext, value: str
    ) -> AnalysisResultItem:
        name = links.label(ctx)
        if value == ctx.project_slug:
            return _item(
                'identifier',
                'Grafana identifier',
                'pass',
                f'Alert rules must carry `{name}={value}`.',
            )
        return _item(
            'identifier',
            'Grafana identifier',
            'warn',
            f'The Grafana identifier `{value}` differs from the project '
            f'slug `{ctx.project_slug}`. Alert rules must carry '
            f'`{name}={value}`. Use the Fix action to switch to the slug.',
            _USE_SLUG_OFFER,
        )

    async def remediate(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        remediation_id: str,
    ) -> RemediationResult:
        if remediation_id not in (_LINK, _USE_SLUG):
            return await super().remediate(ctx, credentials, remediation_id)
        value = (
            ctx.project_slug
            if remediation_id == _USE_SLUG
            else links.identifier(ctx)
        )
        try:
            expected = links.writeback(ctx, value)
        except links.GrafanaConfigError as exc:
            return RemediationResult(status='failed', message=str(exc))
        if links.matches(ctx, expected):
            return RemediationResult(
                status='noop',
                message=f'Already linked as {links.label(ctx)}={value!r}.',
            )
        ctx.service_writeback = expected
        return RemediationResult(
            status='fixed',
            message=f'Linked the project as {links.label(ctx)}={value!r}.',
        )
