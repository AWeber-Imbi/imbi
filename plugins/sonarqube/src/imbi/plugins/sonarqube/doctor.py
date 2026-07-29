"""SonarQube project-doctor analysis capability.

Validates a project's binding to its SonarQube project component and
offers a one-click repair that **searches** SonarQube for the component
and, when none is found, **creates** it — then writes the ``EXISTS_IN``
edge so the gateway's webhook routing (which matches the component key
against ``EXISTS_IN.identifier``) resolves for future measure syncs.

It also checks which branch SonarQube tracks as the component's main
branch. SonarQube reports the project's state from that one branch, and a
repository that moved from ``master`` to ``main`` leaves the abandoned
branch flagged ``isMain`` — so the measures Imbi syncs come from an
analysis that stopped running. The repair points the main branch at the
expected one, which is the ``main_branch`` capability option (default
``main``): set on the Integration for the org-wide convention and
overridden per project-type / project by the ``USES`` edge, for the
repository whose trunk is named something else.

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
from collections import abc

from imbi.common.plugins.base import (
    AnalysisCapability,
    AnalysisResultItem,
    AnalysisResultStatus,
    PluginContext,
    RemediationOffer,
    RemediationResult,
    ServiceConnection,
    ServiceWriteback,
)
from imbi.plugins.sonarqube import client

LOGGER = logging.getLogger(__name__)

#: The destructive remediation: search SonarQube for the component and, if
#: absent, create it, then write the EXISTS_IN edge + dashboard link.
_REPAIR_EDGE = 'repair-edge'

#: The non-destructive remediation: reconcile a drifted edge / link against a
#: component analyze() already found. It must never create — if the component
#: has since vanished, it fails rather than silently creating one.
_RECONCILE_EDGE = 'reconcile-edge'

#: Points SonarQube's main branch at the expected branch. Destructive: the
#: branch SonarQube reports on today stops driving the project's state.
_SET_MAIN_BRANCH = 'set-main-branch'

#: SonarQube's dashboard link uses the integration slug as its key (unlike
#: GitHub's bespoke ``github-repository`` key).
_LINK_KEY = 'sonarqube'

#: Capability option naming the branch SonarQube is expected to track. It
#: is capability- rather than integration-scoped so the host's option
#: layering (Integration < project-type edge < project edge) lets a single
#: repository dissent from the org-wide convention.
MAIN_BRANCH_OPTION = 'main_branch'

#: Value of :data:`MAIN_BRANCH_OPTION` when the operator sets none.
DEFAULT_MAIN_BRANCH = 'main'


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


def _set_main_branch_offer(branch: str) -> RemediationOffer:
    return RemediationOffer(
        id=_SET_MAIN_BRANCH,
        label=f'Track {branch!r} as the main branch',
        confirm=(
            f'This makes {branch!r} the main branch in SonarQube. The branch '
            'it tracks today becomes an ordinary branch and its analysis '
            "stops driving the project's reported state."
        ),
        destructive=True,
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


def _main_branch(ctx: PluginContext) -> str:
    """Resolve the branch SonarQube is expected to track.

    The host has already layered the Integration's value under any
    project-type / project ``USES``-edge override, so this only has to
    supply :data:`DEFAULT_MAIN_BRANCH` when the option is unset — which
    covers every Integration created before the option existed.
    """
    raw = ctx.capability_options.get(MAIN_BRANCH_OPTION)
    branch = str(raw).strip() if raw is not None else ''
    return branch or DEFAULT_MAIN_BRANCH


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


def _token_type_hint(exc: Exception, api_token: str) -> str:
    """Explain a 403 from the token's own prefix.

    SonarQube prefixes tokens by type, so the credential says which of
    two unrelated causes is in play and the finding should not make the
    operator guess.  An analysis token (``sqa_`` global, ``sqp_``
    project) only reaches the endpoints a scanner uses and is refused
    regardless of the issuing account's rights -- replacing it is the
    only fix.  A user token (``squ_``) that is refused is a permissions
    problem, where telling someone to swap a token that is already the
    right type sends them in circles.  Tokens issued before SonarQube
    added the prefixes carry neither, so those get both possibilities.
    Returns ``''`` for non-403 failures, which need no token guidance.
    """
    if '403' not in str(exc):
        return ''
    if api_token.startswith(('sqa_', 'sqp_')):
        return (
            ' The api_token credential is an analysis token, which only '
            'reaches scanner endpoints; replace it with a user token '
            '(`squ_`, from My Account > Security).'
        )
    if api_token.startswith('squ_'):
        return (
            ' The api_token credential is a user token, so this is the '
            "token account's permissions rather than the token type -- "
            'verify it has Browse on this project (SonarQube also '
            'restricts some project APIs to administrators).'
        )
    return (
        ' Check whether the api_token credential is an analysis token '
        '(`sqa_` / `sqp_`), which only reaches scanner endpoints and '
        'needs replacing with a user token (`squ_`); if it is already a '
        "user token, verify the token account's Browse permission on "
        'this project.'
    )


def _canonical_url(base_url: str, key: str) -> str:
    quoted = urllib.parse.quote(key, safe='')
    return f'{base_url.rstrip("/")}/api/components/show?component={quoted}'


def _dashboard_url(base_url: str, key: str) -> str:
    quoted = urllib.parse.quote(key, safe='')
    return f'{base_url.rstrip("/")}/dashboard?id={quoted}'


def _named_branch(
    branches: abc.Sequence[dict[str, typing.Any]], name: str
) -> dict[str, typing.Any] | None:
    return next((b for b in branches if b.get('name') == name), None)


def _tracked_phrase(branches: abc.Sequence[dict[str, typing.Any]]) -> str:
    """Phrase the branch SonarQube currently reports the project's state from.

    A component with no analysis yet has no branch flagged ``isMain``, so
    the findings have to read sensibly without one.
    """
    for branch in branches:
        if branch.get('isMain') is True:
            return f'it reports on {branch.get("name")!r}'
    return 'no branch is flagged as its main branch'


class _Unconfigured(Exception):
    """Raised when the Integration lacks something a remediation needs."""


class _Target(typing.NamedTuple):
    """What every remediation needs resolved before it can call SonarQube."""

    base_url: str
    api_token: str
    key: str
    connection: ServiceConnection | None


def _remediation_target(
    ctx: PluginContext, credentials: dict[str, str]
) -> _Target:
    """Resolve the SonarQube target, or raise :class:`_Unconfigured`.

    The message carried by the exception is the one the Doctor panel shows,
    so each guard explains what to configure rather than that something is
    missing.
    """
    slug = ctx.integration_slug
    if slug is None:
        raise _Unconfigured('Capability is not bound to an Integration.')
    base_url = _service_url(ctx)
    if not base_url:
        raise _Unconfigured('The Integration has no service_url configured.')
    api_token = credentials.get('api_token')
    if not api_token:
        raise _Unconfigured('No api_token credential configured.')
    connection = _find_connection(ctx, slug)
    key = _component_key(ctx, connection)
    if key is None:
        raise _Unconfigured(
            'Cannot derive the SonarQube component key: no EXISTS_IN edge '
            'and no owning team.'
        )
    return _Target(base_url, api_token, key, connection)


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
                    'SonarQube project. Set the Integration credential to a '
                    'SonarQube user token (prefix `squ_`) -- analysis tokens '
                    '(`sqa_` / `sqp_`) cannot read this API.',
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
                    f'{exc}{_token_type_hint(exc, api_token)}',
                )
            ]

        if connection is not None:
            results = self._analyze_existing_edge(
                ctx, connection, base_url, key, component
            )
        else:
            results = self._analyze_no_edge(key, component)
        # The branch check needs a live component, but not an edge: a
        # stale main branch reports stale measures whether or not Imbi has
        # linked the component yet.
        if component is not None:
            results.append(
                await self._analyze_main_branch(
                    base_url, api_token, key, _main_branch(ctx)
                )
            )
        return results

    async def _analyze_main_branch(
        self, base_url: str, api_token: str, key: str, branch: str
    ) -> AnalysisResultItem:
        """Check that SonarQube tracks ``branch`` as the main branch.

        A repository that migrated from ``master`` to ``main`` keeps the
        abandoned branch flagged ``isMain`` in SonarQube, which goes on
        reporting the analysis it last ran. Only a component that *has*
        ``branch`` can be repaired, so one that never adopted it (still on
        ``master``) passes rather than nagging.
        """
        try:
            branches = await client.list_branches(
                base_url=base_url, api_token=api_token, key=key
            )
        except client.SonarqubeClientError as exc:
            return _item(
                'main-branch',
                'Main branch',
                'warn',
                f'Could not list the branches of component {key!r}: '
                f'{exc}{_token_type_hint(exc, api_token)}',
            )
        main = _named_branch(branches, branch)
        if main is None:
            return _item(
                'main-branch',
                'Main branch',
                'pass',
                f'SonarQube has no {branch!r} branch for {key!r}; '
                f'{_tracked_phrase(branches)}.',
            )
        if main.get('isMain') is True:
            return _item(
                'main-branch',
                'Main branch',
                'pass',
                f'SonarQube tracks {branch!r} as the main branch.',
            )
        return _item(
            'main-branch',
            'Main branch',
            'fail',
            f'SonarQube does not track {branch!r} as the main branch of '
            f'{key!r} -- {_tracked_phrase(branches)}, so the measures synced '
            'from this project are those of an abandoned branch. Use the Fix '
            f'action to make {branch!r} the main branch.',
            _set_main_branch_offer(branch),
        )

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
        """Apply one of this capability's three repairs.

        ``_SET_MAIN_BRANCH`` points SonarQube's main branch at the expected
        branch and touches no Imbi state; the other two reconcile the
        ``EXISTS_IN``
        edge by searching for the component and, for ``_REPAIR_EDGE`` only,
        creating it when it is missing. The non-destructive
        ``_RECONCILE_EDGE`` offer fails if the component has vanished since
        ``analyze`` rather than silently creating one.

        Idempotent: returns ``noop`` when the edge already matches a live
        component. The component key is the existing edge identifier or the
        ``<team>:<project>`` default, and is written verbatim to
        ``EXISTS_IN.identifier`` so the gateway's webhook match resolves.
        """
        if remediation_id not in (
            _REPAIR_EDGE,
            _RECONCILE_EDGE,
            _SET_MAIN_BRANCH,
        ):
            return await super().remediate(ctx, credentials, remediation_id)
        try:
            base_url, api_token, key, connection = _remediation_target(
                ctx, credentials
            )
        except _Unconfigured as exc:
            return RemediationResult(status='failed', message=str(exc))
        if remediation_id == _SET_MAIN_BRANCH:
            return await self._set_main_branch(
                base_url, api_token, key, _main_branch(ctx)
            )
        allow_create = remediation_id == _REPAIR_EDGE

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

    async def _set_main_branch(
        self, base_url: str, api_token: str, key: str, branch: str
    ) -> RemediationResult:
        """Make ``branch`` the main branch of the SonarQube component.

        Re-reads the branch list rather than trusting the report: if the
        main branch has moved since, this is a ``noop`` instead of a
        redundant write, and if ``branch`` has vanished it fails rather
        than asking SonarQube to track a branch it does not have.
        """
        try:
            branches = await client.list_branches(
                base_url=base_url, api_token=api_token, key=key
            )
            main = _named_branch(branches, branch)
            if main is None:
                return RemediationResult(
                    status='failed',
                    message=(
                        f'SonarQube component {key!r} has no {branch!r} '
                        'branch to track.'
                    ),
                )
            if main.get('isMain') is True:
                return RemediationResult(
                    status='noop',
                    message=(
                        f'SonarQube already tracks {branch!r} as the main '
                        f'branch of {key!r}.'
                    ),
                )
            await client.set_main_branch(
                base_url=base_url,
                api_token=api_token,
                key=key,
                branch=branch,
            )
        except client.SonarqubeClientError as exc:
            return RemediationResult(
                status='failed',
                message=f'SonarQube request failed: {exc}',
            )
        return RemediationResult(
            status='fixed',
            message=(
                f'SonarQube now tracks {branch!r} as the main branch of '
                f'{key!r}.'
            ),
        )
