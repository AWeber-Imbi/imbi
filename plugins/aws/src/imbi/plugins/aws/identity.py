"""AWS IAM Identity Center identity plugin.

Implements the :class:`IdentityPlugin` contract against the IAM IC
public OIDC + Portal HTTP APIs:

* OIDC: ``https://oidc.{region}.amazonaws.com``
* Portal: ``https://portal.sso.{region}.amazonaws.com``

These endpoints are unauthenticated for the device-code flow (no
sigv4), so we use ``httpx`` directly instead of pulling in
``aioboto3`` for Phase 1.

Flow:

1. ``RegisterClient`` (one-time per ``ServiceApplication``).  The
   returned ``clientId``/``clientSecret`` are cached on the parent
   ``ServiceApplication.plugin_credentials`` blob; the host-side
   credentials machinery threads them back in via the ``credentials``
   dict on subsequent calls.
2. ``StartDeviceAuthorization`` returns a verification URI + user
   code + device code.  We pack the device code (and the cached
   client id/secret) into the state JWT and surface the user code
   via :class:`PollingDescriptor`.
3. The UI polls ``/me/identities/{plugin_id}/poll`` (host endpoint —
   pending in the host) which calls back into ``poll`` here; until the
   ABC gains :meth:`poll`, the host will instead call
   :meth:`exchange_code` with the device code as ``code``.
4. ``CreateToken(grant_type=device_code)`` returns the IAM IC access
   token (and optionally a refresh token).  We populate
   :class:`IdentityProfile` from the IAM IC user metadata and stash
   the chosen ``account_id`` / ``role_name`` in
   ``IdentityCredentials.extra``.
5. ``materialize`` calls ``GetRoleCredentials`` against the Portal API
   to mint short-lived STS keys, returned as
   ``IdentityCredentials.extra`` so the data plugins (``aws-ssm`` /
   ``aws-cloudwatch-logs``) can pick them up transparently.
"""

from __future__ import annotations

import datetime
import logging
import typing

import httpx
from imbi_common.plugins.base import (
    AuthorizationRequest,
    CredentialField,
    IdentityCredentials,
    IdentityPlugin,
    IdentityProfile,
    PluginContext,
    PluginEdgeLabel,
    PluginIndex,
    PluginManifest,
    PluginOption,
    PluginVertexLabel,
    PollingDescriptor,
)

from imbi_plugin_aws.errors import (
    IamIcAuthorizationPending,
    IamIcDeviceFlowExpired,
)

LOGGER = logging.getLogger(__name__)


def _oidc_url(region: str, path: str) -> str:
    return f'https://oidc.{region}.amazonaws.com{path}'


def _portal_url(region: str, path: str) -> str:
    return f'https://portal.sso.{region}.amazonaws.com{path}'


