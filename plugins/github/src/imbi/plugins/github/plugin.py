"""GitHub identity plugins.

Three concrete subclasses share one base and differ only by host:

* :class:`GitHubPlugin` — github.com.
* :class:`GitHubEnterpriseCloudPlugin` — GHEC tenant on ``*.ghe.com``.
* :class:`GitHubEnterpriseServerPlugin` — operator-managed GHES; the
  hostname comes from a manifest option.

Phase 1 implements the OAuth App flow only.  GitHub App installation
tokens (org-scoped automation) are deferred — service principals
continue to use the legacy ``ServiceApplication`` model.
"""

from __future__ import annotations

import datetime
import logging
import secrets
import typing
import urllib.parse

import httpx
from imbi_common.plugins.base import (
    AuthorizationRequest,
    CredentialField,
    IdentityCredentials,
    IdentityPlugin,
    IdentityProfile,
    PluginContext,
    PluginManifest,
    PluginOption,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_SCOPES = ['read:user', 'user:email']


def _build_userinfo(claims: dict[str, typing.Any]) -> IdentityProfile:
    """Map a GitHub ``/user`` payload onto :class:`IdentityProfile`.

    GitHub does not assert ``email_verified``; the email returned from
    the API is the user's primary verified email when one is present.
    The login flow enforces verification by additionally fetching
    ``/user/emails`` and only accepting the row marked
    ``primary=true, verified=true``.
    """
    return IdentityProfile(
        subject=str(claims.get('id', '')),
        email=claims.get('email'),
        email_verified=True if claims.get('email') else False,
        name=claims.get('name') or claims.get('login'),
        avatar_url=claims.get('avatar_url'),
        groups=[],
        raw_claims=claims,
    )


class _GitHubBase(IdentityPlugin):
    """Shared base for GitHub identity plugins.

    Subclasses set :attr:`manifest` and :meth:`_resolve_host`.
    """

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        """Return the hostname this plugin instance targets."""
        raise NotImplementedError

    @staticmethod
    def _normalize_host(raw: typing.Any, label: str) -> str:
        """Validate and normalize a manifest ``host`` value.

        Strips whitespace, accepts optional scheme, and rejects values
        with paths/queries/fragments so callers can compose URLs from
        the result without producing malformed endpoints.
        """
        host = str(raw or '').strip()
        if not host:
            raise ValueError(f'{label} requires the "host" option')
        parsed = urllib.parse.urlsplit(
            host if '://' in host else f'https://{host}'
        )
        if (
            not parsed.hostname
            or parsed.path not in ('', '/')
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f'{label} got invalid host value: {host!r}')
        return parsed.hostname

    def _endpoints(self, options: dict[str, typing.Any]) -> dict[str, str]:
        host = self._resolve_host(options)
        # github.com routes login through github.com/login but API
        # requests through api.github.com.  GHEC tenants (``*.ghe.com``)
        # also send OAuth to github.com but route REST traffic to
        # ``api.<tenant>.ghe.com``.  GHES appliances route both OAuth
        # and REST through ``<host>/api/v3``.
        if host == 'github.com':
            return {
                'authorize': 'https://github.com/login/oauth/authorize',
                'token': 'https://github.com/login/oauth/access_token',
                'user': 'https://api.github.com/user',
                'emails': 'https://api.github.com/user/emails',
            }
        if host.endswith('.ghe.com'):
            api_host = f'api.{host}'
            return {
                'authorize': 'https://github.com/login/oauth/authorize',
                'token': 'https://github.com/login/oauth/access_token',
                'user': f'https://{api_host}/user',
                'emails': f'https://{api_host}/user/emails',
            }
        return {
            'authorize': f'https://{host}/login/oauth/authorize',
            'token': f'https://{host}/login/oauth/access_token',
            'user': f'https://{host}/api/v3/user',
            'emails': f'https://{host}/api/v3/user/emails',
        }

    @staticmethod
    def _scopes(
        options: dict[str, typing.Any],
        scopes: list[str] | None,
    ) -> list[str]:
        if scopes:
            return scopes
        raw = options.get('default_scopes')
        if isinstance(raw, str) and raw.strip():
            return raw.split()
        if isinstance(raw, list):
            items: list[typing.Any] = raw  # pyright: ignore[reportUnknownVariableType]
            return [str(s) for s in items]
        return list(DEFAULT_SCOPES)

    async def authorization_request(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        redirect_uri: str,
        scopes: list[str] | None = None,
    ) -> AuthorizationRequest:
        endpoints = self._endpoints(ctx.assignment_options)
        scope_list = self._scopes(ctx.assignment_options, scopes)
        params: dict[str, str] = {
            'client_id': credentials['client_id'],
            'redirect_uri': redirect_uri,
            'scope': ' '.join(scope_list),
            'state': secrets.token_urlsafe(16),
        }
        url = endpoints['authorize'] + '?' + urllib.parse.urlencode(params)
        return AuthorizationRequest(
            authorization_url=url,
            state=params['state'],
        )

    async def exchange_code(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> tuple[IdentityProfile, IdentityCredentials]:
        endpoints = self._endpoints(ctx.assignment_options)
        data: dict[str, str] = {
            'client_id': credentials['client_id'],
            'client_secret': credentials['client_secret'],
            'code': code,
            'redirect_uri': redirect_uri,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                endpoints['token'],
                data=data,
                headers={'Accept': 'application/json'},
            )
        if token_resp.status_code != 200:
            raise ValueError(
                f'GitHub token exchange failed: {token_resp.status_code} '
                f'{token_resp.text}'
            )
        token = typing.cast(dict[str, typing.Any], token_resp.json())
        if 'access_token' not in token:
            raise ValueError(
                f'GitHub token response missing access_token: {token}'
            )

        access_token = str(token['access_token'])
        profile = await self._fetch_profile(endpoints, access_token)

        expires_at: datetime.datetime | None = None
        if 'expires_in' in token:
            expires_at = datetime.datetime.now(
                datetime.UTC
            ) + datetime.timedelta(seconds=int(token['expires_in']))

        raw_scope = token.get('scope', '')
        scopes: list[str] = (
            [s for s in str(raw_scope).split(',') if s] if raw_scope else []
        )
        return profile, IdentityCredentials(
            access_token=access_token,
            token_type=token.get('token_type', 'Bearer'),
            refresh_token=token.get('refresh_token'),
            expires_at=expires_at,
            scopes=scopes,
        )

    async def refresh(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        refresh_token: str,
    ) -> IdentityCredentials:
        endpoints = self._endpoints(ctx.assignment_options)
        data: dict[str, str] = {
            'client_id': credentials['client_id'],
            'client_secret': credentials['client_secret'],
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                endpoints['token'],
                data=data,
                headers={'Accept': 'application/json'},
            )
        if response.status_code != 200:
            raise ValueError(
                f'GitHub token refresh failed: {response.status_code} '
                f'{response.text}'
            )
        token = typing.cast(dict[str, typing.Any], response.json())
        if 'access_token' not in token:
            raise ValueError(
                f'GitHub refresh response missing access_token: {token}'
            )
        expires_at: datetime.datetime | None = None
        if 'expires_in' in token:
            expires_at = datetime.datetime.now(
                datetime.UTC
            ) + datetime.timedelta(seconds=int(token['expires_in']))
        raw_scope = token.get('scope', '')
        scopes: list[str] = (
            [s for s in str(raw_scope).split(',') if s] if raw_scope else []
        )
        return IdentityCredentials(
            access_token=str(token['access_token']),
            token_type=token.get('token_type', 'Bearer'),
            refresh_token=token.get('refresh_token', refresh_token),
            expires_at=expires_at,
            scopes=scopes,
        )

    async def _fetch_profile(
        self, endpoints: dict[str, str], access_token: str
    ) -> IdentityProfile:
        async with httpx.AsyncClient(timeout=10.0) as client:
            user_resp = await client.get(
                endpoints['user'],
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Accept': 'application/vnd.github+json',
                },
            )
            if user_resp.status_code != 200:
                raise ValueError(
                    f'GitHub /user failed: {user_resp.status_code} '
                    f'{user_resp.text}'
                )
            claims = typing.cast(dict[str, typing.Any], user_resp.json())
            # Fall back to /user/emails when the primary email is
            # private — GitHub returns email=null on /user in that case.
            if not claims.get('email'):
                emails_resp = await client.get(
                    endpoints['emails'],
                    headers={
                        'Authorization': f'Bearer {access_token}',
                        'Accept': 'application/vnd.github+json',
                    },
                )
                if emails_resp.status_code == 200:
                    rows = typing.cast(
                        list[dict[str, typing.Any]], emails_resp.json()
                    )
                    primary = next(
                        (
                            row
                            for row in rows
                            if row.get('primary') and row.get('verified')
                        ),
                        None,
                    )
                    if primary:
                        claims['email'] = primary['email']
        return _build_userinfo(claims)


class GitHubPlugin(_GitHubBase):
    manifest = PluginManifest(
        slug='github',
        name='GitHub',
        description='GitHub.com OAuth App identity provider.',
        plugin_type='identity',
        auth_type='oauth2',
        login_capable=True,
        default_scopes=DEFAULT_SCOPES,
        options=[
            PluginOption(
                name='default_scopes',
                label='Default scopes (space-separated)',
                type='string',
            ),
        ],
        credentials=[
            CredentialField(
                name='client_id',
                label='Client ID',
                required=True,
            ),
            CredentialField(
                name='client_secret',
                label='Client secret',
                required=True,
            ),
        ],
    )

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        return 'github.com'


class GitHubEnterpriseCloudPlugin(_GitHubBase):
    manifest = PluginManifest(
        slug='github-enterprise-cloud',
        name='GitHub Enterprise Cloud',
        description=(
            'GitHub Enterprise Cloud OAuth App identity provider '
            '(tenant.ghe.com).'
        ),
        plugin_type='identity',
        auth_type='oauth2',
        login_capable=True,
        default_scopes=DEFAULT_SCOPES,
        options=[
            PluginOption(
                name='host',
                label='GHEC tenant host',
                description='e.g. tenant.ghe.com',
                type='string',
                required=True,
            ),
            PluginOption(
                name='default_scopes',
                label='Default scopes (space-separated)',
                type='string',
            ),
        ],
        credentials=[
            CredentialField(
                name='client_id',
                label='Client ID',
                required=True,
            ),
            CredentialField(
                name='client_secret',
                label='Client secret',
                required=True,
            ),
        ],
    )

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        host = cls._normalize_host(options.get('host'), 'GHEC plugin')
        if (
            not host.endswith('.ghe.com')
            or host == '.ghe.com'
            or host.startswith('api.')
        ):
            raise ValueError(
                'GHEC plugin requires a tenant host like "tenant.ghe.com"; '
                f'got {host!r}'
            )
        return host


class GitHubEnterpriseServerPlugin(_GitHubBase):
    manifest = PluginManifest(
        slug='github-enterprise-server',
        name='GitHub Enterprise Server',
        description=('GitHub Enterprise Server OAuth App identity provider.'),
        plugin_type='identity',
        auth_type='oauth2',
        login_capable=True,
        default_scopes=DEFAULT_SCOPES,
        options=[
            PluginOption(
                name='host',
                label='GHES host',
                description='Hostname of the GHES install.',
                type='string',
                required=True,
            ),
            PluginOption(
                name='default_scopes',
                label='Default scopes (space-separated)',
                type='string',
            ),
        ],
        credentials=[
            CredentialField(
                name='client_id',
                label='Client ID',
                required=True,
            ),
            CredentialField(
                name='client_secret',
                label='Client secret',
                required=True,
            ),
        ],
    )

    @classmethod
    def _resolve_host(cls, options: dict[str, typing.Any]) -> str:
        return cls._normalize_host(options.get('host'), 'GHES plugin')
