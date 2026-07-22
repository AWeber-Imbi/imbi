"""AWS IAM Identity Center identity capability.

Implements the :class:`IdentityCapability` contract against the IAM IC
public OIDC + Portal HTTP APIs:

* OIDC: ``https://oidc.{region}.amazonaws.com``
* Portal: ``https://portal.sso.{region}.amazonaws.com``

These endpoints are unauthenticated for the device-code flow (no
sigv4), so we use ``httpx`` directly instead of pulling in
``aioboto3``.

Flow:

1. ``RegisterClient`` (one-time per Integration).  The returned
   ``clientId``/``clientSecret`` are surfaced back to the host via
   :attr:`AuthorizationRequest.registered_credentials`, which persists
   them into the Integration's encrypted credential blob; the host
   threads them back in via the ``credentials`` dict on subsequent
   calls.
2. ``StartDeviceAuthorization`` returns a verification URI + user
   code + device code.  We pack the device code (and the cached
   client id/secret) into the state JWT and surface the user code
   via :class:`PollingDescriptor`.
3. The UI polls ``/me/identities/{integration_id}/poll`` (host
   endpoint) which calls back into :meth:`exchange_code` with the
   device code as ``code``.
4. ``CreateToken(grant_type=device_code)`` returns the IAM IC access
   token (and optionally a refresh token).  We populate
   :class:`IdentityProfile` from the IAM IC user metadata and stash
   the chosen ``account_id`` / ``role_name`` in
   ``IdentityCredentials.extra``.
5. ``materialize`` calls ``GetRoleCredentials`` against the Portal API
   to mint short-lived STS keys, returned as
   ``IdentityCredentials.extra`` so the ``logs`` / ``configuration``
   capabilities can pick them up transparently.
"""

from __future__ import annotations

import datetime
import logging
import typing

import httpx
from imbi_common.plugins.base import (
    AuthorizationRequest,
    IdentityCapability,
    IdentityCredentials,
    IdentityProfile,
    PluginContext,
    PollingDescriptor,
)
from imbi_common.plugins.errors import PluginCredentialsMissing
from imbi_common.plugins.templates import expand_template

from imbi_plugin_aws._helpers import template_vars
from imbi_plugin_aws.errors import (
    IamIcAuthorizationPending,
    IamIcDeviceFlowExpired,
)

LOGGER = logging.getLogger(__name__)

# IAM IC only issues refresh tokens when the registered client's
# declared scopes include this value (or another long-lived scope).
REFRESH_SCOPE = 'sso:account:access'

#: Scopes requested at connect time. Surfaced to the host/UI via the
#: identity capability's ``default_scopes`` hint (see plugin.py) and used
#: directly by :meth:`AWSIdentity.authorization_request`.
DEFAULT_SCOPES = [REFRESH_SCOPE]


def _oidc_url(region: str, path: str) -> str:
    return f'https://oidc.{region}.amazonaws.com{path}'


def _portal_url(region: str, path: str) -> str:
    return f'https://portal.sso.{region}.amazonaws.com{path}'


