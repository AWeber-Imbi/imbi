"""GitHub commit / tag history sync (webhook action plugin).

A single :class:`GitHubCommitSyncPlugin` exposes two webhook actions --
``sync_commits`` and ``sync_tags`` -- dispatched by ``imbi-gateway`` on
``push`` deliveries. Unlike the identity / deployment / lifecycle
families, the host (github.com vs. GHEC tenant vs. GHES appliance) is
*runtime* data on the webhook path rather than a class attribute, so one
callable serves all three flavors. The API base is resolved per call, in
order:

1. ``api_base_url`` from the rule's ``handler_config`` (explicit
   override), else
2. the GitHub plugin connected to the same ``ThirdPartyService`` --
   surfaced on ``ctx.service_plugins`` (slug -> flavor,
   ``options['host']`` -> host), else
3. the ``ThirdPartyService.api_endpoint``
   (``ctx.assignment_options['service_endpoint']``), else
4. the push payload's ``repository.url`` (already the flavor-correct API
   URL) as a last resort.

The same plugin also exposes :meth:`GitHubCommitSyncPlugin.sync_all_history`
for an on-demand, host-invoked backfill: there is no push payload, so the
GitHub host is read from ``ctx.service_plugins`` and ``(owner, repo)`` from
the project links; it walks the full default-branch history and the
complete tag list rather than a single push delta.

Commit / tag rows are written to the shared ClickHouse ``commits`` /
``tags`` tables via :func:`imbi_common.clickhouse.insert`. Writes are
best-effort: a storage failure is logged and swallowed so an analytics
hiccup never 5xxs the webhook, exactly as the gateway's own event
recording behaves.
"""

from __future__ import annotations

import datetime
import logging
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
    CredentialField,
    PluginContext,
    PluginManifest,
    ServicePlugin,
    WebhookActionPlugin,
)

from imbi_plugin_github import _app_auth
from imbi_plugin_github._hosts import (
    host_to_api_base,
    normalize_host,
    require_ghec_tenant_host,
)
from imbi_plugin_github._repos import resolve_owner_repo
from imbi_plugin_github.deployment import (
    _auth_headers,  # pyright: ignore[reportPrivateUsage]
    _next_page_url,  # pyright: ignore[reportPrivateUsage]
    _parse_iso,  # pyright: ignore[reportPrivateUsage]
    _query_param,  # pyright: ignore[reportPrivateUsage]
    _raise_on_401,  # pyright: ignore[reportPrivateUsage]
    _short_sha,  # pyright: ignore[reportPrivateUsage]
)

LOGGER = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 10.0
_ZERO_SHA = '0' * 40
# This plugin's own slug; skipped when reading the GitHub host/flavor
# from connected ``service_plugins`` so the commit-sync entry can't
# masquerade as a github.com host on a GHEC/GHES service.
_SELF_SLUG = 'github-commit-sync'
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


def _resolve(pointer: jsonpointer.JsonPointer, payload: object) -> object:
    """Resolve a JSON Pointer against the payload, ``None`` if absent."""
    return typing.cast(
        'object',
        pointer.resolve(payload, None),  # pyright: ignore[reportUnknownMemberType]
    )


def _branch_short_name(ref: str) -> str:
    prefix = 'refs/heads/'
    return ref.removeprefix(prefix)


def _github_plugin_host(plugin: ServicePlugin) -> str | None:
    """Resolve the GitHub host from a connected plugin's slug + options.

    Returns ``None`` for non-GitHub plugins and for GitHub plugins whose
    required ``host`` option is missing or invalid (logged) so the caller
    can fall through to the next resolution source.
    """
    slug = plugin.slug
    if not slug.startswith('github'):
        return None
    label = f'github-commit-sync (via {slug})'
    try:
        if slug.endswith('-ec') or slug == 'github-enterprise-cloud':
            return require_ghec_tenant_host(
                normalize_host(plugin.options.get('host'), label), label
            )
        if slug.endswith('-es') or slug == 'github-enterprise-server':
            return normalize_host(plugin.options.get('host'), label)
    except ValueError as exc:
        LOGGER.warning(
            'Connected GitHub plugin %r has an unusable host option: %s',
            slug,
            exc,
        )
        return None
    return 'github.com'


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
    payload: object,
) -> str | None:
    """Pick the GitHub API base for this call (see module docstring)."""
    if explicit:
        return explicit.rstrip('/')
    for plugin in ctx.service_plugins:
        # Skip our own entry: its slug starts with "github" but carries
        # no host option, so _github_plugin_host would mis-resolve it to
        # github.com on a GHEC/GHES service.
        if plugin.slug == _SELF_SLUG:
            continue
        host = _github_plugin_host(plugin)
        if host:
            return host_to_api_base(host)
    endpoint = ctx.assignment_options.get('service_endpoint')
    if isinstance(endpoint, str) and endpoint:
        return endpoint.rstrip('/')
    base = _api_base_from_repo_url(_resolve(repo_url_pointer, payload))
    if base:
        LOGGER.info(
            'github-commit-sync falling back to payload repository.url for '
            'the API base; no api_base_url, connected GitHub plugin, or '
            'service_endpoint was available'
        )
        return base
    return None


