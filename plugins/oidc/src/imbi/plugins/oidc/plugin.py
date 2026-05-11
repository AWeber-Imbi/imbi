"""Generic OIDC identity plugin."""

from __future__ import annotations

import base64
import datetime
import hashlib
import logging
import secrets
import time
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

DISCOVERY_TTL_SECONDS = 86400


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` per RFC 7636 S256."""
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode('ascii')).digest())
    return verifier, challenge


class OIDCPlugin(IdentityPlugin):
    manifest = PluginManifest(
        slug='oidc',
        name='OIDC',
        description='Generic OpenID Connect identity provider.',
        plugin_type='identity',
        auth_type='oidc',
        login_capable=True,
        default_scopes=['openid', 'profile', 'email'],
        options=[
            PluginOption(
                name='issuer_url',
                label='Issuer URL',
                description='OIDC issuer (without trailing slash).',
                type='string',
                required=True,
            ),
            PluginOption(
                name='authorization_endpoint',
                label='Authorization endpoint',
                type='string',
            ),
            PluginOption(
                name='token_endpoint',
                label='Token endpoint',
                type='string',
            ),
            PluginOption(
                name='userinfo_endpoint',
                label='Userinfo endpoint',
                type='string',
            ),
            PluginOption(name='jwks_uri', label='JWKS URI', type='string'),
            PluginOption(
                name='revocation_endpoint',
                label='Revocation endpoint',
                type='string',
            ),
            PluginOption(name='audience', label='Audience', type='string'),
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
                description='OAuth client identifier.',
                required=True,
            ),
            CredentialField(
                name='client_secret',
                label='Client secret',
                description=(
                    'OAuth client secret. Optional when '
                    'pkce_required=true (public client).'
                ),
                required=False,
            ),
        ],
    )

    _discovery_cache: typing.ClassVar[
        dict[str, tuple[dict[str, typing.Any], float]]
    ] = {}

    async def _discover(self, issuer_url: str) -> dict[str, typing.Any]:
        cached = self._discovery_cache.get(issuer_url)
        if cached:
            data, ts = cached
            if time.time() - ts < DISCOVERY_TTL_SECONDS:
                return data
        url = f'{issuer_url.rstrip("/")}/.well-known/openid-configuration'
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
        if response.status_code != 200:
            raise ValueError(f'OIDC discovery failed: {response.status_code}')
        data = typing.cast(dict[str, typing.Any], response.json())
        self._discovery_cache[issuer_url] = (data, time.time())
        return data

    async def _resolve_endpoints(
        self, options: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        issuer_url = options.get('issuer_url')
        if not issuer_url:
            raise ValueError('OIDC plugin requires issuer_url')
        discovery = await self._discover(issuer_url)
        return {
            'authorization_endpoint': options.get('authorization_endpoint')
            or discovery['authorization_endpoint'],
            'token_endpoint': options.get('token_endpoint')
            or discovery['token_endpoint'],
            'userinfo_endpoint': options.get('userinfo_endpoint')
            or discovery['userinfo_endpoint'],
            'jwks_uri': options.get('jwks_uri') or discovery.get('jwks_uri'),
            'revocation_endpoint': options.get('revocation_endpoint')
            or discovery.get('revocation_endpoint'),
        }

    async def authorization_request(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        redirect_uri: str,
        scopes: list[str] | None = None,
    ) -> AuthorizationRequest:
        options = ctx.assignment_options
        endpoints = await self._resolve_endpoints(options)
        scope_list = scopes or self._default_scopes(options)
        pkce_required = bool(options.get('pkce_required', True))

        verifier, challenge = _generate_pkce() if pkce_required else ('', '')

        params: dict[str, str] = {
            'response_type': 'code',
            'client_id': credentials['client_id'],
            'redirect_uri': redirect_uri,
            'scope': ' '.join(scope_list),
            'state': secrets.token_urlsafe(16),
        }
        if pkce_required:
            params['code_challenge'] = challenge
            params['code_challenge_method'] = 'S256'
        audience = options.get('audience')
        if audience:
            params['audience'] = audience

        url = (
            endpoints['authorization_endpoint']
            + '?'
            + urllib.parse.urlencode(params)
        )
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
        options = ctx.assignment_options
        endpoints = await self._resolve_endpoints(options)

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
            token_resp = await client.post(
                endpoints['token_endpoint'], data=data
            )
        if token_resp.status_code != 200:
            raise ValueError(
                f'Token exchange failed: {token_resp.status_code} '
                f'{token_resp.text}'
            )
        token = typing.cast(dict[str, typing.Any], token_resp.json())

        profile = await self._userinfo(
            endpoints['userinfo_endpoint'],
            token['access_token'],
        )
        expires_at: datetime.datetime | None = None
        if 'expires_in' in token:
            expires_at = datetime.datetime.now(
                datetime.UTC
            ) + datetime.timedelta(seconds=int(token['expires_in']))
        scope_str = typing.cast(str, token.get('scope') or '')
        scopes = scope_str.split()
        return profile, IdentityCredentials(
            access_token=token['access_token'],
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
        options = ctx.assignment_options
        endpoints = await self._resolve_endpoints(options)
        data: dict[str, str] = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'client_id': credentials['client_id'],
        }
        if credentials.get('client_secret'):
            data['client_secret'] = credentials['client_secret']
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                endpoints['token_endpoint'], data=data
            )
        if response.status_code != 200:
            raise ValueError(
                f'Token refresh failed: {response.status_code} {response.text}'
            )
        token = typing.cast(dict[str, typing.Any], response.json())
        expires_at: datetime.datetime | None = None
        if 'expires_in' in token:
            expires_at = datetime.datetime.now(
                datetime.UTC
            ) + datetime.timedelta(seconds=int(token['expires_in']))
        scope_str = typing.cast(str, token.get('scope') or '')
        scopes = scope_str.split()
        return IdentityCredentials(
            access_token=token['access_token'],
            token_type=token.get('token_type', 'Bearer'),
            refresh_token=token.get('refresh_token', refresh_token),
            expires_at=expires_at,
            scopes=scopes,
        )

    async def revoke(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        token: str,
    ) -> None:
        options = ctx.assignment_options
        endpoints = await self._resolve_endpoints(options)
        url = endpoints.get('revocation_endpoint')
        if not url:
            return
        data: dict[str, str] = {
            'token': token,
            'client_id': credentials['client_id'],
        }
        if credentials.get('client_secret'):
            data['client_secret'] = credentials['client_secret']
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, data=data)
        except httpx.HTTPError:
            LOGGER.warning('OIDC revocation request failed', exc_info=True)

    async def _userinfo(self, url: str, access_token: str) -> IdentityProfile:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={'Authorization': f'Bearer {access_token}'},
            )
        if response.status_code != 200:
            raise ValueError(
                f'Userinfo request failed: {response.status_code} '
                f'{response.text}'
            )
        claims = typing.cast(dict[str, typing.Any], response.json())
        return IdentityProfile(
            subject=str(claims.get('sub', '')),
            email=claims.get('email'),
            email_verified=bool(claims.get('email_verified', False)),
            name=claims.get('name'),
            avatar_url=claims.get('picture'),
            groups=list(claims.get('groups', []) or []),
            raw_claims=claims,
        )

    @staticmethod
    def _default_scopes(options: dict[str, typing.Any]) -> list[str]:
        raw = options.get('default_scopes')
        if isinstance(raw, str) and raw.strip():
            return raw.split()
        if isinstance(raw, list):
            return [str(s) for s in typing.cast(list[typing.Any], raw)]
        return ['openid', 'profile', 'email']