class AWSIdentity(IdentityCapability):
    """AWS IAM Identity Center identity handler (device-code flow).

    The ``identity`` capability of :class:`~imbi_plugin_aws.plugin.AWSPlugin`.
    It is the credential mechanism for every AWS Integration: the other
    capabilities receive the STS keys it mints via
    :meth:`materialize` on ``PluginContext.identity``.
    """

    async def authorization_request(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        redirect_uri: str,
        scopes: list[str] | None = None,
    ) -> AuthorizationRequest:
        """Begin a device-flow authorization.

        Auto-registers an OIDC client when ``credentials`` is missing
        ``client_id`` / ``client_secret``.  The host is expected to
        round-trip the new client id/secret back to the Integration's
        encrypted credential blob (via
        :attr:`AuthorizationRequest.registered_credentials`); this
        handler treats the ``credentials`` dict as authoritative on the
        next call.
        """
        region = self._region(ctx)
        start_url = self._start_url(ctx)

        client_id = credentials.get('client_id')
        client_secret = credentials.get('client_secret')
        cached_scopes = _parse_cached_scopes(credentials.get('client_scopes'))
        requested_scopes = DEFAULT_SCOPES if scopes is None else scopes
        # A cached client registered before scope-tracking landed (or
        # with a stale scope set) silently produces connections with no
        # refresh token; force a re-register so the sweeper has
        # something to work with.
        scopes_stale = not _scopes_cover(cached_scopes, requested_scopes)
        registered: dict[str, str] | None = None
        if not client_id or not client_secret or scopes_stale:
            client_id, client_secret = await self._register_client(
                region, requested_scopes
            )
            # Surface the freshly-minted client back to the host so it
            # can persist them; otherwise the matching CreateToken call
            # (which only sees ``credentials`` from storage) would
            # arrive with empty client_id and AWS would 401.  The
            # ``client_scopes`` echo lets the next call short-circuit
            # the scope-staleness check above.
            registered = {
                'client_id': client_id,
                'client_secret': client_secret,
                'client_scopes': ' '.join(requested_scopes),
            }

        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.post(
                _oidc_url(region, '/device_authorization'),
                json={
                    'clientId': client_id,
                    'clientSecret': client_secret,
                    'startUrl': start_url,
                },
            )
        if response.status_code != 200:
            raise ValueError(
                f'IAM IC device authorization failed: '
                f'{response.status_code} {response.text}'
            )
        data = typing.cast(dict[str, typing.Any], response.json())
        polling = PollingDescriptor(
            user_code=str(data['userCode']),
            verification_uri=str(data['verificationUri']),
            verification_uri_complete=data.get('verificationUriComplete'),
            interval=int(data.get('interval', 5)),
            expires_in=int(data.get('expiresIn', 600)),
        )
        # The "code" the host will hand back to ``exchange_code`` is the
        # device code; pack it (plus the freshly registered client
        # id/secret) into the state token via the host's state JWT
        # machinery.  We surface them on the AuthorizationRequest so the
        # host can include them in the JWT it signs.
        return AuthorizationRequest(
            authorization_url=str(
                data.get('verificationUriComplete') or data['verificationUri']
            ),
            state=str(data['deviceCode']),
            code_verifier=None,
            polling=polling,
            registered_credentials=registered,
        )

    async def exchange_code(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> tuple[IdentityProfile, IdentityCredentials]:
        """Exchange a device code for an IAM IC access token.

        ``code`` is the IAM IC ``deviceCode`` returned by
        ``StartDeviceAuthorization``.  Raises
        :class:`IamIcAuthorizationPending` while the user is still
        completing the flow — the host's poll loop should swallow this
        and retry.
        """
        region = self._region(ctx)
        client_id = credentials.get('client_id') or ''
        client_secret = credentials.get('client_secret') or ''

        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.post(
                _oidc_url(region, '/token'),
                json={
                    'clientId': client_id,
                    'clientSecret': client_secret,
                    'grantType': (
                        'urn:ietf:params:oauth:grant-type:device_code'
                    ),
                    'deviceCode': code,
                },
            )
        return self._handle_token_response(ctx, response, code)

    async def refresh(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        refresh_token: str,
    ) -> IdentityCredentials:
        """Refresh the IAM IC access token if a refresh token was issued.

        IAM IC only issues refresh tokens when the registered client
        scopes include ``sso:account:access`` — the connect-time grant
        without that scope returns no refresh token, in which case the
        sweeper should mark the connection ``status='expired'`` and
        require the user to re-run the device flow.
        """
        region = self._region(ctx)
        client_id = credentials.get('client_id') or ''
        client_secret = credentials.get('client_secret') or ''
        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.post(
                _oidc_url(region, '/token'),
                json={
                    'clientId': client_id,
                    'clientSecret': client_secret,
                    'grantType': 'refresh_token',
                    'refreshToken': refresh_token,
                },
            )
        if response.status_code != 200:
            raise ValueError(
                f'IAM IC refresh failed: {response.status_code} '
                f'{response.text}'
            )
        token = typing.cast(dict[str, typing.Any], response.json())
        expires_at = _expires_at(token)
        return IdentityCredentials(
            access_token=str(token['accessToken']),
            token_type=str(token.get('tokenType', 'Bearer')),
            refresh_token=token.get('refreshToken', refresh_token),
            expires_at=expires_at,
            scopes=[],
        )

    async def materialize(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        connection: IdentityCredentials,
        *,
        db: typing.Any | None = None,
        identity_options: dict[str, typing.Any] | None = None,
    ) -> IdentityCredentials:
        """Call ``GetRoleCredentials`` to mint short-lived STS keys.

        Resolves ``(account_id, role_name, region)`` in this order:

        1. The ``Environment.slug`` -> ``MAPS_TO`` -> ``AwsAccount``
           graph walk when ``ctx.environment`` is set and ``db`` is
           available.  This is the per-environment path: each env has
           its own AWS account, so log searches scoped to a specific
           env mint STS keys against that env's account.
        2. The Integration-level ``default_role_name`` option
           (:attr:`PluginContext.integration_options`), shared by every
           AWS capability.
        3. Connect-time defaults stamped onto ``connection.extra``
           (legacy single-account path).
        4. The identity capability's own ``identity_options``
           (``default_role_name`` in particular), as a last resort.

        Falls back through the chain so a partially configured
        deployment keeps working: an account with no
        ``default_role_name`` still mints creds via the Integration
        default, and a project with no environment query param still
        lands on the connect-time account.
        """
        identity_options = identity_options or {}
        account_id, role_name, account_region = await self._resolve_account(
            db, ctx
        )

        # Fallback: connect-time extras (legacy single-account path).
        extra = dict(connection.extra)
        if not account_id:
            account_id = extra.get('aws_account_id')
        if not role_name:
            role_name = (
                ctx.integration_options.get('default_role_name')
                or extra.get('aws_role_name')
                or identity_options.get('default_role_name')
            )

        # Region: AwsAccount.default_region > Integration region option
        # > connection extras > identity capability's region option.
        # ``_region`` guarantees a non-empty string (or raises) so the
        # portal URL below always has a region.
        region = (
            account_region
            or ctx.integration_options.get('region')
            or extra.get('aws_region')
            or identity_options.get('region')
            or self._region(ctx)
        )

        if not account_id or not role_name:
            # A config-time absence (no AwsAccount mapped for this
            # environment, no connect-time fallback), not an internal
            # error: surface it as PluginCredentialsMissing so the host
            # returns 503 with this detail instead of an opaque 500.
            raise PluginCredentialsMissing(
                'AWSIdentity.materialize: could not resolve '
                f'aws_account_id / aws_role_name for environment='
                f'{ctx.environment!r}; expected an Environment-MAPS_TO->'
                f'AwsAccount with default_role_name, a connect-time '
                f"extra, or an identity-plugin 'default_role_name' option"
            )

        # The role name may carry template placeholders (e.g.
        # ``${team_slug}``) so a single identity-plugin option can map
        # to per-project permission sets.  Expansion is whitelist-driven
        # (see imbi_common.plugins.templates) — unknown vars raise
        # ``ValueError`` and don't silently default to empty.
        if '${' in role_name:
            role_name = expand_template(role_name, template_vars(ctx))
            if not role_name:
                raise PluginCredentialsMissing(
                    'AWSIdentity.materialize: role_name template '
                    f'expanded to empty string for environment='
                    f'{ctx.environment!r}, team_slug={ctx.team_slug!r}'
                )

        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.get(
                _portal_url(region, '/federation/credentials'),
                params={
                    'account_id': account_id,
                    'role_name': role_name,
                },
                headers={
                    'x-amz-sso_bearer_token': connection.access_token,
                },
            )
        if response.status_code != 200:
            raise ValueError(
                f'IAM IC GetRoleCredentials failed: '
                f'{response.status_code} {response.text}'
            )
        body = typing.cast(dict[str, typing.Any], response.json())
        rc: dict[str, typing.Any] = body.get('roleCredentials') or {}
        sts_extra: dict[str, typing.Any] = {
            **extra,
            'aws_access_key_id': str(rc['accessKeyId']),
            'aws_secret_access_key': str(rc['secretAccessKey']),
            'aws_session_token': str(rc['sessionToken']),
            'aws_region': region,
            'aws_account_id': account_id,
        }
        return IdentityCredentials(
            access_token=connection.access_token,
            token_type=connection.token_type,
            expires_at=connection.expires_at,
            refresh_token=connection.refresh_token,
            scopes=connection.scopes,
            extra=sts_extra,
        )

    async def _resolve_account(
        self,
        db: typing.Any | None,
        ctx: PluginContext,
    ) -> tuple[str | None, str | None, str | None]:
        """Walk ``Environment.slug -> MAPS_TO -> AwsAccount``.

        Returns ``(account_id, role_name, region)`` from the matched
        :class:`AwsAccount`.  Any element may be ``None`` if absent;
        the caller falls back to other sources for what's missing.
        Returns ``(None, None, None)`` when ``db`` is not available
        (smoke / unit harnesses) or when the environment / mapping is
        not configured.

        Operational ``db.execute`` failures are *not* swallowed: an
        empty result is the only signal callers may treat as "no
        mapping".  Quietly returning ``(None, None, None)`` on a real
        DB error would mask a graph outage and let ``materialize``
        fall back to legacy connection-level credentials, which can
        mint a session for the *wrong* AWS account in an
        environment-scoped deployment.
        """
        if db is None or not ctx.environment:
            return None, None, None
        query: typing.LiteralString = (
            'MATCH (e:Environment {{slug: {env}}})'
            '-[:MAPS_TO]->(a:AwsAccount) '
            'RETURN a.account_id AS account_id, '
            'a.default_role_name AS role_name, '
            'a.default_region AS region '
            'LIMIT 1'
        )
        rows = await db.execute(
            query,
            {'env': ctx.environment},
            ['account_id', 'role_name', 'region'],
        )
        if not rows:
            return None, None, None
        try:
            from imbi_common.graph import parse_agtype
        except ImportError:
            return None, None, None
        row = rows[0]
        account_id = parse_agtype(row.get('account_id'))
        role_name = parse_agtype(row.get('role_name'))
        region = parse_agtype(row.get('region'))
        return (
            str(account_id) if account_id else None,
            str(role_name) if role_name else None,
            str(region) if region else None,
        )

    async def _register_client(
        self, region: str, scopes: list[str] | None = None
    ) -> tuple[str, str]:
        """One-time OIDC client registration.

        Returns ``(client_id, client_secret)``.  The host is expected
        to persist these into the Integration credential blob so the
        next call sees them in ``credentials``.  ``scopes`` is the list
        of OAuth scopes the client will be allowed to request — IAM IC
        gates refresh-token issuance on the registered scope set.
        """
        body: dict[str, typing.Any] = {
            'clientName': 'imbi',
            'clientType': 'public',
        }
        if scopes is not None:
            body['scopes'] = list(scopes)
        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.post(
                _oidc_url(region, '/client/register'),
                json=body,
            )
        if response.status_code not in (200, 201):
            raise ValueError(
                f'IAM IC RegisterClient failed: '
                f'{response.status_code} {response.text}'
            )
        data = typing.cast(dict[str, typing.Any], response.json())
        return str(data['clientId']), str(data['clientSecret'])

    def _handle_token_response(
        self,
        ctx: PluginContext,
        response: httpx.Response,
        device_code: str,
    ) -> tuple[IdentityProfile, IdentityCredentials]:
        if response.status_code == 400:
            body = typing.cast(dict[str, typing.Any], response.json())
            error = body.get('error')
            if error == 'authorization_pending':
                raise IamIcAuthorizationPending()
            if error == 'expired_token':
                raise IamIcDeviceFlowExpired()
            raise ValueError(
                f'IAM IC CreateToken failed: {error} '
                f'({body.get("error_description")})'
            )
        if response.status_code != 200:
            raise ValueError(
                f'IAM IC CreateToken failed: {response.status_code} '
                f'{response.text}'
            )
        token = typing.cast(dict[str, typing.Any], response.json())
        access_token = str(token['accessToken'])
        expires_at = _expires_at(token)

        # The IAM IC token response doesn't include user identity
        # claims directly — the subject is the device-code proxy.  We
        # populate a minimal :class:`IdentityProfile`; the host can
        # later call ``ListAccounts`` (out-of-scope for Phase 1) to
        # populate the user-visible email / name.
        profile = IdentityProfile(subject=device_code)

        # Default account / role from configured options when set.  When
        # both are unset, the host UI is expected to prompt the user
        # and post back the choice via the connection metadata path.
        # ``default_account_id`` is an identity capability option;
        # ``default_role_name`` is an Integration-level option.
        extra: dict[str, typing.Any] = {}
        default_account = ctx.capability_options.get('default_account_id')
        default_role = ctx.integration_options.get('default_role_name')
        if default_account:
            extra['aws_account_id'] = str(default_account)
        if default_role:
            extra['aws_role_name'] = str(default_role)
        region = self._region(ctx)
        if region:
            extra['aws_region'] = region

        return profile, IdentityCredentials(
            access_token=access_token,
            token_type=str(token.get('tokenType', 'Bearer')),
            expires_at=expires_at,
            refresh_token=token.get('refreshToken'),
            scopes=[],
            extra=extra,
        )

    @staticmethod
    def _region(ctx: PluginContext) -> str:
        region = ctx.integration_options.get('region')
        if not region:
            raise ValueError('AWSIdentity requires the "region" option')
        return str(region)

    @staticmethod
    def _start_url(ctx: PluginContext) -> str:
        start_url = ctx.capability_options.get('start_url')
        if not start_url:
            raise ValueError('AWSIdentity requires the "start_url" option')
        return str(start_url)


def _expires_at(token: dict[str, typing.Any]) -> datetime.datetime | None:
    if 'expiresIn' not in token:
        return None
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        seconds=int(token['expiresIn'])
    )


def _parse_cached_scopes(raw: str | None) -> frozenset[str]:
    """Decode the persisted ``client_scopes`` blob.

    Stored as a space-separated string so it survives the
    ``dict[str, str]`` shape of plugin credentials.  An empty / absent
    value yields an empty set, which fails :func:`_scopes_cover` and
    forces re-registration.
    """
    if not raw:
        return frozenset()
    return frozenset(part for part in raw.split() if part)


def _scopes_cover(cached: frozenset[str], requested: list[str] | None) -> bool:
    """True when ``cached`` is a superset of every requested scope."""
    if not requested:
        return True
    return all(scope in cached for scope in requested)
