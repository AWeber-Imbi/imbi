"""GitHub deployment plugins.

Three concrete subclasses share a common base and differ only by host:

* :class:`GitHubDeploymentPlugin` — github.com.
* :class:`GitHubEnterpriseCloudDeploymentPlugin` — GHEC tenant on
  ``*.ghe.com``.
* :class:`GitHubEnterpriseServerDeploymentPlugin` — operator-managed GHES.

Phase 1 implements ref / commit discovery, comparison, and workflow
dispatch.  Tag and release creation arrive with the Promote tab in
Phase 2.

The plugin runs as the user via the paired ``IdentityPlugin``: callers
materialize an :class:`~imbi_common.plugins.base.IdentityCredentials`
and pass the access token through ``credentials['access_token']``.
"""

from __future__ import annotations

import asyncio
import collections.abc
import datetime
import hashlib
import logging
import time
import typing
import urllib.parse

import httpx
from imbi_common.plugins.base import (
    CheckStatus,
    Commit,
    CompareResult,
    CredentialField,
    DeploymentPlugin,
    DeploymentRun,
    PluginContext,
    PluginManifest,
    PluginOption,
    Ref,
    RefInfo,
    ReleaseInfo,
)
from imbi_common.plugins.errors import PluginAuthenticationFailed

from imbi_plugin_github._hosts import normalize_host, require_ghec_tenant_host

LOGGER = logging.getLogger(__name__)

_DEFAULT_WORKFLOW = 'deploy.yml'
_DEFAULT_ENVIRONMENT_INPUT = 'environment'
_DEFAULT_REF_INPUT = 'ref'
_HTTP_TIMEOUT_SECONDS = 10.0
# Cap pagination so a pathological repo (10k+ branches/tags) can't pin
# us indefinitely.  100 per page * 10 pages = 1000 refs is plenty for
# the deployment-plugin UI's purposes.
_MAX_REF_PAGES = 10

# Process-wide cache of (token, host, repo) tuples for which the
# GitHub ``/check-runs`` endpoint has already returned 403 (insufficient
# scope, or Actions disabled on the repo). Keys are short SHA-256
# digests over the bearer token plus the resolved host and
# ``<owner>/<repo>`` so a single forbidden repo doesn't suppress CI
# status for every other repo the same user opens. Values are the
# unix timestamp at which the entry was recorded. Hydrating commit
# CI status spawns one call per commit; without this cache a missing
# scope produces 25+ wasted 403s every time the deploy dialog opens.
_CHECKS_DISABLED_TOKENS: dict[str, float] = {}
# How long to remember a 403 before re-probing. Long enough that a
# scope fix takes effect on the next session, short enough that we
# don't spam after the user fixes the underlying scope.
_CHECKS_DISABLED_TTL_SECONDS = 600.0


async def _raise_on_401(response: httpx.Response) -> None:
    """Convert a 401 from GitHub into :class:`PluginAuthenticationFailed`.

    Installed as an httpx response hook on the deployment client so the
    host's retry layer can refresh the actor's identity connection
    once before failing the user-visible request.  Other status codes
    pass through to ``raise_for_status`` (or per-call swallowing) as
    before.
    """
    if response.status_code != 401:
        return
    # The exception message is surfaced in API logs; reading the body
    # keeps GitHub's ``message`` field (e.g. "Bad credentials") in
    # the trail without leaking the bearer token.
    await response.aread()
    raise PluginAuthenticationFailed(
        f'GitHub 401 from {response.request.url}: {response.text}'
    )


def _accept_header() -> dict[str, str]:
    return {'Accept': 'application/vnd.github+json'}


def _auth_headers(token: str) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {token}',
        **_accept_header(),
    }


def _short_sha(sha: str) -> str:
    return sha[:7]


def _next_page_url(link_header: str | None) -> str | None:
    """Extract the ``rel="next"`` URL from a GitHub ``Link`` header.

    Returns ``None`` when no next page is advertised.
    """
    if not link_header:
        return None
    for part in link_header.split(','):
        section = part.strip()
        if not section.startswith('<'):
            continue
        end = section.find('>')
        if end == -1:
            continue
        url = section[1:end]
        params = section[end + 1 :]
        if 'rel="next"' in params:
            return url
    return None


