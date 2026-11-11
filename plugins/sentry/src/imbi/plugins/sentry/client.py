"""Sentry REST API client, plus the settings every capability shares."""

import importlib.metadata
import re
import typing
import urllib.parse

import httpx

from imbi.common.plugins.base import PluginContext, ServiceWriteback

_VERSION = importlib.metadata.version('imbi-plugin-sentry')

#: Project link key the issues URL is written under.
LINK_KEY = 'sentry'

#: Fact name -> Sentry issue search, when the operator sets none.
DEFAULT_ISSUE_COUNT_FACTS = {'sentry_open_issues': 'is:unresolved'}

#: Issue search window, when the operator sets none. Sentry's issue
#: stream defaults to the same window, so the linked page shows the
#: issues that were counted.
DEFAULT_ISSUE_PERIOD = '14d'


class SentryClientError(Exception):
    """Raised on non-2xx responses or transport errors."""


_SLUG_RE = re.compile(r'[A-Za-z0-9_-]+')


class Settings(typing.NamedTuple):
    """What every Sentry call needs, resolved from the Integration."""

    base_url: str
    organization: str
    auth_token: str


def settings(ctx: PluginContext, credentials: dict[str, str]) -> Settings:
    """Resolve the Integration settings, or raise :class:`SentryClientError`.

    The message is the one the operator sees, so it names what to set.
    """
    base_url = str(ctx.integration_options.get('service_url') or '').strip()
    organization = str(
        ctx.integration_options.get('organization') or ''
    ).strip()
    auth_token = credentials.get('auth_token', '')
    if not organization:
        raise SentryClientError('The Integration has no organization set.')
    if not auth_token:
        raise SentryClientError('No auth_token credential configured.')
    return Settings(
        (base_url or 'https://sentry.io').rstrip('/'), organization, auth_token
    )


def _mapping(ctx: PluginContext, name: str) -> dict[str, str]:
    """Return the ``mapping`` option ``name`` as ``dict[str, str]``."""
    raw: object = ctx.integration_options.get(name)
    if not isinstance(raw, dict):
        return {}
    items = typing.cast('dict[object, object]', raw).items()
    return {str(k): str(v) for k, v in items}


def issue_count_facts(ctx: PluginContext) -> dict[str, str]:
    """Return the configured ``fact name -> Sentry issue search`` map."""
    return _mapping(ctx, 'issue_count_facts') or dict(
        DEFAULT_ISSUE_COUNT_FACTS
    )


def issue_period(ctx: PluginContext) -> str:
    raw = str(ctx.integration_options.get('issue_period') or '').strip()
    return raw or DEFAULT_ISSUE_PERIOD


def sentry_team(ctx: PluginContext) -> str | None:
    """Return the Sentry team that owns the project's Sentry project.

    The ``team_mapping`` option wins; an unmapped team uses its own slug.
    """
    if ctx.team_slug is None:
        return None
    return _mapping(ctx, 'team_mapping').get(ctx.team_slug) or ctx.team_slug


def writeback(
    ctx: PluginContext, s: Settings, project: dict[str, typing.Any]
) -> ServiceWriteback:
    """Build the ``EXISTS_IN`` edge + issues link for a Sentry project."""
    slug = str(project['slug'])
    query = urllib.parse.urlencode(
        {'project': project['id'], 'statsPeriod': issue_period(ctx)}
    )
    return ServiceWriteback(
        identifier=slug,
        canonical_url=canonical_url(s, slug),
        dashboard_links={
            LINK_KEY: (
                f'{s.base_url}/organizations/{s.organization}/issues/?{query}'
            )
        },
    )


def _q(segment: str) -> str:
    """Return a Sentry slug for a URL path, or raise.

    Sentry slugs hold only letters, digits, ``-`` and ``_``. Anything
    else (``..``, ``/``, encoded forms of either) could point a call at a
    different API path, because httpx normalizes the path.
    """
    if not _SLUG_RE.fullmatch(segment):
        raise SentryClientError(f'{segment!r} is not a valid Sentry slug')
    return segment


def canonical_url(s: Settings, slug: str) -> str:
    return f'{s.base_url}/api/0/projects/{_q(s.organization)}/{_q(slug)}/'