def _owner_repo(
    selector: jsonpointer.JsonPointer, payload: object
) -> tuple[str, str] | None:
    full_name = _resolve(selector, payload)
    if not isinstance(full_name, str) or '/' not in full_name:
        return None
    owner, _, repo = full_name.partition('/')
    if not owner or not repo:
        return None
    return owner, repo


def _resolve_repo_and_base(
    ctx: PluginContext,
    action_config: SyncCommitsConfig | SyncTagsConfig,
    payload: object,
) -> tuple[str, str, str] | None:
    """Resolve ``(owner, repo, api_base)`` for an action.

    Returns ``None`` (after logging) when the owner/repo or API base
    can't be determined, so both action callables share one short-circuit.
    """
    owner_repo = _owner_repo(action_config.repository_selector, payload)
    if owner_repo is None:
        LOGGER.warning('github-commit-sync: no owner/repo in push payload')
        return None
    base = _resolve_api_base(
        ctx,
        action_config.api_base_url,
        action_config.repo_api_url_selector,
        payload,
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


def _commit_record(
    item: dict[str, typing.Any],
    *,
    project_id: str,
    ref: str,
    pushed_at: datetime.datetime,
) -> CommitRecord:
    """Map a GitHub commit object onto a :class:`CommitRecord`.

    Reads the full set of fields the ``commits`` table carries (author
    email + linked login + committer), which the UI-facing
    ``Commit``/``_commit_from_payload`` mapping drops, so it maps the raw
    item directly while reusing the low-level ``_short_sha`` / ``_parse_iso``
    helpers.
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
        committer_name=str(committer_meta.get('name') or ''),
        authored_at=authored_at or pushed_at,
        committed_at=_parse_iso(committer_meta.get('date')),
        url=str(item.get('html_url') or ''),
        pushed_at=pushed_at,
    )


async def _fetch_compare_commits(
    client: httpx.AsyncClient, base: str, head: str
) -> list[dict[str, typing.Any]]:
    """``GET /compare/{base}...{head}`` following the Link pagination."""
    quoted = urllib.parse.quote(f'{base}...{head}', safe='.')
    path = f'/compare/{quoted}'
    params: dict[str, str] = {'per_page': '250'}
    commits: list[dict[str, typing.Any]] = []
    for page in range(1, _MAX_COMPARE_PAGES + 1):
        resp = await client.get(path, params=params)
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
    client: httpx.AsyncClient, head: str, limit: int
) -> list[dict[str, typing.Any]]:
    """Bounded ``GET /commits?sha={head}`` fallback for new branches."""
    resp = await client.get(
        '/commits',
        params={'sha': head, 'per_page': str(max(1, min(limit, 100)))},
    )
    resp.raise_for_status()
    return typing.cast('list[dict[str, typing.Any]]', resp.json())


def _resolve_host_for_context(ctx: PluginContext) -> str | None:
    """Resolve the GitHub web host for an on-demand sync (no payload).

    Walks the connected GitHub plugins on ``ctx.service_plugins`` and
    returns the first usable host (github.com, a GHEC tenant, or a GHES
    appliance), skipping this plugin's own entry so a commit-sync row on a
    GHEC/GHES service can't be read as github.com.  Unlike the webhook
    path there is no push payload to fall back to, so the absence of a
    connected GitHub plugin yields ``None``.
    """
    for plugin in ctx.service_plugins:
        if plugin.slug == _SELF_SLUG:
            continue
        host = _github_plugin_host(plugin)
        if host:
            return host
    return None


async def _fetch_default_branch(client: httpx.AsyncClient) -> str:
    """Return the repo's default branch name (``main`` when unknown)."""
    # httpx normalises ``base_url`` with a trailing slash; GHEC's gateway
    # 404s on ``/repos/<o>/<r>/`` so request the absolute URL with the
    # trailing slash stripped, matching the deployment plugin.
    url = str(client.base_url).rstrip('/')
    resp = await client.get(url)
    resp.raise_for_status()
    meta = typing.cast('dict[str, typing.Any]', resp.json())
    return str(meta.get('default_branch') or 'main')


async def _fetch_all_commits(
    client: httpx.AsyncClient, branch: str
) -> list[dict[str, typing.Any]]:
    """Walk every commit reachable from ``branch`` via Link pagination.

    Capped at ``_MAX_HISTORY_PAGES`` (logged on truncation) so a very deep
    repo can't pin a one-shot backfill indefinitely.
    """
    params: dict[str, str] = {'sha': branch, 'per_page': '100'}
    out: list[dict[str, typing.Any]] = []
    for page in range(1, _MAX_HISTORY_PAGES + 1):
        resp = await client.get('/commits', params=params)
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
    """``WebhookRule.handler_config`` for ``sync_commits``."""

    before_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer('/before')
    )
    after_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer('/after')
    )
    ref_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer('/ref')
    )
    repository_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer(
            '/repository/full_name'
        )
    )
    api_base_url: str | None = None
    repo_api_url_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer('/repository/url')
    )
    initial_limit: int = 100


