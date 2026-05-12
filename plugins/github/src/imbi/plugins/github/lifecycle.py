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

import logging
import typing

import httpx
from imbi_common.plugins.base import (
    CredentialField,
    LifecyclePlugin,
    LifecycleResult,
    PluginContext,
    PluginManifest,
    PluginOption,
)
from imbi_common.plugins.errors import PluginAuthenticationFailed

from imbi_plugin_github._hosts import normalize_host, require_ghec_tenant_host
from imbi_plugin_github._repos import resolve_owner_repo

LOGGER = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 10.0


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
        return httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT_SECONDS,
            headers=_auth_headers(self._token(credentials)),
            base_url=self._api_base(ctx.assignment_options),
            event_hooks={'response': [_raise_on_401]},
        )

    @staticmethod
    def _target_org(options: dict[str, typing.Any]) -> str | None:
        raw = options.get('archive_target_org')
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return None

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
            already_archived = bool(current.get('archived'))
            current_owner = self._current_owner(current, owner)

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
                        'repo_url': self._repo_html_url(host, owner, repo),
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
    def _repo_html_url(host: str, owner: str, repo: str) -> str:
        return f'https://{host}/{owner}/{repo}'

    async def _get_repo(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> dict[str, typing.Any]:
        resp = await client.get(f'/repos/{owner}/{repo}')
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
]

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
            'React to project archive / unarchive on github.com by '
            'archiving (or unarchiving) the matching repository.  '
            'Optionally transfers the repo to a sunset organization '
            'before archiving so retired projects do not crowd primary '
            'org searches.'
        ),
        plugin_type='lifecycle',
        options=_COMMON_OPTIONS,
        credentials=_COMMON_CREDENTIALS,
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
            'React to project archive / unarchive on a GHEC tenant '
            '(``*.ghe.com``) by archiving (or unarchiving) the matching '
            'repository; optional transfer to a sunset org first.'
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
            'React to project archive / unarchive on a GHES install by '
            'archiving (or unarchiving) the matching repository; '
            'optional transfer to a sunset org first.'
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
    )

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        return normalize_host(options.get('host'), 'GHES lifecycle plugin')