def _query_param(url: str, name: str) -> str | None:
    """Return the first value of ``name`` in ``url``'s query string."""
    qs = urllib.parse.urlsplit(url).query
    values = urllib.parse.parse_qs(qs).get(name)
    if not values:
        return None
    return values[0]


def _parse_iso(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def _checks_cache_key(
    credentials: dict[str, str], host: str, owner: str, repo: str
) -> str | None:
    """Hash the bearer token together with the resolved host and
    ``<owner>/<repo>`` so the 403 cache is scoped per repo+host+token.

    Returns ``None`` when no token is present, which short-circuits
    both ``_checks_disabled`` and ``_record_checks_disabled``.
    """
    token = credentials.get('access_token') or credentials.get('token')
    if not token:
        return None
    material = f'{token}\n{host.lower()}\n{owner}/{repo}'
    return hashlib.sha256(material.encode()).hexdigest()


def _checks_disabled(
    credentials: dict[str, str], host: str, owner: str, repo: str
) -> bool:
    """Return ``True`` when this (token, host, repo) tuple has 403'd
    on ``/check-runs`` recently enough that we shouldn't probe again.
    """
    key = _checks_cache_key(credentials, host, owner, repo)
    if key is None:
        return False
    recorded = _CHECKS_DISABLED_TOKENS.get(key)
    if recorded is None:
        return False
    if time.monotonic() - recorded > _CHECKS_DISABLED_TTL_SECONDS:
        _CHECKS_DISABLED_TOKENS.pop(key, None)
        return False
    return True


def _record_checks_disabled(
    credentials: dict[str, str], host: str, owner: str, repo: str
) -> None:
    """Mark this (token, host, repo) as forbidden from ``/check-runs``
    for the TTL.

    Also opportunistically evicts any entries whose TTL has expired so
    the dict can't grow unbounded — ``_checks_disabled`` only prunes
    the key it looks up, which leaves long-tail stale tuples sitting
    around forever for tokens / repos that never get re-probed.
    """
    key = _checks_cache_key(credentials, host, owner, repo)
    if key is None:
        return
    now = time.monotonic()
    expired = [
        k
        for k, recorded in _CHECKS_DISABLED_TOKENS.items()
        if now - recorded > _CHECKS_DISABLED_TTL_SECONDS
    ]
    for k in expired:
        _CHECKS_DISABLED_TOKENS.pop(k, None)
    _CHECKS_DISABLED_TOKENS[key] = now


def _commit_from_payload(payload: dict[str, typing.Any]) -> Commit:
    """Convert a GitHub commit list/object payload into a :class:`Commit`."""
    sha = str(payload.get('sha', ''))
    commit_meta: dict[str, typing.Any] = payload.get('commit') or {}
    author_meta: dict[str, typing.Any] = commit_meta.get('author') or {}
    raw_message = str(commit_meta.get('message') or '')
    message_lines = raw_message.splitlines()
    return Commit(
        sha=sha,
        short_sha=_short_sha(sha),
        message=message_lines[0] if message_lines else '',
        author=author_meta.get('name'),
        authored_at=_parse_iso(author_meta.get('date')),
        url=payload.get('html_url'),
    )


def _check_runs_to_status(
    payload: dict[str, typing.Any],
) -> typing.Literal['pass', 'fail', 'warn', 'unknown']:
    """Roll up the GitHub /check-runs payload into a single status."""
    raw_runs: list[dict[str, typing.Any]] = payload.get('check_runs') or []
    if not raw_runs:
        return 'unknown'
    # Don't roll up while any run is still in flight — a mix of one
    # ``success`` and one ``in_progress`` would otherwise surface as
    # ``pass`` because the in-progress conclusion is ``None``.
    if any(str(run.get('status') or '') != 'completed' for run in raw_runs):
        return 'unknown'
    conclusions = {str(run.get('conclusion') or '') for run in raw_runs}
    failed = {'failure', 'timed_out', 'action_required'}
    if conclusions & failed:
        return 'fail'
    if 'cancelled' in conclusions or 'stale' in conclusions:
        return 'warn'
    if conclusions <= {'success', 'neutral', 'skipped', ''}:
        if 'success' in conclusions:
            return 'pass'
        return 'unknown'
    return 'unknown'


class _DeploymentBase(DeploymentPlugin):
    """Shared base for GitHub deployment plugins.

    Subclasses set :attr:`manifest` and override :meth:`_resolve_host`.
    Each plugin instance is single-shot: callers pass ``credentials``
    (from the paired :class:`IdentityPlugin`) and ``ctx`` per call.
    """

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        raise NotImplementedError

    def _api_base(self, options: dict[str, typing.Any]) -> str:
        host = self._resolve_host(options)
        if host == 'github.com':
            return 'https://api.github.com'
        if host.endswith('.ghe.com'):
            return f'https://api.{host}'
        return f'https://{host}/api/v3'

    # Reserved GitHub URL prefixes that share the host with repository
    # URLs but never point at a real ``<owner>/<repo>`` pair.  Any link
    # whose first path segment matches one of these is skipped during
    # owner/repo derivation so e.g. ``github.com/orgs/<org>`` or a
    # marketplace link can't silently bind a deployment to the wrong
    # target.
    _RESERVED_LINK_PREFIXES = frozenset(
        {
            'orgs',
            'marketplace',
            'settings',
            'enterprises',
            'features',
            'pricing',
            'about',
            'login',
            'logout',
            'signup',
            'sponsors',
            'topics',
            'collections',
            'trending',
            'codespaces',
            'notifications',
            'issues',
            'pulls',
            'search',
            'stars',
            'explore',
        }
    )

    @classmethod
    def _derive_owner_repo_from_links(
        cls, links: dict[str, str], host: str
    ) -> tuple[str, str] | None:
        """Find a project link pointing at ``host`` and parse owner/repo.

        Prefers an explicit ``github-repository`` link key when one is
        present and points at ``host``; otherwise scans the remaining
        same-host links and returns the first usable one.  Path entries
        whose first segment is a reserved GitHub route (e.g. ``orgs``,
        ``marketplace``) are rejected so a non-repo URL can't silently
        bind the deployment to a wrong target.  A trailing ``.git`` is
        stripped from the repo segment.  Returns ``None`` when nothing
        matches.
        """
        target = host.lower()
        preferred = links.get('github-repository')
        if preferred is not None:
            owner_repo = cls._parse_owner_repo(preferred, target)
            if owner_repo is not None:
                return owner_repo
        for key, url in links.items():
            if key == 'github-repository':
                continue
            owner_repo = cls._parse_owner_repo(url, target)
            if owner_repo is not None:
                return owner_repo
        return None

    @classmethod
    def _parse_owner_repo(
        cls, url: str, target_host: str
    ) -> tuple[str, str] | None:
        """Extract ``(owner, repo)`` from ``url`` when it's a repo URL on
        ``target_host``.  Returns ``None`` for other hosts, short paths,
        or reserved-prefix paths like ``/orgs/<org>``.
        """
        try:
            parsed = urllib.parse.urlparse(url)
        except ValueError:
            return None
        if (parsed.hostname or '').lower() != target_host:
            return None
        parts = [p for p in parsed.path.split('/') if p]
        if len(parts) < 2:
            return None
        if parts[0].lower() in cls._RESERVED_LINK_PREFIXES:
            return None
        return parts[0], parts[1].removesuffix('.git')

    def _owner_repo(self, ctx: PluginContext) -> tuple[str, str]:
        derived = self._derive_owner_repo_from_links(
            ctx.project_links, self._resolve_host(ctx.assignment_options)
        )
        if derived is not None:
            return derived
        # Final fallback: convention is ``<project_type_slug>/<project_slug>``.
        # Most projects carry a single type, so the first slug is what
        # callers expect; we don't probe each candidate against GitHub here
        # because ``_owner_repo`` is consulted on every API call.
        if ctx.project_type_slugs and ctx.project_slug:
            return ctx.project_type_slugs[0], ctx.project_slug
        raise ValueError(
            'GitHub deployment plugin could not determine the target '
            "repository: set the project's GitHub Repository link or "
            'tag the project with a ProjectType'
        )

    def _repo_url(self, ctx: PluginContext) -> str:
        owner, repo = self._owner_repo(ctx)
        return f'{self._api_base(ctx.assignment_options)}/repos/{owner}/{repo}'

    @staticmethod
    def _option_str(
        options: dict[str, typing.Any], key: str, default: str
    ) -> str:
        value = options.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default

    @staticmethod
    def _token(credentials: dict[str, str]) -> str:
        token = credentials.get('access_token') or credentials.get('token')
        if not token:
            raise ValueError(
                'GitHub deployment plugin requires an OAuth access token; '
                'expected ``credentials["access_token"]``'
            )
        return token

    def _client(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT_SECONDS,
            headers=_auth_headers(self._token(credentials)),
            base_url=self._repo_url(ctx),
            event_hooks={'response': [_raise_on_401]},
        )

    # -- Refs ---------------------------------------------------------------

    async def list_refs(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        kind: typing.Literal['default', 'branch', 'tag', 'all'] = 'all',
        query: str | None = None,
    ) -> list[Ref]:
        async with self._client(ctx, credentials) as client:
            tasks: list[collections.abc.Awaitable[list[Ref]]] = []
            if kind in ('default', 'branch', 'all'):
                # Resolve the repo's actual default branch up front so
                # ``_list_branches`` can suppress it without guessing —
                # the manifest option is just a hint and may be stale.
                default_branch = await self._fetch_default_branch(client)
                if kind in ('default', 'all'):
                    tasks.append(
                        self._list_default_ref(client, default_branch)
                    )
                if kind in ('branch', 'all'):
                    tasks.append(
                        self._list_branches(
                            client, default_branch, query=query
                        )
                    )
            if kind in ('tag', 'all'):
                tasks.append(self._list_tags(client, query=query))
            groups = await asyncio.gather(*tasks)
            return [ref for group in groups for ref in group]

    async def _fetch_default_branch(self, client: httpx.AsyncClient) -> str:
        # ``base_url`` is normalized with a trailing slash by httpx, so
        # ``client.get('')`` produces ``.../repos/<owner>/<repo>/`` which
        # GHEC's API gateway answers with a 404 even though the
        # trailing-slash form succeeds on github.com. Pass the absolute
        # URL with the trailing slash stripped so both backends agree.
        url = str(client.base_url).rstrip('/')
        repo_resp = await client.get(url)
        repo_resp.raise_for_status()
        repo_meta = typing.cast(dict[str, typing.Any], repo_resp.json())
        return str(repo_meta.get('default_branch') or 'main')

    async def _list_default_ref(
        self, client: httpx.AsyncClient, default_branch: str
    ) -> list[Ref]:
        branch_resp = await client.get(f'/branches/{default_branch}')
        if branch_resp.status_code != 200:
            return []
        branch = typing.cast(dict[str, typing.Any], branch_resp.json())
        branch_commit: dict[str, typing.Any] = branch.get('commit') or {}
        sha = str(branch_commit.get('sha') or '')
        return [
            Ref(
                name=default_branch,
                kind='default',
                sha=sha,
                is_default=True,
            )
        ]

    async def _paginate(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, str],
    ) -> list[dict[str, typing.Any]]:
        """Walk GitHub's ``Link: rel="next"`` pagination chain.

        Caps at ``_MAX_REF_PAGES`` so a pathological repo can't pin us
        on a single endpoint indefinitely.
        """
        all_rows: list[dict[str, typing.Any]] = []
        page_params: dict[str, str] = dict(params)
        for _ in range(_MAX_REF_PAGES):
            resp = await client.get(path, params=page_params)
            resp.raise_for_status()
            rows = typing.cast(list[dict[str, typing.Any]], resp.json())
            all_rows.extend(rows)
            next_url = _next_page_url(resp.headers.get('link'))
            if next_url is None:
                break
            # Pull the ``page`` cursor out of the Link header rather
            # than re-issuing against the absolute URL — keeps us on
            # the existing client base_url and respx-matchable.
            next_page = _query_param(next_url, 'page')
            if next_page is None:
                break
            page_params['page'] = next_page
        return all_rows

    async def _list_branches(
        self,
        client: httpx.AsyncClient,
        default_branch: str,
        query: str | None = None,
    ) -> list[Ref]:
        rows = await self._paginate(client, '/branches', {'per_page': '100'})
        out: list[Ref] = []
        for row in rows:
            name = str(row.get('name') or '')
            if not name or name == default_branch:
                continue
            if query and query.lower() not in name.lower():
                continue
            commit: dict[str, typing.Any] = row.get('commit') or {}
            sha = str(commit.get('sha') or '')
            out.append(Ref(name=name, kind='branch', sha=sha))
        return out

    async def _list_tags(
        self, client: httpx.AsyncClient, query: str | None = None
    ) -> list[Ref]:
        rows = await self._paginate(client, '/tags', {'per_page': '100'})
        out: list[Ref] = []
        for row in rows:
            name = str(row.get('name') or '')
            if not name:
                continue
            if query and query.lower() not in name.lower():
                continue
            commit: dict[str, typing.Any] = row.get('commit') or {}
            sha = str(commit.get('sha') or '')
            out.append(Ref(name=name, kind='tag', sha=sha))
        return out

    # -- Commits ------------------------------------------------------------

    async def list_commits(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        ref: str,
        limit: int = 25,
    ) -> list[Commit]:
        params = {'sha': ref, 'per_page': str(max(1, min(limit, 100)))}
        host = self._resolve_host(ctx.assignment_options)
        owner, repo = self._owner_repo(ctx)
        async with self._client(ctx, credentials) as client:
            resp = await client.get('/commits', params=params)
            resp.raise_for_status()
            rows = typing.cast(list[dict[str, typing.Any]], resp.json())
            commits = [_commit_from_payload(row) for row in rows]
            if commits:
                commits[0] = commits[0].model_copy(update={'is_head': True})
            if not commits or _checks_disabled(credentials, host, owner, repo):
                return commits
            # Probe the head commit synchronously: if check-runs is
            # forbidden for this token (missing scope or Actions
            # disabled on the repo) we'd otherwise issue one wasted
            # 403 per commit in parallel. Probing first lets the cache
            # short-circuit the rest.
            commits[0] = await self._hydrate_check_status(
                client, credentials, host, owner, repo, commits[0]
            )
            if len(commits) == 1 or _checks_disabled(
                credentials, host, owner, repo
            ):
                return commits
            tail = await asyncio.gather(
                *(
                    self._hydrate_check_status(
                        client, credentials, host, owner, repo, c
                    )
                    for c in commits[1:]
                )
            )
            return [commits[0], *tail]

    async def _hydrate_check_status(
        self,
        client: httpx.AsyncClient,
        credentials: dict[str, str],
        host: str,
        owner: str,
        repo: str,
        commit: Commit,
    ) -> Commit:
        if _checks_disabled(credentials, host, owner, repo):
            return commit
        try:
            resp = await client.get(f'/commits/{commit.sha}/check-runs')
        except httpx.HTTPError:
            return commit
        if resp.status_code == 403:
            _record_checks_disabled(credentials, host, owner, repo)
            return commit
        if resp.status_code != 200:
            return commit
        try:
            payload = typing.cast(dict[str, typing.Any], resp.json())
        except ValueError:
            return commit
        return commit.model_copy(
            update={'ci_status': _check_runs_to_status(payload)}
        )

    async def resolve_committish(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        committish: str,
    ) -> Commit:
        async with self._client(ctx, credentials) as client:
            resp = await client.get(
                f'/commits/{urllib.parse.quote(committish, safe="")}'
            )
            resp.raise_for_status()
            payload = typing.cast(dict[str, typing.Any], resp.json())
            return _commit_from_payload(payload)

    # -- Compare ------------------------------------------------------------

    async def compare(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        base: str,
        head: str,
    ) -> CompareResult:
        async with self._client(ctx, credentials) as client:
            quoted = urllib.parse.quote(f'{base}...{head}', safe='.')
            resp = await client.get(f'/compare/{quoted}')
            resp.raise_for_status()
            payload = typing.cast(dict[str, typing.Any], resp.json())
            commits_raw: list[dict[str, typing.Any]] = (
                payload.get('commits') or []
            )
            commits: list[Commit] = [
                _commit_from_payload(item) for item in commits_raw
            ]
            files: list[dict[str, typing.Any]] = payload.get('files') or []
            additions = sum(int(f.get('additions') or 0) for f in files)
            deletions = sum(int(f.get('deletions') or 0) for f in files)
            base_commit: dict[str, typing.Any] = (
                payload.get('base_commit')
                or payload.get('merge_base_commit')
                or {}
            )
            base_sha = str(base_commit.get('sha') or base)
            head_sha = commits[-1].sha if commits else head
            return CompareResult(
                base_sha=base_sha,
                head_sha=head_sha,
                ahead=int(payload.get('ahead_by') or 0),
                behind=int(payload.get('behind_by') or 0),
                commits=commits,
                files_changed=len(files),
                additions=additions,
                deletions=deletions,
            )

    # -- Tags / Releases (Phase 2 — implemented here for completeness) -----

    async def create_tag(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        sha: str,
        tag: str,
        message: str,
    ) -> RefInfo:
        async with self._client(ctx, credentials) as client:
            tag_resp = await client.post(
                '/git/tags',
                json={
                    'tag': tag,
                    'message': message,
                    'object': sha,
                    'type': 'commit',
                },
            )
            tag_resp.raise_for_status()
            tag_payload = typing.cast(dict[str, typing.Any], tag_resp.json())
            ref_resp = await client.post(
                '/git/refs',
                json={
                    'ref': f'refs/tags/{tag}',
                    'sha': str(tag_payload.get('sha') or sha),
                },
            )
            ref_resp.raise_for_status()
            ref_payload = typing.cast(dict[str, typing.Any], ref_resp.json())
            return RefInfo(
                name=str(ref_payload.get('ref') or f'refs/tags/{tag}'),
                sha=str(ref_payload.get('object', {}).get('sha') or sha),
                url=ref_payload.get('url'),
            )

    async def create_release(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        tag: str,
        name: str,
        body_markdown: str,
        prerelease: bool = False,
    ) -> ReleaseInfo:
        async with self._client(ctx, credentials) as client:
            resp = await client.post(
                '/releases',
                json={
                    'tag_name': tag,
                    'name': name,
                    'body': body_markdown,
                    'prerelease': prerelease,
                },
            )
            resp.raise_for_status()
            payload = typing.cast(dict[str, typing.Any], resp.json())
            return ReleaseInfo(
                id=str(payload.get('id') or ''),
                tag=str(payload.get('tag_name') or tag),
                name=payload.get('name'),
                url=payload.get('url'),
                html_url=payload.get('html_url'),
                prerelease=bool(payload.get('prerelease', prerelease)),
            )

    # -- Workflow dispatch --------------------------------------------------

    async def trigger_deployment(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        ref_or_sha: str,
        inputs: dict[str, str] | None = None,
    ) -> DeploymentRun:
        options = ctx.assignment_options
        workflow = self._option_str(options, 'workflow', _DEFAULT_WORKFLOW)
        env_input = self._option_str(
            options, 'environment_input', _DEFAULT_ENVIRONMENT_INPUT
        )
        ref_input = self._option_str(options, 'ref_input', _DEFAULT_REF_INPUT)
        if not ctx.environment:
            raise ValueError(
                'trigger_deployment requires PluginContext.environment'
            )
        # Caller-supplied inputs come first; the reserved env/ref keys
        # are written last so the plugin's contract (deploy *this* ref
        # to *this* environment) can't be subverted by a stray entry.
        body_inputs: dict[str, str] = dict(inputs or {})
        body_inputs[env_input] = ctx.environment
        body_inputs[ref_input] = ref_or_sha
        # Capture the dispatch instant *before* POSTing so we can
        # correlate the resulting workflow run on the listing endpoint.
        # GitHub records ``created_at`` with second precision, so subtract
        # a small skew to avoid losing the run to clock drift.
        dispatch_started = datetime.datetime.now(
            datetime.UTC
        ) - datetime.timedelta(seconds=2)
        async with self._client(ctx, credentials) as client:
            dispatch_resp = await client.post(
                f'/actions/workflows/{workflow}/dispatches',
                json={'ref': ref_or_sha, 'inputs': body_inputs},
            )
            dispatch_resp.raise_for_status()
            # GitHub returns 204 with no body — find the run we just
            # created by listing recent runs and matching event +
            # creation time (and ref when present) so a concurrent
            # dispatch can't bind us to its run.
            runs_resp = await client.get(
                f'/actions/workflows/{workflow}/runs',
                params={'event': 'workflow_dispatch', 'per_page': '10'},
            )
            run_id = ''
            run_url: str | None = None
            if runs_resp.status_code == 200:
                payload = typing.cast(dict[str, typing.Any], runs_resp.json())
                runs: list[dict[str, typing.Any]] = (
                    payload.get('workflow_runs') or []
                )
                match = self._match_dispatched_run(
                    runs, dispatch_started, ref_or_sha
                )
                if match is not None:
                    run_id = str(match.get('id') or '')
                    run_url = match.get('html_url')
            return DeploymentRun(
                run_id=run_id,
                run_url=run_url,
                status='queued',
            )

    @staticmethod
    def _match_dispatched_run(
        runs: list[dict[str, typing.Any]],
        dispatch_started: datetime.datetime,
        ref_or_sha: str,
    ) -> dict[str, typing.Any] | None:
        """Pick the run created by the dispatch we just issued.

        Only runs whose ``head_branch`` or ``head_sha`` explicitly
        match ``ref_or_sha`` and whose ``created_at`` is at or after
        ``dispatch_started`` are eligible.  Returns ``None`` when the
        result is ambiguous (zero or multiple matches) — the caller
        surfaces an empty ``run_id`` rather than binding to someone
        else's run.
        """
        candidates: list[dict[str, typing.Any]] = []
        for run in runs:
            created = _parse_iso(run.get('created_at'))
            if created is None or created < dispatch_started:
                continue
            head_branch = run.get('head_branch')
            head_sha = run.get('head_sha')
            if head_branch == ref_or_sha or head_sha == ref_or_sha:
                candidates.append(run)
        if len(candidates) == 1:
            return candidates[0]
        return None

    async def get_check_status(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        committish: str,
    ) -> CheckStatus:
        """Aggregate ``/commits/{ref}/check-runs`` to a single status.

        Tolerates the same failure modes as commit-level hydration:
        network errors, non-200 responses, and unparseable JSON all
        degrade to ``'unknown'`` rather than raising — the release
        train should never fail to render because a side hydration
        call hiccuped.
        """
        host = self._resolve_host(ctx.assignment_options)
        owner, repo = self._owner_repo(ctx)
        if _checks_disabled(credentials, host, owner, repo):
            return 'unknown'
        encoded = urllib.parse.quote(committish, safe='')
        async with self._client(ctx, credentials) as client:
            try:
                resp = await client.get(f'/commits/{encoded}/check-runs')
            except httpx.HTTPError:
                return 'unknown'
            if resp.status_code == 403:
                _record_checks_disabled(credentials, host, owner, repo)
                return 'unknown'
            if resp.status_code != 200:
                return 'unknown'
            try:
                payload = typing.cast(dict[str, typing.Any], resp.json())
            except ValueError:
                return 'unknown'
            return _check_runs_to_status(payload)

    async def get_deployment_status(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        run_id: str,
    ) -> DeploymentRun:
        async with self._client(ctx, credentials) as client:
            resp = await client.get(f'/actions/runs/{run_id}')
            resp.raise_for_status()
            payload = typing.cast(dict[str, typing.Any], resp.json())
            status_raw = str(payload.get('status') or '')
            conclusion = str(payload.get('conclusion') or '')
            status: typing.Literal[
                'queued',
                'in_progress',
                'success',
                'failure',
                'cancelled',
                'unknown',
            ]
            if status_raw == 'queued':
                status = 'queued'
            elif status_raw == 'in_progress':
                status = 'in_progress'
            elif conclusion == 'success':
                status = 'success'
            elif conclusion in {'failure', 'timed_out', 'action_required'}:
                status = 'failure'
            elif conclusion == 'cancelled':
                status = 'cancelled'
            else:
                status = 'unknown'
            return DeploymentRun(
                run_id=str(payload.get('id') or run_id),
                run_url=payload.get('html_url'),
                status=status,
                started_at=_parse_iso(payload.get('run_started_at')),
                completed_at=_parse_iso(payload.get('updated_at'))
                if conclusion
                else None,
            )


