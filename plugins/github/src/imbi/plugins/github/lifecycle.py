"""GitHub lifecycle capability handler.

:class:`GitHubLifecycle` resolves its GitHub host from the Integration's
``flavor`` + ``host`` options on ``ctx.integration_options``, so one
handler serves github.com, a GHEC tenant, or a GHES appliance
interchangeably.

On project archive the handler:

1. Looks up the repo's current state.  If it's already archived (and
   already at the configured target org, when one is set) the call is
   a no-op (``status='skipped'``).
2. When ``archive_target_org`` is set and the repo is not at that
   owner, transfers the repo via ``POST /repos/{owner}/{repo}/transfer``.
   GitHub refuses to transfer an already-archived repo, so an
   already-archived source is briefly unarchived first, transferred,
   then re-archived.
3. Archives the repo via ``PATCH /repos/{owner}/{repo}`` with
   ``{"archived": true}``.

GitHub's repo transfer is asynchronous: ``POST .../transfer`` returns
``202 Accepted`` and the repo is briefly unreachable at the
destination owner.  A PATCH fired immediately after the transfer
therefore 404s, leaving the repo transferred-but-not-archived (see
the ``archives`` org incidents on the GHEC tenant).  The post-transfer
archive is retried on 404 with a bounded backoff so the common case
(transfer settles within a few seconds) succeeds, while a genuinely
stuck transfer still fails fast enough to stay inside the dispatcher's
per-plugin timeout and surface to the operator.

On unarchive the plugin only flips ``archived`` back to ``false`` at
the repo's current location — it does **not** attempt to transfer
the repo back to its original org because the original owner is not
tracked anywhere.

The handler acts as the user: callers pass the access token through the
Integration credential blob's ``credentials['access_token']``.
Archiving and transferring both require repo admin scope on the
source, and transfer additionally requires admin permission on the
target organization.
"""

from __future__ import annotations

import asyncio
import logging
import typing

import httpx

from imbi.common.plugins.base import (
    LifecycleCapability,
    LifecycleResult,
    LinkWriteback,
    PluginContext,
    RelocationTarget,
    ServiceWriteback,
)
from imbi.common.plugins.errors import PluginAuthenticationFailed
from imbi.common.plugins.templates import expand_template
from imbi.plugins.github._hosts import flavor_host, host_to_api_base
from imbi.plugins.github._repos import (
    derive_owner_repo_from_links,
    resolve_owner_repo,
)

LOGGER = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 10.0

# Backoffs (seconds) between attempts to archive a freshly-transferred
# repo while GitHub's async transfer settles.  len + 1 == total
# attempts; the sum is kept well under the dispatcher's per-plugin
# timeout (default 10s) so a stuck transfer fails fast rather than
# hanging the operator's archive request.
_TRANSFER_ARCHIVE_BACKOFFS: tuple[float, ...] = (0.5, 1.0, 2.0)

# Visibilities accepted by the ``create_visibility`` option.  ``internal``
# is only meaningful on a GHEC tenant or GHES appliance.
_VISIBILITIES = frozenset({'private', 'internal', 'public'})

# GitHub's cap on a repo description.  Imbi's own project description
# field has no limit, and GitHub rejects the *whole* request when the
# value is longer -- so an over-long description cost the repo entirely
# until this was clamped (issue #254).
_MAX_DESCRIPTION_CHARS = 350
_DESCRIPTION_ELLIPSIS = '\u2026'


def _normalize_description(value: str | None) -> str | None:
    """Clamp a project description to GitHub's repo-description limit.

    Truncates on a word boundary where one exists in the last word of
    the budget, and marks the cut with an ellipsis.  Losing the tail is
    acceptable because the full text stays in Imbi and the repo's
    ``homepage`` links back to it; losing the repo is not.

    ``None`` passes through unchanged so the caller can still tell
    "unknown" from "empty" -- see :meth:`_patch_repo_attrs`.
    """
    if value is None or len(value) <= _MAX_DESCRIPTION_CHARS:
        return value
    budget = _MAX_DESCRIPTION_CHARS - len(_DESCRIPTION_ELLIPSIS)
    candidate = value[:budget]
    head, separator, _ = candidate.rpartition(' ')
    if separator and head.strip():
        candidate = head
    return candidate.rstrip() + _DESCRIPTION_ELLIPSIS


