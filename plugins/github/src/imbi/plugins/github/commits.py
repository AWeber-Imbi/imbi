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

from imbi_plugin_github._hosts import (
    host_to_api_base,
    normalize_host,
    require_ghec_tenant_host,
)
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
# GitHub's compare endpoint caps ``commits[]`` at 250 per page and
# paginates the rest; bound the walk so a pathological single push
# (force-push of thousands of commits) can't pin us on one endpoint.
# 250 * 20 = 5000 commits is far more than any realistic push.
_MAX_COMPARE_PAGES = 20


def _token(credentials: dict[str, str]) -> str:
    token = credentials.get('access_token') or credentials.get('token')
    if not token:
        raise ValueError(
            'github-commit-sync requires a service token; expected '
            "``credentials['access_token']``"
        )
    return token


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
    async with _client(base, owner, repo, _token(credentials)) as client:
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
    async with _client(base, owner, repo, _token(credentials)) as client:
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

    Declares its own ``access_token`` service credential -- it is *not*
    folded into the identity / deployment / lifecycle plugins, which run
    as the acting user and carry no service token.
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
                label='GitHub Token',
                description='Service token used to fetch commit history.',
            )
        ],
    )

    @classmethod
    def actions(cls) -> list[ActionDescriptor]:
        return [sync_commits_descriptor, sync_tags_descriptor]
