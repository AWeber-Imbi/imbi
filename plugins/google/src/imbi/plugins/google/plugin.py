"""Google identity plugin.

Sign in with Google (Google Workspace / consumer Google accounts) via the
OAuth 2.0 authorization-code + PKCE flow. Endpoints are fixed (Google is a
stable, well-known provider), so unlike the generic OIDC plugin there is no
discovery round-trip. A Workspace ``hosted_domain`` can be enforced by
Google itself via the ``hd`` authorization parameter.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import logging
import secrets
import typing
import urllib.parse

import httpx
from imbi_common.plugins.base import (
    AuthorizationRequest,
    Capability,
    CredentialField,
    IdentityCapability,
    IdentityCredentials,
    IdentityProfile,
    Plugin,
    PluginContext,
    PluginManifest,
    PluginOption,
)

LOGGER = logging.getLogger(__name__)

AUTHORIZATION_ENDPOINT = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'
USERINFO_ENDPOINT = 'https://openidconnect.googleapis.com/v1/userinfo'
REVOCATION_ENDPOINT = 'https://oauth2.googleapis.com/revoke'

DEFAULT_SCOPES = ['openid', 'profile', 'email']


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` per RFC 7636 S256."""
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode('ascii')).digest())
    return verifier, challenge


class GoogleIdentity(IdentityCapability):
    """Authorization-code + PKCE identity handler for Google."""

    async def authorization_request(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        redirect_uri: str,
        scopes: list[str] | None = None,
    ) -> AuthorizationRequest:
        options = ctx.integration_options
        scope_list = scopes or self._default_scopes(options)
        pkce_required = bool(options.get('pkce_required', True))

        verifier, challenge = _generate_pkce() if pkce_required else ('', '')

        params: dict[str, str] = {
            'response_type': 'code',
            'client_id': credentials['client_id'],
            'redirect_uri': redirect_uri,
            'scope': ' '.join(scope_list),
            'state': secrets.token_urlsafe(16),
            # Request a refresh token and force the consent screen so one is
            # reliably returned (Google only issues it on first consent).
            'access_type': 'offline',
            'prompt': 'consent',
        }
        if pkce_required:
            params['code_challenge'] = challenge
            params['code_challenge_method'] = 'S256'
        hosted_domain = options.get('hosted_domain')
        if hosted_domain:
            params['hd'] = str(hosted_domain)

        url = AUTHORIZATION_ENDPOINT + '?' + urllib.parse.urlencode(params)
        return AuthorizationRequest(
            authorization_url=url,
            state=params['state'],
            code_verifier=verifier or None,
        )

    async def exchange_code(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> tuple[IdentityProfile, IdentityCredentials]:
        _ = ctx
        data: dict[str, str] = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'client_id': credentials['client_id'],
        }
        if credentials.get('client_secret'):
            data['client_secret'] = credentials['client_secret']
        if code_verifier:
            data['code_verifier'] = code_verifier

        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(TOKEN_ENDPOINT, data=data)
        if token_resp.status_code != 200:
            raise ValueError(
                f'Token exchange failed: {token_resp.status_code} '
                f'{token_resp.text}'
            )
        token = typing.cast('dict[str, typing.Any]', token_resp.json())

        profile = await self._userinfo(token['access_token'])
        return profile, self._credentials(token)

    async def refresh(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        refresh_token: str,
    ) -> IdentityCredentials:
        _ = ctx
        data: dict[str, str] = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'client_id': credentials['client_id'],
        }
        if credentials.get('client_secret'):
            data['client_secret'] = credentials['client_secret']
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(TOKEN_ENDPOINT, data=data)
        if response.status_code != 200:
            raise ValueError(
                f'Token refresh failed: {response.status_code} {response.text}'
            )
        token = typing.cast('dict[str, typing.Any]', response.json())
        # Google does not return a new refresh token on refresh; keep the
        # existing one so the identity stays renewable.
        return self._credentials(token, fallback_refresh=refresh_token)

    async def revoke(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        token: str,
    ) -> None:
        _ = ctx, credentials
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(REVOCATION_ENDPOINT, data={'token': token})
        except httpx.HTTPError:
            LOGGER.warning('Google revocation request failed', exc_info=True)

    async def _userinfo(self, access_token: str) -> IdentityProfile:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                USERINFO_ENDPOINT,
                headers={'Authorization': f'Bearer {access_token}'},
            )
        if response.status_code != 200:
            raise ValueError(
                f'Userinfo request failed: {response.status_code} '
                f'{response.text}'
            )
        claims = typing.cast('dict[str, typing.Any]', response.json())
        return IdentityProfile(
            subject=str(claims.get('sub', '')),
            email=claims.get('email'),
            email_verified=bool(claims.get('email_verified', False)),
            name=claims.get('name'),
            avatar_url=claims.get('picture'),
            raw_claims=claims,
        )

    @staticmethod
    def _credentials(
        token: dict[str, typing.Any],
        fallback_refresh: str | None = None,
    ) -> IdentityCredentials:
        expires_at: datetime.datetime | None = None
        if 'expires_in' in token:
            expires_at = datetime.datetime.now(
                datetime.UTC
            ) + datetime.timedelta(seconds=int(token['expires_in']))
        scope_str = typing.cast('str', token.get('scope') or '')
        return IdentityCredentials(
            access_token=token['access_token'],
            token_type=token.get('token_type', 'Bearer'),
            refresh_token=token.get('refresh_token', fallback_refresh),
            expires_at=expires_at,
            scopes=scope_str.split(),
        )

    @staticmethod
    def _default_scopes(options: dict[str, typing.Any]) -> list[str]:
        raw = options.get('default_scopes')
        if isinstance(raw, str) and raw.strip():
            return raw.split()
        if isinstance(raw, list):
            return [str(s) for s in typing.cast('list[typing.Any]', raw)]
        return list(DEFAULT_SCOPES)


class GooglePlugin(Plugin):
    manifest = PluginManifest(
        slug='google',
        name='Google',
        description='Sign in with a Google or Google Workspace account.',
        auth_type='oidc',
        options=[
            PluginOption(
                name='hosted_domain',
                label='Workspace domain',
                description=(
                    'Restrict sign-in to a Google Workspace domain '
                    '(sent as the `hd` parameter, e.g. example.com). '
                    'Leave blank to allow any Google account.'
                ),
                type='string',
            ),
            PluginOption(
                name='pkce_required',
                label='Require PKCE',
                type='boolean',
                default=True,
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
                description='Google OAuth client identifier.',
                required=True,
                secret=False,
            ),
            CredentialField(
                name='client_secret',
                label='Client secret',
                description='Google OAuth client secret.',
                required=True,
            ),
        ],
        capabilities=[
            Capability(
                kind='identity',
                label='Sign in with Google',
                description='Google OAuth 2.0 identity provider.',
                default_enabled=False,
                project_scoped=False,
                hints={
                    'login_capable': True,
                    'default_scopes': DEFAULT_SCOPES,
                    'widget_text': 'Sign in with Google',
                },
                handler=GoogleIdentity,
            ),
        ],
    )
