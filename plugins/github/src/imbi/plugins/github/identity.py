"""GitHub identity plugin.

A single, host-agnostic :class:`GitHubIdentityPlugin` implements the
OAuth App flow for every GitHub flavor. The target host (github.com, a
GHEC ``*.ghe.com`` tenant, or a GHES appliance) is resolved at call time
from the ``github-connection`` plugin attached to the same
``ThirdPartyService``, so there is no longer a per-flavor subclass.

The access token from the OAuth grant is passed straight to GitHub APIs
as a ``Bearer`` token.
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

from imbi_plugin_github._hosts import resolve_connection_host

LOGGER = logging.getLogger(__name__)

# Default scope set for the GitHub identity flow. Each scope maps to
# at least one endpoint the plugin family actually calls:
#   * ``read:user``   — ``GET /user`` (sign-in / profile)
#   * ``user:email``  — ``GET /user/emails`` (verified email fallback)
#   * ``repo``        — ``GET /repos/{owner}/{repo}/...`` (branches,
#                       tags, commits, compare, check-runs, action
#                       runs) plus ``POST /git/refs`` and
#                       ``POST /releases`` for the Promote tab. There
#                       is no read-only equivalent in OAuth classic
#                       once private repos are in play.
#   * ``workflow``    — ``POST /actions/workflows/{file}/dispatches``
#                       (Deploy tab).
# ``read:org`` was deliberately dropped — no org/team endpoints are
# called today. Operators that need a narrower bind can override this
# on the identity assignment via the ``default_scopes`` plugin option.
DEFAULT_SCOPES = [
    'read:user',
    'user:email',
    'repo',
    'workflow',
]


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


class GitHubIdentityPlugin(IdentityPlugin):
    """Host-agnostic GitHub OAuth App identity plugin.

    The target host is resolved per call from the ``github-connection``
    plugin attached to the same service.
    """

    manifest = PluginManifest(
        slug='github-identity',
        name='GitHub',
        description='GitHub OAuth App identity provider.',
        widget_text=(
            'Connect to enable functionality such as pull-request visibility, '
            'project creation, and deployments.'
        ),
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

    def _endpoints(self, ctx: PluginContext) -> dict[str, str]:
        host = resolve_connection_host(ctx.service_plugins, 'github-identity')
        # github.com routes login through github.com/login but API
        # requests through api.github.com.  GHEC with Data Residency
        # tenants (``*.ghe.com``) are isolated: OAuth authorize/token
        # live on the tenant host and REST traffic on
        # ``api.<tenant>.ghe.com``.  GHES appliances host OAuth at
        # ``<host>/login/oauth/...`` and REST at ``<host>/api/v3/...``.
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
                'authorize': f'https://{host}/login/oauth/authorize',
                'token': f'https://{host}/login/oauth/access_token',
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
        endpoints = self._endpoints(ctx)
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
        endpoints = self._endpoints(ctx)
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
        endpoints = self._endpoints(ctx)
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