class AwsIamIcPlugin(IdentityPlugin):
    """AWS IAM Identity Center identity plugin (device-code flow)."""

    manifest = PluginManifest(
        slug='aws-iam-ic',
        name='AWS IAM Identity Center',
        description='Federated AWS access via IAM Identity Center.',
        plugin_type='identity',
        auth_type='aws-iam-ic',
        cacheable=False,
        login_capable=True,
        requires_identity=False,
        default_scopes=['sso:account:access'],
        widget_text=(
            'Connect to enable project level functionality '
            'such as configuration and log access.'
        ),
        options=[
            PluginOption(
                name='start_url',
                label='IAM IC Start URL',
                type='string',
                required=True,
                description=('e.g. https://example.awsapps.com/start'),
            ),
            PluginOption(
                name='region',
                label='IAM IC Region',
                type='string',
                required=True,
                description=(
                    'Region where IAM Identity Center is provisioned.'
                ),
            ),
            PluginOption(
                name='default_account_id',
                label='Default AWS account id',
                type='string',
                required=False,
            ),
            PluginOption(
                name='default_role_name',
                label='Default IAM role',
                type='string',
                required=False,
            ),
        ],
        credentials=[
            CredentialField(
                name='client_id',
                label='Cached IAM IC Client ID',
                description='Auto-managed via RegisterClient.',
                required=False,
            ),
            CredentialField(
                name='client_secret',
                label='Cached IAM IC Client Secret',
                description='Auto-managed via RegisterClient.',
                required=False,
            ),
        ],
        vertex_labels=[
            PluginVertexLabel(
                name='AwsAccount',
                model_ref='imbi_plugin_aws.models:AwsAccount',
                indexes=[
                    PluginIndex(fields=['account_id'], unique=True),
                    PluginIndex(fields=['name']),
                ],
            ),
        ],
        edge_labels=[
            PluginEdgeLabel(
                name='MAPS_TO',
                from_labels=[
                    'Environment',
                    'Project',
                    'ProjectType',
                    'Organization',
                ],
                to_labels=['AwsAccount'],
                properties={'tags': 'dict[str, str]'},
            ),
        ],
    )

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
        round-trip the new client id/secret back to the
        ``ServiceApplication.plugin_credentials`` blob via the existing
        encryption layer; this plugin treats the ``credentials`` dict
        as authoritative on the next call.
        """
        region = self._region(ctx)
        start_url = self._start_url(ctx)

        client_id = credentials.get('client_id')
        client_secret = credentials.get('client_secret')
        registered: dict[str, str] | None = None
        if not client_id or not client_secret:
            # IAM IC only issues a refresh token on CreateToken when the
            # registered client's declared scopes include
            # ``sso:account:access`` (or another long-lived scope).  Pass
            # the requested scopes through to RegisterClient so the
            # device-flow grant is allowed to refresh later.
            client_id, client_secret = await self._register_client(
                region, scopes or self.manifest.default_scopes or None
            )
            # Surface the freshly-minted client back to the host so it
            # can persist them; otherwise the matching CreateToken call
            # (which only sees ``credentials`` from storage) would
            # arrive with empty client_id and AWS would 401.
            registered = {
                'client_id': client_id,
                'client_secret': client_secret,
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
    ) -> IdentityCredentials:
        """Call ``GetRoleCredentials`` to mint short-lived STS keys.

        Reads ``account_id`` / ``role_name`` / ``region`` from
        ``connection.extra`` (set at connect time) and returns a new
        :class:`IdentityCredentials` whose ``extra`` carries the STS
        access key, secret, and session token.
        """
        extra = dict(connection.extra)
        account_id = extra.get('aws_account_id')
        role_name = extra.get('aws_role_name')
        region = extra.get('aws_region') or self._region(ctx)
        if not account_id or not role_name:
            raise ValueError(
                'AwsIamIcPlugin.materialize: connection.extra must '
                'carry aws_account_id and aws_role_name'
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

    async def _register_client(
        self, region: str, scopes: list[str] | None = None
    ) -> tuple[str, str]:
        """One-time OIDC client registration.

        Returns ``(client_id, client_secret)``.  The host is expected
        to persist these on the parent ``ServiceApplication`` so the
        next call sees them in ``credentials``.  ``scopes`` is the list
        of OAuth scopes the client will be allowed to request — IAM IC
        gates refresh-token issuance on the registered scope set.
        """
        body: dict[str, typing.Any] = {
            'clientName': 'imbi',
            'clientType': 'public',
        }
        if scopes:
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

        # Default account / role from manifest options when set.  When
        # both are unset, the host UI is expected to prompt the user
        # and post back the choice via the connection metadata path.
        options = ctx.assignment_options
        extra: dict[str, typing.Any] = {}
        default_account = options.get('default_account_id')
        default_role = options.get('default_role_name')
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
        region = ctx.assignment_options.get('region')
        if not region:
            raise ValueError('AwsIamIcPlugin requires the "region" option')
        return str(region)

    @staticmethod
    def _start_url(ctx: PluginContext) -> str:
        start_url = ctx.assignment_options.get('start_url')
        if not start_url:
            raise ValueError('AwsIamIcPlugin requires the "start_url" option')
        return str(start_url)


def _expires_at(token: dict[str, typing.Any]) -> datetime.datetime | None:
    if 'expiresIn' not in token:
        return None
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        seconds=int(token['expiresIn'])
    )