_COMMON_OPTIONS: list[PluginOption] = [
    PluginOption(
        name='workflow',
        label='Workflow file',
        description='File name in .github/workflows to dispatch.',
        type='string',
        default=_DEFAULT_WORKFLOW,
    ),
    PluginOption(
        name='environment_input',
        label='Environment input name',
        type='string',
        default=_DEFAULT_ENVIRONMENT_INPUT,
    ),
    PluginOption(
        name='ref_input',
        label='Ref input name',
        type='string',
        default=_DEFAULT_REF_INPUT,
    ),
]

_COMMON_CREDENTIALS: list[CredentialField] = [
    CredentialField(
        name='access_token',
        label='Service-account PAT (optional fallback)',
        description=(
            'Personal access token used when no per-user identity is '
            'bound.  Requires contents:write and actions:write scopes.'
        ),
        required=False,
    ),
]


class GitHubDeploymentPlugin(_DeploymentBase):
    manifest = PluginManifest(
        slug='github-deployment',
        name='GitHub Deployment',
        description=(
            'Drive github.com workflow_dispatch deployments and record '
            'GitHub Releases on behalf of an Imbi project.'
        ),
        plugin_type='deployment',
        options=_COMMON_OPTIONS,
        credentials=_COMMON_CREDENTIALS,
    )

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        return 'github.com'


