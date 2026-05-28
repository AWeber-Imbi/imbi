"""GitHub deployment plugins.

Three concrete subclasses share a common base and differ only by host:

* :class:`GitHubDeploymentPlugin` — github.com.
* :class:`GitHubEnterpriseCloudDeploymentPlugin` — GHEC tenant on
  ``*.ghe.com``.
* :class:`GitHubEnterpriseServerDeploymentPlugin` — operator-managed GHES.

Plugins drive the GitHub Deployments API
(``POST /repos/{owner}/{repo}/deployments``) rather than
``workflow_dispatch`` — Imbi's ``Environment`` maps 1:1 to GitHub's
``environment`` field, deployment protection rules apply server-side,
and ``GET /deployments/{id}/statuses`` gives a clean status loop.
Tag/release creation is handled separately by ``create_tag`` and
``create_release`` and continues to feed projects whose deploys are
triggered by ``on: release: [published]`` instead of ``on: deployment``.

The plugin runs as the user via the paired ``IdentityPlugin``: callers
materialize an :class:`~imbi_common.plugins.base.IdentityCredentials`
and pass the access token through ``credentials['access_token']``.
"""

from __future__ import annotations

import asyncio
import collections.abc
import contextlib
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
    DeploymentEventStatus,
    DeploymentPlugin,
    DeploymentRun,
    OpsLogTemplate,
    PluginContext,
    PluginEdgeLabel,
    PluginManifest,
    PluginOption,
    Ref,
    RefInfo,
    ReleaseInfo,
    RemoteDeployment,
    RepositoryRelocation,
    WorkflowFile,
)
from imbi_common.plugins.errors import PluginAuthenticationFailed

from imbi_plugin_github._hosts import normalize_host, require_ghec_tenant_host
from imbi_plugin_github._repos import (
    derive_owner_repo_from_links,
    parse_owner_repo,
    resolve_owner_repo,
)

LOGGER = logging.getLogger(__name__)

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


