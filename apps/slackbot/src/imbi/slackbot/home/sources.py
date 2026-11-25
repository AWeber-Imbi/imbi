"""Read the data of the Home tab from imbi-api, as the user.

Each source is one call (or one fan-out over the projects of the
user's teams). :class:`Sources` starts each source one time, with a
timeout, and the sections share the results. A source that fails or
times out makes only the sections that need it fail (R8).

The shared caches are in Valkey, so they work across pods. A short
lock per key makes sure that only one pod fills a key at a time.

"""

from __future__ import annotations

import asyncio
import collections
import dataclasses
import logging
import typing
from collections import abc

import httpx
import orjson

from imbi.common import valkey
from imbi.slackbot.home import prefs as prefs_

LOGGER = logging.getLogger(__name__)

type Json = typing.Any
type Row = dict[str, typing.Any]

#: Seconds that one source can take.
TIMEOUT = 4.0
#: The most projects of the user's teams that a fan-out reads (PRD §10).
MAX_PROJECTS = 25
LOCK_SECONDS = 5
GATHERED_TTL = 30
NOTICE_TTL = 300
INCIDENTS_TTL = 60
ADVISORIES_TTL = 600
DRIFT_TTL = 300
TREND_TTL = 3600
#: A shared cache holds data that the API returned to another user. A
#: source reads it only when the user has the permission of its route.
_SHARED_CACHE_PERMISSIONS = frozenset(
    {'project:read', 'component:read', 'project:deployment:read'}
)
#: The shared caches that the Retry button of a section drops.
SECTION_CACHES: dict[str, tuple[str, ...]] = {
    'needs_attention': ('incidents', 'advisories'),
    'release_drift': ('drift',),
    'my_projects': ('incidents', 'advisories', 'trend'),
}


@dataclasses.dataclass(frozen=True)
class Failure:
    """A section whose source failed or timed out."""

    reason: str


@dataclasses.dataclass
class Gathered:
    """What :func:`imbi.slackbot.home.render.render` shows."""

    org: Row | None
    orgs: list[Row]
    teams: list[str]
    sections: dict[str, Json | Failure]
    ui_url: str = ''
    ask_url: str = ''
    notice: str | None = None


def dig(value: Json, *keys: str) -> Json:
    """Return ``value[k1][k2]...``, or ``None`` where a key is missing."""
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = typing.cast('dict[str, Json]', value).get(key)
    return value


def gathered_key(email: str) -> str:
    return f'home:gathered:{email}'


def notice_key(email: str) -> str:
    return f'home:notice:{email}'


async def cached(
    key: str, ttl: int, fill: abc.Callable[[], abc.Awaitable[Json]]
) -> Json:
    """Return the cached value of ``key``, or fill it with ``fill``."""
    client = valkey.get_client()
    raw = await client.get(key)
    if raw is not None:
        return orjson.loads(raw)
    lock = f'{key}:lock'
    if not await client.set(lock, b'1', nx=True, ex=LOCK_SECONDS):
        # Another pod fills the key. Wait for it a short time.
        for _ in range(10):
            await asyncio.sleep(0.1)
            raw = await client.get(key)
            if raw is not None:
                return orjson.loads(raw)
        # ponytail: after 1 s, read without the cache; no second wait.
        return await fill()
    try:
        value = await fill()
        await client.set(key, orjson.dumps(value), ex=ttl)
        return value
    finally:
        await client.delete(lock)


async def drop(org: str, section: str) -> None:
    """Drop the shared caches of ``section`` in ``org``."""
    if not org:
        return
    client: typing.Any = valkey.get_client()
    for name in SECTION_CACHES.get(section, ()):
        match = f'home:{org}:{name}*'
        keys = [k async for k in client.scan_iter(match=match)]
        if keys:
            await client.delete(*keys)


async def _json(client: httpx.AsyncClient, path: str, **params: Json) -> Json:
    response = await client.get(path, params=params or None)
    response.raise_for_status()
    return response.json()