class GitHubEnterpriseCloudDeploymentPlugin(_DeploymentBase):
    manifest = PluginManifest(
        slug='github-deployment-ec',
        name='GitHub Enterprise Cloud Deployment',
        description=(
            'Drive workflow_dispatch deployments against a GHEC tenant '
            '(``*.ghe.com``).'
        ),
        plugin_type='deployment',
        options=[
            PluginOption(
                name='host',
                label='GHEC tenant host',
                description='e.g. tenant.ghe.com',
                type='string',
                required=True,
            ),
            *_COMMON_OPTIONS,
        ],
        credentials=_COMMON_CREDENTIALS,
    )

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        return require_ghec_tenant_host(
            normalize_host(options.get('host'), 'GHEC deployment plugin'),
            'GHEC deployment plugin',
        )


class GitHubEnterpriseServerDeploymentPlugin(_DeploymentBase):
    manifest = PluginManifest(
        slug='github-deployment-es',
        name='GitHub Enterprise Server Deployment',
        description=(
            'Drive workflow_dispatch deployments against a GHES install.'
        ),
        plugin_type='deployment',
        options=[
            PluginOption(
                name='host',
                label='GHES host',
                type='string',
                required=True,
            ),
            *_COMMON_OPTIONS,
        ],
        credentials=_COMMON_CREDENTIALS,
    )

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        return normalize_host(options.get('host'), 'GHES deployment plugin')
