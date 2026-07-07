"""GitHub commit / tag history sync (webhook action plugin).

The module exposes two webhook actions -- ``sync_commits`` and
``sync_tags`` -- dispatched by ``imbi-gateway`` on ``push`` deliveries
(catalogued by the plugin's ``webhook-actions`` capability). The API base
is resolved per call, in order:

1. ``api_base_url`` from the rule's ``handler_config`` (explicit
   override), else
2. the Integration's ``flavor`` + ``host`` options on
   ``ctx.integration_options``, else
3. the push payload's ``repository.url`` (already the flavor-correct API
   URL) as a last resort.

The :class:`GitHubCommitSync` capability handler exposes
:meth:`~GitHubCommitSync.sync_all_history` for an on-demand, host-invoked
backfill: there is no push payload, so the GitHub host is read from
``ctx.integration_options`` and ``(owner, repo)`` from the project links;
it walks the full default-branch history and the complete tag list rather
than a single push delta.

Commit / tag rows are written to the shared ClickHouse ``commits`` /
``tags`` tables via :func:`imbi_common.clickhouse.insert`. Writes are
best-effort: a storage failure is logged and swallowed so an analytics
hiccup never 5xxs the webhook, exactly as the gateway's own event
recording behaves.
"""

from __future__ import annotations

import asyncio
import collections
import collections.abc
import datetime
import logging
import time
import typing
import urllib.parse

import httpx
import jsonpointer
import pydantic
from imbi_common import clickhouse
from imbi_common.json_pointer import JsonPointer
from imbi_common.models import CommitRecord, TagRecord
from imbi_common.plugins.base import (
    ActionDescriptor,
    CheckStatus,
    CommitSyncCapability,
    PluginContext,
)
from imbi_common.plugins.errors import PluginRateLimited

from imbi_plugin_github import _app_auth
from imbi_plugin_github._hosts import host_to_api_base, resolve_host
from imbi_plugin_github._repos import resolve_owner_repo
from imbi_plugin_github.deployment import (
    _auth_headers,  # pyright: ignore[reportPrivateUsage]
    _check_runs_to_status,  # pyright: ignore[reportPrivateUsage]
    _checks_disabled,  # pyright: ignore[reportPrivateUsage]
    _next_page_url,  # pyright: ignore[reportPrivateUsage]
    _parse_iso,  # pyright: ignore[reportPrivateUsage]
    _query_param,  # pyright: ignore[reportPrivateUsage]
    _raise_on_401,  # pyright: ignore[reportPrivateUsage]
    _record_checks_disabled,  # pyright: ignore[reportPrivateUsage]
    _short_sha,  # pyright: ignore[reportPrivateUsage]
)

LOGGER = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 10.0
_ZERO_SHA = '0' * 40
# GitHub's compare endpoint caps ``commits[]`` at 250 per page and
# paginates the rest; bound the walk so a pathological single push
# (force-push of thousands of commits) can't pin us on one endpoint.
# 250 * 20 = 5000 commits is far more than any realistic push.
_MAX_COMPARE_PAGES = 20
# On-demand full-history sync walks ``GET /commits`` from the default
# branch head.  100 per page * 100 pages = 10k commits caps a one-shot
# backfill so a very deep repo can't pin the worker indefinitely; the
# walk logs a truncation warning when it hits the cap.
_MAX_HISTORY_PAGES = 100
# CI status is hydrated with one ``/check-runs`` call per commit, which is
# prohibitively expensive across a full-history backfill.  Bound it to the
# most-recent commits (the only ones whose CI is still meaningful and
# unexpired); older commits keep the ``'unknown'`` default.
_BACKFILL_CI_LIMIT = 25

# Per-context ceilings on how long a *single* rate-limit pause may block
# before the sync gives up best-effort (logged).  The webhook actions
# (``sync_commits`` / ``sync_tags``) run inside the gateway's request
# path, so they pause only briefly and bail when GitHub's reset is
# further out -- a later push re-syncs the gap (``ReplacingMergeTree``
# dedupes).  The on-demand backfill (``sync_all_history``) runs in a
# background worker and can wait out a full primary-limit reset.
_WEBHOOK_MAX_WAIT_SECONDS = 60.0
_BACKFILL_MAX_WAIT_SECONDS = 900.0
# GitHub's documented floor to wait when a secondary (abuse) rate-limit
# response carries neither ``retry-after`` nor an exhausted
# ``x-ratelimit-*`` to time the resume from.
_SECONDARY_LIMIT_WAIT_SECONDS = 60.0
# Small cushion added to a primary-limit reset wait so minor clock skew
# between us and GitHub can't wake us a hair early into a re-throttle.
_RESET_BUFFER_SECONDS = 1.0
# Pathological-loop guard: how many times one request may be paused and
# retried before giving up.  A primary reset / ``retry-after`` normally
# clears the limit on the first retry, so this only bounds a misbehaving
# endpoint.
_MAX_THROTTLE_RETRIES = 3


