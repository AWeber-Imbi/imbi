"""GitHub pull-request history sync (webhook action plugin).

:class:`GitHubPRSyncPlugin` exposes one webhook action --
``sync_pull_requests`` -- dispatched by ``imbi-gateway`` on
``pull_request`` deliveries.  It writes directly to the ClickHouse
``pull_requests`` table rather than relying on the materialized view
that previously extracted PR data from ``imbi.events``.

The plugin also exposes :meth:`GitHubPRSyncPlugin.sync_all_history`
for an on-demand, host-invoked backfill: it walks
``GET /repos/{owner}/{repo}/pulls?state=all`` and records every PR.
GitHub's list-PRs API omits per-file diff stats
(``additions``/``deletions``/``changed_files``), so backfill rows
store ``0`` for those fields; they are accurate on webhook-driven rows.

PR rows are written to the shared ClickHouse ``pull_requests`` table via
:func:`imbi_common.clickhouse.insert`. Writes are best-effort: a storage
failure is logged and swallowed so an analytics hiccup never 5xxs the
webhook, exactly as the gateway's own event recording behaves.
"""

from __future__ import annotations

import datetime
import logging
import typing

import httpx
import jsonpointer
import pydantic
from imbi_common import clickhouse
from imbi_common.json_pointer import JsonPointer
from imbi_common.models import PullRequestRecord
from imbi_common.plugins.base import (
    ActionDescriptor,
    CredentialField,
    PluginContext,
    PluginManifest,
    WebhookActionPlugin,
)

from imbi_plugin_github._hosts import host_to_api_base
from imbi_plugin_github._repos import resolve_owner_repo
from imbi_plugin_github.commits import (
    _BACKFILL_MAX_WAIT_SECONDS,  # pyright: ignore[reportPrivateUsage]
    _client,  # pyright: ignore[reportPrivateUsage]
    _insert_best_effort,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
    _resolve,  # pyright: ignore[reportPrivateUsage]
    _resolve_bearer,  # pyright: ignore[reportPrivateUsage]
    _resolve_host_for_context,  # pyright: ignore[reportPrivateUsage]
)
from imbi_plugin_github.deployment import (
    _next_page_url,  # pyright: ignore[reportPrivateUsage]
    _parse_iso,  # pyright: ignore[reportPrivateUsage]
    _query_param,  # pyright: ignore[reportPrivateUsage]
)

LOGGER = logging.getLogger(__name__)

_SELF_SLUG = 'github-pr-sync'
# GitHub's pulls list is 100 per page; cap at 100 pages = 10k PRs so a
# very large repo can't pin a one-shot backfill indefinitely.
_MAX_HISTORY_PAGES = 100
# Webhook actions handle these PR lifecycle transitions; synchronize
# fires when new commits are pushed to the PR branch (title/state may
# also change).
_SYNC_ACTIONS = frozenset({'opened', 'closed', 'reopened', 'synchronize'})