def _error_detail(response: httpx.Response) -> str:
    """Flatten a GitHub error body into one operator-facing string.

    Keeps the top-level ``message`` and each entry of the ``errors``
    array (``field: message``) so a validation failure names the field
    that GitHub rejected.
    """
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return f'HTTP {response.status_code}: {response.text[:200]}'
    payload = typing.cast(dict[str, object], body)
    parts = [str(payload.get('message') or f'HTTP {response.status_code}')]
    errors = payload.get('errors')
    if isinstance(errors, list):
        for item in typing.cast(list[object], errors):
            if not isinstance(item, dict):
                continue
            entry = typing.cast(dict[str, object], item)
            text = entry.get('message') or entry.get('code')
            if not text:
                continue
            field = entry.get('field')
            parts.append(f'{field}: {text}' if field else str(text))
    return ' - '.join(parts)


async def _raise_on_401(response: httpx.Response) -> None:
    """Convert a 401 from GitHub into :class:`PluginAuthenticationFailed`.

    Mirrors the deployment plugin's hook so the host's retry layer
    can refresh the actor's identity once before failing the
    user-visible request.
    """
    if response.status_code != 401:
        return
    await response.aread()
    raise PluginAuthenticationFailed(
        f'GitHub 401 from {response.request.url}: {response.text}'
    )


def _auth_headers(token: str) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
    }


