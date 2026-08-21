"""GitHub deployment capability handler.

:class:`GitHubDeployment` resolves its host from the Integration's
``flavor`` + ``host`` options on ``ctx.integration_options`` (github.com,
a ``*.ghe.com`` GHEC tenant, or an operator-managed GHES appliance), and
reads ``mainline_branches`` from the same map to know which deployment
refs are branches rather than release tags (see
:func:`_mainline_branches`).

*Deploying* drives the GitHub Deployments API
(``POST /repos/{owner}/{repo}/deployments``) rather than
``workflow_dispatch`` — Imbi's ``Environment`` maps 1:1 to GitHub's
``environment`` field, deployment protection rules apply server-side,
and ``GET /deployments/{id}/statuses`` gives a clean status loop.
Tag/release creation is handled separately by ``create_tag`` and
``create_release`` and continues to feed projects whose deploys are
triggered by ``on: release: [published]`` instead of ``on: deployment``.

*Building the artifact that a deployment deploys* is the separate,
earlier stage: ``create_deployment_artifact`` dispatches a release
workflow, and ``get_artifact_run_status`` reports it. These deliberately
do not share :class:`~imbi.common.plugins.base.DeploymentRun` or its
status endpoint with the deploy stage — a workflow run id and a
Deployment id are different identifier spaces on the same remote, and
resolving one through the other's endpoint 404s.

The handler runs as the acting user: the host passes the materialized
access token through the Integration credential blob's
``credentials['access_token']``.
"""

from __future__ import annotations

import asyncio
import base64
import collections.abc
import contextlib
import datetime
import hashlib
import logging
import re
import time
import typing
import urllib.parse

import httpx