def _header_int(response: httpx.Response, name: str) -> int | None:
    """Parse an integer response header, ``None`` when absent/malformed."""
    raw = response.headers.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _throttle_wait(response: httpx.Response) -> float | None:
    """Seconds to pause for GitHub's rate-limit headers, else ``None``.

    Detects both throttle styles GitHub documents and reads the resume
    time straight from the response:

    * **secondary limit** -- a ``retry-after`` header (any status): honor
      it verbatim;
    * **primary limit** -- ``x-ratelimit-remaining: 0`` with an
      ``x-ratelimit-reset`` epoch: wait until the reset (plus a small
      clock-skew cushion);
    * a 403/429 that exhausted the quota but gives no reset -> the
      conservative ``_SECONDARY_LIMIT_WAIT_SECONDS`` floor.

    GHES/GHEC sometimes return a secondary (abuse) limit as a 403/429 with
    *none* of the standard headers -- only the documented body message
    ("You have exceeded a secondary rate limit ..."); that phrase is
    matched as a last resort so such a response pauses on the floor rather
    than being mistaken for a hard failure.

    Returns ``None`` for anything that is *not* a throttle signal --
    including a non-rate-limit 403 (e.g. insufficient scope), which must
    fall through to the caller's normal error handling rather than be
    mistaken for a pause.  A successful response that merely depleted the
    quota (``remaining == 0`` on a 2xx) also yields a wait, so the caller
    can pause pre-emptively before the next request.
    """
    retry_after = response.headers.get('retry-after')
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            return _SECONDARY_LIMIT_WAIT_SECONDS
    if _header_int(response, 'x-ratelimit-remaining') == 0:
        reset = _header_int(response, 'x-ratelimit-reset')
        if reset is not None:
            return max(0.0, reset - time.time()) + _RESET_BUFFER_SECONDS
        if response.status_code in (403, 429):
            return _SECONDARY_LIMIT_WAIT_SECONDS
    if response.status_code in (403, 429) and _is_secondary_limit_body(
        response
    ):
        return _SECONDARY_LIMIT_WAIT_SECONDS
    return None


def _is_secondary_limit_body(response: httpx.Response) -> bool:
    """True if a 403/429 body carries GitHub's secondary-limit message.

    Matched conservatively on the documented phrase so a genuine
    permission 403 (which the caller must surface) is never mistaken for
    a throttle.
    """
    try:
        body = response.text
    except (UnicodeDecodeError, httpx.ResponseNotRead):
        return False
    return 'secondary rate limit' in body.lower()


async def _request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_wait: float,
    **kwargs: typing.Any,
) -> httpx.Response:
    """Issue a request, pausing and resuming on GitHub rate limits.

    On a throttled response (403/429 carrying a rate-limit signal) sleeps
    for the interval GitHub states in its headers, then retries -- up to
    ``_MAX_THROTTLE_RETRIES`` times and never longer than *max_wait* on a
    single pause.  When the stated wait exceeds *max_wait* (or the retries
    are exhausted) :class:`PluginRateLimited` is raised carrying the epoch
    at which GitHub will resume, so the host can pause the work and keep it
    queued rather than fail it; on the webhook path the caller swallows it
    (a later push re-syncs the gap).  After a *successful* response that
    exhausted the remaining quota, pauses pre-emptively (subject to the
    same cap) so the next call doesn't spend a round-trip on a guaranteed
    rejection.
    """
    attempts = 0
    while True:
        response = await client.request(method, url, **kwargs)
        wait = _throttle_wait(response)
        if wait is None:
            return response
        if response.status_code not in (403, 429):
            # Pre-emptive: the request succeeded but drained the quota;
            # pause (bounded) so the next call isn't a guaranteed 403,
            # then hand back the good response.
            if wait <= max_wait:
                LOGGER.info(
                    'github-commit-sync quota exhausted on %s; pausing '
                    '%.0fs before continuing',
                    url,
                    wait,
                )
                await asyncio.sleep(wait)
            return response
        if wait > max_wait or attempts >= _MAX_THROTTLE_RETRIES:
            LOGGER.warning(
                'github-commit-sync rate-limited on %s (wait %.0fs, cap '
                '%.0fs, attempt %d); pausing job until GitHub resumes',
                url,
                wait,
                max_wait,
                attempts + 1,
            )
            raise PluginRateLimited(
                retry_at=time.time() + wait,
                message=(
                    f'github-commit-sync rate-limited on {url}; '
                    f'resume in {wait:.0f}s'
                ),
            )
        attempts += 1
        LOGGER.warning(
            'github-commit-sync rate-limited on %s; pausing %.0fs then '
            'retrying (attempt %d/%d)',
            url,
            wait,
            attempts,
            _MAX_THROTTLE_RETRIES,
        )
        await asyncio.sleep(wait)


async def _resolve_bearer(
    credentials: dict[str, str], base: str, owner: str, repo: str
) -> str:
    """Resolve the Bearer token used for the repo's GitHub API calls.

    Prefers an explicit PAT (``access_token``/``token``).  Otherwise
    mints a short-lived GitHub App installation token from ``app_id`` +
    ``private_key`` (with an optional ``installation_id`` that skips
    per-repo installation discovery).  Tokens are cached process-wide by
    :mod:`imbi_plugin_github._app_auth`.
    """
    token = credentials.get('access_token') or credentials.get('token')
    if token:
        return token
    app_id = credentials.get('app_id')
    private_key = credentials.get('private_key')
    if app_id and private_key:
        return await _app_auth.installation_token(
            base=base,
            app_id=app_id,
            private_key=private_key,
            installation_id=credentials.get('installation_id') or None,
            owner=owner,
            repo=repo,
        )
    raise ValueError(
        'github-commit-sync requires either an access_token (PAT) or '
        'app_id + private_key (GitHub App) credentials'
    )


def _resolve(pointer: jsonpointer.JsonPointer, event: object) -> object:
    """Resolve a JSON Pointer against the event, ``None`` if absent."""
    return typing.cast(
        'object',
        pointer.resolve(event, None),  # pyright: ignore[reportUnknownMemberType]
    )


def _branch_short_name(ref: str) -> str:
    prefix = 'refs/heads/'
    return ref.removeprefix(prefix)


