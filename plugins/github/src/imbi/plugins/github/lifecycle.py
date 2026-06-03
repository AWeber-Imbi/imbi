"""GitHub lifecycle plugins.

Three concrete subclasses share a common base and differ only by host:

* :class:`GitHubLifecyclePlugin` — github.com.
* :class:`GitHubEnterpriseCloudLifecyclePlugin` — GHEC tenant on
  ``*.ghe.com``.
* :class:`GitHubEnterpriseServerLifecyclePlugin` — operator-managed GHES.

On project archive the plugin:

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

The plugin acts as the user via the paired :class:`IdentityPlugin`:
callers materialise an :class:`~imbi_common.plugins.base.IdentityCredentials`
and pass the access token through ``credentials['access_token']``.
Archiving and transferring both require repo admin scope on the
source, and transfer additionally requires admin permission on the
target organization.
"""

from __future__ import annotations

import asyncio
import logging
import typing

import httpx
from imbi_common.plugins.base import (
    CredentialField,
    LifecyclePlugin,
    LifecycleResult,
    LinkWriteback,
    PluginContext,
    PluginManifest,
    PluginOption,
    RelocationTarget,
    ServiceWriteback,
)
from imbi_common.plugins.errors import PluginAuthenticationFailed
from imbi_common.plugins.templates import expand_template

