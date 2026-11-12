"""Sentry project doctor.

Checks that the project's ``EXISTS_IN`` edge names a live Sentry project
and that the edge and the ``sentry`` issues link match it, offering to
create or link the project. Then compares each configured issue-count
fact against Sentry and offers a sweepable sync.

Diagnosis is best-effort: missing configuration or an unreachable Sentry
degrades to ``warn`` findings, so the Doctor panel never hard-fails.
"""

from __future__ import annotations

import typing

from imbi.common.plugins.base import (
    AnalysisCapability,
    AnalysisResultItem,
    AnalysisResultStatus,
    PluginContext,
    RemediationOffer,
    RemediationResult,
    ServiceConnection,
)
from imbi.plugins.sentry import client
from imbi.plugins.sentry.lifecycle import find_or_create

#: Search Sentry for the project, create it when absent, write the edge.
_CREATE = 'create-project'
#: Rewrite the edge + link for a project analyze() found. Never creates.
_LINK = 'link-project'
#: Write the issue-count facts.
_SYNC_FACTS = 'sync-issue-counts'
#: Make the expected team the only owner of the Sentry project.
_SET_TEAM = 'set-team'

_CREATE_OFFER = RemediationOffer(
    id=_CREATE,
    label='Create / link the Sentry project',
    confirm=(
        'This creates the Sentry project if it does not exist, then links '
        'it to this project.'
    ),
    destructive=True,
)
_SET_TEAM_OFFER = RemediationOffer(
    id=_SET_TEAM,
    label='Set the Sentry team',
    confirm=(
        'This makes the expected team the only owner of the Sentry project. '
        'Every other team loses its access to the project.'
    ),
    destructive=True,
)
_LINK_OFFER = RemediationOffer(id=_LINK, label='Repair the Sentry link')
_SYNC_OFFER = RemediationOffer(
    id=_SYNC_FACTS, label='Sync issue counts from Sentry', sweepable=True
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


def _connection(ctx: PluginContext) -> ServiceConnection | None:
    return next(
        (
            c
            for c in ctx.service_connections
            if c.integration_slug == ctx.integration_slug
        ),
        None,
    )


def linked_slug(ctx: PluginContext) -> str:
    """The edge's identifier wins over the project-slug convention."""
    connection = _connection(ctx)
    return connection.identifier if connection else ctx.project_slug


def _count_matches(value: object, count: int) -> bool:
    """Return whether a stored fact equals a Sentry count.

    A bool is an int in Python, so ``True == 1``; reject it explicitly.
    """
    return type(value) is int and value == count


def _may_link(ctx: PluginContext, project: dict[str, typing.Any]) -> bool:
    """Return whether the Doctor may link ``project`` to this project.

    An existing edge is kept: someone already chose it. A new link follows
    the rule of :func:`find_or_create`.
    """
    return _connection(ctx) is not None or client.may_link(
        project, client.sentry_team(ctx)
    )


def _owns_sentry_project(ctx: PluginContext) -> bool:
    """Return whether the project may change its Sentry project's teams.

    Only for the Sentry project named after this project, through an edge
    the plugin wrote itself (or no edge yet). An identifier set by hand
    could name another team's Sentry project, and replacing its teams
    would take that project away from them.
    """
    connection = _connection(ctx)
    if connection is not None and (
        connection.verified_identifier != connection.identifier
    ):
        return False
    return linked_slug(ctx) == ctx.project_slug


class SentryDoctor(AnalysisCapability):
    """Validate and repair the project's Sentry project binding."""

    async def analyze(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> list[AnalysisResultItem]:
        if not ctx.integration_slug:
            return [
                _item(
                    'exists-in',
                    'Sentry project',
                    'warn',
                    'This capability is not bound to an Integration.',
                )
            ]
        slug = linked_slug(ctx)
        try:
            s = client.settings(ctx, credentials)
            project = await client.get_project(s, slug)
        except client.SentryClientError as exc:
            return [
                _item(
                    'exists-in',
                    'Sentry project',
                    'warn',
                    f'Cannot verify Sentry project {slug!r}: {exc}',
                )
            ]
        if project is None:
            return [
                _item(
                    'exists-in',
                    'Sentry project',
                    'fail',
                    f'Sentry project {slug!r} does not exist. Use the Fix '
                    'action to create and link it.',
                    _CREATE_OFFER,
                )
            ]
        return [
            self._check_link(ctx, s, project),
            self._check_team(ctx, project),
            *await self._check_facts(ctx, s, project),
        ]

    def _check_link(
        self,
        ctx: PluginContext,
        s: client.Settings,
        project: dict[str, typing.Any],
    ) -> AnalysisResultItem:
        expected = client.writeback(ctx, s, project)
        connection = _connection(ctx)
        if (
            connection is not None
            and connection.identifier == expected.identifier
            and connection.canonical_url == expected.canonical_url
            and ctx.project_links.get(client.LINK_KEY)
            == expected.dashboard_links[client.LINK_KEY]
        ):
            return _item(
                'exists-in',
                'Sentry project',
                'pass',
                f'Linked to Sentry project {expected.identifier!r}.',
            )
        if not _may_link(ctx, project):
            return _item(
                'exists-in',
                'Sentry project',
                'fail',
                f'Sentry project {expected.identifier!r} is owned only by '
                f'other teams ({", ".join(client.team_slugs(project))}); '
                'Imbi cannot link it. Add the mapped team to it in Sentry, '
                'then re-run the doctor.',
            )
        return _item(
            'exists-in',
            'Sentry project',
            'warn' if connection is None else 'fail',
            f'Sentry project {expected.identifier!r} exists, but the '
            'project edge or issues link does not match it. Use the Fix '
            'action to link it.',
            _LINK_OFFER,
        )

    def _check_team(
        self, ctx: PluginContext, project: dict[str, typing.Any]
    ) -> AnalysisResultItem:
        expected = client.sentry_team(ctx)
        teams = client.team_slugs(project)
        if expected is None:
            return _item(
                'sentry-team',
                'Sentry team',
                'warn',
                'The project has no owning team to map to a Sentry team.',
            )
        if teams == [expected]:
            return _item(
                'sentry-team',
                'Sentry team',
                'pass',
                f'Sentry team {expected!r} owns the project.',
            )
        if not _owns_sentry_project(ctx) or not client.may_link(
            project, expected
        ):
            return _item(
                'sentry-team',
                'Sentry team',
                'fail',
                f'The Sentry project is owned by {teams or "no team"}; '
                f'expected only {expected!r}. Imbi cannot claim this Sentry '
                f'project; add {expected!r} to it in Sentry, then re-run the '
                'doctor.',
            )
        return _item(
            'sentry-team',
            'Sentry team',
            'fail',
            f'The Sentry project is owned by {teams or "no team"}; expected '
            f'only {expected!r}. Use the Fix action to set the team.',
            _SET_TEAM_OFFER,
        )

    async def _check_facts(
        self,
        ctx: PluginContext,
        s: client.Settings,
        project: dict[str, typing.Any],
    ) -> list[AnalysisResultItem]:
        try:
            counts = await client.count_all(ctx, s, project)
        except client.SentryClientError as exc:
            return [
                _item(
                    'issue-counts',
                    'Sentry issue counts',
                    'warn',
                    f'Cannot count Sentry issues: {exc}',
                )
            ]
        return [
            _item(
                f'issue-count:{fact}',
                f'Fact {fact}',
                'pass',
                f'{fact} matches Sentry ({count}).',
            )
            if _count_matches(ctx.project_facts.get(fact), count)
            else _item(
                f'issue-count:{fact}',
                f'Fact {fact}',
                'warn',
                f'{fact} is {ctx.project_facts.get(fact)!r}; Sentry reports '
                f'{count}.',
                _SYNC_OFFER,
            )
            for fact, count in counts.items()
        ]

    async def remediate(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        remediation_id: str,
    ) -> RemediationResult:
        if remediation_id not in (_CREATE, _LINK, _SYNC_FACTS, _SET_TEAM):
            return await super().remediate(ctx, credentials, remediation_id)
        slug = linked_slug(ctx)
        try:
            s = client.settings(ctx, credentials)
            project: dict[str, typing.Any] | None
            if remediation_id == _CREATE:
                project, created = await find_or_create(ctx, s, slug)
            else:
                project, created = await client.get_project(s, slug), False
            if project is None:
                return RemediationResult(
                    status='failed',
                    message=(
                        f'Sentry project {slug!r} no longer exists; '
                        're-run the doctor to create it.'
                    ),
                )
            if remediation_id == _LINK and not _may_link(ctx, project):
                return RemediationResult(
                    status='failed',
                    message=(
                        f'Sentry project {slug!r} is owned only by other '
                        'teams; refusing to link it.'
                    ),
                )
            if remediation_id == _SYNC_FACTS:
                return await self._sync_facts(ctx, s, project)
            if remediation_id == _SET_TEAM:
                return await self._set_team(ctx, s, project)
        except client.SentryClientError as exc:
            return RemediationResult(status='failed', message=str(exc))
        ctx.service_writeback = client.writeback(ctx, s, project)
        verb = 'Created and linked' if created else 'Linked'
        return RemediationResult(
            status='fixed', message=f'{verb} Sentry project {slug!r}.'
        )

    async def _sync_facts(
        self,
        ctx: PluginContext,
        s: client.Settings,
        project: dict[str, typing.Any],
    ) -> RemediationResult:
        counts = await client.count_all(ctx, s, project)
        if all(
            _count_matches(ctx.project_facts.get(f), c)
            for f, c in counts.items()
        ):
            return RemediationResult(
                status='noop', message='Issue counts already match Sentry.'
            )
        ctx.fact_writeback = dict[str, typing.Any](counts)
        return RemediationResult(
            status='fixed',
            message=', '.join(f'{f} = {c}' for f, c in counts.items()),
        )

    async def _set_team(
        self,
        ctx: PluginContext,
        s: client.Settings,
        project: dict[str, typing.Any],
    ) -> RemediationResult:
        if not _owns_sentry_project(ctx):
            return RemediationResult(
                status='failed',
                message=(
                    'Imbi did not link this Sentry project itself; change '
                    'its teams in Sentry.'
                ),
            )
        team = client.sentry_team(ctx)
        if team is None:
            return RemediationResult(
                status='failed',
                message='The project has no owning team to map.',
            )
        if client.team_slugs(project) == [team]:
            return RemediationResult(
                status='noop', message=f'Sentry team {team!r} already set.'
            )
        removed = await client.set_team(s, project, team)
        suffix = f'; removed {", ".join(removed)}' if removed else ''
        return RemediationResult(
            status='fixed', message=f'Set Sentry team {team!r}{suffix}.'
        )