def _api_base_from_repo_url(repo_url: object) -> str | None:
    """Derive the API base from the push payload's ``repository.url``.

    The repo URL is the flavor-correct API URL
    (``https://api.github.com/repos/owner/repo`` on github.com,
    ``https://host/api/v3/repos/owner/repo`` on GHES); strip everything
    from ``/repos/`` onward to recover the base.
    """
    if not isinstance(repo_url, str):
        return None
    marker = '/repos/'
    idx = repo_url.find(marker)
    if idx == -1:
        return None
    return repo_url[:idx]


def _resolve_api_base(
    ctx: PluginContext,
    explicit: str | None,
    repo_url_pointer: jsonpointer.JsonPointer,
    event: object,
) -> str | None:
    """Pick the GitHub API base for this call (see module docstring)."""
    if explicit:
        return explicit.rstrip('/')
    host = resolve_host(ctx.integration_options, 'github-commit-sync')
    if host:
        return host_to_api_base(host)
    base = _api_base_from_repo_url(_resolve(repo_url_pointer, event))
    if base:
        LOGGER.info(
            "github-commit-sync falling back to the event's repository.url "
            'for the API base; no api_base_url or resolvable Integration '
            'flavor/host was available'
        )
        return base
    return None


def _owner_repo(
    selector: jsonpointer.JsonPointer, event: object
) -> tuple[str, str] | None:
    full_name = _resolve(selector, event)
    if not isinstance(full_name, str) or '/' not in full_name:
        return None
    owner, _, repo = full_name.partition('/')
    if not owner or not repo:
        return None
    return owner, repo


def _resolve_repo_and_base(
    ctx: PluginContext,
    action_config: SyncCommitsConfig | SyncTagsConfig,
    event: object,
) -> tuple[str, str, str] | None:
    """Resolve ``(owner, repo, api_base)`` for an action.

    Returns ``None`` (after logging) when the owner/repo or API base
    can't be determined, so both action callables share one short-circuit.
    """
    owner_repo = _owner_repo(action_config.repository_selector, event)
    if owner_repo is None:
        LOGGER.warning('github-commit-sync: no owner/repo in push payload')
        return None
    base = _resolve_api_base(
        ctx,
        action_config.api_base_url,
        action_config.repo_api_url_selector,
        event,
    )
    if base is None:
        LOGGER.warning(
            'github-commit-sync: could not resolve a GitHub API base for '
            'project %s',
            ctx.project_id,
        )
        return None
    owner, repo = owner_repo
    return owner, repo, base


def _client(base: str, owner: str, repo: str, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f'{base}/repos/{owner}/{repo}',
        headers=_auth_headers(token),
        timeout=_HTTP_TIMEOUT_SECONDS,
        event_hooks={'response': [_raise_on_401]},
    )


ResolveUser = collections.abc.Callable[
    [str], collections.abc.Awaitable[str | None]
]

# Process-wide, bounded LRU cache of resolved commit-author identities,
# keyed by ``(api_base, subject)``.  The subject is GitHub's numeric user
# id, which is only unique *per host* (github.com id 42 != a GHES id 42),
# so the resolved API base scopes the key.  Only *successful* resolutions
# are cached: within a single sync :func:`_resolve_author_users` already
# de-dupes subjects, and leaving misses uncached means a contributor who
# links their Imbi identity later is picked up on the next sync instead
# of being stuck unresolved for the process's lifetime.  An
# ``OrderedDict`` gives LRU eviction once the cache exceeds
# ``_USER_CACHE_MAX`` entries.
_USER_CACHE: collections.OrderedDict[tuple[str, str], str] = (
    collections.OrderedDict()
)
_USER_CACHE_MAX = 8192


async def _resolve_user(
    resolver: ResolveUser, base: str, subject: str
) -> str | None:
    """Resolve a GitHub user id to an Imbi email, LRU-cached per host.

    ``subject`` is the GitHub numeric user id (the identity-plugin
    subject).  Only successful resolutions are memoized under
    ``(base, subject)``; a miss is returned but not cached, so a
    contributor who links their Imbi identity later resolves on a
    subsequent sync rather than being memoized as unresolved for the
    process's lifetime.
    """
    key = (base, subject)
    if key in _USER_CACHE:
        _USER_CACHE.move_to_end(key)
        return _USER_CACHE[key]
    email = await resolver(subject)
    if email is None:
        return None
    _USER_CACHE[key] = email
    _USER_CACHE.move_to_end(key)
    if len(_USER_CACHE) > _USER_CACHE_MAX:
        _USER_CACHE.popitem(last=False)
    return email


async def _resolve_author_users(
    raw: list[dict[str, typing.Any]],
    resolver: ResolveUser | None,
    base: str,
) -> dict[str, str]:
    """Map each commit's GitHub author id to a resolved Imbi email.

    Returns an empty map when the host wired no resolver.  Distinct
    author ids are resolved once each (LRU-cached across syncs); misses
    are dropped, so the map carries only positive matches and
    :func:`_author_user` falls back to ``''`` for everyone else.
    """
    if resolver is None:
        return {}
    subjects: set[str] = set()
    for item in raw:
        gh_author: dict[str, typing.Any] = item.get('author') or {}
        gid = gh_author.get('id')
        if gid is not None:
            subjects.add(str(gid))
    out: dict[str, str] = {}
    for subject in subjects:
        try:
            email = await _resolve_user(resolver, base, subject)
        except Exception as exc:  # noqa: BLE001 - attribution is best-effort
            LOGGER.warning(
                'github-commit-sync: failed to resolve author %s; '
                'leaving unattributed: %s',
                subject,
                exc,
            )
            continue
        if email:
            out[subject] = email
    return out


def _author_user(item: dict[str, typing.Any], user_map: dict[str, str]) -> str:
    """Resolved Imbi email for a commit's author, ``''`` when unmatched."""
    gh_author: dict[str, typing.Any] = item.get('author') or {}
    gid = gh_author.get('id')
    return user_map.get(str(gid), '') if gid is not None else ''