class GitHubLifecycle(LifecycleCapability):
    """React to the project lifecycle on the configured GitHub host.

    The host is resolved from the Integration's ``flavor`` + ``host``
    options.  Instances are single-shot per request.
    """

    def _resolve_host(self, ctx: PluginContext) -> str:
        return flavor_host(ctx.integration_options, 'github lifecycle')

    def _api_base(self, ctx: PluginContext) -> str:
        return host_to_api_base(self._resolve_host(ctx))

    @staticmethod
    def _token(credentials: dict[str, str]) -> str:
        token = credentials.get('access_token') or credentials.get('token')
        if not token:
            raise ValueError(
                'GitHub lifecycle plugin requires an OAuth access token; '
                'expected ``credentials["access_token"]``'
            )
        return token

    def _client(
        self, ctx: PluginContext, credentials: dict[str, str]
    ) -> httpx.AsyncClient:
        # follow_redirects so a repo renamed outside Imbi (GitHub answers
        # the stale ``/repos/{owner}/{repo}`` path with a 301 to the by-id
        # form) is followed instead of crashing in ``raise_for_status``.
        # The canonical owner/repo are then adopted from the repo payload;
        # see ``on_project_archived``.
        return httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT_SECONDS,
            headers=_auth_headers(self._token(credentials)),
            base_url=self._api_base(ctx),
            follow_redirects=True,
            event_hooks={'response': [_raise_on_401]},
        )

    @staticmethod
    def _target_org(options: dict[str, typing.Any]) -> str | None:
        raw = options.get('archive_target_org')
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return None

    @staticmethod
    def _default_visibility(ctx: PluginContext) -> str:
        """Pick the create visibility when the option is unset.

        The right default differs per host, so it can't be a manifest
        constant: enterprise hosts (a GHEC tenant or a GHES appliance)
        get ``internal`` -- readable across the enterprise, and the only
        useful non-public choice on orgs that forbid public repos --
        while github.com has no ``internal`` visibility at all and gets
        ``public``.  Never *silently* narrower than that on enterprise
        and never wider on github.com; operators who want something
        else set ``create_visibility`` explicitly.
        """
        flavor = str(ctx.integration_options.get('flavor') or '').strip()
        return 'public' if flavor == 'github' else 'internal'

    def _resolve_visibility(self, ctx: PluginContext) -> str:
        """Resolve the visibility new repos are created with.

        An explicit ``create_visibility`` option wins; anything unset or
        unrecognized falls back to the host-appropriate default rather
        than inheriting GitHub's create API default of *public*, which
        an enterprise org that forbids public repos rejects with a 422.
        """
        raw = ctx.capability_options.get('create_visibility')
        if isinstance(raw, str) and raw.strip().lower() in _VISIBILITIES:
            return raw.strip().lower()
        return self._default_visibility(ctx)

    @staticmethod
    def _resolve_create_org(ctx: PluginContext) -> str | None:
        """Resolve the GitHub org for create / relocate from plugin options.

        Checks ``org_mapping`` (project-type-slug → org) first so per-type
        overrides win, then falls back to the ``create_org`` template.
        Returns ``None`` when neither is configured so the caller can
        emit a clean ``status='skipped'``.
        """
        options = ctx.capability_options
        mapping_raw = options.get('org_mapping')
        if isinstance(mapping_raw, dict):
            mapping = typing.cast(dict[str, typing.Any], mapping_raw)
            for pt_slug in ctx.project_type_slugs:
                if pt_slug in mapping:
                    value = mapping[pt_slug]
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        template = options.get('create_org')
        if isinstance(template, str) and template.strip():
            first_type_slug = (
                ctx.project_type_slugs[0] if ctx.project_type_slugs else None
            )
            expanded = expand_template(
                template,
                {
                    'project_slug': ctx.project_slug,
                    'org_slug': ctx.org_slug,
                    'team_slug': ctx.team_slug,
                    'project_type_slug': first_type_slug,
                    'project_id': ctx.project_id,
                },
            ).strip()
            return expanded or None
        return None

    async def on_project_created(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        target_org = self._resolve_create_org(ctx)
        if not target_org:
            return LifecycleResult(
                status='skipped',
                message=(
                    'No target org configured for project creation; set '
                    "the plugin's ``create_org`` or ``org_mapping`` option"
                ),
            )
        host = self._resolve_host(ctx)
        async with self._client(ctx, credentials) as client:
            existing = await self._get_repo_or_none(
                client, target_org, ctx.project_slug
            )
            if existing is not None:
                # Already provisioned (e.g. retry after a partial failure):
                # adopt the existing repo's URL/edge so the operator can
                # wire it up without a second attempt.
                html_url = self._record_repo(
                    ctx, host, target_org, ctx.project_slug, existing
                )
                return LifecycleResult(
                    status='skipped',
                    message=(
                        f'Repository {target_org}/{ctx.project_slug} '
                        'already exists'
                    ),
                    artifacts={'repo_url': html_url},
                )
            created = await self._create_repo(client, target_org, ctx)
            html_url = self._record_repo(
                ctx, host, target_org, ctx.project_slug, created
            )
        return LifecycleResult(
            status='ok',
            message=f'Created {target_org}/{ctx.project_slug}',
            artifacts={'repo_url': html_url},
        )

    async def on_project_updated(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        host = self._resolve_host(ctx)
        # ``prefer_previous_slug`` so a slug rename still locates the
        # pre-rename repo on GitHub when the project has no stored link.
        owner, repo = resolve_owner_repo(
            ctx,
            host,
            'GitHub lifecycle plugin',
            prefer_previous_slug=True,
        )
        async with self._client(ctx, credentials) as client:
            current = await self._get_repo(client, owner, repo)
            current_owner = self._current_owner(current, owner)
            current_repo = self._current_repo(current, repo)
            # Surface an external rename even when there's nothing else
            # to do, so the host can self-heal the link.
            self._maybe_report_relocation(
                ctx, host, current, owner, repo, current_owner, current_repo
            )
            patched = await self._patch_repo_attrs(
                client,
                current_owner,
                current_repo,
                name=ctx.project_slug,
                description=ctx.project_description,
                homepage=ctx.project_ui_url,
            )
            new_repo = str(patched.get('name') or current_repo)
            # If the patch itself renamed the repo (we asked GitHub to
            # set ``name`` to a new slug), record the writeback even when
            # the external-rename check above didn't.
            if new_repo != current_repo:
                new_url = self._record_repo(
                    ctx,
                    host,
                    current_owner,
                    new_repo,
                    patched,
                    old_owner_repo=f'{current_owner}/{current_repo}',
                    new_owner_repo=f'{current_owner}/{new_repo}',
                )
            else:
                new_url = str(
                    patched.get('html_url')
                    or self._repo_html_url(host, current_owner, new_repo)
                )
        return LifecycleResult(
            status='ok',
            message=f'Updated {current_owner}/{new_repo}',
            artifacts={'repo_url': new_url},
        )

    async def on_project_deleted(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        host = self._resolve_host(ctx)
        try:
            owner, repo = resolve_owner_repo(
                ctx, host, 'GitHub lifecycle plugin'
            )
        except ValueError as exc:
            return LifecycleResult(status='skipped', message=str(exc))
        async with self._client(ctx, credentials) as client:
            resp = await client.delete(f'/repos/{owner}/{repo}')
            if resp.status_code == 404:
                return LifecycleResult(
                    status='skipped',
                    message=f'Repository {owner}/{repo} already gone',
                )
            resp.raise_for_status()
        return LifecycleResult(
            status='ok',
            message=f'Deleted {owner}/{repo}',
        )

    async def on_project_relocated(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        host = self._resolve_host(ctx)
        target = await self.resolve_relocation_target(ctx, credentials)
        if target is None:
            return LifecycleResult(
                status='skipped',
                message='No relocation target resolved',
            )
        try:
            new_owner, _new_repo_hint = target.identifier.split('/', 1)
        except ValueError:
            return LifecycleResult(
                status='failed',
                message=(
                    f'Malformed relocation identifier {target.identifier!r};'
                    ' expected ``<owner>/<repo>``'
                ),
            )
        try:
            owner, repo = resolve_owner_repo(
                ctx, host, 'GitHub lifecycle plugin'
            )
        except ValueError as exc:
            return LifecycleResult(status='skipped', message=str(exc))
        if owner.lower() == new_owner.lower():
            return LifecycleResult(
                status='skipped',
                message=(
                    f'Repository {owner}/{repo} is already at the '
                    f'target org {new_owner}'
                ),
            )
        async with self._client(ctx, credentials) as client:
            transferred = await self._transfer(client, owner, repo, new_owner)
            final_repo = str(transferred.get('name') or repo)
            html_url = self._record_repo(
                ctx,
                host,
                new_owner,
                final_repo,
                transferred,
                old_owner_repo=f'{owner}/{repo}',
                new_owner_repo=f'{new_owner}/{final_repo}',
            )
        return LifecycleResult(
            status='ok',
            message=f'Transferred to {new_owner}/{final_repo}',
            artifacts={'repo_url': html_url},
        )

    async def resolve_relocation_target(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> RelocationTarget | None:
        del credentials  # resolution is local; never hits the remote.
        target_org = self._resolve_create_org(ctx)
        if not target_org:
            return None
        host = self._resolve_host(ctx)
        # Prefer the canonical repo name from a stored link; fall back to
        # project_slug so a preview before any link exists still resolves.
        derived = derive_owner_repo_from_links(ctx.project_links, host)
        repo_name = derived[1] if derived is not None else ctx.project_slug
        identifier = f'{target_org}/{repo_name}'
        return RelocationTarget(
            link_key='github-repository',
            identifier=identifier,
            display=identifier,
        )

    async def on_project_archived(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        host = self._resolve_host(ctx)
        owner, repo = resolve_owner_repo(ctx, host, 'GitHub lifecycle plugin')
        target_org = self._target_org(ctx.capability_options)

        async with self._client(ctx, credentials) as client:
            current = await self._get_repo(client, owner, repo)
            current_owner = self._current_owner(current, owner)
            current_repo = self._current_repo(current, repo)
            # If the repo moved out from under the stored link *before*
            # we touched it (an external rename), report it so the host
            # self-heals the link.  This is computed before any transfer
            # we initiate below, so an intentional archive-org transfer
            # is never mistaken for an external relocation.
            self._maybe_report_relocation(
                ctx, host, current, owner, repo, current_owner, current_repo
            )
            repo = current_repo
            already_archived = bool(current.get('archived'))

            needs_transfer = bool(
                target_org and current_owner.lower() != target_org.lower()
            )

            if not needs_transfer and already_archived:
                return LifecycleResult(
                    status='skipped',
                    message=(
                        f'Repository {current_owner}/{repo} is already '
                        'archived'
                    ),
                    artifacts={
                        'repo_url': self._repo_html_url(
                            host, current_owner, repo
                        ),
                    },
                )

            if needs_transfer:
                # GitHub refuses to transfer archived repos.  Briefly
                # flip ``archived`` off so the transfer goes through;
                # the final PATCH below re-archives at the destination.
                if already_archived:
                    await self._set_archived(
                        client, current_owner, repo, False
                    )
                transferred = await self._transfer(
                    client, current_owner, repo, target_org or ''
                )
                # GitHub may rename the repo as part of a transfer if
                # the destination org already has a repo by that name;
                # honour the response value.
                repo = str(transferred.get('name') or repo)
                owner = target_org or current_owner
                current_owner = owner
                # The repo may not be reachable at the destination
                # owner yet; tolerate the transfer-settle 404 window.
                await self._archive_after_transfer(client, current_owner, repo)
            else:
                await self._set_archived(client, current_owner, repo, True)

        return LifecycleResult(
            status='ok',
            message=f'Archived {current_owner}/{repo}',
            artifacts={
                'repo_url': self._repo_html_url(host, current_owner, repo),
            },
        )

    async def on_project_unarchived(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> LifecycleResult:
        host = self._resolve_host(ctx)
        owner, repo = resolve_owner_repo(ctx, host, 'GitHub lifecycle plugin')
        async with self._client(ctx, credentials) as client:
            current = await self._get_repo(client, owner, repo)
            current_owner = self._current_owner(current, owner)
            current_repo = self._current_repo(current, repo)
            self._maybe_report_relocation(
                ctx, host, current, owner, repo, current_owner, current_repo
            )
            repo = current_repo
            if not current.get('archived'):
                return LifecycleResult(
                    status='skipped',
                    message=(
                        f'Repository {current_owner}/{repo} is not archived'
                    ),
                    artifacts={
                        'repo_url': self._repo_html_url(
                            host, current_owner, repo
                        ),
                    },
                )
            await self._set_archived(client, current_owner, repo, False)
        return LifecycleResult(
            status='ok',
            message=f'Unarchived {current_owner}/{repo}',
            artifacts={
                'repo_url': self._repo_html_url(host, current_owner, repo),
            },
        )

    @staticmethod
    def _current_owner(payload: dict[str, typing.Any], fallback: str) -> str:
        """Return the owner login from a repo payload, fallback when absent."""
        owner_obj = payload.get('owner')
        if isinstance(owner_obj, dict):
            owner_dict = typing.cast(dict[str, typing.Any], owner_obj)
            login = owner_dict.get('login')
            if isinstance(login, str) and login:
                return login
        return fallback

    @staticmethod
    def _current_repo(payload: dict[str, typing.Any], fallback: str) -> str:
        """Return the repo name from a repo payload, fallback when absent."""
        name = payload.get('name')
        if isinstance(name, str) and name:
            return name
        return fallback

    def _maybe_report_relocation(
        self,
        ctx: PluginContext,
        host: str,
        payload: dict[str, typing.Any],
        link_owner: str,
        link_repo: str,
        current_owner: str,
        current_repo: str,
    ) -> None:
        """Record a link writeback when the repo moved out from under the link.

        Compares the link-derived ``<owner>/<repo>`` against the repo's
        canonical name from ``payload``.  When they differ the repo was
        renamed (or its owner renamed) outside Imbi, so record the repo
        on ``ctx`` (via :meth:`_record_repo`) for the host to persist the
        refreshed dashboard link / ``EXISTS_IN`` edge.  No-op when they
        match.
        """
        old_owner_repo = f'{link_owner}/{link_repo}'
        new_owner_repo = f'{current_owner}/{current_repo}'
        if new_owner_repo.lower() == old_owner_repo.lower():
            return
        self._record_repo(
            ctx,
            host,
            current_owner,
            current_repo,
            payload,
            old_owner_repo=old_owner_repo,
            new_owner_repo=new_owner_repo,
        )

    @staticmethod
    def _repo_html_url(host: str, owner: str, repo: str) -> str:
        return f'https://{host}/{owner}/{repo}'

    def _record_repo(
        self,
        ctx: PluginContext,
        host: str,
        owner: str,
        repo: str,
        payload: dict[str, typing.Any] | None = None,
        *,
        old_owner_repo: str | None = None,
        new_owner_repo: str | None = None,
    ) -> str:
        """Record the repo on ``ctx`` for the host to persist.

        Returns the dashboard (human) URL.  When the handler is bound to
        an Integration and the GitHub payload carries the numeric
        repo id, emit a :class:`ServiceWriteback` that maintains the
        ``EXISTS_IN`` edge -- the id plus the rename-stable
        ``/repositories/{id}`` API URL -- and a dashboard link keyed by
        the Integration slug.  Otherwise fall back to the legacy
        ``github-repository`` :class:`LinkWriteback` so a project not
        wired to an Integration still gets its stored link.
        """
        data = payload or {}
        html_url = str(
            data.get('html_url') or self._repo_html_url(host, owner, repo)
        )
        slug = ctx.integration_slug
        repo_id = data.get('id')
        if slug and isinstance(repo_id, int):
            api_base = self._api_base(ctx)
            ctx.service_writeback = ServiceWriteback(
                identifier=str(repo_id),
                canonical_url=f'{api_base}/repositories/{repo_id}',
                dashboard_links={slug: html_url},
            )
        else:
            ctx.link_writeback = LinkWriteback(
                link_key='github-repository',
                new_url=html_url,
                old_owner_repo=old_owner_repo,
                new_owner_repo=new_owner_repo,
            )
        return html_url

    async def _get_repo(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> dict[str, typing.Any]:
        resp = await client.get(f'/repos/{owner}/{repo}')
        resp.raise_for_status()
        return typing.cast(dict[str, typing.Any], resp.json())

    async def _get_repo_or_none(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> dict[str, typing.Any] | None:
        """Read a repo, returning ``None`` on 404 instead of raising.

        Used by :meth:`on_project_created` for the idempotency check —
        any other status is treated as a real failure and re-raised.
        """
        resp = await client.get(f'/repos/{owner}/{repo}')
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return typing.cast(dict[str, typing.Any], resp.json())

    async def _create_repo(
        self,
        client: httpx.AsyncClient,
        org: str,
        ctx: PluginContext,
    ) -> dict[str, typing.Any]:
        visibility = self._resolve_visibility(ctx)
        resp = await client.post(
            f'/orgs/{org}/repos',
            json={
                'name': ctx.project_slug,
                'description': _normalize_description(ctx.project_description)
                or '',
                'homepage': ctx.project_ui_url or '',
                # ``visibility`` is authoritative where it's supported;
                # ``private`` rides along so a host that only honors the
                # older field degrades to private instead of silently
                # creating a public repo.
                'visibility': visibility,
                'private': visibility != 'public',
            },
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # ``raise_for_status`` reports only the status line, hiding
            # the ``message``/``errors`` body that says *why* -- e.g. an
            # org whose policy forbids the requested visibility.
            raise RuntimeError(
                f'GitHub refused to create {org}/{ctx.project_slug} with '
                f'visibility={visibility}: {_error_detail(exc.response)}'
            ) from exc
        return typing.cast(dict[str, typing.Any], resp.json())

    async def _patch_repo_attrs(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        *,
        name: str,
        description: str | None,
        homepage: str | None,
    ) -> dict[str, typing.Any]:
        """Sync name / description / homepage via a single PATCH.

        One call covers all three sync fields so an update that touches
        several is still a single GitHub round trip.  ``raise_for_status``
        on any non-2xx so the dispatcher captures the failure.

        ``None`` means "the caller doesn't know this value" and omits the
        key, so a dispatch path that never populated
        ``ctx.project_description`` leaves the repo's own description
        alone instead of clearing it.  An empty string still rides
        along, because that is a deliberate clear.  The description is
        clamped here rather than at the call site so create and update
        cannot disagree about the limit.
        """
        payload: dict[str, typing.Any] = {'name': name}
        if description is not None:
            payload['description'] = _normalize_description(description)
        if homepage is not None:
            payload['homepage'] = homepage
        resp = await client.patch(f'/repos/{owner}/{repo}', json=payload)
        resp.raise_for_status()
        return typing.cast(dict[str, typing.Any], resp.json())

    async def _set_archived(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        archived: bool,
    ) -> None:
        resp = await client.patch(
            f'/repos/{owner}/{repo}',
            json={'archived': archived},
        )
        resp.raise_for_status()

    async def _archive_after_transfer(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
    ) -> None:
        """Archive a freshly-transferred repo, retrying the 404 window.

        GitHub's transfer is async: the repo is briefly unreachable at
        the destination owner, so the archive PATCH 404s until the
        transfer settles.  Retry only on 404 — any other status (auth,
        permissions, validation) is a real failure and re-raises
        immediately.
        """
        for backoff in (*_TRANSFER_ARCHIVE_BACKOFFS, None):
            try:
                await self._set_archived(client, owner, repo, True)
                return
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404 or backoff is None:
                    raise
                LOGGER.info(
                    'Repo %s/%s not yet reachable after transfer; '
                    'retrying archive in %ss',
                    owner,
                    repo,
                    backoff,
                )
                await asyncio.sleep(backoff)

    async def _transfer(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        new_owner: str,
    ) -> dict[str, typing.Any]:
        resp = await client.post(
            f'/repos/{owner}/{repo}/transfer',
            json={'new_owner': new_owner},
        )
        resp.raise_for_status()
        return typing.cast(dict[str, typing.Any], resp.json())