def _parse_pr_datetime(value: object) -> datetime.datetime | None:
    """Parse a GitHub ISO timestamp or return ``None`` for null/missing."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return _parse_iso(value)
    except Exception:  # noqa: BLE001
        return None


def _pr_record(
    pr: dict[str, typing.Any],
    *,
    project_id: str,
) -> PullRequestRecord | None:
    """Map a GitHub PR object onto a :class:`PullRequestRecord`.

    Returns ``None`` if the PR object is missing required fields (id,
    number, created_at) so malformed payloads are silently skipped.
    """
    pr_id = pr.get('id')
    pr_number = pr.get('number')
    created_at_raw = pr.get('created_at')
    if not pr_id or not pr_number or not created_at_raw:
        return None
    created_at = _parse_pr_datetime(created_at_raw)
    if created_at is None:
        return None
    updated_at = _parse_pr_datetime(pr.get('updated_at')) or created_at
    user: dict[str, typing.Any] = pr.get('user') or {}
    return PullRequestRecord(
        project_id=project_id,
        pr_id=str(pr_id),
        pr_number=int(pr_number),
        title=str(pr.get('title') or ''),
        url=str(pr.get('html_url') or ''),
        state=str(pr.get('state') or 'open'),
        author=str(user.get('login') or ''),
        draft=bool(pr.get('draft', False)),
        merged=bool(pr.get('merged', False)),
        created_at=created_at,
        updated_at=updated_at,
        merged_at=_parse_pr_datetime(pr.get('merged_at')),
        additions=int(pr.get('additions') or 0),
        deletions=int(pr.get('deletions') or 0),
        changed_files=int(pr.get('changed_files') or 0),
    )


async def _fetch_all_prs(
    client: httpx.AsyncClient,
    *,
    max_wait: float,
) -> list[dict[str, typing.Any]]:
    """Walk ``GET /pulls?state=all`` and return every PR object.

    GitHub's list-PRs endpoint omits ``additions``, ``deletions``, and
    ``changed_files``; backfill rows store ``0`` for those fields.
    Caps at ``_MAX_HISTORY_PAGES`` pages (10k PRs) so a repo with a very
    large PR history can't pin the worker indefinitely.
    """
    out: list[dict[str, typing.Any]] = []
    params: dict[str, str] = {'state': 'all', 'per_page': '100'}
    for _ in range(_MAX_HISTORY_PAGES):
        resp = await _request(
            client, 'GET', '/pulls', params=params, max_wait=max_wait
        )
        resp.raise_for_status()
        page: list[dict[str, typing.Any]] = resp.json()
        if not page:
            break
        out.extend(page)
        next_url = _next_page_url(resp.headers.get('link'))
        if next_url is None:
            break
        next_page = _query_param(next_url, 'page')
        if next_page is None:
            break
        params['page'] = next_page
    else:
        LOGGER.warning(
            'github-pr-sync: reached %d-page cap fetching PRs; '
            'history may be truncated',
            _MAX_HISTORY_PAGES,
        )
    return out


class SyncPRsConfig(pydantic.BaseModel):
    """``WebhookRule.handler_config`` for ``sync_pull_requests``.

    Selectors resolve against the event context; the PR body lives
    under ``/payload`` (e.g. ``/payload/action``).
    """

    action_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer('/payload/action')
    )
    pr_selector: JsonPointer = pydantic.Field(
        default_factory=lambda: jsonpointer.JsonPointer(
            '/payload/pull_request'
        )
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


async def sync_pull_requests(
    *,
    ctx: PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: SyncPRsConfig,
    event: object,
) -> None:
    """Sync a pull_request event delivery into the ``pull_requests`` table.

    Handles ``opened``, ``closed``, ``reopened``, and ``synchronize``
    actions.  Other actions (e.g. ``labeled``, ``review_requested``) are
    silently ignored -- the rule's CEL filter can pre-screen them, but
    this action is defensive too.

    The full PR object is in the webhook payload so no extra GitHub API
    call is needed.
    """
    del external_identifier
    action = _resolve(action_config.action_selector, event)
    if not isinstance(action, str) or action not in _SYNC_ACTIONS:
        return
    pr_raw = _resolve(action_config.pr_selector, event)
    if not isinstance(pr_raw, dict):
        return
    pr_obj = typing.cast('dict[str, typing.Any]', pr_raw)
    record = _pr_record(pr_obj, project_id=ctx.project_id)
    if record is None:
        LOGGER.warning(
            'github-pr-sync: skipping malformed PR payload for project %s '
            '(action=%s, missing required fields)',
            ctx.project_id,
            action,
        )
        return
    try:
        await clickhouse.insert('pull_requests', [record])
    except Exception:
        LOGGER.exception(
            'github-pr-sync: failed to record PR #%d for project %s',
            record.pr_number,
            ctx.project_id,
        )


sync_pull_requests_descriptor = ActionDescriptor(
    name='sync_pull_requests',
    label='Sync Pull Request History',
    description=(
        'Record pull_request webhook events (opened, closed, reopened, '
        'synchronize) directly into the ClickHouse pull_requests table.'
    ),
    callable=typing.cast(
        'typing.Any',
        'imbi_plugin_github.pull_requests:sync_pull_requests',
    ),
    config_model=typing.cast(
        'typing.Any',
        'imbi_plugin_github.pull_requests:SyncPRsConfig',
    ),
)


class GitHubPRSyncPlugin(WebhookActionPlugin):
    """Webhook-action plugin syncing GitHub pull-request history.

    Carries its own service credential (PAT or GitHub App) -- it is not
    folded into the identity / deployment / lifecycle plugins, which run
    as the acting user.  Auth is resolved identically to
    :class:`~imbi_plugin_github.commits.GitHubCommitSyncPlugin`.
    """

    manifest = PluginManifest(
        slug='github-pr-sync',
        name='GitHub Pull Request History Sync',
        description=(
            'Syncs pull request history from GitHub webhooks into '
            'ClickHouse for analytics. Also supports on-demand backfill '
            'of the full PR history via sync_all_history.'
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
                    'from the repository.'
                ),
                required=False,
            ),
        ],
    )

    @classmethod
    def actions(cls) -> list[ActionDescriptor]:
        return [sync_pull_requests_descriptor]

    async def sync_all_history(
        self,
        *,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> int:
        """Record the project's full pull request history.

        Host-invoked (no webhook payload): the host instantiates the
        plugin, builds a :class:`PluginContext` carrying the project's
        links and the connected ``service_plugins``, resolves this
        plugin's service ``credentials``, and awaits this method.  The
        GitHub host/flavor is read from ``service_plugins``, the
        ``(owner, repo)`` from the project links, and the bearer token
        from the same PAT-or-App resolution the webhook actions use.

        Walks every PR in the repo (``state=all``, paginated) and upserts
        into the ClickHouse ``pull_requests`` table.
        ``ReplacingMergeTree`` dedupes against rows the webhook already
        recorded, so re-running is safe.

        ``additions``, ``deletions``, and ``changed_files`` are ``0`` for
        backfill rows (GitHub's list-PRs API omits them); they are
        accurate for any future webhook-driven rows.

        Returns the number of PRs recorded.  Raises :class:`ValueError`
        only when the host or repository can't be resolved; ClickHouse
        failures are swallowed (the count reflects what was written).
        Propagates :class:`PluginRateLimited` when a GitHub rate-limit
        reset is further out than ``_BACKFILL_MAX_WAIT_SECONDS`` so the
        host can pause the worker and keep the job queued until GitHub
        resumes rather than fail it.
        """
        host = _resolve_host_for_context(ctx)
        if host is None:
            raise ValueError(
                'github-pr-sync could not resolve a GitHub host for an '
                'on-demand sync: connect a GitHub plugin to the service'
            )
        base = host_to_api_base(host)
        owner, repo = resolve_owner_repo(ctx, host, _SELF_SLUG)
        token = await _resolve_bearer(credentials, base, owner, repo)
        async with _client(base, owner, repo, token) as client:
            raw_prs = await _fetch_all_prs(
                client, max_wait=_BACKFILL_MAX_WAIT_SECONDS
            )
        records: list[pydantic.BaseModel] = []
        for pr in raw_prs:
            record = _pr_record(pr, project_id=ctx.project_id)
            if record is not None:
                records.append(record)
        return await _insert_best_effort(
            'pull_requests', records, ctx.project_id
        )