def _commit_record(
    item: dict[str, typing.Any],
    *,
    project_id: str,
    ref: str,
    pushed_at: datetime.datetime,
    author_user: str = '',
    ci_status: CheckStatus = 'unknown',
) -> CommitRecord:
    """Map a GitHub commit object onto a :class:`CommitRecord`.

    Reads the full set of fields the ``commits`` table carries (author
    email + linked login + committer), which the UI-facing
    ``Commit``/``_commit_from_payload`` mapping drops, so it maps the raw
    item directly while reusing the low-level ``_short_sha`` / ``_parse_iso``
    helpers.  ``ci_status`` is supplied by the caller (hydrated from
    ``/check-runs``); it defaults to ``'unknown'`` when not resolved.
    """
    sha = str(item.get('sha') or '')
    commit_meta: dict[str, typing.Any] = item.get('commit') or {}
    author_meta: dict[str, typing.Any] = commit_meta.get('author') or {}
    committer_meta: dict[str, typing.Any] = commit_meta.get('committer') or {}
    gh_author: dict[str, typing.Any] = item.get('author') or {}
    authored_at = _parse_iso(author_meta.get('date'))
    return CommitRecord(
        project_id=project_id,
        sha=sha,
        short_sha=_short_sha(sha),
        ref=ref,
        message=str(commit_meta.get('message') or ''),
        author_name=str(author_meta.get('name') or ''),
        author_email=str(author_meta.get('email') or ''),
        author_login=str(gh_author.get('login') or ''),
        author_user=author_user,
        committer_name=str(committer_meta.get('name') or ''),
        ci_status=ci_status,
        authored_at=authored_at or pushed_at,
        committed_at=_parse_iso(committer_meta.get('date')),
        url=str(item.get('html_url') or ''),
        pushed_at=pushed_at,
    )


async def _fetch_compare_commits(
    client: httpx.AsyncClient, base: str, head: str, *, max_wait: float
) -> list[dict[str, typing.Any]]:
    """``GET /compare/{base}...{head}`` following the Link pagination."""
    quoted = urllib.parse.quote(f'{base}...{head}', safe='.')
    path = f'/compare/{quoted}'
    params: dict[str, str] = {'per_page': '250'}
    commits: list[dict[str, typing.Any]] = []
    for page in range(1, _MAX_COMPARE_PAGES + 1):
        resp = await _request(
            client, 'GET', path, params=params, max_wait=max_wait
        )
        resp.raise_for_status()
        payload = typing.cast('dict[str, typing.Any]', resp.json())
        commits.extend(payload.get('commits') or [])
        next_url = _next_page_url(resp.headers.get('link'))
        if next_url is None:
            return commits
        next_page = _query_param(next_url, 'page')
        if next_page is None:
            return commits
        params['page'] = next_page
        if page == _MAX_COMPARE_PAGES:
            LOGGER.warning(
                'github-commit-sync truncated compare at %d pages (%d '
                'commits); a wider range will not be fully captured',
                _MAX_COMPARE_PAGES,
                len(commits),
            )
    return commits


async def _last_known_sha(project_id: str) -> str | None:
    """Best-effort lookup of the project's most recently pushed commit.

    Heals gaps from missed deliveries when a push arrives with a zero
    ``before`` (new branch). Any failure is swallowed -- the caller
    falls back to a bounded recent-history fetch.
    """
    try:
        rows = await clickhouse.query(
            'SELECT argMax(sha, pushed_at) AS sha FROM commits '
            'WHERE project_id = {pid:String}',
            {'pid': project_id},
        )
    except Exception:  # noqa: BLE001
        LOGGER.debug(
            'github-commit-sync last-known-sha lookup failed for %s',
            project_id,
            exc_info=True,
        )
        return None
    if rows and rows[0].get('sha'):
        return str(rows[0]['sha'])
    return None


async def _fetch_recent_commits(
    client: httpx.AsyncClient, head: str, limit: int, *, max_wait: float
) -> list[dict[str, typing.Any]]:
    """Bounded ``GET /commits?sha={head}`` fallback for new branches."""
    resp = await _request(
        client,
        'GET',
        '/commits',
        params={'sha': head, 'per_page': str(max(1, min(limit, 100)))},
        max_wait=max_wait,
    )
    resp.raise_for_status()
    return typing.cast('list[dict[str, typing.Any]]', resp.json())


async def _ci_status(
    client: httpx.AsyncClient,
    sha: str,
    *,
    credentials: dict[str, str],
    base: str,
    owner: str,
    repo: str,
    max_wait: float,
) -> CheckStatus:
    """Roll up ``/commits/{sha}/check-runs`` into a ci_status string.

    Reuses the deployment plugin's ``/check-runs`` mapping and its 403
    "checks disabled" cache so a token without the scope spends one 403
    rather than one per commit.  Degrades to ``'unknown'`` on a 403, any
    non-200, a parse error, a network error, or a rate-limit pause -- CI
    status is best-effort metadata and must never fail the sync, mirroring
    the swallow-and-continue contract the rest of this module follows.
    """
    if _checks_disabled(credentials, base, owner, repo):
        return 'unknown'
    try:
        resp = await _request(
            client, 'GET', f'/commits/{sha}/check-runs', max_wait=max_wait
        )
        if resp.status_code == 403:
            _record_checks_disabled(credentials, base, owner, repo)
            return 'unknown'
        if resp.status_code != 200:
            return 'unknown'
        payload = typing.cast('dict[str, typing.Any]', resp.json())
    except Exception:  # noqa: BLE001 - CI status is best-effort metadata
        return 'unknown'
    return _check_runs_to_status(payload)