async def _request(
    s: Settings,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    json: dict[str, typing.Any] | None = None,
) -> httpx.Response:
    headers = {
        'Authorization': f'Bearer {s.auth_token}',
        'Accept': 'application/json',
        'User-Agent': f'imbi-plugin-sentry/{_VERSION}',
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            return await http_client.request(
                method,
                f'{s.base_url}/api/0{path}',
                params=params,
                json=json,
                headers=headers,
            )
    except httpx.RequestError as exc:
        raise SentryClientError(f'Sentry request failed: {exc}') from exc


def _raise_for_error(response: httpx.Response) -> None:
    if response.is_error:
        raise SentryClientError(
            f'Sentry returned status {response.status_code}: '
            f'{response.text[:200]}'
        )


def _json(response: httpx.Response) -> dict[str, typing.Any]:
    _raise_for_error(response)
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise SentryClientError('Sentry returned non-JSON response') from exc
    if not isinstance(payload, dict):
        raise SentryClientError('Sentry returned an unexpected payload')
    return typing.cast('dict[str, typing.Any]', payload)


async def get_project(s: Settings, slug: str) -> dict[str, typing.Any] | None:
    """Return the Sentry project ``slug``, or ``None`` when it is absent."""
    response = await _request(
        s, 'GET', f'/projects/{_q(s.organization)}/{_q(slug)}/'
    )
    if response.status_code == 404:
        return None
    return _json(response)


async def create_project(
    s: Settings, team: str, slug: str, name: str
) -> dict[str, typing.Any]:
    """Create a Sentry project owned by ``team``.

    Sentry answers ``404`` when the team does not exist.
    """
    response = await _request(
        s,
        'POST',
        f'/teams/{_q(s.organization)}/{_q(team)}/projects/',
        json={'name': name, 'slug': slug},
    )
    if response.status_code == 404:
        raise SentryClientError(
            f'Sentry team {team!r} does not exist; map the Imbi team to a '
            'Sentry team in the team_mapping option.'
        )
    return _json(response)


def team_slugs(project: dict[str, typing.Any]) -> list[str]:
    """Return the slugs of the teams that own a Sentry project."""
    teams: object = project.get('teams') or []
    if not isinstance(teams, list):
        return []
    return [
        str(typing.cast('dict[str, typing.Any]', t).get('slug'))
        for t in typing.cast('list[object]', teams)
        if isinstance(t, dict)
    ]


def may_link(project: dict[str, typing.Any], team: str | None) -> bool:
    """Return whether Imbi may link an existing Sentry project.

    Only when no team owns it, or ``team`` already does: linking a
    project owned only by other teams would hand it to this project.
    """
    current = team_slugs(project)
    return not current or team in current


async def set_team(
    s: Settings, project: dict[str, typing.Any], team: str
) -> list[str]:
    """Make ``team`` the only team that owns ``project``.

    Removes other teams only when ``team`` already owns the project, so
    someone with access in Sentry has granted it; a project with no team
    gets ``team`` added. Otherwise raises, because replacing the owners
    of a project that ``team`` has no claim to would take it from them.
    Returns the removed team slugs.
    """
    slug = str(project['slug'])
    path = f'/projects/{_q(s.organization)}/{_q(slug)}/teams'
    current = team_slugs(project)
    if current and team not in current:
        raise SentryClientError(
            f'Sentry team {team!r} does not own this project; add it to the '
            'project in Sentry first.'
        )
    if not current:
        response = await _request(s, 'POST', f'{path}/{_q(team)}/')
        if response.status_code == 404:
            raise SentryClientError(
                f'Sentry team {team!r} does not exist; map the Imbi team to '
                'a Sentry team in the team_mapping option.'
            )
        _raise_for_error(response)
    removed = [t for t in current if t != team]
    for other in removed:
        _raise_for_error(await _request(s, 'DELETE', f'{path}/{_q(other)}/'))
    return removed


async def count_issues(
    s: Settings, project_id: str, query: str, period: str
) -> int:
    """Count the project's issues that match ``query`` in ``period``.

    Reads the ``X-Hits`` header of the organization issues endpoint.
    """
    # ponytail: X-Hits is approximate and caps at 1000; paginate the
    # issue list if a fact needs an exact count past that.
    response = await _request(
        s,
        'GET',
        f'/organizations/{_q(s.organization)}/issues/',
        params={
            'project': project_id,
            'query': query,
            'statsPeriod': period,
            'limit': '1',
        },
    )
    _raise_for_error(response)
    hits = response.headers.get('X-Hits')
    if hits is None or not hits.isdigit():
        raise SentryClientError('Sentry returned no X-Hits issue count')
    return int(hits)


async def count_all(
    ctx: PluginContext, s: Settings, project: dict[str, typing.Any]
) -> dict[str, int]:
    """Return ``{fact name: issue count}`` for every configured fact."""
    period = issue_period(ctx)
    return {
        fact: await count_issues(s, str(project['id']), query, period)
        for fact, query in issue_count_facts(ctx).items()
    }