class SyncTagsConfig(pydantic.BaseModel):
    """``WebhookRule.handler_config`` for ``sync_tags``."""

    ref_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer('/ref')
    )
    after_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer('/after')
    )
    repository_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer(
            '/repository/full_name'
        )
    )
    api_base_url: str | None = None
    repo_api_url_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer('/repository/url')
    )
    reconcile_all: bool = False


async def sync_commits(
    *,
    ctx: PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: SyncCommitsConfig,
    payload: object,
) -> None:
    """Sync the commits in a ``push`` delivery into the ``commits`` table.

    Branch gating is the rule's CEL ``filter_expression``'s job; this
    action does not filter refs itself.
    """
    del external_identifier
    after = _resolve(action_config.after_selector, payload)
    if not isinstance(after, str) or not after or after == _ZERO_SHA:
        return  # branch delete / no head -- nothing to sync
    resolved = _resolve_repo_and_base(ctx, action_config, payload)
    if resolved is None:
        return
    owner, repo, base = resolved
    ref_raw = _resolve(action_config.ref_selector, payload)
    ref = _branch_short_name(ref_raw if isinstance(ref_raw, str) else '')
    before = _resolve(action_config.before_selector, payload)
    pushed_at = datetime.datetime.now(datetime.UTC)
    token = await _resolve_bearer(credentials, base, owner, repo)
    async with _client(base, owner, repo, token) as client:
        if isinstance(before, str) and before and before != _ZERO_SHA:
            raw = await _fetch_compare_commits(client, before, after)
        else:
            last = await _last_known_sha(ctx.project_id)
            if last:
                raw = await _fetch_compare_commits(client, last, after)
            else:
                raw = await _fetch_recent_commits(
                    client, after, action_config.initial_limit
                )
    records: list[pydantic.BaseModel] = [
        _commit_record(
            item, project_id=ctx.project_id, ref=ref, pushed_at=pushed_at
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
    client: httpx.AsyncClient, sha: str
) -> dict[str, typing.Any] | None:
    """Fetch annotated-tag metadata, ``None`` for a lightweight tag."""
    resp = await client.get(f'/git/tags/{sha}')
    if resp.status_code != 200:
        return None
    return typing.cast('dict[str, typing.Any]', resp.json())


def _tag_record(
    *,
    project_id: str,
    name: str,
    sha: str,
    annotated: dict[str, typing.Any] | None = None,
) -> TagRecord:
    if annotated is None:
        return TagRecord(project_id=project_id, name=name, sha=sha)
    tagger: dict[str, typing.Any] = annotated.get('tagger') or {}
    return TagRecord(
        project_id=project_id,
        name=name,
        sha=sha,
        message=str(annotated.get('message') or ''),
        tagger_name=str(tagger.get('name') or ''),
        tagger_email=str(tagger.get('email') or ''),
        tagged_at=_parse_iso(tagger.get('date')),
    )


async def _reconcile_tags(
    client: httpx.AsyncClient, project_id: str
) -> list[TagRecord]:
    """Upsert the repo's full tag list (lightweight); ``ReplacingMergeTree``
    dedupes against rows recorded from individual pushes."""
    out: list[TagRecord] = []
    params: dict[str, str] = {'per_page': '100'}
    while True:
        resp = await client.get('/tags', params=params)
        resp.raise_for_status()
        rows = typing.cast('list[dict[str, typing.Any]]', resp.json())
        for row in rows:
            name = str(row.get('name') or '')
            commit: dict[str, typing.Any] = row.get('commit') or {}
            sha = str(commit.get('sha') or '')
            if name and sha:
                out.append(
                    _tag_record(project_id=project_id, name=name, sha=sha)
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
    payload: object,
) -> None:
    """Sync the tag in a ``push`` delivery into the ``tags`` table."""
    del external_identifier
    ref_raw = _resolve(action_config.ref_selector, payload)
    prefix = 'refs/tags/'
    if not isinstance(ref_raw, str) or not ref_raw.startswith(prefix):
        return
    name = ref_raw[len(prefix) :]
    after = _resolve(action_config.after_selector, payload)
    if (
        not name
        or not isinstance(after, str)
        or not after
        or after == _ZERO_SHA
    ):
        return  # tag delete / no target
    resolved = _resolve_repo_and_base(ctx, action_config, payload)
    if resolved is None:
        return
    owner, repo, base = resolved
    token = await _resolve_bearer(credentials, base, owner, repo)
    async with _client(base, owner, repo, token) as client:
        annotated = await _annotated_tag(client, after)
        records: list[pydantic.BaseModel] = [
            _tag_record(
                project_id=ctx.project_id,
                name=name,
                sha=after,
                annotated=annotated,
            )
        ]
        if action_config.reconcile_all:
            extra = await _reconcile_tags(client, ctx.project_id)
            seen = {name}
            records.extend(r for r in extra if r.name not in seen)
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


class GitHubCommitSyncPlugin(WebhookActionPlugin):
    """Webhook-action plugin syncing GitHub commit / tag history.

    Carries its own service credential -- it is *not* folded into the
    identity / deployment / lifecycle plugins, which run as the acting
    user.  Two mutually exclusive auth modes are supported (resolved by
    :func:`_resolve_bearer`):

    * **PAT** -- a static ``access_token``.
    * **GitHub App** -- ``app_id`` + ``private_key`` (raw or base64 PEM),
      with an optional ``installation_id``; the plugin mints a
      short-lived installation token per call and caches it.
    """

    manifest = PluginManifest(
        slug='github-commit-sync',
        name='GitHub Commit History Sync',
        description=(
            'Syncs commit and tag history from GitHub push webhooks into '
            'ClickHouse for analytics.'
        ),
        plugin_type='webhook',
        credentials=[
            CredentialField(
                name='access_token',
                label='GitHub Token (PAT)',
                description=(
                    'Static personal/service access token. Use this *or* '
                    'the GitHub App fields below.'
                ),
                required=False,
            ),
            CredentialField(
                name='app_id',
                label='GitHub App ID',
                description=(
                    'GitHub App identifier; with a private key the plugin '
                    'mints short-lived installation tokens.'
                ),
                required=False,
            ),
            CredentialField(
                name='private_key',
                label='GitHub App Private Key',
                description=(
                    'App private key, raw PEM or base64-encoded PEM.'
                ),
                required=False,
            ),
            CredentialField(
                name='installation_id',
                label='GitHub App Installation ID',
                description=(
                    'Optional. When unset, the installation is discovered '
                    'from the pushed repository.'
                ),
                required=False,
            ),
        ],
    )

    @classmethod
    def actions(cls) -> list[ActionDescriptor]:
        return [sync_commits_descriptor, sync_tags_descriptor]

    async def sync_all_history(
        self,
        *,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> tuple[int, int]:
        """Record the project's full default-branch history and all tags.

        Host-invoked (no webhook payload): the host instantiates the
        plugin, builds a :class:`PluginContext` carrying the project's
        links and the connected ``service_plugins``, resolves this
        plugin's service ``credentials``, and awaits this method.  The
        GitHub host/flavor is read from ``service_plugins``, the
        ``(owner, repo)`` from the project links, and the bearer token
        from the same PAT-or-App resolution the webhook actions use.

        Walks every commit reachable from the default branch head plus the
        repo's complete (lightweight) tag list, maps them onto
        ``CommitRecord`` / ``TagRecord``, and upserts into the ClickHouse
        ``commits`` / ``tags`` tables.  ``ReplacingMergeTree`` dedupes
        against rows the webhook already recorded, so re-running is safe.

        Returns ``(commits_recorded, tags_recorded)``.  Raises
        :class:`ValueError` only when the host or repository can't be
        resolved; ClickHouse failures are swallowed (the count reflects
        what was written).
        """
        host = _resolve_host_for_context(ctx)
        if host is None:
            raise ValueError(
                'github-commit-sync could not resolve a GitHub host for an '
                'on-demand sync: connect a GitHub plugin to the service'
            )
        base = host_to_api_base(host)
        owner, repo = resolve_owner_repo(ctx, host, 'github-commit-sync')
        pushed_at = datetime.datetime.now(datetime.UTC)
        token = await _resolve_bearer(credentials, base, owner, repo)
        async with _client(base, owner, repo, token) as client:
            branch = await _fetch_default_branch(client)
            raw_commits = await _fetch_all_commits(client, branch)
            tags = await _reconcile_tags(client, ctx.project_id)
        commit_records: list[pydantic.BaseModel] = [
            _commit_record(
                item,
                project_id=ctx.project_id,
                ref=branch,
                pushed_at=pushed_at,
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