async def _hydrate_ci(
    client: httpx.AsyncClient,
    shas: list[str],
    *,
    credentials: dict[str, str],
    base: str,
    owner: str,
    repo: str,
    max_wait: float,
) -> dict[str, CheckStatus]:
    """Resolve ``ci_status`` for ``shas`` -> ``{sha: status}``.

    Probes the head commit first so a 403 (missing scope / Actions
    disabled) populates the cache and short-circuits the rest, mirroring
    the deployment plugin's commit picker.  Shas absent from the returned
    map fall back to ``'unknown'`` at the call site.
    """
    out: dict[str, CheckStatus] = {}
    if not shas or _checks_disabled(credentials, base, owner, repo):
        return out
    head, *tail = shas
    out[head] = await _ci_status(
        client,
        head,
        credentials=credentials,
        base=base,
        owner=owner,
        repo=repo,
        max_wait=max_wait,
    )
    if not tail or _checks_disabled(credentials, base, owner, repo):
        return out
    results = await asyncio.gather(
        *(
            _ci_status(
                client,
                sha,
                credentials=credentials,
                base=base,
                owner=owner,
                repo=repo,
                max_wait=max_wait,
            )
            for sha in tail
        )
    )
    out.update(dict(zip(tail, results, strict=True)))
    return out


def _resolve_host_for_context(ctx: PluginContext) -> str | None:
    """Resolve the GitHub web host for an on-demand sync (no payload).

    Reads the Integration's ``flavor`` + ``host`` options from
    ``ctx.integration_options`` and returns the resolved host (github.com,
    a GHEC tenant, or a GHES appliance). Unlike the webhook path there is
    no push payload to fall back to, so a missing/unusable flavor/host
    yields ``None``.
    """
    return resolve_host(ctx.integration_options, 'github-commit-sync')


async def _fetch_default_branch(
    client: httpx.AsyncClient, *, max_wait: float
) -> str:
    """Return the repo's default branch name (``main`` when unknown)."""
    # httpx normalises ``base_url`` with a trailing slash; GHEC's gateway
    # 404s on ``/repos/<o>/<r>/`` so request the absolute URL with the
    # trailing slash stripped, matching the deployment plugin.
    url = str(client.base_url).rstrip('/')
    resp = await _request(client, 'GET', url, max_wait=max_wait)
    resp.raise_for_status()
    meta = typing.cast('dict[str, typing.Any]', resp.json())
    return str(meta.get('default_branch') or 'main')


async def _fetch_all_commits(
    client: httpx.AsyncClient, branch: str, *, max_wait: float
) -> list[dict[str, typing.Any]]:
    """Walk every commit reachable from ``branch`` via Link pagination.

    Capped at ``_MAX_HISTORY_PAGES`` (logged on truncation) so a very deep
    repo can't pin a one-shot backfill indefinitely.
    """
    params: dict[str, str] = {'sha': branch, 'per_page': '100'}
    out: list[dict[str, typing.Any]] = []
    for page in range(1, _MAX_HISTORY_PAGES + 1):
        resp = await _request(
            client, 'GET', '/commits', params=params, max_wait=max_wait
        )
        resp.raise_for_status()
        out.extend(typing.cast('list[dict[str, typing.Any]]', resp.json()))
        next_url = _next_page_url(resp.headers.get('link'))
        if next_url is None:
            return out
        next_page = _query_param(next_url, 'page')
        if next_page is None:
            return out
        params['page'] = next_page
        if page == _MAX_HISTORY_PAGES:
            LOGGER.warning(
                'github-commit-sync truncated history at %d pages (%d '
                'commits); older commits will not be recorded',
                _MAX_HISTORY_PAGES,
                len(out),
            )
    return out


async def _insert_best_effort(
    table: str, records: list[pydantic.BaseModel], project_id: str
) -> int:
    """Insert ``records`` into ``table``; return rows written (0 on fail).

    ``imbi_common.clickhouse.insert`` rejects an empty list, so an empty
    set short-circuits to 0.  A storage failure is logged and swallowed,
    mirroring the webhook actions -- an analytics hiccup must not fail the
    sync.
    """
    if not records:
        return 0
    try:
        await clickhouse.insert(table, records)
    except Exception:
        LOGGER.exception(
            'github-commit-sync: failed to record %d %s rows for project %s',
            len(records),
            table,
            project_id,
        )
        return 0
    return len(records)


class SyncCommitsConfig(pydantic.BaseModel):
    """``WebhookRule.handler_config`` for ``sync_commits``.

    Selectors resolve against the event context, so the push body lives
    under ``/payload`` (e.g. ``/payload/after``).
    """

    before_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer('/payload/before')
    )
    after_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer('/payload/after')
    )
    ref_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer('/payload/ref')
    )
    repository_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer(
            '/payload/repository/full_name'
        )
    )
    api_base_url: str | None = None
    repo_api_url_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer(
            '/payload/repository/url'
        )
    )
    initial_limit: int = 100


class SyncTagsConfig(pydantic.BaseModel):
    """``WebhookRule.handler_config`` for ``sync_tags``.

    Selectors resolve against the event context, so the push body lives
    under ``/payload`` (e.g. ``/payload/ref``).
    """

    ref_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer('/payload/ref')
    )
    after_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer('/payload/after')
    )
    repository_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer(
            '/payload/repository/full_name'
        )
    )
    api_base_url: str | None = None
    repo_api_url_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer(
            '/payload/repository/url'
        )
    )
    reconcile_all: bool = False