async def _json_or(
    client: httpx.AsyncClient, path: str, default: Json, **params: Json
) -> Json:
    """Return the body, or ``default`` on a 404 (nothing bound)."""
    response = await client.get(path, params=params or None)
    if response.status_code == 404:
        return default
    response.raise_for_status()
    return response.json()


async def _fan_out[T](aws: abc.Iterable[abc.Awaitable[T]]) -> list[T]:
    """Like :func:`asyncio.gather`, but when one call fails, cancel and
    await the others, so the source timeout bounds all of them."""
    tasks = [asyncio.ensure_future(a) for a in aws]
    try:
        return await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class Sources:
    """The sources of one render, each started one time."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        org: str,
        email: str,
        teams: list[str],
        permissions: set[str],
    ) -> None:
        self.client = client
        self.org = org
        self.email = email
        self.teams = teams
        self.permissions = permissions
        self.base = f'/organizations/{org}'
        self._tasks: dict[str, asyncio.Future[Json]] = {}

    def get(self, name: str) -> asyncio.Future[Json]:
        """Return the task of the source ``name``, started on first use.

        The task is shielded: when one waiter is cancelled (for example
        by the timeout of a source that waits on this one), the shared
        task continues for the other waiters.

        """
        if name not in self._tasks:
            source: abc.Callable[[], abc.Awaitable[Json]] = getattr(
                self, f'_{name}'
            )
            self._tasks[name] = asyncio.ensure_future(
                asyncio.wait_for(source(), TIMEOUT)
            )
        return asyncio.shield(self._tasks[name])

    async def optional(self, name: str, default: Json) -> Json:
        """Return the source, or ``default`` when it failed."""
        try:
            return await self.get(name)
        except Exception:  # noqa: BLE001 -- the section shows no counts
            return default

    async def settle(self) -> None:
        """Wait for every started source, so no error goes unread."""
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    def _key(self, name: str, *parts: str) -> str:
        return ':'.join(('home', self.org, name, *parts))

    # ----- sources -------------------------------------------------

    async def _projects(self) -> list[Row]:
        """``GET /projects?slim=true``: every project of the org."""
        rows: list[Row] = await _json(
            self.client, f'{self.base}/projects/', slim='true'
        )
        return rows

    async def _team_projects(self) -> list[Row]:
        """The projects of the user's teams, in team order, at most
        :data:`MAX_PROJECTS`."""
        rows: list[Row] = await self.get('projects')
        order = {slug: i for i, slug in enumerate(self.teams)}
        mine = [
            p
            for p in rows
            if dig(p, 'team', 'slug') in order and not p.get('archived')
        ]
        mine.sort(key=lambda p: (order[p['team']['slug']], p['name']))
        return mine[:MAX_PROJECTS]

    async def _waiting(self) -> Row:
        row: Row = await _json(
            self.client, f'{self.base}/tickets/waiting', lists='true'
        )
        return row

    async def _incidents(self) -> list[Row]:
        """Triggered and acknowledged incidents of the team projects."""
        if 'project:read' not in self.permissions:
            return []
        projects: list[Row] = await self.get('team_projects')

        async def one(project: Row) -> list[Row]:
            path = f'{self.base}/projects/{project["id"]}/incidents/'
            result: Row = await cached(
                self._key('incidents', project['id']),
                INCIDENTS_TTL,
                lambda: _json_or(
                    self.client,
                    path,
                    {'incidents': []},
                    status=['triggered', 'acknowledged'],
                ),
            )
            incidents: list[Row] = result.get('incidents') or []
            return [
                {**i, 'project_id': project['id'], 'project': project['name']}
                for i in incidents
            ]

        found = await _fan_out(one(p) for p in projects)
        return [i for rows in found for i in rows]

    async def _advisories(self) -> list[Row]:
        """The rows of the problem packages report for the team
        projects that carry an advisory."""
        if 'component:read' not in self.permissions:
            return []
        report: Row = await cached(
            self._key('advisories'),
            ADVISORIES_TTL,
            lambda: _json(
                self.client, f'{self.base}/reports/problem-packages'
            ),
        )
        teams = set(self.teams)
        rows: list[Row] = report.get('rows') or []
        return [
            r
            for r in rows
            if r.get('team_slug') in teams and r.get('advisories')
        ]

    async def _runs(self) -> list[Row]:
        """Failed and stuck runs that the user started. A person's run
        has ``origin_kind`` ``human`` and the email in ``origin_id``."""
        rows: list[Row] = await _json(
            self.client, f'{self.base}/workflow-runs/attention'
        )
        return [
            r
            for r in rows
            if r.get('origin_kind') == 'human'
            and r.get('origin_id') == self.email
        ]

    async def _review_prs(self) -> Row:
        row: Row = await _json(
            self.client,
            f'{self.base}/pull-requests/',
            state='open',
            reviewer='@me',
            limit=10,
        )
        return row

    async def _authored_prs(self) -> Row:
        row: Row = await _json(
            self.client,
            f'{self.base}/pull-requests/',
            state='open',
            author='@me',
            limit=10,
        )
        return row

    async def _pending(self) -> Row:
        row: Row = await _json(
            self.client,
            f'{self.base}/pull-requests/pending-deploy',
            author='@me',
        )
        return row

    async def _drift(self) -> list[Row]:
        """Release drift of the team projects the projects list marks
        ``release_drifted``, with the open blockers of the suggested tag.

        The slim project row has the verdict already, so only a project
        with drift costs the slow ``release-drift`` call.

        """
        if 'project:deployment:read' not in self.permissions:
            return []
        projects: list[Row] = [
            p
            for p in await self.get('team_projects')
            if p.get('release_drifted')
        ]

        async def one(project: Row) -> Row | None:
            summary: Row = project['release_summary']
            path = f'{self.base}/projects/{project["id"]}/deployments'
            drift: Row = await cached(
                # The latest tag is in the key: a new release must not
                # show beside a suggestion from the previous tag.
                self._key(
                    'drift', project['id'], summary.get('latest_tag') or ''
                ),
                DRIFT_TTL,
                lambda: _json_or(self.client, f'{path}/release-drift', {}),
            )
            # A response from a different tag, fresh or cached, must
            # not show its suggestion beside the row's tag.
            if not drift.get('suggested_tag') or drift.get(
                'latest_tag'
            ) != summary.get('latest_tag'):
                return None
            blockers: list[Row] = await _json_or(
                self.client,
                f'{path}/releases/{drift["suggested_tag"]}/blockers',
                [],
                status='open',
            )
            return {
                'project_id': project['id'],
                'project': project['name'],
                'commits': summary['commits_since_tag'],
                'latest_tag': summary.get('latest_tag'),
                'latest_tag_at': summary.get('latest_tag_at'),
                'suggested_tag': drift['suggested_tag'],
                'blockers': len(blockers),
            }

        found = await _fan_out(one(p) for p in projects)
        return [d for d in found if d]

    async def _trends(self) -> dict[str, Row]:
        """The 7-day score trend of each team project, by id."""
        if 'project:read' not in self.permissions:
            return {}
        projects: list[Row] = await self.get('team_projects')

        async def one(project: Row) -> Row:
            path = f'{self.base}/projects/{project["id"]}/score/trend'
            trend: Row = await cached(
                self._key('trend', project['id']),
                TREND_TTL,
                lambda: _json_or(self.client, path, {}, days=7),
            )
            return trend

        found = await _fan_out(one(p) for p in projects)
        return {p['id']: t for p, t in zip(projects, found, strict=True)}

    async def _agent_tickets(self) -> list[Row]:
        """The user's agent tickets that run, are paused, or wait."""
        groups = ('running', 'paused', 'queued')
        found = await _fan_out(
            _json(
                self.client,
                f'{self.base}/tickets/',
                mine='true',
                group=g,
                limit=25,
            )
            for g in groups
        )
        return [
            {**t, 'group': g}
            for g, rows in zip(groups, found, strict=True)
            for t in rows
            if t.get('owner') == self.email
            and t.get('assignee_kind', 'agent') == 'agent'
        ]

    async def _agents(self) -> dict[str, str]:
        """The names of the org's agents, by id."""
        rows: list[Row] = await _json(self.client, f'{self.base}/agents/')
        return {r['id']: r['name'] for r in rows}

    async def _comments(self) -> list[Row]:
        body: Row = await _json(
            self.client, f'{self.base}/comments/attention', limit=20
        )
        rows: list[Row] = body.get('data') or []
        return rows

    # ----- sections ------------------------------------------------

    async def section(self, key: str) -> Json:
        """Return the data of the section ``key``."""
        builder: abc.Callable[[], abc.Awaitable[Json]] = getattr(
            self, f'_section_{key}'
        )
        return await builder()

    async def _section_needs_attention(self) -> Row:
        waiting, incidents, advisories, runs = await asyncio.gather(
            self.get('waiting'),
            self.get('incidents'),
            self.get('advisories'),
            self.get('runs'),
        )
        return {
            'incidents': incidents,
            'requests': waiting.get('requests') or [],
            'held': waiting.get('held') or [],
            'advisories': _critical(advisories),
            'runs': runs,
        }

    async def _section_my_tickets(self) -> Row:
        waiting: Row = await self.get('waiting')
        return {'tickets': waiting.get('assigned') or []}

    async def _section_pull_requests(self) -> Row:
        review, authored = await asyncio.gather(
            self.get('review_prs'), self.get('authored_prs')
        )
        return {
            'review': review.get('data') or [],
            'review_total': review.get('total', 0),
            'authored': authored.get('data') or [],
            'authored_total': authored.get('total', 0),
            'github_identity_missing': bool(
                review.get('github_identity_missing')
                or authored.get('github_identity_missing')
            ),
        }

    async def _section_merged_not_deployed(self) -> Row:
        pending, projects = await asyncio.gather(
            self.get('pending'), self.optional('projects', [])
        )
        names = {p['id']: p['name'] for p in projects}
        prs: list[Row] = pending.get('data') or []
        return {
            'prs': [
                {**pr, 'project': names.get(pr['project_id'], '')}
                for pr in prs
            ],
            'total': pending.get('total', len(prs)),
        }

    async def _section_release_drift(self) -> Row:
        drift: list[Row] = await self.get('drift')
        return {'projects': drift}

    async def _section_my_projects(self) -> Row:
        projects, trends, incidents, advisories = await asyncio.gather(
            self.get('team_projects'),
            self.optional('trends', {}),
            self.optional('incidents', []),
            self.optional('advisories', []),
        )
        open_incidents = collections.Counter(
            i['project_id'] for i in incidents
        )
        severities: dict[str, collections.Counter[str]] = (
            collections.defaultdict(collections.Counter)
        )
        for row in advisories:
            for advisory in row['advisories']:
                severity = (advisory.get('severity') or '').lower()
                severities[row['project_id']][severity] += 1
        return {
            'projects': [
                {
                    'id': p['id'],
                    'name': p['name'],
                    'team': p['team']['name'],
                    'score': p.get('score'),
                    'delta': dig(trends, p['id'], 'delta'),
                    'incidents': open_incidents[p['id']],
                    'critical': severities[p['id']]['critical'],
                    'high': severities[p['id']]['high'],
                }
                for p in projects
            ]
        }

    async def _section_agent_activity(self) -> Row:
        tickets, agents = await asyncio.gather(
            self.get('agent_tickets'), self.optional('agents', {})
        )
        return {
            'tickets': [
                {**t, 'agent': agents.get(t.get('agent_id'), '')}
                for t in tickets
            ]
        }

    async def _section_document_comments(self) -> Row:
        comments: list[Row] = await self.get('comments')
        return {'comments': comments}


