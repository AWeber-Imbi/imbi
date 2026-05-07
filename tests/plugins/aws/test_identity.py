"""Tests for the AwsIamIcPlugin device-flow contract."""

import unittest

import httpx
import respx
from imbi_common.plugins.base import (
    IdentityCredentials,
    IdentityPlugin,
    PluginContext,
)

from imbi_plugin_aws.errors import (
    IamIcAuthorizationPending,
    IamIcDeviceFlowExpired,
)
from imbi_plugin_aws.identity import AwsIamIcPlugin


def _ctx(options: dict[str, object] | None = None) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug='proj',
        org_slug='org',
        assignment_options=options
        or {
            'region': 'us-east-1',
            'start_url': 'https://example.awsapps.com/start',
        },
        actor_user_id='u-1',
    )


class ManifestTestCase(unittest.TestCase):
    def test_basics(self) -> None:
        plugin = AwsIamIcPlugin()
        self.assertIsInstance(plugin, IdentityPlugin)
        self.assertEqual(plugin.manifest.slug, 'aws-iam-ic')
        self.assertEqual(plugin.manifest.plugin_type, 'identity')
        self.assertEqual(plugin.manifest.auth_type, 'aws-iam-ic')
        self.assertTrue(plugin.manifest.login_capable)
        self.assertFalse(plugin.manifest.cacheable)
        self.assertEqual(len(plugin.manifest.vertex_labels), 1)
        self.assertEqual(plugin.manifest.vertex_labels[0].name, 'AwsAccount')
        self.assertEqual(len(plugin.manifest.edge_labels), 1)
        self.assertEqual(plugin.manifest.edge_labels[0].name, 'MAPS_TO')

    def test_region_and_start_url_required(self) -> None:
        plugin = AwsIamIcPlugin()
        with self.assertRaises(ValueError):
            plugin._region(  # pyright: ignore[reportPrivateUsage]
                _ctx({'start_url': 'https://x'})
            )
        with self.assertRaises(ValueError):
            plugin._start_url(  # pyright: ignore[reportPrivateUsage]
                _ctx({'region': 'us-east-1'})
            )


class AuthorizationRequestTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_uses_cached_client_credentials(self) -> None:
        respx.post(
            'https://oidc.us-east-1.amazonaws.com/device_authorization'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'deviceCode': 'dev-code',
                    'userCode': 'ABCD-1234',
                    'verificationUri': 'https://device.sso.example.com',
                    'verificationUriComplete': (
                        'https://device.sso.example.com?code=ABCD-1234'
                    ),
                    'interval': 5,
                    'expiresIn': 600,
                },
            )
        )
        plugin = AwsIamIcPlugin()
        request = await plugin.authorization_request(
            _ctx(),
            {'client_id': 'cached-cid', 'client_secret': 'cached-sec'},
            'https://imbi.test/cb',
        )
        self.assertEqual(request.state, 'dev-code')
        self.assertIsNotNone(request.polling)
        assert request.polling is not None
        self.assertEqual(request.polling.user_code, 'ABCD-1234')
        self.assertEqual(request.polling.interval, 5)

    @respx.mock
    async def test_registers_client_when_missing(self) -> None:
        respx.post(
            'https://oidc.us-east-1.amazonaws.com/client/register'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'clientId': 'fresh-cid',
                    'clientSecret': 'fresh-sec',
                    'clientSecretExpiresAt': 999999999,
                },
            )
        )
        respx.post(
            'https://oidc.us-east-1.amazonaws.com/device_authorization'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'deviceCode': 'dev-code',
                    'userCode': 'CODE',
                    'verificationUri': 'https://device.sso',
                    'interval': 3,
                    'expiresIn': 300,
                },
            )
        )
        plugin = AwsIamIcPlugin()
        request = await plugin.authorization_request(
            _ctx(),
            {},
            'https://imbi.test/cb',
        )
        self.assertEqual(request.state, 'dev-code')


class ExchangeCodeTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_authorization_pending_raises_sentinel(self) -> None:
        respx.post('https://oidc.us-east-1.amazonaws.com/token').mock(
            return_value=httpx.Response(
                400,
                json={
                    'error': 'authorization_pending',
                    'error_description': 'still waiting',
                },
            )
        )
        plugin = AwsIamIcPlugin()
        with self.assertRaises(IamIcAuthorizationPending):
            await plugin.exchange_code(
                _ctx(),
                {
                    'client_id': 'cid',
                    'client_secret': 'sec',
                },
                'dev-code',
                'https://imbi.test/cb',
            )

    @respx.mock
    async def test_expired_token_raises_specific_error(self) -> None:
        respx.post('https://oidc.us-east-1.amazonaws.com/token').mock(
            return_value=httpx.Response(
                400,
                json={'error': 'expired_token'},
            )
        )
        plugin = AwsIamIcPlugin()
        with self.assertRaises(IamIcDeviceFlowExpired):
            await plugin.exchange_code(
                _ctx(),
                {'client_id': 'cid', 'client_secret': 'sec'},
                'dev-code',
                'https://imbi.test/cb',
            )

    @respx.mock
    async def test_happy_path(self) -> None:
        respx.post('https://oidc.us-east-1.amazonaws.com/token').mock(
            return_value=httpx.Response(
                200,
                json={
                    'accessToken': 'iam-ic-token',
                    'tokenType': 'Bearer',
                    'expiresIn': 3600,
                    'refreshToken': 'rt',
                },
            )
        )
        plugin = AwsIamIcPlugin()
        profile, credentials = await plugin.exchange_code(
            _ctx(
                {
                    'region': 'us-east-1',
                    'start_url': 'https://example.awsapps.com/start',
                    'default_account_id': '111111111111',
                    'default_role_name': 'PowerUserAccess',
                }
            ),
            {'client_id': 'cid', 'client_secret': 'sec'},
            'dev-code',
            'https://imbi.test/cb',
        )
        self.assertEqual(credentials.access_token, 'iam-ic-token')
        self.assertEqual(credentials.refresh_token, 'rt')
        self.assertEqual(credentials.extra['aws_account_id'], '111111111111')
        self.assertEqual(credentials.extra['aws_role_name'], 'PowerUserAccess')
        self.assertEqual(profile.subject, 'dev-code')


class MaterializeTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_returns_sts_keys(self) -> None:
        respx.get(
            'https://portal.sso.us-east-1.amazonaws.com/federation/credentials'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'roleCredentials': {
                        'accessKeyId': 'AKIA...',
                        'secretAccessKey': 'wJalrXUtnFEMI...',
                        'sessionToken': 'session-token',
                        'expiration': 1700000000000,
                    }
                },
            )
        )
        plugin = AwsIamIcPlugin()
        connection = IdentityCredentials(
            access_token='iam-ic-token',
            extra={
                'aws_account_id': '111111111111',
                'aws_role_name': 'PowerUserAccess',
                'aws_region': 'us-east-1',
            },
        )
        result = await plugin.materialize(_ctx(), {}, connection)
        self.assertEqual(result.extra['aws_access_key_id'], 'AKIA...')
        self.assertEqual(
            result.extra['aws_secret_access_key'], 'wJalrXUtnFEMI...'
        )
        self.assertEqual(result.extra['aws_session_token'], 'session-token')
        # Original IAM IC token should be unchanged.
        self.assertEqual(result.access_token, 'iam-ic-token')

    async def test_missing_account_or_role_raises(self) -> None:
        plugin = AwsIamIcPlugin()
        connection = IdentityCredentials(
            access_token='iam-ic-token',
            extra={'aws_account_id': '111111111111'},
        )
        with self.assertRaises(ValueError):
            await plugin.materialize(_ctx(), {}, connection)

    @respx.mock
    async def test_resolves_account_via_environment_maps_to(self) -> None:
        captured: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(dict(request.url.params))
            return httpx.Response(
                200,
                json={
                    'roleCredentials': {
                        'accessKeyId': 'AKIA-prod',
                        'secretAccessKey': 'sec-prod',
                        'sessionToken': 'tok-prod',
                        'expiration': 1700000000000,
                    }
                },
            )

        respx.get(
            'https://portal.sso.us-east-1.amazonaws.com/federation/credentials'
        ).mock(side_effect=handler)

        class _FakeDB:
            def __init__(self, account_id: str, role: str) -> None:
                self.account_id = account_id
                self.role = role

            async def execute(
                self,
                _query: str,
                _params: dict[str, object],
                _columns: list[str],
            ) -> list[dict[str, object]]:
                return [
                    {
                        'account_id': f'"{self.account_id}"',
                        'role_name': f'"{self.role}"',
                        'region': '"us-east-1"',
                    }
                ]

        plugin = AwsIamIcPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='org',
            environment='production',
            assignment_options={
                'region': 'us-east-1',
                'start_url': 'https://example.awsapps.com/start',
            },
            actor_user_id='u-1',
        )
        connection = IdentityCredentials(
            access_token='iam-ic-token',
            extra={
                # Connect-time defaults — should be ignored in favor of
                # the env-mapped account.
                'aws_account_id': '999999999999',
                'aws_role_name': 'OldRole',
            },
        )
        result = await plugin.materialize(
            ctx,
            {},
            connection,
            db=_FakeDB('111111111111', 'ImbiOperator'),
        )
        # GetRoleCredentials called with the env-resolved account/role.
        self.assertEqual(
            captured[0],
            {'account_id': '111111111111', 'role_name': 'ImbiOperator'},
        )
        self.assertEqual(result.extra['aws_access_key_id'], 'AKIA-prod')
        self.assertEqual(result.extra['aws_account_id'], '111111111111')

    @respx.mock
    async def test_role_name_template_expanded_with_team_slug(self) -> None:
        captured: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(dict(request.url.params))
            return httpx.Response(
                200,
                json={
                    'roleCredentials': {
                        'accessKeyId': 'AKIA',
                        'secretAccessKey': 'sec',
                        'sessionToken': 'tok',
                        'expiration': 1700000000000,
                    }
                },
            )

        respx.get(
            'https://portal.sso.us-east-1.amazonaws.com/federation/credentials'
        ).mock(side_effect=handler)

        class _FakeDB:
            async def execute(
                self,
                _query: str,
                _params: dict[str, object],
                _columns: list[str],
            ) -> list[dict[str, object]]:
                return [
                    {
                        'account_id': '"333333333333"',
                        'role_name': None,
                        'region': None,
                    }
                ]

        plugin = AwsIamIcPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='widget',
            org_slug='org',
            team_slug='platform',
            environment='production',
            assignment_options={
                'region': 'us-east-1',
                'start_url': 'https://example.awsapps.com/start',
            },
            actor_user_id='u-1',
        )
        connection = IdentityCredentials(access_token='iam-ic-token')
        result = await plugin.materialize(
            ctx,
            {},
            connection,
            db=_FakeDB(),
            identity_options={'default_role_name': '${team_slug}'},
        )
        # ${team_slug} expanded to 'platform'.
        self.assertEqual(
            captured[0],
            {'account_id': '333333333333', 'role_name': 'platform'},
        )
        self.assertEqual(result.extra['aws_access_key_id'], 'AKIA')

    @respx.mock
    async def test_falls_back_to_identity_options_role(self) -> None:
        captured: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(dict(request.url.params))
            return httpx.Response(
                200,
                json={
                    'roleCredentials': {
                        'accessKeyId': 'AKIA',
                        'secretAccessKey': 'sec',
                        'sessionToken': 'tok',
                        'expiration': 1700000000000,
                    }
                },
            )

        respx.get(
            'https://portal.sso.us-east-1.amazonaws.com/federation/credentials'
        ).mock(side_effect=handler)

        class _FakeDB:
            async def execute(
                self,
                _query: str,
                _params: dict[str, object],
                _columns: list[str],
            ) -> list[dict[str, object]]:
                # AwsAccount with no default_role_name — forces fallback
                # to the identity plugin's default.
                return [
                    {
                        'account_id': '"222222222222"',
                        'role_name': None,
                        'region': None,
                    }
                ]

        plugin = AwsIamIcPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='org',
            environment='staging',
            assignment_options={
                'region': 'us-east-1',
                'start_url': 'https://example.awsapps.com/start',
            },
            actor_user_id='u-1',
        )
        connection = IdentityCredentials(access_token='iam-ic-token')
        result = await plugin.materialize(
            ctx,
            {},
            connection,
            db=_FakeDB(),
            identity_options={'default_role_name': 'ImbiOperator'},
        )
        self.assertEqual(
            captured[0],
            {'account_id': '222222222222', 'role_name': 'ImbiOperator'},
        )
        self.assertEqual(result.extra['aws_account_id'], '222222222222')


class RefreshTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_happy_path(self) -> None:
        respx.post('https://oidc.us-east-1.amazonaws.com/token').mock(
            return_value=httpx.Response(
                200,
                json={
                    'accessToken': 'new-token',
                    'tokenType': 'Bearer',
                    'expiresIn': 3600,
                    'refreshToken': 'rt-2',
                },
            )
        )
        plugin = AwsIamIcPlugin()
        result = await plugin.refresh(
            _ctx(),
            {'client_id': 'cid', 'client_secret': 'sec'},
            'rt-1',
        )
        self.assertEqual(result.access_token, 'new-token')
        self.assertEqual(result.refresh_token, 'rt-2')

    @respx.mock
    async def test_no_rotation_keeps_original_refresh(self) -> None:
        respx.post('https://oidc.us-east-1.amazonaws.com/token').mock(
            return_value=httpx.Response(
                200,
                json={
                    'accessToken': 'new-token',
                    'tokenType': 'Bearer',
                    'expiresIn': 3600,
                },
            )
        )
        plugin = AwsIamIcPlugin()
        result = await plugin.refresh(
            _ctx(),
            {'client_id': 'cid', 'client_secret': 'sec'},
            'keep-this',
        )
        self.assertEqual(result.refresh_token, 'keep-this')