async def sync_commits(
    *,
    ctx: PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: SyncCommitsConfig,
    event: object,
) -> None:
    """Sync the commits in a ``push`` delivery into the ``commits`` table.

    Branch gating is the rule's CEL ``filter_expression``'s job; this
    action does not filter refs itself.
    """
    del external_identifier
    after = _resolve(action_config.after_selector, event)
    if not isinstance(after, str) or not after or after == _ZERO_SHA:
        return  # branch delete / no head -- nothing to sync
    resolved = _resolve_repo_and_base(ctx, action_config, event)
    if resolved is None:
        return
    owner, repo, base = resolved
    ref_raw = _resolve(action_config.ref_selector, event)
    ref = _branch_short_name(ref_raw if isinstance(ref_raw, str) else '')
    before = _resolve(action_config.before_selector, event)
    pushed_at = datetime.datetime.now(datetime.UTC)
    token = await _resolve_bearer(credentials, base, owner, repo)
    ci_by_sha: dict[str, CheckStatus] = {}
    try:
        async with _client(base, owner, repo, token) as client:
            if isinstance(before, str) and before and before != _ZERO_SHA:
                raw = await _fetch_compare_commits(
                    client, before, after, max_wait=_WEBHOOK_MAX_WAIT_SECONDS
                )
            else:
                last = await _last_known_sha(ctx.project_id)
                if last:
                    raw = await _fetch_compare_commits(
                        client, last, after, max_wait=_WEBHOOK_MAX_WAIT_SECONDS
                    )
                else:
                    raw = await _fetch_recent_commits(
                        client,
                        after,
                        action_config.initial_limit,
                        max_wait=_WEBHOOK_MAX_WAIT_SECONDS,
                    )
            ci_by_sha = await _hydrate_ci(
                client,
                [str(i['sha']) for i in raw if i.get('sha')],
                credentials=credentials,
                base=base,
                owner=owner,
                repo=repo,
                max_wait=_WEBHOOK_MAX_WAIT_SECONDS,
            )
    except PluginRateLimited as exc:
        LOGGER.warning(
            'github-commit-sync: rate-limited syncing commits for project '
            '%s; skipping this push (a later push re-syncs the gap): %s',
            ctx.project_id,
            exc,
        )
        return
    user_map = await _resolve_author_users(
        raw, ctx.resolve_user_by_identity, base
    )
    records: list[pydantic.BaseModel] = [
        _commit_record(
            item,
            project_id=ctx.project_id,
            ref=ref,
            pushed_at=pushed_at,
            author_user=_author_user(item, user_map),
            ci_status=ci_by_sha.get(str(item['sha']), 'unknown'),
        )
        for item in raw
        if item.get('sha')
    ]
    if not records:
        return
    try:
        await clickhouse.insert('commits', records)
    except Exception:
        LOGGER.exception(
            'github-commit-sync: failed to record %d commits for project %s',
            len(records),
            ctx.project_id,
        )


async def _annotated_tag(
    client: httpx.AsyncClient, sha: str, *, max_wait: float
) -> dict[str, typing.Any] | None:
    """Fetch annotated-tag metadata, ``None`` for a lightweight tag."""
    resp = await _request(client, 'GET', f'/git/tags/{sha}', max_wait=max_wait)
    if resp.status_code != 200:
        return None
    return typing.cast('dict[str, typing.Any]', resp.json())


async def _commit_date(
    client: httpx.AsyncClient, sha: str, *, max_wait: float
) -> datetime.datetime | None:
    """Committer date of commit *sha*, ``None`` when unavailable.

    Lightweight tags carry no tagger date, so their target commit's
    date stands in for ``tagged_at`` — otherwise the ClickHouse row
    falls back to ``recorded_at`` (sync time) and every release in the
    UI reads "just now" after a full reconcile.
    """
    resp = await _request(
        client, 'GET', f'/git/commits/{sha}', max_wait=max_wait
    )
    if resp.status_code != 200:
        return None
    data = typing.cast('dict[str, typing.Any]', resp.json())
    committer: dict[str, typing.Any] = data.get('committer') or {}
    return _parse_iso(committer.get('date'))


async def _release_published_for_tag(
    client: httpx.AsyncClient, name: str, *, max_wait: float
) -> datetime.datetime | None:
    """Published date of the GitHub release for tag *name*, if any."""
    resp = await _request(
        client,
        'GET',
        f'/releases/tags/{urllib.parse.quote(name, safe="")}',
        max_wait=max_wait,
    )
    if resp.status_code != 200:
        return None
    data = typing.cast('dict[str, typing.Any]', resp.json())
    return _parse_iso(data.get('published_at'))


async def _release_published_map(
    client: httpx.AsyncClient, *, max_wait: float
) -> dict[str, datetime.datetime]:
    """Map tag name -> GitHub release published date for the repo.

    One paginated ``/releases`` sweep instead of a per-tag lookup;
    drafts (``published_at`` null) are skipped.
    """
    out: dict[str, datetime.datetime] = {}
    params: dict[str, str] = {'per_page': '100'}
    while True:
        resp = await _request(
            client, 'GET', '/releases', params=params, max_wait=max_wait
        )
        if resp.status_code != 200:
            return out
        rows = typing.cast('list[dict[str, typing.Any]]', resp.json())
        for row in rows:
            tag = row.get('tag_name')
            published = _parse_iso(row.get('published_at'))
            if tag and published:
                out[str(tag)] = published
        next_url = _next_page_url(resp.headers.get('link'))
        if next_url is None:
            return out
        next_page = _query_param(next_url, 'page')
        if next_page is None:
            return out
        params['page'] = next_page


def _web_base(api_base: str) -> str:
    """Map a REST API base to the web host (inverse of the routing table).

    ``https://api.github.com`` -> ``https://github.com``;
    ``https://api.<tenant>.ghe.com`` -> ``https://<tenant>.ghe.com``;
    GHES ``https://<host>/api/v3`` -> ``https://<host>``.
    """
    if api_base.endswith('/api/v3'):
        return api_base[: -len('/api/v3')]
    return api_base.replace('://api.', '://', 1)