def _critical(rows: list[Row]) -> list[Row]:
    """Group the critical advisories by CVE and package version, with
    the projects that deploy it (Q8: critical only)."""
    found: dict[tuple[str, str, str], Row] = {}
    for row in rows:
        for advisory in row['advisories']:
            if (advisory.get('severity') or '').lower() != 'critical':
                continue
            key = (advisory['cve_id'], row['component_name'], row['version'])
            item = found.setdefault(
                key,
                {
                    'cve_id': advisory['cve_id'],
                    'url': advisory.get('url'),
                    'package': row['component_name'],
                    'version': row['version'],
                    'published_at': advisory.get('published_at')
                    or advisory.get('created_at'),
                    'projects': [],
                },
            )
            if row['project_name'] not in item['projects']:
                item['projects'].append(row['project_name'])
    return list(found.values())


async def gather(
    client: httpx.AsyncClient,
    email: str,
    stored: prefs_.Prefs | None,
) -> tuple[Gathered, prefs_.Prefs]:
    """Read the user, the preferences, and the visible sections.

    ``stored`` skips the read of the preferences when the caller
    has them already (after a write).

    """
    me: Row
    me, preferences = await asyncio.gather(
        _json(client, '/users/me'), _prefs(client, stored)
    )
    orgs: list[Row] = me.get('organizations') or []
    orgs.sort(key=lambda m: str(m['organization_name']).lower())
    org: Row | None = next(
        (m for m in orgs if m['organization_slug'] == preferences.org_slug),
        orgs[0] if orgs else None,
    )
    if org is None:
        return Gathered(None, [], [], {}), preferences
    slug: str = org['organization_slug']
    all_teams: list[Row] = me.get('teams') or []
    my_teams = [t for t in all_teams if t.get('organization_slug') == slug]
    visible = [
        k for k in preferences.order if preferences.display(k) != 'hidden'
    ]
    key = gathered_key(email)
    store = valkey.get_client()
    raw = await store.get(key)
    hit: Row | None = orjson.loads(raw) if raw else None
    if hit and hit['org'] == slug and set(visible) <= set(hit['data']):
        sections: dict[str, Json | Failure] = hit['data']
    else:
        granted: list[str] = org.get('permissions') or []
        permissions = set(granted)
        if me.get('is_admin'):
            permissions |= _SHARED_CACHE_PERMISSIONS
        sources = Sources(
            client,
            slug,
            email,
            [t['team_slug'] for t in my_teams],
            permissions,
        )
        results = await asyncio.gather(
            *(sources.section(k) for k in visible), return_exceptions=True
        )
        await sources.settle()
        sections = {}
        for k, result in zip(visible, results, strict=True):
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                LOGGER.warning('Home section %s failed: %r', k, result)
                sections[k] = Failure(type(result).__name__)
            else:
                sections[k] = result
        if not any(isinstance(s, Failure) for s in sections.values()):
            await store.set(
                key,
                orjson.dumps({'org': slug, 'data': sections}),
                ex=GATHERED_TTL,
            )
    notice = await store.getdel(notice_key(email))
    return (
        Gathered(
            org={'slug': slug, 'name': org['organization_name']},
            orgs=[
                {
                    'slug': o['organization_slug'],
                    'name': o['organization_name'],
                }
                for o in orgs
            ],
            teams=[t['team_name'] for t in my_teams],
            sections=sections,
            notice=notice.decode() if notice else None,
        ),
        preferences,
    )


async def _prefs(
    client: httpx.AsyncClient, preferences: prefs_.Prefs | None
) -> prefs_.Prefs:
    if preferences is not None:
        return preferences
    try:
        return await prefs_.read(client)
    except Exception:  # noqa: BLE001 -- the defaults apply
        # A layout that cannot load is no reason to show no data.
        LOGGER.warning('Could not read the Home preferences', exc_info=True)
        return prefs_.Prefs()