def _repo_root_from_redirect(location: str) -> str | None:
    """Derive the canonical repo-root URL from a rename redirect target.

    GitHub answers a request to a renamed repo with a ``301`` whose
    ``Location`` points at the by-id form, e.g.
    ``https://api.host/repositories/687046/commits``.  Strip the
    sub-resource path back to ``https://api.host/repositories/687046`` so
    we can ``GET`` it for the repo's current ``full_name``/``html_url``.
    Returns ``None`` when ``location`` isn't a ``/repositories/{id}`` URL.
    """
    parsed = urllib.parse.urlsplit(location)
    parts = [segment for segment in parsed.path.split('/') if segment]
    try:
        idx = parts.index('repositories')
    except ValueError:
        return None
    if idx + 1 >= len(parts):
        return None
    repo_id = parts[idx + 1]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, f'/repositories/{repo_id}', '', '')
    )


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

    def _owner_repo(self, ctx: PluginContext) -> tuple[str, str]:
        return resolve_owner_repo(
            ctx,
            self._resolve_host(ctx.assignment_options),
            'GitHub deployment plugin',
        )

    # Backwards-compatible aliases for the previously private helpers.
    # The actual logic lives in :mod:`imbi_plugin_github._repos`; these
    # remain so existing tests that reach into the class continue to
    # work and so subclasses overriding the resolution path still have
    # a stable surface to hook into.
    _derive_owner_repo_from_links = staticmethod(derive_owner_repo_from_links)
    _parse_owner_repo = staticmethod(parse_owner_repo)

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

    @contextlib.asynccontextmanager
    async def _client(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> collections.abc.AsyncGenerator[httpx.AsyncClient]:
        """Yield an httpx client that survives — and self-heals — renames.

        ``follow_redirects=True`` means a renamed repo's ``301`` is
        followed and the request transparently retried against the
        canonical ``/repositories/{id}`` location instead of crashing in
        ``raise_for_status``.  A response hook records that redirect; once
        the caller's request succeeds we resolve the repo's new
        ``full_name``/``html_url`` and stash a
        :class:`~imbi_common.plugins.base.RepositoryRelocation` on ``ctx``
        so the host can self-heal the project's stored link.  This is the
        single chokepoint for every deployment call.
        """
        captured: list[str] = []

        async def _capture_redirect(response: httpx.Response) -> None:
            if response.is_redirect:
                location = response.headers.get('location') or ''
                if '/repositories/' in location:
                    captured.append(location)

        client = httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT_SECONDS,
            headers=_auth_headers(self._token(credentials)),
            base_url=self._repo_url(ctx),
            follow_redirects=True,
            event_hooks={'response': [_capture_redirect, _raise_on_401]},
        )
        async with client:
            yield client
            # Only after the caller's request succeeded: a captured
            # redirect means the repo was renamed out from under the
            # stored link.  Resolve the new name once and report it.
            if captured and ctx.repository_relocation is None:
                await self._record_relocation(client, ctx, captured[-1])

    async def _record_relocation(
        self,
        client: httpx.AsyncClient,
        ctx: PluginContext,
        redirect_location: str,
    ) -> None:
        """Resolve a renamed repo's canonical name and stash it on ``ctx``.

        Best-effort: any failure to resolve the repo root leaves
        ``ctx.repository_relocation`` unset so the user-facing call (which
        already succeeded via the followed redirect) is never disturbed.
        """
        repo_root = _repo_root_from_redirect(redirect_location)
        if repo_root is None:
            return
        try:
            resp = await client.get(repo_root)
        except (httpx.HTTPError, PluginAuthenticationFailed):
            # The user-facing request already succeeded; a probe failure
            # (network, or a 401 surfaced by the response hook) must not
            # turn that success into an error during teardown.
            return
        if resp.status_code != 200:
            return
        try:
            payload = typing.cast(dict[str, typing.Any], resp.json())
        except ValueError:
            return
        full_name = str(payload.get('full_name') or '')
        html_url = str(payload.get('html_url') or '')
        if not full_name or not html_url:
            return
        old_owner, old_repo = self._owner_repo(ctx)
        old_owner_repo = f'{old_owner}/{old_repo}'
        if full_name.lower() == old_owner_repo.lower():
            return
        ctx.repository_relocation = RepositoryRelocation(
            link_key='github-repository',
            new_url=html_url,
            old_owner_repo=old_owner_repo,
            new_owner_repo=full_name,
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

    # -- Tags / Releases ----------------------------------------------------

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

    # -- Deployments --------------------------------------------------------

    async def trigger_deployment(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        ref_or_sha: str,
        inputs: dict[str, str] | None = None,
    ) -> DeploymentRun:
        """Create a GitHub Deployment via ``POST /repos/{o}/{r}/deployments``.

        Imbi's ``Environment`` maps 1:1 to GitHub's ``environment`` field,
        so the deployment is bound to the target env server-side and any
        environment protection rules (required reviewers, branch policies,
        wait timers) are enforced by GitHub before the deploy workflow
        runs.  Repos consume this via ``on: deployment`` (or
        ``on: deployment_status``) in their workflow files.

        ``auto_merge=False`` keeps GitHub from silently merging the base
        branch into the ref before deploying — which routinely fails on
        protected branches.  ``required_contexts=[]`` skips the default
        gate that demands every check-run on the ref already be green;
        promote refs are often freshly-cut tags whose CI hasn't run yet,
        and the deploy workflow itself is what we're waiting on.

        Payload precedence (lowest → highest): plugin assignment
        ``env_payloads[env_slug]`` (carried by the host on
        ``ctx.environment_config``) below the ``inputs`` map from the
        caller.  The ``ref`` and ``environment`` are not part of the
        payload — they're top-level fields on the deployment object.
        """
        if not ctx.environment:
            raise ValueError(
                'trigger_deployment requires PluginContext.environment'
            )
        merged_payload: dict[str, typing.Any] = dict(ctx.environment_config)
        if inputs:
            merged_payload.update(inputs)
        async with self._client(ctx, credentials) as client:
            resp = await client.post(
                '/deployments',
                json={
                    'ref': ref_or_sha,
                    'environment': ctx.environment,
                    'auto_merge': False,
                    'required_contexts': [],
                    'payload': merged_payload,
                },
            )
            resp.raise_for_status()
            payload = typing.cast(dict[str, typing.Any], resp.json())
            deployment_id = str(payload.get('id') or '')
            return DeploymentRun(
                run_id=deployment_id,
                # GitHub's ``Deployment`` object has no ``html_url`` —
                # the human-facing URL surfaces only after the deploy
                # workflow posts its first status with a ``log_url``
                # (see :meth:`get_deployment_status`).  Leaving this
                # ``None`` is honest about the state at create time.
                run_url=None,
                status='queued',
            )

    async def list_workflows(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[WorkflowFile]:
        """List ``.github/workflows/*.yml`` registered for the repo.

        Used by the UI to populate a workflow dropdown when an operator
        configures plugin assignment ``env_payloads``.  Returns only
        ``active`` workflows by default; callers that need disabled
        entries can filter the result themselves.  GitHub caps the
        ``/actions/workflows`` page at 100 — that's more than enough for
        any real repo, so this intentionally doesn't paginate.
        """
        async with self._client(ctx, credentials) as client:
            resp = await client.get(
                '/actions/workflows', params={'per_page': '100'}
            )
            resp.raise_for_status()
            payload = typing.cast(dict[str, typing.Any], resp.json())
            workflows: list[dict[str, typing.Any]] = (
                payload.get('workflows') or []
            )
            return [
                WorkflowFile(
                    id=str(w.get('id') or ''),
                    path=str(w.get('path') or ''),
                    name=str(w.get('name') or ''),
                    state=str(w.get('state') or 'active'),
                )
                for w in workflows
            ]

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
        """Aggregate a GitHub Deployment's status history.

        ``run_id`` is the GitHub deployment id returned by
        :meth:`trigger_deployment`.  GitHub returns status updates
        newest-first; the latest entry wins.  An empty list means the
        deploy workflow hasn't posted anything yet, which Imbi surfaces
        as ``'queued'``.

        ``log_url`` (and the legacy ``target_url``) on the latest status
        is what the deploy workflow set to point at its own logs (e.g.
        the Actions run URL).  We carry that as ``run_url`` so the UI
        can deep-link without having to walk back to the workflow run
        through a check-suite join.
        """
        async with self._client(ctx, credentials) as client:
            resp = await client.get(f'/deployments/{run_id}/statuses')
            resp.raise_for_status()
            statuses = typing.cast(list[dict[str, typing.Any]], resp.json())
            if not statuses:
                return DeploymentRun(run_id=str(run_id), status='queued')
            latest = statuses[0]
            state = str(latest.get('state') or '').lower()
            status: typing.Literal[
                'queued',
                'in_progress',
                'success',
                'failure',
                'cancelled',
                'unknown',
            ]
            if state in {'pending', 'queued', 'waiting'}:
                status = 'queued'
            elif state == 'in_progress':
                status = 'in_progress'
            elif state == 'success':
                status = 'success'
            elif state in {'failure', 'error'}:
                status = 'failure'
            elif state == 'inactive':
                # Deployment was superseded by a newer one for the same
                # env — Imbi treats that as cancelled rather than failed.
                status = 'cancelled'
            else:
                status = 'unknown'
            log_url = latest.get('log_url') or latest.get('target_url')
            completed = status in {'success', 'failure', 'cancelled'}
            return DeploymentRun(
                run_id=str(run_id),
                run_url=str(log_url) if log_url else None,
                status=status,
                started_at=_parse_iso(latest.get('created_at')),
                completed_at=_parse_iso(latest.get('updated_at'))
                if completed
                else None,
            )

    async def list_recent_deployments(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        environments: list[str],
        limit: int = 1,
    ) -> list[RemoteDeployment]:
        """Return the latest ``limit`` deployments per environment.

        Fans out one ``GET /deployments?environment={env}`` call per
        requested environment in parallel, then for each returned
        deployment fetches the latest status via ``GET
        /deployments/{id}/statuses?per_page=1``.  Environments the
        remote does not recognise are silently skipped so a partial
        resync still returns the deployments that do exist (an env
        the repo simply hasn't deployed to yet is the common case).

        The host calls this from the resync flow only when webhook
        delivery has lapsed, so we keep the fan-out modest (``limit=1``
        is the host's default) and let the host walk further history
        with explicit pagination if it ever needs to.
        """
        page_size = max(1, min(limit, 100))
        async with self._client(ctx, credentials) as client:
            per_env = await asyncio.gather(
                *(
                    self._list_deployments_for_env(client, env, page_size)
                    for env in environments
                )
            )
        return [observed for group in per_env for observed in group]

    async def _list_deployments_for_env(
        self,
        client: httpx.AsyncClient,
        environment: str,
        page_size: int,
    ) -> list[RemoteDeployment]:
        try:
            resp = await client.get(
                '/deployments',
                params={
                    'environment': environment,
                    'per_page': str(page_size),
                },
            )
            if resp.status_code == 404:
                # Repo or environment unknown on the remote — treat as
                # "nothing to backfill" rather than failing the resync.
                return []
            resp.raise_for_status()
        except httpx.HTTPError:
            LOGGER.warning(
                'Failed to list deployments for env=%s',
                environment,
                exc_info=True,
            )
            return []
        try:
            deployments = typing.cast(list[dict[str, typing.Any]], resp.json())
        except ValueError:
            LOGGER.warning(
                'Failed to parse deployments payload for env=%s',
                environment,
            )
            return []
        observed: list[RemoteDeployment] = []
        for deployment in deployments:
            run = await self._observe_deployment(
                client, environment, deployment
            )
            if run is not None:
                observed.append(run)
        return observed

    async def _observe_deployment(
        self,
        client: httpx.AsyncClient,
        environment: str,
        deployment: dict[str, typing.Any],
    ) -> RemoteDeployment | None:
        deployment_id = deployment.get('id')
        sha = deployment.get('sha')
        if not deployment_id or not sha:
            # GitHub always returns both, but defend the resync path
            # against a malformed response — we'd rather skip one row
            # than corrupt the graph by inventing identifiers.
            return None
        created_at = _parse_iso(deployment.get('created_at')) or (
            datetime.datetime.now(datetime.UTC)
        )
        status, status_url = await self._latest_status(
            client, str(deployment_id)
        )
        ref_value = deployment.get('ref')
        description = deployment.get('description')
        deployment_url = deployment.get('url') or deployment.get('html_url')
        creator_login: str | None = None
        creator_raw = deployment.get('creator')
        if isinstance(creator_raw, dict):
            creator_dict = typing.cast(dict[str, typing.Any], creator_raw)
            login = creator_dict.get('login')
            if isinstance(login, str) and login:
                creator_login = login
        return RemoteDeployment(
            environment=environment,
            sha=str(sha),
            ref=str(ref_value) if ref_value else None,
            status=status,
            created_at=created_at,
            external_run_id=str(deployment_id),
            run_url=status_url,
            deployment_url=str(deployment_url) if deployment_url else None,
            description=str(description) if description else None,
            creator=creator_login,
        )

    async def _latest_status(
        self, client: httpx.AsyncClient, deployment_id: str
    ) -> tuple[DeploymentEventStatus, str | None]:
        """Return the canonical event status + workflow log URL.

        Falls back to ``'pending'`` whenever the deploy workflow has
        not yet posted a status: a freshly-created deployment with no
        statuses is structurally identical to one whose workflow has
        not started, and ``pending`` is the host's vocabulary for
        both.  Network / parse errors degrade the same way so resync
        is never blocked by a single noisy row.
        """
        try:
            resp = await client.get(
                f'/deployments/{deployment_id}/statuses',
                params={'per_page': '1'},
            )
        except httpx.HTTPError:
            return 'pending', None
        if resp.status_code != 200:
            return 'pending', None
        try:
            statuses = typing.cast(list[dict[str, typing.Any]], resp.json())
        except ValueError:
            return 'pending', None
        if not statuses:
            return 'pending', None
        latest = statuses[0]
        state = str(latest.get('state') or '').lower()
        log_url = latest.get('log_url') or latest.get('target_url')
        return _to_event_status(state), str(log_url) if log_url else None


def _to_event_status(github_state: str) -> DeploymentEventStatus:
    """Map a GitHub deployment-status ``state`` to the host vocabulary.

    Unknown states fold to ``pending`` rather than raising so a single
    novel value on the remote does not break resync for the whole
    project.  ``inactive`` on GitHub means a newer deployment for the
    same environment superseded this one, which the host models as
    ``rolled_back`` on the ``DeploymentEvent``.
    """
    if github_state in {'pending', 'queued', 'waiting'}:
        return 'pending'
    if github_state == 'in_progress':
        return 'in_progress'
    if github_state == 'success':
        return 'success'
    if github_state in {'failure', 'error'}:
        return 'failed'
    if github_state == 'inactive':
        return 'rolled_back'
    return 'pending'


_COMMON_OPTIONS: list[PluginOption] = []

# Promote behaviour is now inferred from the ``body.tag`` shape on the
# imbi-api side: semver tags trigger a Deployment, raw SHAs cut a tag
# + GitHub Release.  Per-env workflow input overrides live on the
# ``USES_PLUGIN`` edge under ``env_payloads`` (keyed by env slug),
# resolved by the host and passed in via ``ctx.environment_config``.
_COMMON_EDGE_LABELS: list[PluginEdgeLabel] = []

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


# Templates for the operations-log JSON payload the API writes from
# ``_record_deployment_event`` in imbi-api: ``{action, plugin_slug,
# run_url, release_url, from_environment}``.  Row-level fields
# ``version`` and ``environment`` (from the entry's
# ``environment_slug``/``environment.name``) are also in scope.
_COMMON_OPS_LOG_TEMPLATES: dict[str, OpsLogTemplate] = {
    'deploy': OpsLogTemplate(
        label='Deployed {{version}} to {{environment}}',
        summary='deployed',
    ),
    'redeploy': OpsLogTemplate(
        label='Re-deployed {{version}} to {{environment}}',
        summary='re-deployed',
    ),
    'promote': OpsLogTemplate(
        label=(
            'Promoted {{from_environment}} to {{environment}} as {{version}}.'
        ),
        summary='promoted',
    ),
    'resync': OpsLogTemplate(
        label='Recorded {{version}} deploy in {{environment}}',
        summary='recorded a deploy in',
    ),
}


class GitHubDeploymentPlugin(_DeploymentBase):
    manifest = PluginManifest(
        slug='github-deployment',
        name='GitHub Deployment',
        description=(
            'Drive github.com Deployments and record GitHub Releases '
            'on behalf of an Imbi project.  Each promote creates a '
            'Deployment object so GitHub environment protection rules '
            '(required reviewers, branch policies, wait timers) apply '
            'server-side.'
        ),
        plugin_type='deployment',
        supports_deployment_sync=True,
        options=_COMMON_OPTIONS,
        credentials=_COMMON_CREDENTIALS,
        edge_labels=_COMMON_EDGE_LABELS,
        ops_log_templates=_COMMON_OPS_LOG_TEMPLATES,
    )

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        return 'github.com'


class GitHubEnterpriseCloudDeploymentPlugin(_DeploymentBase):
    manifest = PluginManifest(
        slug='github-deployment-ec',
        name='GitHub Enterprise Cloud Deployment',
        description=(
            'Drive GitHub Deployments against a GHEC tenant '
            '(``*.ghe.com``).  Repos must use ``on: deployment`` (or '
            '``on: deployment_status``) in their deploy workflow.'
        ),
        plugin_type='deployment',
        supports_deployment_sync=True,
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
        edge_labels=_COMMON_EDGE_LABELS,
        ops_log_templates=_COMMON_OPS_LOG_TEMPLATES,
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
            'Drive GitHub Deployments against a GHES install.  Repos '
            'must use ``on: deployment`` (or ``on: deployment_status``) '
            'in their deploy workflow.'
        ),
        plugin_type='deployment',
        supports_deployment_sync=True,
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
        edge_labels=_COMMON_EDGE_LABELS,
        ops_log_templates=_COMMON_OPS_LOG_TEMPLATES,
    )

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        return normalize_host(options.get('host'), 'GHES deployment plugin')