def _tag_web_url(client: httpx.AsyncClient, name: str) -> str:
    """Build the web URL for *name* from the client's repo-scoped base."""
    full = str(client.base_url).rstrip('/')
    marker = '/repos/'
    idx = full.find(marker)
    if idx == -1:
        return ''
    web = _web_base(full[:idx])
    owner_repo = full[idx + len(marker) :]
    return f'{web}/{owner_repo}/releases/tag/{urllib.parse.quote(name)}'


def _tag_record(
    *,
    project_id: str,
    name: str,
    sha: str,
    annotated: dict[str, typing.Any] | None = None,
    url: str = '',
    published_at: datetime.datetime | None = None,
    fallback_tagged_at: datetime.datetime | None = None,
) -> TagRecord:
    """Build the ClickHouse row for one tag.

    ``tagged_at`` preference: the GitHub release's published date
    (*published_at*), then the annotated tag's tagger date, then the
    target commit's committer date (*fallback_tagged_at*, lightweight
    tags only).
    """
    if annotated is None:
        return TagRecord(
            project_id=project_id,
            name=name,
            sha=sha,
            url=url,
            tagged_at=published_at or fallback_tagged_at,
        )
    tagger: dict[str, typing.Any] = annotated.get('tagger') or {}
    return TagRecord(
        project_id=project_id,
        name=name,
        sha=sha,
        url=url,
        message=str(annotated.get('message') or ''),
        tagger_name=str(tagger.get('name') or ''),
        tagger_email=str(tagger.get('email') or ''),
        tagged_at=published_at or _parse_iso(tagger.get('date')),
    )


async def _reconcile_tags(
    client: httpx.AsyncClient, project_id: str, *, max_wait: float
) -> list[TagRecord]:
    """Upsert the repo's full tag list via the git-refs API.

    ``/git/matching-refs/tags`` yields each tag's object sha + type;
    annotated tags (``type == 'tag'``) are enriched with tagger/message/
    date from the tag object, lightweight tags carry name/sha/url only.
    ``ReplacingMergeTree`` dedupes against rows recorded from pushes.
    """
    out: list[TagRecord] = []
    prefix = 'refs/tags/'
    params: dict[str, str] = {'per_page': '100'}
    # Lazily fetched on the first tag so tag-less repos cost nothing.
    released: dict[str, datetime.datetime] | None = None
    while True:
        resp = await _request(
            client,
            'GET',
            '/git/matching-refs/tags',
            params=params,
            max_wait=max_wait,
        )
        resp.raise_for_status()
        rows = typing.cast('list[dict[str, typing.Any]]', resp.json())
        for row in rows:
            ref = str(row.get('ref') or '')
            obj: dict[str, typing.Any] = row.get('object') or {}
            sha = str(obj.get('sha') or '')
            if not ref.startswith(prefix) or not sha:
                continue
            name = ref[len(prefix) :]
            if released is None:
                released = await _release_published_map(
                    client, max_wait=max_wait
                )
            published = released.get(name)
            annotated = (
                await _annotated_tag(client, sha, max_wait=max_wait)
                if obj.get('type') == 'tag'
                else None
            )
            out.append(
                _tag_record(
                    project_id=project_id,
                    name=name,
                    sha=sha,
                    annotated=annotated,
                    url=_tag_web_url(client, name),
                    published_at=published,
                    fallback_tagged_at=(
                        await _commit_date(client, sha, max_wait=max_wait)
                        if annotated is None and published is None
                        else None
                    ),
                )
            )
        next_url = _next_page_url(resp.headers.get('link'))
        if next_url is None:
            return out
        next_page = _query_param(next_url, 'page')
        if next_page is None:
            return out
        params['page'] = next_page


async def sync_tags(
    *,
    ctx: PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: SyncTagsConfig,
    event: object,
) -> None:
    """Sync the tag in a ``push`` delivery into the ``tags`` table."""
    del external_identifier
    ref_raw = _resolve(action_config.ref_selector, event)
    prefix = 'refs/tags/'
    if not isinstance(ref_raw, str) or not ref_raw.startswith(prefix):
        return
    name = ref_raw[len(prefix) :]
    after = _resolve(action_config.after_selector, event)
    if (
        not name
        or not isinstance(after, str)
        or not after
        or after == _ZERO_SHA
    ):
        return  # tag delete / no target
    resolved = _resolve_repo_and_base(ctx, action_config, event)
    if resolved is None:
        return
    owner, repo, base = resolved
    token = await _resolve_bearer(credentials, base, owner, repo)
    try:
        async with _client(base, owner, repo, token) as client:
            annotated = await _annotated_tag(
                client, after, max_wait=_WEBHOOK_MAX_WAIT_SECONDS
            )
            published = await _release_published_for_tag(
                client, name, max_wait=_WEBHOOK_MAX_WAIT_SECONDS
            )
            records: list[pydantic.BaseModel] = [
                _tag_record(
                    project_id=ctx.project_id,
                    name=name,
                    sha=after,
                    annotated=annotated,
                    url=_tag_web_url(client, name),
                    published_at=published,
                    fallback_tagged_at=(
                        await _commit_date(
                            client, after, max_wait=_WEBHOOK_MAX_WAIT_SECONDS
                        )
                        if annotated is None and published is None
                        else None
                    ),
                )
            ]
            if action_config.reconcile_all:
                extra = await _reconcile_tags(
                    client, ctx.project_id, max_wait=_WEBHOOK_MAX_WAIT_SECONDS
                )
                seen = {name}
                records.extend(r for r in extra if r.name not in seen)
    except PluginRateLimited as exc:
        LOGGER.warning(
            'github-commit-sync: rate-limited syncing tags for project '
            '%s; skipping this push (a later push re-syncs the gap): %s',
            ctx.project_id,
            exc,
        )
        return
    try:
        await clickhouse.insert('tags', records)
    except Exception:
        LOGGER.exception(
            'github-commit-sync: failed to record %d tags for project %s',
            len(records),
            ctx.project_id,
        )


