"""Grafana project doctor.

Checks that the project has an ``EXISTS_IN`` edge to the Grafana
integration, that the plugin verified it, and that the edge and the
``grafana`` link match the integration options. Warns when the edge
identifier differs from ``{slug}-{id}`` (for example after a rename),
because the alert rules must carry that value in the label.

With the optional ``api_token``, the doctor also asks Grafana whether
the token works, whether alert rules carry the label, and whether a
dashboard has the ``<label>:<value>`` tag. Without it, it skips these
checks.
"""

from __future__ import annotations

import typing
import urllib.parse

from imbi.common.plugins import errors
from imbi.common.plugins.base import (
    AnalysisCapability,
    AnalysisResultItem,
    AnalysisResultStatus,
    PluginContext,
    RemediationOffer,
    RemediationResult,
    ServiceWriteback,
)
from imbi.plugins.grafana import links, steps

#: Write the edge and link for the current identifier.
_LINK = 'link-project'
#: Rewrite the edge and link with ``{slug}-{id}`` as the identifier.
_USE_DEFAULT = 'use-project-value'

_LINK_OFFER = RemediationOffer(
    id=_LINK,
    label='Link the project to Grafana',
    confirm=(
        'This writes the Grafana link of this project. The alert rules '
        'must carry the identifier in the configured label.'
    ),
    destructive=True,
)
_USE_DEFAULT_OFFER = RemediationOffer(
    id=_USE_DEFAULT,
    label='Use the current project value as the identifier',
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


def _count_rules(data: object, name: str, value: str) -> int:
    """Count the rules with the label. The filter is also applied here,
    because a Grafana without ``rule_matcher`` returns every rule."""
    groups = typing.cast(
        'list[dict[str, list[dict[str, typing.Any]]]]',
        typing.cast('dict[str, typing.Any]', data)['data']['groups'],
    )
    return sum(
        1
        for group in groups
        for rule in group.get('rules', [])
        if typing.cast('dict[str, str]', rule.get('labels') or {}).get(name)
        == value
    )


class GrafanaDoctor(AnalysisCapability):
    """Validate and repair the project's Grafana edge and link."""

    async def analyze(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> list[AnalysisResultItem]:
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
        items = [
            self._check_link(ctx, expected),
            self._check_identifier(ctx, value),
        ]
        if credentials.get('api_token', '').strip():
            items.extend(await self._check_grafana(ctx, credentials, value))
        return items

    @staticmethod
    async def _check_grafana(
        ctx: PluginContext, credentials: dict[str, str], value: str
    ) -> list[AnalysisResultItem]:
        """Ask Grafana for the alert rules and dashboards of the project."""
        name = links.label(ctx)
        tag = f'{name}:{value}'
        try:
            rules = await steps.request(
                ctx, credentials, 'GET', links.rules_path(name, value)
            )
            dashboards = await steps.request(
                ctx,
                credentials,
                'GET',
                '/api/search?'
                + urllib.parse.urlencode({'type': 'dash-db', 'tag': tag}),
            )
            count = _count_rules(rules, name, value)
            found = (
                len(typing.cast('list[object]', dashboards))
                if isinstance(dashboards, list)
                else None
            )
        except errors.PluginAuthenticationFailed as exc:
            return [_item('api-token', 'Grafana token', 'fail', str(exc))]
        except Exception as exc:  # noqa: BLE001 - report, do not fail the run
            return [
                _item(
                    'api-token',
                    'Grafana token',
                    'warn',
                    f'Could not reach Grafana: {exc}',
                )
            ]
        return [
            _item(
                'api-token',
                'Grafana token',
                'pass',
                'Grafana accepted the service account token.',
            ),
            _item(
                'alert-rules',
                'Grafana alert rules',
                'pass' if count else 'warn',
                f'{count} alert rule(s) carry `{name}={value}`.'
                if count
                else f'No alert rule carries `{name}={value}`, so Grafana '
                'sends no alerts for this project. Add the label to its '
                'rules.',
            ),
            _item(
                'dashboards',
                'Grafana dashboards',
                'warn',
                'Grafana returned an invalid search response.',
            )
            if found is None
            else _item(
                'dashboards',
                'Grafana dashboards',
                'pass' if found else 'warn',
                f'{found} dashboard(s) have the tag `{tag}`.'
                if found
                else f'No dashboard has the tag `{tag}`. Add the tag to the '
                'dashboards of this project.',
            ),
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
        default = links.default_identifier(ctx)
        if value == default:
            return _item(
                'identifier',
                'Grafana identifier',
                'pass',
                f'Alert rules and dashboards must carry `{name}={value}`.',
            )
        return _item(
            'identifier',
            'Grafana identifier',
            'warn',
            f'The Grafana identifier `{value}` differs from the current '
            f'project value `{default}`. Alert rules must carry '
            f'`{name}={value}`. Update the labels in Grafana, then use the '
            f'Fix action to switch to `{default}`.',
            _USE_DEFAULT_OFFER,
        )

    async def remediate(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        remediation_id: str,
    ) -> RemediationResult:
        if remediation_id not in (_LINK, _USE_DEFAULT):
            return await super().remediate(ctx, credentials, remediation_id)
        value = (
            links.default_identifier(ctx)
            if remediation_id == _USE_DEFAULT
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