from imbi_plugin_github._hosts import normalize_host, require_ghec_tenant_host
from imbi_plugin_github._repos import (
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


class _LifecycleBase(LifecyclePlugin):
    """Shared base for GitHub lifecycle plugins.

    Subclasses set :attr:`manifest` and override :meth:`_resolve_host`.
    Plugin instances are single-shot per request.
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
            base_url=self._api_base(ctx.assignment_options),
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
    def _resolve_create_org(ctx: PluginContext) -> str | None:
        """Resolve the GitHub org for create / relocate from plugin options.

        Checks ``org_mapping`` (project-type-slug → org) first so per-type
        overrides win, then falls back to the ``create_org`` template.
        Returns ``None`` when neither is configured so the caller can
        emit a clean ``status='skipped'``.
        """
        options = ctx.assignment_options
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
        host = self._resolve_host(ctx.assignment_options)
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
        host = self._resolve_host(ctx.assignment_options)
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
                description=ctx.project_description or '',
                homepage=ctx.project_ui_url or '',
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
        host = self._resolve_host(ctx.assignment_options)
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
        host = self._resolve_host(ctx.assignment_options)
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
        host = self._resolve_host(ctx.assignment_options)
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
        host = self._resolve_host(ctx.assignment_options)
        owner, repo = resolve_owner_repo(ctx, host, 'GitHub lifecycle plugin')
        target_org = self._target_org(ctx.assignment_options)

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
        host = self._resolve_host(ctx.assignment_options)
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

        Returns the dashboard (human) URL.  When the plugin is bound to a
        third-party service and the GitHub payload carries the numeric
        repo id, emit a :class:`ServiceWriteback` that maintains the
        ``EXISTS_IN`` edge -- the id plus the rename-stable
        ``/repositories/{id}`` API URL -- and a dashboard link keyed by
        the service slug.  Otherwise fall back to the legacy
        ``github-repository`` :class:`LinkWriteback` so a project not
        wired to a service still gets its stored link.
        """
        data = payload or {}
        html_url = str(
            data.get('html_url') or self._repo_html_url(host, owner, repo)
        )
        slug = ctx.third_party_service_slug
        repo_id = data.get('id')
        if slug and isinstance(repo_id, int):
            api_base = self._api_base(ctx.assignment_options)
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
        resp = await client.post(
            f'/orgs/{org}/repos',
            json={
                'name': ctx.project_slug,
                'description': ctx.project_description or '',
                'homepage': ctx.project_ui_url or '',
            },
        )
        resp.raise_for_status()
        return typing.cast(dict[str, typing.Any], resp.json())

    async def _patch_repo_attrs(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        *,
        name: str,
        description: str,
        homepage: str,
    ) -> dict[str, typing.Any]:
        """Sync name / description / homepage via a single PATCH.

        One call covers all three sync fields so an update that touches
        several is still a single GitHub round trip.  ``raise_for_status``
        on any non-2xx so the dispatcher captures the failure.
        """
        resp = await client.patch(
            f'/repos/{owner}/{repo}',
            json={
                'name': name,
                'description': description,
                'homepage': homepage,
            },
        )
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


_COMMON_OPTIONS: list[PluginOption] = [
    PluginOption(
        name='archive_target_org',
        label='Transfer to org on archive',
        description=(
            'When set, repos are transferred to this organization before '
            'being archived.  Useful for moving sunset projects into a '
            'dedicated "archive" org so they no longer count against your '
            "primary org's repo quota or surface in default searches.  "
            'Leave blank to archive in place.  Requires admin permission '
            'on both the source repo and the destination organization.'
        ),
        type='string',
        required=False,
    ),
    PluginOption(
        name='create_org',
        label='Default org for repo creation',
        description=(
            'Org used by ``on_project_created`` (and the relocate-target '
            'preview) when no per-project-type override matches in '
            '``org_mapping``.  Supports the template variables '
            '``${project_slug}``, ``${org_slug}``, ``${team_slug}``, '
            '``${project_type_slug}``, ``${project_id}``.  Leave blank '
            'to skip create / relocate when no mapping matches.'
        ),
        type='string',
        required=False,
    ),
    PluginOption(
        name='org_mapping',
        label='Project-type to org overrides',
        description=(
            'Per-project-type-slug overrides for the target GitHub org.  '
            'The first ``project_type_slug`` that has a mapping wins '
            'over ``create_org``.  Use this when different project types '
            'live in different orgs (e.g. ``api`` → ``aweber-services``, '
            '``library`` → ``aweber-libs``).'
        ),
        type='mapping',
        required=False,
    ),
]

# Lifecycle events every GitHub lifecycle variant supports.  Shared
# across the three host flavors -- they inherit the same ``_LifecycleBase``
# implementation, so their capability lists are identical.
_COMMON_LIFECYCLE_EVENTS: list[
    typing.Literal[
        'created',
        'updated',
        'archived',
        'unarchived',
        'deleted',
        'relocated',
    ]
] = ['created', 'updated', 'archived', 'unarchived', 'deleted', 'relocated']

_COMMON_CREDENTIALS: list[CredentialField] = [
    CredentialField(
        name='access_token',
        label='Service-account PAT (optional fallback)',
        description=(
            'Personal access token used when no per-user identity is '
            'bound.  Requires repo admin scope; transfers additionally '
            'require admin permission on the target organization.'
        ),
        required=False,
    ),
]


class GitHubLifecyclePlugin(_LifecycleBase):
    manifest = PluginManifest(
        slug='github-lifecycle',
        name='GitHub Lifecycle',
        description=(
            'React to the project lifecycle on github.com by creating, '
            'renaming, archiving, transferring, or deleting the matching '
            'repository.  Org selection on create / relocate is driven '
            'by per-project-type overrides plus a template fallback.'
        ),
        plugin_type='lifecycle',
        options=_COMMON_OPTIONS,
        credentials=_COMMON_CREDENTIALS,
        lifecycle_events=_COMMON_LIFECYCLE_EVENTS,
    )

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        del options
        return 'github.com'


class GitHubEnterpriseCloudLifecyclePlugin(_LifecycleBase):
    manifest = PluginManifest(
        slug='github-lifecycle-ec',
        name='GitHub Enterprise Cloud Lifecycle',
        description=(
            'React to the project lifecycle on a GHEC tenant '
            '(``*.ghe.com``) by creating, renaming, archiving, '
            'transferring, or deleting the matching repository.'
        ),
        plugin_type='lifecycle',
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
        lifecycle_events=_COMMON_LIFECYCLE_EVENTS,
    )

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        return require_ghec_tenant_host(
            normalize_host(options.get('host'), 'GHEC lifecycle plugin'),
            'GHEC lifecycle plugin',
        )


class GitHubEnterpriseServerLifecyclePlugin(_LifecycleBase):
    manifest = PluginManifest(
        slug='github-lifecycle-es',
        name='GitHub Enterprise Server Lifecycle',
        description=(
            'React to the project lifecycle on a GHES install by '
            'creating, renaming, archiving, transferring, or deleting '
            'the matching repository.'
        ),
        plugin_type='lifecycle',
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
        lifecycle_events=_COMMON_LIFECYCLE_EVENTS,
    )

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        return normalize_host(options.get('host'), 'GHES lifecycle plugin')