sync_commits_descriptor = ActionDescriptor(
    name='sync_commits',
    label='Sync Commit History',
    description=(
        'Fetch the full set of commits in a push (via the GitHub compare '
        'API) and record them in the ClickHouse commits table.'
    ),
    callable=typing.cast(
        'typing.Any', 'imbi_plugin_github.commits:sync_commits'
    ),
    config_model=typing.cast(
        'typing.Any', 'imbi_plugin_github.commits:SyncCommitsConfig'
    ),
)

sync_tags_descriptor = ActionDescriptor(
    name='sync_tags',
    label='Sync Tag History',
    description=(
        'Record the pushed tag (and, when reconcile_all is set, the full '
        'tag list) in the ClickHouse tags table.'
    ),
    callable=typing.cast('typing.Any', 'imbi_plugin_github.commits:sync_tags'),
    config_model=typing.cast(
        'typing.Any', 'imbi_plugin_github.commits:SyncTagsConfig'
    ),
)


class GitHubCommitSync(CommitSyncCapability):
    """Commit / tag history sync capability handler.

    Uses the Integration's shared credential blob (resolved by
    :func:`_resolve_bearer`): a static ``access_token`` PAT when present,
    otherwise a GitHub App (``app_id`` + ``private_key``, raw or base64
    PEM, with an optional ``installation_id``) whose short-lived
    installation token is minted per call and cached.  The gateway-side
    incremental sync flows through the ``sync_commits`` / ``sync_tags``
    webhook actions catalogued by the plugin's ``webhook-actions``
    capability.
    """

    async def check_available(
        self,
        *,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> bool:
        """Whether an on-demand sync can resolve a host + repo for ``ctx``."""
        del credentials
        host = _resolve_host_for_context(ctx)
        if host is None:
            return False
        try:
            resolve_owner_repo(ctx, host, 'github-commit-sync')
        except ValueError:
            return False
        return True

    async def sync_all_history(
        self,
        *,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> tuple[int, int]:
        """Record the project's full default-branch history and all tags.

        Host-invoked (no webhook payload): the host instantiates the
        handler, builds a :class:`PluginContext` carrying the project's
        links and the Integration options, resolves the Integration's
        ``credentials``, and awaits this method.  The GitHub host/flavor
        is read from ``ctx.integration_options``, the ``(owner, repo)``
        from the project links, and the bearer token from the same
        PAT-or-App resolution the webhook actions use.

        Walks every commit reachable from the default branch head plus the
        repo's complete (lightweight) tag list, maps them onto
        ``CommitRecord`` / ``TagRecord``, and upserts into the ClickHouse
        ``commits`` / ``tags`` tables.  ``ReplacingMergeTree`` dedupes
        against rows the webhook already recorded, so re-running is safe.

        Returns ``(commits_recorded, tags_recorded)``.  Raises
        :class:`ValueError` only when the host or repository can't be
        resolved; ClickHouse failures are swallowed (the count reflects
        what was written).  Propagates :class:`PluginRateLimited` when a
        GitHub rate-limit reset is further out than
        ``_BACKFILL_MAX_WAIT_SECONDS`` so the host can pause the worker and
        keep the job queued until GitHub resumes rather than fail it.
        """
        host = _resolve_host_for_context(ctx)
        if host is None:
            raise ValueError(
                'github-commit-sync could not resolve a GitHub host for an '
                'on-demand sync: set the Integration flavor/host'
            )
        base = host_to_api_base(host)
        owner, repo = resolve_owner_repo(ctx, host, 'github-commit-sync')
        pushed_at = datetime.datetime.now(datetime.UTC)
        token = await _resolve_bearer(credentials, base, owner, repo)
        async with _client(base, owner, repo, token) as client:
            branch = await _fetch_default_branch(
                client, max_wait=_BACKFILL_MAX_WAIT_SECONDS
            )
            raw_commits = await _fetch_all_commits(
                client, branch, max_wait=_BACKFILL_MAX_WAIT_SECONDS
            )
            tags = await _reconcile_tags(
                client, ctx.project_id, max_wait=_BACKFILL_MAX_WAIT_SECONDS
            )
            # CI status only for the most-recent commits: one /check-runs
            # call per commit is too costly across full history, and old
            # commits' CI is no longer meaningful.
            ci_by_sha = await _hydrate_ci(
                client,
                [
                    str(i['sha'])
                    for i in raw_commits[:_BACKFILL_CI_LIMIT]
                    if i.get('sha')
                ],
                credentials=credentials,
                base=base,
                owner=owner,
                repo=repo,
                max_wait=_BACKFILL_MAX_WAIT_SECONDS,
            )
        user_map = await _resolve_author_users(
            raw_commits, ctx.resolve_user_by_identity, base
        )
        commit_records: list[pydantic.BaseModel] = [
            _commit_record(
                item,
                project_id=ctx.project_id,
                ref=branch,
                pushed_at=pushed_at,
                author_user=_author_user(item, user_map),
                ci_status=ci_by_sha.get(str(item['sha']), 'unknown'),
            )
            for item in raw_commits
            if item.get('sha')
        ]
        commits_recorded = await _insert_best_effort(
            'commits', commit_records, ctx.project_id
        )
        tags_recorded = await _insert_best_effort(
            'tags', list(tags), ctx.project_id
        )
        return commits_recorded, tags_recorded