from imbi.common.plugins.base import (
    ArtifactRun,
    CheckStatus,
    Commit,
    CompareResult,
    DeploymentCapability,
    DeploymentEventStatus,
    DeploymentRun,
    EnvironmentDeploymentState,
    LinkWriteback,
    NotesListing,
    PluginContext,
    Ref,
    RefInfo,
    ReleaseInfo,
    RemoteDeployment,
    RemoteRelease,
    WorkflowFile,
)
from imbi.common.plugins.errors import PluginAuthenticationFailed
from imbi.plugins.github._hosts import flavor_host, host_to_api_base
from imbi.plugins.github._repos import (
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

# Pinned *per call* on the workflow-dispatch request only -- never on the
# shared client.  From this version GitHub answers a dispatch with 200 +
# a body naming the run it started, instead of a bodiless 204; older
# appliances ignore the header and keep returning 204 (see
# ``create_deployment_artifact``).  Raising the version for every
# deployment call would be a far wider behavioural change than the one
# response body we're after.
_DISPATCH_API_VERSION = '2026-03-10'
# Raised from 10 to 25 by GitHub in December 2025. Checked client-side so
# an over-long payload names itself instead of coming back as an opaque
# 422 -- but the remote stays the authority: a GHES release predating the
# increase still caps at 10, and that 422 propagates rather than being
# second-guessed here.
_MAX_DISPATCH_INPUTS = 25

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


#: A push event's ``before`` when the ref did not exist until now.
_ZERO_SHA = '0' * 40
# GitHub's compare endpoint lists at most 300 changed files and offers
# no pagination for them -- a list this long may be incomplete.
_COMPARE_FILES_CAP = 300
# How many note-blob reads run at once when listing a whole notes tree.
_NOTE_BLOB_CONCURRENCY = 10

_FULL_SHA_PATTERN = re.compile(r'^[0-9a-f]{40}$')


class _StatusRead(typing.NamedTuple):
    """One deployment's status history, as far as it could be read."""

    status: DeploymentEventStatus
    log_url: str | None
    #: The newest entry is GitHub's ``inactive`` notice, so this
    #: deployment has been retired whatever ``status`` says it did.
    superseded: bool
    #: Nothing was read -- ``status`` is the ``pending`` fallback rather
    #: than an observation.  Resync wants that fallback (a noisy row must
    #: not fail a whole project); anything deciding what an environment
    #: serves has to know the difference.
    unreadable: bool


def _note_sha(path: object) -> str | None:
    """Annotated commit SHA for a notes-tree path, or ``None``.

    Notes trees key blobs by the annotated commit's full SHA, optionally
    fanned out into subtrees (``ab/cdef...``); flattening the path
    recovers the SHA.  Non-note files (``README`` and friends can live
    on a notes ref) do not flatten to 40 hex chars and are skipped.
    """
    if not isinstance(path, str):
        return None
    flattened = path.replace('/', '').lower()
    return flattened if _FULL_SHA_PATTERN.match(flattened) else None


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


def _dispatch_payload(
    response: httpx.Response,
) -> dict[str, typing.Any] | None:
    """Return a dispatch response's JSON body, or ``None`` when bodiless.

    A ``204`` (any appliance that doesn't know
    :data:`_DISPATCH_API_VERSION`) is the expected bodiless case.  A
    ``200`` carrying an empty or non-object body is treated the same way
    rather than raised on: the dispatch already succeeded, so failing here
    would report a started build as a failed one.
    """
    if response.status_code == 204 or not response.content:
        return None
    try:
        payload: object = response.json()
    except ValueError:
        LOGGER.warning(
            'github-deployment: workflow dispatch returned HTTP %s with an '
            'unparseable body; treating the run id as unknown',
            response.status_code,
        )
        return None
    if not isinstance(payload, dict):
        return None
    return typing.cast('dict[str, typing.Any]', payload)


def _artifact_status(
    state: str, conclusion: str
) -> typing.Literal[
    'queued', 'in_progress', 'success', 'failure', 'cancelled', 'unknown'
]:
    """Map an Actions run's ``status``/``conclusion`` pair onto our set.

    A run is only terminal once ``status == 'completed'`` *and* it carries
    a conclusion; every other state is still in flight, so an unrecognised
    one is reported as ``queued`` rather than ``unknown`` -- the host polls
    on, which is the safe reading for a run that hasn't finished.
    """
    if state != 'completed':
        return 'in_progress' if state == 'in_progress' else 'queued'
    if not conclusion:
        # GitHub briefly reports ``completed`` before populating
        # ``conclusion``. Reporting that as ``unknown`` would let a host
        # that stops on any terminal-ish status settle on a run whose
        # outcome lands a moment later, so keep it in flight instead.
        return 'in_progress'
    if conclusion == 'success':
        return 'success'
    # ``action_required`` and ``startup_failure`` are completed runs that
    # did not produce an artifact -- a failure from the host's point of
    # view, whatever the remote calls it.
    if conclusion in {
        'failure',
        'timed_out',
        'action_required',
        'startup_failure',
    }:
        return 'failure'
    if conclusion in {'cancelled', 'skipped', 'stale'}:
        return 'cancelled'
    # ``neutral``, or a conclusion GitHub added since: terminal, but we
    # can't say whether the artifact exists.
    return 'unknown'


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


# Process-wide 403 suppression for release-notes lookups, mirroring the
# check-runs cache above: a token that lacks the scope to read releases
# must not re-issue ``GET /releases/tags/{ref}`` for every deployment on
# every resync sweep.  Keyed by a hash of the repo-scoped client's base
# URL (host + ``owner/repo``) plus its bearer header (the token), so a
# single forbidden repo doesn't suppress release reads elsewhere.
_RELEASES_FORBIDDEN_TOKENS: dict[str, float] = {}


def _releases_cache_key(client: httpx.AsyncClient) -> str:
    material = f'{client.base_url}\n{client.headers.get("authorization", "")}'
    return hashlib.sha256(material.encode()).hexdigest()


def _releases_forbidden(client: httpx.AsyncClient) -> bool:
    """Whether this client's token has recently 403'd on releases."""
    key = _releases_cache_key(client)
    recorded = _RELEASES_FORBIDDEN_TOKENS.get(key)
    if recorded is None:
        return False
    if time.monotonic() - recorded > _CHECKS_DISABLED_TTL_SECONDS:
        _RELEASES_FORBIDDEN_TOKENS.pop(key, None)
        return False
    return True


def _record_releases_forbidden(client: httpx.AsyncClient) -> None:
    """Mark this client's token as forbidden from releases for the TTL.

    Opportunistically evicts expired entries so the dict can't grow
    unbounded, mirroring :func:`_record_checks_disabled`.
    """
    now = time.monotonic()
    expired = [
        k
        for k, recorded in _RELEASES_FORBIDDEN_TOKENS.items()
        if now - recorded > _CHECKS_DISABLED_TTL_SECONDS
    ]
    for k in expired:
        _RELEASES_FORBIDDEN_TOKENS.pop(k, None)
    _RELEASES_FORBIDDEN_TOKENS[_releases_cache_key(client)] = now


# Fallback for the ``mainline_branches`` integration option: deployment
# refs that are branch names rather than release tags. A repo that deploys
# off its default branch reports ``ref == 'main'`` on every deployment, so
# ``GET /releases/tags/main`` is a guaranteed 404 — skip the request
# outright instead of paying for it once per deployment row.
_DEFAULT_MAINLINE_BRANCHES = frozenset({'main', 'master'})


def _mainline_branches(
    integration_options: dict[str, typing.Any],
) -> frozenset[str]:
    """Resolve the ``mainline_branches`` integration option to a set.

    Declared integration-level (beside ``flavor`` / ``host``) because
    mainline branch naming is a property of the org's repos rather than of
    any one capability, so every capability can read the same value.  The
    manifest's ``default`` is a form pre-fill only -- the host does not
    substitute it -- so an absent or blank value resolves to
    :data:`_DEFAULT_MAINLINE_BRANCHES` here, mirroring how
    ``artifact_version_input`` re-applies its own default.  Consequently
    the guard can be *retargeted* but not switched off; a repo that cuts
    releases tagged with a branch name is not a case worth supporting.

    Operator-entered, so tolerate commas as well as the advertised spaces
    and discard surrounding whitespace -- a stray separator would
    otherwise register as a branch named ``''``.
    """
    raw = integration_options.get('mainline_branches')
    if not isinstance(raw, str):
        return _DEFAULT_MAINLINE_BRANCHES
    configured = frozenset(raw.replace(',', ' ').split())
    return configured or _DEFAULT_MAINLINE_BRANCHES


# How many deployments per environment ``get_environment_state`` walks
# before it stops looking for the active one.  GitHub returns
# deployments newest-first, and the active deployment is normally the
# first or second row; a deeper walk only pays off on an environment
# whose recent history is a run of failures.  Each row costs one status
# request, so the cap bounds the request count per environment rather
# than the wall time of one call.
_DEFAULT_ACTIVE_SCAN_LIMIT = 10
# One page holds the whole scan -- GitHub caps ``per_page`` at 100.
_MAX_ACTIVE_SCAN_LIMIT = 100


def _active_scan_limit(
    integration_options: dict[str, typing.Any],
) -> int:
    """Resolve the ``active_scan_limit`` integration option.

    Declared integration-level beside ``mainline_branches`` because how
    deep the scan has to go is a property of the org's deploy habits, not
    of one capability.  Operator-entered values arrive as strings from the
    admin form as often as integers, so both are accepted; anything absent,
    unparseable, or below 1 resolves to
    :data:`_DEFAULT_ACTIVE_SCAN_LIMIT`, and the value is clamped to what a
    single GitHub page can carry.
    """
    raw = integration_options.get('active_scan_limit')
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        return _DEFAULT_ACTIVE_SCAN_LIMIT
    try:
        limit = int(raw)
    except ValueError:
        return _DEFAULT_ACTIVE_SCAN_LIMIT
    if limit < 1:
        return _DEFAULT_ACTIVE_SCAN_LIMIT
    return min(limit, _MAX_ACTIVE_SCAN_LIMIT)


def _commit_from_payload(payload: dict[str, typing.Any]) -> Commit:
    """Convert a GitHub commit list/object payload into a :class:`Commit`."""
    sha = str(payload.get('sha', ''))
    commit_meta: dict[str, typing.Any] = payload.get('commit') or {}
    author_meta: dict[str, typing.Any] = commit_meta.get('author') or {}
    raw_message = str(commit_meta.get('message') or '')
    subject, _, body = raw_message.partition('\n')
    return Commit(
        sha=sha,
        short_sha=_short_sha(sha),
        message=subject,
        body=body.strip() or None,
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


class GitHubDeployment(DeploymentCapability):
    """GitHub deployment capability handler.

    The host is resolved per call from the Integration's ``flavor`` +
    ``host`` options via :meth:`_resolve_host`.  Each instance is
    single-shot: callers pass ``credentials`` (the Integration's
    decrypted blob, carrying the acting user's access token) and ``ctx``
    per call.
    """

    def _resolve_host(self, ctx: PluginContext) -> str:
        return flavor_host(ctx.integration_options, 'github deployment')

    def _api_base(self, ctx: PluginContext) -> str:
        return host_to_api_base(self._resolve_host(ctx))

    def _owner_repo(self, ctx: PluginContext) -> tuple[str, str]:
        return resolve_owner_repo(
            ctx,
            self._resolve_host(ctx),
            'GitHub deployment plugin',
        )

    # Backwards-compatible aliases for the previously private helpers.
    # The actual logic lives in :mod:`imbi.plugins.github._repos`; these
    # remain so existing tests that reach into the class continue to
    # work and so subclasses overriding the resolution path still have
    # a stable surface to hook into.
    _derive_owner_repo_from_links = staticmethod(derive_owner_repo_from_links)
    _parse_owner_repo = staticmethod(parse_owner_repo)

    def _repo_url(self, ctx: PluginContext) -> str:
        owner, repo = self._owner_repo(ctx)
        return f'{self._api_base(ctx)}/repos/{owner}/{repo}'

    @staticmethod
    def _option_str(
        options: dict[str, typing.Any], key: str, default: str
    ) -> str:
        value = options.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default

    async def _bearer(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> str:
        """Resolve the Bearer token for this deployment call.

        Prefers the per-user OAuth token the host threads in as
        ``access_token``; when a service configured with only GitHub App
        credentials drives the call (e.g. the headless deployment-resync
        sweep, which has no acting user), mints an installation token
        from ``app_id`` + ``private_key`` instead.
        """
        # Local import: ``_app_auth`` imports this module for its shared
        # HTTP helpers, so a top-level import here would be circular.
        from imbi.plugins.github import _app_auth

        owner, repo = self._owner_repo(ctx)
        return await _app_auth.resolve_bearer(
            credentials, self._api_base(ctx), owner, repo
        )

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
        :class:`~imbi.common.plugins.base.LinkWriteback` on ``ctx`` so the
        host can persist the project's updated stored link.  This is the
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
            headers=_auth_headers(await self._bearer(ctx, credentials)),
            base_url=self._repo_url(ctx),
            follow_redirects=True,
            event_hooks={'response': [_capture_redirect, _raise_on_401]},
        )
        async with client:
            yield client
            # Only after the caller's request succeeded: a captured
            # redirect means the repo was renamed out from under the
            # stored link.  Resolve the new name once and report it.
            if captured and ctx.link_writeback is None:
                await self._record_relocation(client, ctx, captured[-1])

    async def _record_relocation(
        self,
        client: httpx.AsyncClient,
        ctx: PluginContext,
        redirect_location: str,
    ) -> None:
        """Resolve a renamed repo's canonical name and stash it on ``ctx``.

        Best-effort: any failure to resolve the repo root leaves
        ``ctx.link_writeback`` unset so the user-facing call (which
        already succeeded via the followed redirect) is never disturbed.
        """
        repo_root = _repo_root_from_redirect(redirect_location)
        if repo_root is None:
            return
        try:
            resp = await client.get(repo_root)
        except httpx.HTTPError, PluginAuthenticationFailed:
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
        ctx.link_writeback = LinkWriteback(
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
        host = self._resolve_host(ctx)
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

    # -- Git notes ----------------------------------------------------------

    async def get_commit_note(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        namespace: str,
        committish: str,
    ) -> str | None:
        """Read the note on ``committish`` from ``refs/notes/<namespace>``.

        The notes tree keys blobs by the *full* SHA of the annotated
        commit (with optional fan-out subtrees like ``ab/cdef...``), so a
        short committish is resolved through the commits endpoint first.
        """
        async with self._client(ctx, credentials) as client:
            full_sha = committish.lower()
            if not _FULL_SHA_PATTERN.match(full_sha):
                commit = await client.get(
                    f'/commits/{urllib.parse.quote(committish, safe="")}'
                )
                commit.raise_for_status()
                full_sha = str(commit.json()['sha']).lower()
            notes = await self._notes_tree(client, namespace)
            if notes is None:
                return None
            blob_sha = notes.get(full_sha)
            if blob_sha is None:
                return None
            return await self._blob_text(client, blob_sha)

    async def list_commit_notes(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        namespace: str,
        skip_shas: collections.abc.Collection[str] = (),
    ) -> NotesListing:
        """Every note on ``refs/notes/<namespace>`` at its current tip.

        Two Git Data calls to reach the tree, then one blob read per
        note the caller did not ask us to skip.  A missing ref answers
        an empty, complete listing.

        ``complete`` compares what the tree holds against what came
        back: :meth:`_all_notes` drops a note whose blob it cannot read
        (logging why), and a truncated tree listing hides notes before
        that.  Either way the caller must not treat the result as the
        whole ref.  A note skipped on request does not make the listing
        incomplete -- the caller already has that answer.
        """
        async with self._client(ctx, credentials) as client:
            tip = await self._notes_ref_tip(client, namespace)
            if tip is None:
                return NotesListing({}, True)
            return await self._all_notes(client, tip, skip_shas)

    async def diff_commit_notes(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        namespace: str,
        before: str,
        after: str,
    ) -> dict[str, str | None]:
        """Diff ``refs/notes/<namespace>`` between two of its commits.

        ``before``/``after`` come from a push event on the notes ref;
        the *files* changed between them are the notes of the annotated
        commits, so the tree diff -- not the push's ``commits`` list --
        is what names the commits whose notes changed.  An all-zero
        ``before`` (the ref was just created) returns every note at
        ``after``.

        Known limitation: GitHub's compare endpoint is three-dot only
        (``after`` against the merge base), so a *force-pushed* notes
        ref whose ``before`` is not an ancestor of ``after`` can miss a
        note that the rewrite flipped or removed.  The 404 fallback
        below covers a ``before`` GitHub no longer has at all, and the
        sweep backfill only repairs verdicts that are still ``null`` --
        a stale non-null verdict from this window persists until the
        next ordinary push touches the note.
        """
        async with self._client(ctx, credentials) as client:
            if before == _ZERO_SHA:
                return (await self._all_notes(client, after)).notes
            quoted = urllib.parse.quote(f'{before}...{after}', safe='.')
            resp = await client.get(f'/compare/{quoted}')
            if resp.status_code == 404:
                # ``before`` was garbage-collected or the ref history
                # was rewritten; fall back to the full tree at ``after``
                # so the push still lands rather than being dropped.
                return (await self._all_notes(client, after)).notes
            resp.raise_for_status()
            payload = typing.cast('dict[str, typing.Any]', resp.json())
            files: list[dict[str, typing.Any]] = payload.get('files') or []
            if len(files) >= _COMPARE_FILES_CAP:
                # The compare endpoint stops listing files at 300 and
                # offers no pagination for them, so a full list this
                # long may be missing entries.  Fall back to the whole
                # tree at ``after`` -- same trade-off as the 404 path:
                # removals in the window are missed until the sweep or
                # the next push touches them.
                LOGGER.warning(
                    'Notes compare %s...%s hit the %d-file cap; '
                    'reading the full tree instead',
                    before,
                    after,
                    _COMPARE_FILES_CAP,
                )
                return (await self._all_notes(client, after)).notes
            out: dict[str, str | None] = {}
            for item in files:
                status = str(item.get('status') or '')
                previous = _note_sha(item.get('previous_filename'))
                if status == 'renamed' and previous is not None:
                    # Fan-out reshuffle: the note moved paths.  The old
                    # path's flattened SHA only differs from the new one
                    # if the note now annotates a different commit.
                    out.setdefault(previous, None)
                annotated = _note_sha(item.get('filename'))
                if annotated is None:
                    continue
                if status == 'removed':
                    out[annotated] = None
                    continue
                blob_sha = item.get('sha')
                if not blob_sha:
                    continue
                try:
                    body = await self._blob_text(client, str(blob_sha))
                except httpx.HTTPError:
                    LOGGER.warning(
                        'Could not read note blob %s for %s; skipping',
                        blob_sha,
                        annotated,
                    )
                    body = None
                if body is None:
                    # Skip rather than record ``None``: in the diff a
                    # ``None`` means "note removed" and would resolve a
                    # drift blocker over a note we merely could not
                    # read (``_blob_text`` already logged why).
                    out.pop(annotated, None)
                    continue
                out[annotated] = body
            return out

    @staticmethod
    async def _notes_ref_tip(
        client: httpx.AsyncClient, namespace: str
    ) -> str | None:
        """The commit ``refs/notes/<namespace>`` points at, or ``None``."""
        ref = await client.get(
            f'/git/ref/{urllib.parse.quote(f"notes/{namespace}", safe="/")}'
        )
        if ref.status_code == 404:
            return None
        ref.raise_for_status()
        return str(ref.json()['object']['sha'])

    async def _notes_tree(
        self, client: httpx.AsyncClient, namespace: str
    ) -> dict[str, str] | None:
        """Map annotated full SHA -> note blob SHA, or ``None`` sans ref."""
        tip = await self._notes_ref_tip(client, namespace)
        if tip is None:
            return None
        # A truncated tree can only cost this caller a note it then
        # reports as absent, which is already its answer for "no note".
        notes, _complete = await self._tree_notes(client, tip)
        return notes

    async def _tree_notes(
        self, client: httpx.AsyncClient, commit_sha: str
    ) -> tuple[dict[str, str], bool]:
        """Flatten one notes-ref commit's tree to annotated SHA -> blob.

        Also answers whether the tree listing was whole.  GitHub
        truncates a large recursive tree, and the truncated map is
        indistinguishable from a small complete one, so the flag has to
        travel with it -- a caller that persists "backfill finished"
        would otherwise do so over notes it never saw.
        """
        commit = await client.get(f'/git/commits/{commit_sha}')
        commit.raise_for_status()
        tree_sha = str(commit.json()['tree']['sha'])
        tree = await client.get(f'/git/trees/{tree_sha}?recursive=1')
        tree.raise_for_status()
        payload = typing.cast('dict[str, typing.Any]', tree.json())
        truncated = bool(payload.get('truncated'))
        if truncated:
            LOGGER.warning(
                'Notes tree %s is truncated; some notes will be missed',
                tree_sha,
            )
        entries: list[dict[str, typing.Any]] = payload.get('tree') or []
        out: dict[str, str] = {}
        for entry in entries:
            if entry.get('type') != 'blob':
                continue
            annotated = _note_sha(entry.get('path'))
            if annotated is not None:
                out[annotated] = str(entry['sha'])
        return out, not truncated

    async def _all_notes(
        self,
        client: httpx.AsyncClient,
        commit_sha: str,
        skip_shas: collections.abc.Collection[str] = (),
    ) -> NotesListing:
        """Every note at one notes-ref commit, bodies included.

        Blob reads run a few at a time (one request per note) and an
        unreadable note is skipped rather than failing the batch or
        recording a false "removed".  A note whose annotated commit is
        in ``skip_shas`` costs no request at all.

        ``complete`` combines the two ways this can fall short: a
        truncated tree listing, and a blob that would not read.  Either
        means the map is not the whole ref.  Notes skipped on request do
        not count against it.
        """
        notes, tree_complete = await self._tree_notes(client, commit_sha)
        gate = asyncio.Semaphore(_NOTE_BLOB_CONCURRENCY)

        async def _read(blob_sha: str) -> str | BaseException | None:
            async with gate:
                try:
                    return await self._blob_text(client, blob_sha)
                except httpx.HTTPError as exc:
                    return exc

        skip = {sha.lower() for sha in skip_shas}
        items = [
            (annotated, blob_sha)
            for annotated, blob_sha in notes.items()
            if annotated.lower() not in skip
        ]
        bodies = await asyncio.gather(
            *(_read(blob_sha) for _, blob_sha in items)
        )
        out: dict[str, str | None] = {}
        for (annotated, blob_sha), body in zip(items, bodies, strict=True):
            if isinstance(body, BaseException):
                LOGGER.warning(
                    'Could not read note blob %s for %s; skipping',
                    blob_sha,
                    annotated,
                )
                continue
            if body is None:
                # ``_blob_text`` could not decode it and logged why;
                # a ``None`` here would read as "note removed".
                continue
            out[annotated] = body
        return NotesListing(out, tree_complete and len(out) == len(items))

    @staticmethod
    async def _blob_text(
        client: httpx.AsyncClient, blob_sha: str
    ) -> str | None:
        """Fetch and decode one note blob; ``None`` when undecodable."""
        resp = await client.get(f'/git/blobs/{blob_sha}')
        resp.raise_for_status()
        payload = typing.cast('dict[str, typing.Any]', resp.json())
        content = str(payload.get('content') or '')
        if payload.get('encoding') != 'base64':
            if not content:
                # ``encoding: none`` with an empty body is how GitHub
                # answers for blobs above the inline size limit --
                # "cannot read", not "empty note".
                LOGGER.warning(
                    'Note blob %s answered encoding %r with no content',
                    blob_sha,
                    payload.get('encoding'),
                )
                return None
            return content
        try:
            # Strip GitHub's line wrapping, then decode strictly --
            # the default decoder silently discards invalid characters,
            # turning garbage like '%%%%' into an empty body instead of
            # landing on this "cannot read" path.
            return base64.b64decode(
                ''.join(content.split()), validate=True
            ).decode('utf-8')
        except (ValueError, UnicodeDecodeError):
            LOGGER.warning('Could not decode note blob %s', blob_sha)
            return None

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

    async def create_deployment_artifact(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        ref: str,
        version: str,
        inputs: dict[str, str] | None = None,
    ) -> ArtifactRun:
        """Dispatch the release workflow that builds ``version``.

        ``POST /actions/workflows/{id}/dispatches`` against the workflow
        named by the ``artifact_workflow`` capability option.  The
        dispatched workflow is what cuts the tag and pushes any
        version-bump commits, so neither exists on the remote when this
        returns -- the host waits on
        :meth:`get_artifact_run_status` before syncing them or deploying.

        ``version`` is passed as a workflow input under the key named by
        the ``artifact_version_input`` option (default ``version``);
        caller-supplied ``inputs`` layer on top, so an explicit override
        wins on a shared key.

        Degrades on appliances predating :data:`_DISPATCH_API_VERSION`:
        those answer ``204 No Content``, which yields an
        :class:`ArtifactRun` with ``run_id=None`` -- dispatched, run id
        unknown.  That is deliberately not an error; the build is running
        and the caller resolves the id another way if it needs to watch.
        """
        # Both options are operator-entered through the Integration form,
        # so strip them: a trailing space would otherwise reach the URL as
        # %20 and 404, or name a workflow input that does not exist.
        workflow_id = str(
            ctx.capability_options.get('artifact_workflow') or ''
        ).strip()
        if not workflow_id:
            raise ValueError(
                'create_deployment_artifact requires the '
                "'artifact_workflow' capability option naming the workflow "
                'to dispatch (a workflow file name or numeric id)'
            )
        version_key = (
            str(
                ctx.capability_options.get('artifact_version_input') or ''
            ).strip()
            or 'version'
        )
        merged_inputs: dict[str, str] = {version_key: version}
        if inputs:
            merged_inputs.update(inputs)
        if len(merged_inputs) > _MAX_DISPATCH_INPUTS:
            raise ValueError(
                f'create_deployment_artifact was given '
                f'{len(merged_inputs)} workflow inputs; GitHub accepts at '
                f'most {_MAX_DISPATCH_INPUTS} per workflow_dispatch'
            )
        async with self._client(ctx, credentials) as client:
            resp = await client.post(
                f'/actions/workflows/'
                f'{urllib.parse.quote(workflow_id, safe="")}/dispatches',
                json={'ref': ref, 'inputs': merged_inputs},
                headers={'X-GitHub-Api-Version': _DISPATCH_API_VERSION},
            )
            resp.raise_for_status()
            payload = _dispatch_payload(resp)
            if payload is None:
                # 204, or a 200 whose body we can't read: the dispatch
                # was accepted, we just don't know which run it started.
                LOGGER.info(
                    'github-deployment: dispatched %s@%s for project %s; '
                    'remote reported no run id (HTTP %s)',
                    workflow_id,
                    ref,
                    ctx.project_id,
                    resp.status_code,
                )
                return ArtifactRun(status='queued')
            run_id = payload.get('workflow_run_id')
            html_url = payload.get('html_url')
            return ArtifactRun(
                run_id=str(run_id) if run_id else None,
                # ``html_url`` is the human-facing run page; the sibling
                # ``run_url`` in the response is the API URL, which is no
                # use to the UI.
                run_url=str(html_url) if html_url else None,
                status='queued',
            )

    async def get_artifact_run_status(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        run_id: str,
    ) -> ArtifactRun:
        """Report an Actions run's status via ``GET /actions/runs/{id}``.

        Distinct from :meth:`get_deployment_status`, which resolves a
        GitHub *Deployment* id through ``/deployments/{id}/statuses``.
        Passing a workflow run id to that one would 404, which is why the
        two ids never share a method.
        """
        async with self._client(ctx, credentials) as client:
            resp = await client.get(
                f'/actions/runs/{urllib.parse.quote(str(run_id), safe="")}'
            )
            resp.raise_for_status()
            payload = typing.cast('dict[str, typing.Any]', resp.json())
        state = str(payload.get('status') or '').lower()
        conclusion = str(payload.get('conclusion') or '').lower()
        status = _artifact_status(state, conclusion)
        completed = status in {'success', 'failure', 'cancelled'}
        html_url = payload.get('html_url')
        return ArtifactRun(
            run_id=str(payload.get('id') or run_id),
            run_url=str(html_url) if html_url else None,
            status=status,
            started_at=_parse_iso(
                payload.get('run_started_at') or payload.get('created_at')
            ),
            completed_at=(
                _parse_iso(payload.get('updated_at')) if completed else None
            ),
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
        host = self._resolve_host(ctx)
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
        newest-first; the newest entry that describes this deployment's
        own lifecycle wins.  An empty list means the deploy workflow
        hasn't posted anything yet, which Imbi surfaces as ``'queued'``.

        ``inactive`` entries are skipped rather than read as the answer.
        Every other state is something this deployment's own run
        reported about itself; ``inactive`` is written by GitHub *on
        behalf of a later deployment* when that one supersedes this one.
        Treating it as the outcome is wrong twice over: it relabels a
        rollout that succeeded (the success is still in the list, one
        entry further down), and its ``updated_at`` is the moment the
        successor went live, so a caller stamping the close-out with
        ``completed_at`` would date this deployment *after* the one that
        replaced it.  That is what taught a production environment it
        was running a release eleven days stale.

        Note that ``inactive`` reaches Imbi only by polling -- here and
        in :meth:`_latest_status`.  GitHub creates the status but emits no
        ``deployment_status`` webhook for it, which its own docs state
        outright: "A webhook event is not fired for deployment statuses
        with an inactive state."  Confirmed 2026-08-21 against a repo
        hook subscribed to ``*``, which saw the successor's ``success``
        and nothing for the auto-inactive written in the same second.
        So a poll is the only place the state can be handled correctly,
        and there is no upstream fix to wait for.

        Suppressing the state at source is not the alternative it looks
        like: ``auto_inactive`` is documented as affecting only
        "non-transient, non-production" deployments, yet the deployments
        observed here carry ``production_environment=true`` and were
        auto-inactivated anyway.  The documented carve-out does not
        describe them, so setting ``auto_inactive=false`` would need an
        experiment rather than a reading.

        A deployment superseded while still in flight has no terminal
        entry left once ``inactive`` is skipped, so it reads as whatever
        it last genuinely reported and the sweeper expires it on age --
        honest, because it never did finish.

        ``log_url`` (and the legacy ``target_url``) on the selected
        status is what the deploy workflow set to point at its own logs
        (e.g. the Actions run URL).  We carry that as ``run_url`` so the
        UI can deep-link without having to walk back to the workflow run
        through a check-suite join.
        """
        async with self._client(ctx, credentials) as client:
            resp = await client.get(f'/deployments/{run_id}/statuses')
            resp.raise_for_status()
            statuses = typing.cast(list[dict[str, typing.Any]], resp.json())
            latest = next(
                (
                    entry
                    for entry in statuses
                    if str(entry.get('state') or '').lower() != 'inactive'
                ),
                None,
            )
            if latest is None:
                # Either nothing posted yet, or every entry is an
                # auto-inactive -- both mean this deployment has told us
                # nothing about itself.
                return DeploymentRun(run_id=str(run_id), status='queued')
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
        # One run commonly backs several deployments in a sweep; cache
        # the triggering-actor lookup by run id so we resolve each run
        # at most once. Shared across the parallel per-env fan-out.
        run_cache: dict[str, tuple[str, str] | None] = {}
        # Likewise, deployments in a sweep share a handful of refs; the
        # lookup for each is memoised here as a task so it happens once
        # per ref instead of once per deployment. Holding the task (not
        # its result) also coalesces the per-env fan-out below: envs that
        # deployed the same ref await one in-flight request rather than
        # each issuing their own, which is the common shape at the host's
        # default limit=1 where no single env repeats a ref.
        release_lookups: dict[str, asyncio.Task[RemoteRelease | None]] = {}
        mainline = _mainline_branches(ctx.integration_options)
        async with self._client(ctx, credentials) as client:
            per_env = await asyncio.gather(
                *(
                    self._list_deployments_for_env(
                        client,
                        env,
                        page_size,
                        run_cache,
                        release_lookups,
                        mainline,
                    )
                    for env in environments
                )
            )
        return [observed for group in per_env for observed in group]

    async def get_environment_state(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        environments: list[str],
    ) -> list[EnvironmentDeploymentState]:
        """Report the active deployment per environment.

        Fans out one ``GET /deployments?environment={env}`` call per
        environment (newest-first, as GitHub orders them) and walks the
        page fetching each deployment's statuses until one both maps to
        exactly ``success`` -- not ``pending``, not ``in_progress`` -- and
        carries no ``inactive`` notice on top.  That deployment is the
        active one.

        Policy note: GitHub can leave several deployments active at once
        when automatic inactivation is disabled, so "active" cannot be
        read off the provider's own flag.  Imbi's policy is *active = the
        newest deployment whose latest provider status is success*, which
        is well-defined either way.

        The walk is bounded by the ``active_scan_limit`` option (see
        :func:`_active_scan_limit`).  Reaching the cap without a success
        resolves ``unknown``, never ``none``: an older active deployment
        may sit just past the cap, and reporting ``none`` would have the
        host clear a pointer that is right.

        Two degraded reads resolve ``error`` for the same reason.  A row
        whose status history would not read (``status_unknown``), or one
        too malformed to identify at all, leaves the walk unable to say
        what that deployment did -- throttling blinds every row at once
        -- and a 404 on the listing itself means the repo moved or the
        token lost access, not that the environment is empty.  An *empty*
        listing resolves ``unknown``: GitHub says ``[]`` both for an
        environment never deployed to and for a name it does not
        recognise, and local slugs reach it unmapped.

        An unreadable row outranks a success found *below* it, so it wins
        over ``found`` rather than being noted alongside it.  The walk
        stops at the first clean success, which means every row it could
        not read is newer than that success and may be the deployment
        actually serving the environment; calling the older one active
        would have the host write a stale pointer.

        So ``none`` requires positive evidence -- rows read, none of them
        serving.  Everything else the host must read as "keep what you
        have".
        """
        scan_limit = _active_scan_limit(ctx.integration_options)
        # Same memoisation as the resync sweep: one triggering-actor
        # lookup per run and one release lookup per ref, shared across the
        # parallel per-env fan-out.
        run_cache: dict[str, tuple[str, str] | None] = {}
        release_lookups: dict[str, asyncio.Task[RemoteRelease | None]] = {}
        mainline = _mainline_branches(ctx.integration_options)
        async with self._client(ctx, credentials) as client:
            return list(
                await asyncio.gather(
                    *(
                        self._environment_state(
                            client,
                            env,
                            scan_limit,
                            run_cache,
                            release_lookups,
                            mainline,
                        )
                        for env in environments
                    )
                )
            )

    async def _environment_state(
        self,
        client: httpx.AsyncClient,
        environment: str,
        scan_limit: int,
        run_cache: dict[str, tuple[str, str] | None],
        release_lookups: dict[str, asyncio.Task[RemoteRelease | None]],
        mainline: frozenset[str],
    ) -> EnvironmentDeploymentState:
        """Resolve one environment's active deployment."""
        try:
            resp = await client.get(
                '/deployments',
                params={
                    'environment': environment,
                    'per_page': str(scan_limit),
                },
            )
            if resp.status_code == 404:
                # NOT ``none``, though the listing path treats a 404 as
                # "nothing to import".  Here ``none`` authorizes the host
                # to clear the environment's current-release pointer, and
                # GitHub answers 404 for a repo that was renamed or
                # transferred, or one this installation lost access to --
                # the very conditions link writeback exists to self-heal.
                # An unknown *environment* is a 200 with an empty list, so
                # nothing legitimate is lost by refusing to read a 404 as
                # an answer.
                LOGGER.warning(
                    'Active deployment scan got 404 for env=%s; treating '
                    'it as unreadable rather than as "nothing deployed"',
                    environment,
                )
                return EnvironmentDeploymentState(
                    environment=environment, active_resolution='error'
                )
            resp.raise_for_status()
            deployments = typing.cast(list[dict[str, typing.Any]], resp.json())
        except (httpx.HTTPError, ValueError):
            LOGGER.warning(
                'Failed to resolve active deployment for env=%s',
                environment,
                exc_info=True,
            )
            return EnvironmentDeploymentState(
                environment=environment, active_resolution='error'
            )
        active: RemoteDeployment | None = None
        latest: RemoteDeployment | None = None
        scanned = 0
        # Set by any row above the walk's stopping point that we could
        # not read: a malformed listing entry, or one whose status
        # history would not load.  Because the walk stops at the first
        # clean success, every such row is *newer* than whatever success
        # we go on to find, so it may itself be the deployment actually
        # serving the environment.
        unresolved = False
        for deployment in deployments:
            scanned += 1
            observed = await self._observe_deployment(
                client,
                environment,
                deployment,
                run_cache,
                release_lookups,
                mainline,
            )
            if observed is None:
                # A row we could not even identify.  It is still a row
                # newer than any success below it, so it has to count as
                # uncertainty rather than be skipped silently.
                unresolved = True
                continue
            if latest is None:
                latest = observed
            if observed.status_unknown:
                # Its status read failed, so this row's ``pending`` is a
                # fallback.  Keep walking -- an older row may still
                # answer -- but remember that the walk passed something
                # it could not see.
                unresolved = True
            # ``status`` looks past GitHub's ``inactive`` notice on
            # purpose, so a superseded rollout still reads as the
            # ``success`` it was.  For "what is serving now" that notice
            # is the answer, not noise: without the ``superseded`` test
            # a deactivated environment reports its last success as
            # active forever.  Walking on is safe -- an ``inactive``
            # written because a later deployment took over has that
            # deployment above it in this same newest-first page.
            if observed.status == 'success' and not observed.superseded:
                if unresolved:
                    # A newer row we could not read sits above this
                    # success, so we cannot claim this one is serving.
                    # Stop here and report the uncertainty: the walk has
                    # nothing older left to learn from.
                    break
                active = observed
                break
        # The result set is exhausted only when the walk read every row
        # GitHub returned *and* GitHub returned fewer than we asked for
        # (a full page means there is more history past the cap).  An
        # empty listing does not count: GitHub answers 200 with ``[]``
        # both for an environment that has never been deployed to and
        # for an environment *name it has never heard of*, and the host
        # passes local slugs through unmapped.  A project whose local
        # slug is 'prod' against a remote 'production' would otherwise
        # resolve ``none`` and have its pointer cleared on every sweep.
        # Clearing needs positive evidence -- rows we read, none of them
        # serving -- which is the deactivated-environment case.
        exhausted = (
            bool(deployments)
            and scanned == len(deployments)
            and scanned < scan_limit
        )
        resolution: typing.Literal['found', 'none', 'unknown', 'error']
        if unresolved:
            # Tested BEFORE ``found`` on purpose.  The walk stops at the
            # first clean success, so every row it could not read is
            # newer than that success -- and a 403 on the newest
            # deployment's status hides exactly the deployment most
            # likely to be serving.  Reporting ``found`` here would name
            # an older release as current and have the host write that
            # stale pointer.  ``error``, not ``none`` and not
            # ``unknown``: the scan was not capped, it was blinded --
            # most often by throttling, where every status read fails
            # and ``none`` would clear every pointer on the project.
            resolution = 'error'
        elif active is not None:
            resolution = 'found'
        elif exhausted:
            resolution = 'none'
        else:
            resolution = 'unknown'
        LOGGER.info(
            'Active deployment scan env=%s deployments_scanned=%d '
            'unresolved_above_success=%s scan_exhausted=%s '
            'active_resolution=%s',
            environment,
            scanned,
            unresolved,
            exhausted,
            resolution,
        )
        return EnvironmentDeploymentState(
            environment=environment,
            active=active,
            latest=latest,
            active_resolution=resolution,
        )

    async def get_release_notes(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        tag: str,
    ) -> str | None:
        """Return the GitHub release body for ``tag``.

        Tag-keyed enrichment path: the host calls this when it knows the
        release tag but not its notes -- a webhook that created the
        ``Release`` node from a deployment event (whose payload carries no
        body), or a resync whose deployment ``ref`` was a raw SHA.  Opens
        a repo-scoped client and defers to :meth:`_release_notes_for_ref`,
        which 404s to ``None`` for tags without a release and caches 403s
        so a scope-limited token short-circuits.
        """
        mainline = _mainline_branches(ctx.integration_options)
        async with self._client(ctx, credentials) as client:
            return await self._release_notes_for_ref(client, tag, mainline)

    async def _list_deployments_for_env(
        self,
        client: httpx.AsyncClient,
        environment: str,
        page_size: int,
        run_cache: dict[str, tuple[str, str] | None],
        release_lookups: dict[str, asyncio.Task[RemoteRelease | None]],
        mainline: frozenset[str],
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
                client,
                environment,
                deployment,
                run_cache,
                release_lookups,
                mainline,
            )
            if run is not None:
                observed.append(run)
        return observed

    async def _observe_deployment(
        self,
        client: httpx.AsyncClient,
        environment: str,
        deployment: dict[str, typing.Any],
        run_cache: dict[str, tuple[str, str] | None],
        release_lookups: dict[str, asyncio.Task[RemoteRelease | None]],
        mainline: frozenset[str],
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
        read = await self._latest_status(client, str(deployment_id))
        status, status_url = read.status, read.log_url
        ref_value = deployment.get('ref')
        description = deployment.get('description')
        release_notes = (
            await self._release_notes_for_ref(
                client, str(ref_value), mainline, release_lookups
            )
            if ref_value
            else None
        )
        deployment_url = deployment.get('url') or deployment.get('html_url')
        creator_login: str | None = None
        creator_subject: str | None = None
        creator_raw = deployment.get('creator')
        if isinstance(creator_raw, dict):
            creator_dict = typing.cast(dict[str, typing.Any], creator_raw)
            login = creator_dict.get('login')
            if isinstance(login, str) and login:
                creator_login = login
            # GitHub's numeric user id is the stable identity subject the
            # host resolves to an Imbi user (logins can be renamed).
            creator_id = creator_dict.get('id')
            if isinstance(creator_id, int):
                creator_subject = str(creator_id)
            # Deployments made by an Actions workflow carry the app bot
            # as creator (``deployer[bot]``), never the human who
            # triggered the run. Re-attribute to the run's triggering
            # actor so the host can resolve the deploy to a real user.
            if _is_bot(creator_dict):
                run_id = _run_id_from_status_url(status_url)
                if run_id is not None:
                    actor = await self._resolve_triggering_actor(
                        client, run_id, run_cache
                    )
                    if actor is not None:
                        creator_login, creator_subject = actor
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
            release_notes=release_notes,
            creator=creator_login,
            creator_subject=creator_subject,
            superseded=read.superseded,
            status_unknown=read.unreadable,
        )

    async def _resolve_triggering_actor(
        self,
        client: httpx.AsyncClient,
        run_id: str,
        run_cache: dict[str, tuple[str, str] | None],
    ) -> tuple[str, str] | None:
        """Resolve a workflow run's human trigger to ``(login, subject)``.

        Attributes a bot-created deployment to the person who started
        the Actions run via ``GET /actions/runs/{run_id}``, preferring
        ``triggering_actor`` (the account that re-ran or dispatched the
        run) and falling back to ``actor``. Best-effort: a fetch/parse
        error, a missing actor, or an actor that is itself a bot yields
        ``None`` so the caller keeps the bot creator -- attribution must
        never fail the resync. Results (including ``None``) are cached
        per sweep because one run backs several deployments.
        """
        if run_id in run_cache:
            return run_cache[run_id]
        result: tuple[str, str] | None = None
        try:
            resp = await client.get(f'/actions/runs/{run_id}')
            resp.raise_for_status()
            run = typing.cast(dict[str, typing.Any], resp.json())
        except (httpx.HTTPError, PluginAuthenticationFailed, ValueError):
            LOGGER.warning(
                'Failed to fetch workflow run %s for deploy attribution',
                run_id,
                exc_info=True,
            )
            run_cache[run_id] = None
            return None
        actor_raw = run.get('triggering_actor') or run.get('actor')
        if isinstance(actor_raw, dict):
            actor = typing.cast(dict[str, typing.Any], actor_raw)
            login = actor.get('login')
            actor_id = actor.get('id')
            if (
                isinstance(login, str)
                and login
                and isinstance(actor_id, int)
                and not _is_bot(actor)
            ):
                result = (login, str(actor_id))
        run_cache[run_id] = result
        return result

    async def _release_for_ref(
        self,
        client: httpx.AsyncClient,
        ref: str,
        mainline: frozenset[str],
        release_lookups: dict[str, asyncio.Task[RemoteRelease | None]]
        | None = None,
    ) -> RemoteRelease | None:
        """Return the GitHub release for ``ref``, metadata included.

        Refs in ``mainline`` (the resolved ``mainline_branches`` option)
        never name a release, so they never reach the API.

        ``release_lookups`` memoises one lookup per ref for the duration of
        a sweep.  It holds the in-flight task rather than its result, so
        the parallel per-env fan-out in
        :meth:`list_recent_deployments` coalesces onto a single request
        when several environments deployed the same ref -- checking a
        result-only cache would let every env past the check before the
        first response landed.  Like ``run_cache`` it memoises every
        outcome, failures included, so one sweep never retries a ref that
        just errored; it is scoped the same way (one sweep, one repo, one
        token), and omitting it disables the memo for one-off host-facing
        lookups.
        """
        if ref in mainline:
            return None
        if release_lookups is None:
            return await self._fetch_release(client, ref)
        task = release_lookups.get(ref)
        if task is None:
            task = asyncio.ensure_future(self._fetch_release(client, ref))
            release_lookups[ref] = task
        return await task

    async def _fetch_release(
        self, client: httpx.AsyncClient, ref: str
    ) -> RemoteRelease | None:
        """Issue the release lookup for ``ref`` and shape the response.

        The single release request every caller degrades through: a 404 /
        410 / non-200 / parse failure yields ``None``, and a ``403`` (token
        lacks scope to read releases) is cached process-wide so a forbidden
        token short-circuits instead of re-issuing the request for every
        deployment on every resync sweep.  ``author`` is the login GitHub
        credits with the release and ``author_subject`` its numeric user
        id, which the host resolves to an Imbi user through the identity
        plugins on the same service.
        """
        if _releases_forbidden(client):
            return None
        try:
            resp = await client.get(
                f'/releases/tags/{urllib.parse.quote(ref, safe="")}'
            )
        except httpx.HTTPError:
            return None
        if resp.status_code == 403:
            _record_releases_forbidden(client)
            return None
        if resp.status_code != 200:
            return None
        try:
            data = typing.cast(dict[str, typing.Any], resp.json())
        except ValueError:
            return None
        author: dict[str, typing.Any] = data.get('author') or {}
        login = author.get('login')
        subject = author.get('id')
        body = data.get('body')
        name = data.get('name')
        html_url = data.get('html_url')
        return RemoteRelease(
            tag=ref,
            name=str(name) if name else None,
            body_markdown=str(body) if body else None,
            author=str(login) if login else None,
            author_subject=str(subject) if subject is not None else None,
            html_url=str(html_url) if html_url else None,
            published_at=_parse_iso(data.get('published_at')),
        )

    async def get_release(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        tag: str,
    ) -> RemoteRelease | None:
        """Return the GitHub release for ``tag`` with its author."""
        mainline = _mainline_branches(ctx.integration_options)
        async with self._client(ctx, credentials) as client:
            return await self._release_for_ref(client, tag, mainline)

    async def _release_notes_for_ref(
        self,
        client: httpx.AsyncClient,
        ref: str,
        mainline: frozenset[str],
        release_lookups: dict[str, asyncio.Task[RemoteRelease | None]]
        | None = None,
    ) -> str | None:
        """Return the GitHub release notes body for a deployed ref.

        A deployment created against a semver tag has a matching GitHub
        release whose ``body`` is the "What's Changed" markdown the host
        persists on the ``Release`` node.  Refs that aren't a release tag
        (branches, raw SHAs) 404 in :meth:`_release_for_ref` and yield
        ``None`` -- resync is never blocked by a missing or unreadable
        release.
        """
        release = await self._release_for_ref(
            client, ref, mainline, release_lookups
        )
        return release.body_markdown if release else None

    async def _latest_status(
        self, client: httpx.AsyncClient, deployment_id: str
    ) -> _StatusRead:
        """Return the canonical event status, log URL, and retirement.

        The third element is ``True`` when the newest status entry is
        ``inactive``: the deployment's own outcome (the first element)
        looks past that notice, so this is the only place the caller can
        learn that GitHub has since retired it.  Both readings are
        needed and neither substitutes for the other -- "what did this
        rollout do" is a different question from "is it serving now".

        Falls back to ``'pending'`` whenever the deploy workflow has
        not yet posted a status: a freshly-created deployment with no
        statuses is structurally identical to one whose workflow has
        not started, and ``pending`` is the host's vocabulary for
        both.  Network / parse errors degrade the same way so resync
        is never blocked by a single noisy row.

        An ``inactive`` entry is looked *past* when something sits
        beneath it.  GitHub writes one on a deployment when a later one
        supersedes it, so it reports the successor's arrival rather than
        this deployment's outcome -- and every deployment except an
        environment's newest carries one.  Reading it verbatim therefore
        relabelled whole deployment histories as ``rolled_back``, each
        node's ``history`` showing the ``success`` it overwrote; ~14k
        nodes in the production graph were in that state before this
        skip existed.

        An ``inactive`` with nothing beneath it still reports
        ``rolled_back``: that deployment was superseded without ever
        reporting on itself, and ``rolled_back`` is the accurate
        terminal for it.  The distinction is the whole point -- skip the
        retirement notice when it is hiding a real outcome, keep it when
        it is the only thing we know.

        This is why the page size is not 1.  A single-status window
        cannot see past an ``inactive`` to the ``success`` underneath,
        which is what made the misread unavoidable.
        """
        try:
            resp = await client.get(
                f'/deployments/{deployment_id}/statuses',
                params={'per_page': '10'},
            )
        except httpx.HTTPError:
            return _StatusRead('pending', None, False, True)
        if resp.status_code != 200:
            # 403/429 land here, which is how a throttled scan used to
            # read every row as ``pending`` and conclude that nothing was
            # deployed.  The status is still ``pending`` for resync; the
            # flag is what stops a currency decision resting on it.
            LOGGER.warning(
                'Deployment %s statuses answered %d; status unread',
                deployment_id,
                resp.status_code,
            )
            return _StatusRead('pending', None, False, True)
        try:
            statuses = typing.cast(list[dict[str, typing.Any]], resp.json())
        except ValueError:
            return _StatusRead('pending', None, False, True)
        if not statuses:
            # Read fine and there is genuinely nothing: a deployment
            # whose workflow has not posted yet.  Not unreadable.
            return _StatusRead('pending', None, False, False)
        superseded = str(statuses[0].get('state') or '').lower() == 'inactive'
        latest = next(
            (
                entry
                for entry in statuses
                if str(entry.get('state') or '').lower() != 'inactive'
            ),
            statuses[0],
        )
        state = str(latest.get('state') or '').lower()
        log_url = latest.get('log_url') or latest.get('target_url')
        return _StatusRead(
            _to_event_status(state),
            str(log_url) if log_url else None,
            superseded,
            False,
        )


_RUN_ID_RE = re.compile(r'/actions/runs/(\d+)')


def _is_bot(user: dict[str, typing.Any]) -> bool:
    """Return ``True`` when a GitHub user object denotes an app/bot.

    GitHub marks app identities with ``type == 'Bot'`` on the user
    object and gives them a ``login`` suffixed ``[bot]``
    (``github-actions[bot]``, ``deployer[bot]``). Either signal alone is
    sufficient; both comparisons are case-insensitive.
    """
    if str(user.get('type') or '').lower() == 'bot':
        return True
    login = user.get('login')
    return isinstance(login, str) and login.lower().endswith('[bot]')


def _run_id_from_status_url(url: str | None) -> str | None:
    """Extract the Actions run id from a deployment status URL.

    A GitHub Actions deploy posts its status ``log_url``/``target_url``
    pointing at the workflow run
    (``.../actions/runs/{run_id}`` optionally followed by
    ``/job/{job_id}``). Any URL that is not an Actions run link yields
    ``None``.
    """
    if not url:
        return None
    match = _RUN_ID_RE.search(url)
    return match.group(1) if match else None


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
