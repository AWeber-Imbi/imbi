"""Tests for the secret provider plugins (ADR 0022, plan 9.7).

The AWS client is a mock: no AWS call leaves the test.
"""

import contextlib
import datetime
import typing
import unittest
import uuid
from collections import abc
from unittest import mock

from botocore import (  # pyright: ignore[reportMissingTypeStubs]
    exceptions as botocore_exceptions,
)

from imbi.api.secret_broker import providers

AWS = providers.PROVIDERS['aws_secrets_manager']
ROLE = 'arn:aws:iam::123456789012:role/imbi-secrets'
CONFIG = {'region': 'us-east-1', 'role_arn': ROLE}
CONTEXT = providers.ResolveContext(
    organization_id='org',
    task_id=uuid.uuid4(),
    project_id=None,
    purpose='github_write',
    ttl_seconds=300,
    credential_class='static',
)


class FakeSession:
    """Stands in for ``aioboto3.Session``; records each session."""

    def __init__(self, clients: dict[str, mock.AsyncMock]) -> None:
        self.clients = clients
        self.sessions: list[dict[str, typing.Any]] = []
        self.endpoints: list[str | None] = []

    def __call__(self, **kwargs: typing.Any) -> FakeSession:
        self.sessions.append(kwargs)
        return self

    @contextlib.asynccontextmanager
    async def client(
        self, service: str, **kwargs: typing.Any
    ) -> abc.AsyncGenerator[mock.AsyncMock]:
        self.endpoints.append(kwargs.get('endpoint_url'))
        yield self.clients[service]


def _client_error(code: str) -> botocore_exceptions.ClientError:
    return botocore_exceptions.ClientError(
        {'Error': {'Code': code, 'Message': 'raw provider text'}},
        'GetSecretValue',
    )


class AwsSecretsManagerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sm = mock.AsyncMock()
        self.sts = mock.AsyncMock()
        self.session = FakeSession(
            {'secretsmanager': self.sm, 'sts': self.sts}
        )
        self.sts.assume_role.return_value = {
            'Credentials': {
                'AccessKeyId': 'AKIA',
                'SecretAccessKey': 'secret',
                'SessionToken': 'token',
            }
        }
        patcher = mock.patch.object(
            providers.aioboto3, 'Session', self.session
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _resolve(
        self,
        locator: dict[str, typing.Any] | None = None,
        field: str | None = None,
        config: dict[str, typing.Any] | None = None,
    ) -> providers.Material:
        return await AWS.resolve(
            config or CONFIG,
            locator or {'secret_id': 'prod/github'},
            field,
            CONTEXT,
        )

    async def test_text_with_default_stage(self) -> None:
        self.sm.get_secret_value.return_value = {
            'SecretString': 'token-value',
            'VersionId': 'v1',
        }
        material = await self._resolve()
        self.assertEqual(material.value, b'token-value')
        self.assertFalse(material.binary)
        self.assertEqual(material.provider_version, 'v1')
        self.assertIsNone(material.lease_id)
        self.sm.get_secret_value.assert_awaited_once_with(
            SecretId='prod/github', VersionStage='AWSCURRENT'
        )

    async def test_version_stage_and_id(self) -> None:
        self.sm.get_secret_value.return_value = {'SecretString': 'x'}
        await self._resolve({'secret_id': 's', 'version_stage': 'AWSPREVIOUS'})
        self.sm.get_secret_value.assert_awaited_with(
            SecretId='s', VersionStage='AWSPREVIOUS'
        )
        version_id = uuid.uuid4().hex
        await self._resolve({'secret_id': 's', 'version_id': version_id})
        self.sm.get_secret_value.assert_awaited_with(
            SecretId='s', VersionId=version_id
        )

    async def test_binary(self) -> None:
        self.sm.get_secret_value.return_value = {'SecretBinary': b'\x00\x01'}
        material = await self._resolve()
        self.assertEqual(material.value, b'\x00\x01')
        self.assertTrue(material.binary)
        with self.assertRaises(providers.BrokerError) as ctx:
            await self._resolve(field='token')
        self.assertEqual(ctx.exception.reason, 'not_a_json_object')

    async def test_structured_field(self) -> None:
        self.sm.get_secret_value.return_value = {
            'SecretString': '{"token": "abc", "count": 3}'
        }
        material = await self._resolve(field='token')
        self.assertEqual(material.value, b'abc')
        for field, reason in (
            ('missing', 'field_missing'),
            ('count', 'field_missing'),
        ):
            with self.subTest(field=field):
                with self.assertRaises(providers.BrokerError) as ctx:
                    await self._resolve(field=field)
                self.assertEqual(ctx.exception.reason, reason)
        for text in ('not json', '["a"]'):
            with self.subTest(text=text):
                self.sm.get_secret_value.return_value = {'SecretString': text}
                with self.assertRaises(providers.BrokerError) as ctx:
                    await self._resolve(field='token')
                self.assertEqual(ctx.exception.reason, 'not_a_json_object')
        # JSON is parsed only for a field: the whole text is returned.
        self.assertEqual((await self._resolve()).value, b'["a"]')

    async def test_errors_are_translated(self) -> None:
        for error, code, reason in (
            (
                _client_error('ResourceNotFoundException'),
                'secret_materialization_failed',
                'not_found',
            ),
            (
                _client_error('AccessDeniedException'),
                'secret_materialization_failed',
                'access_denied',
            ),
            (
                _client_error('SomethingNew'),
                'secret_materialization_failed',
                'provider_error',
            ),
            (
                _client_error('ThrottlingException'),
                'secret_provider_unavailable',
                'throttled',
            ),
            (
                botocore_exceptions.EndpointConnectionError(
                    endpoint_url='https://x'
                ),
                'secret_provider_unavailable',
                'unreachable',
            ),
        ):
            with self.subTest(reason=reason):
                self.sm.get_secret_value.side_effect = error
                with (
                    self.assertLogs(providers.LOGGER) as logs,
                    self.assertRaises(providers.BrokerError) as ctx,
                ):
                    await self._resolve()
                self.assertEqual(
                    (ctx.exception.code, ctx.exception.reason),
                    (code, reason),
                )
                self.assertIsNone(ctx.exception.__cause__)
                self.assertNotIn('raw provider text', str(ctx.exception))
                self.assertNotIn('raw provider text', '\n'.join(logs.output))

    async def test_role_assumption_with_external_id(self) -> None:
        self.sm.get_secret_value.return_value = {'SecretString': 'x'}
        await self._resolve()
        self.sts.assume_role.assert_awaited_once()
        kwargs = self.sts.assume_role.call_args.kwargs
        self.assertEqual(kwargs['RoleArn'], ROLE)
        self.assertEqual(kwargs['ExternalId'], 'imbi:org')
        self.assertEqual(providers.external_id('org'), 'imbi:org')
        self.assertEqual(
            self.session.sessions[0], {'region_name': 'us-east-1'}
        )
        self.assertEqual(
            self.session.sessions[1]['aws_session_token'], 'token'
        )

    async def test_health(self) -> None:
        self.sts.get_caller_identity.return_value = {
            'Account': '123456789012',
            'Arn': 'arn:aws:sts::123456789012:assumed-role/imbi/x',
        }
        health = await AWS.health(
            CONFIG | {'account_id': '123456789012'}, 'org'
        )
        self.assertEqual(health.status, 'healthy')
        self.assertEqual(health.identity['account_id'], '123456789012')
        self.assertEqual(
            self.sts.assume_role.call_args.kwargs['ExternalId'], 'imbi:org'
        )
        health = await AWS.health(
            CONFIG | {'account_id': '999999999999'}, 'org'
        )
        self.assertEqual(
            (health.status, health.reason), ('unhealthy', 'account_mismatch')
        )

    async def test_validate_binding_returns_metadata_only(self) -> None:
        self.sm.describe_secret.return_value = {
            'Name': 'prod/github',
            'RotationEnabled': True,
            'LastRotatedDate': datetime.datetime(
                2026, 1, 1, tzinfo=datetime.UTC
            ),
            'VersionIdsToStages': {'v1': ['AWSCURRENT']},
        }
        metadata = await AWS.validate_binding(
            CONFIG, {'secret_id': 'prod/github'}, 'org'
        )
        self.assertEqual(metadata['name'], 'prod/github')
        self.assertTrue(metadata['rotation_enabled'])
        self.assertTrue(metadata['version_stage_present'])
        self.sm.get_secret_value.assert_not_awaited()

    def test_config_refuses_access_keys(self) -> None:
        for config in (
            CONFIG | {'aws_access_key_id': 'AKIA'},
            CONFIG | {'secret_access_key': 'x'},
            {'region': 'Not a region'},
            CONFIG | {'role_arn': 'arn:aws:iam::1:user/x'},
            {'region': 'us-east-1'},
            CONFIG | {'endpoint_url': 'http://169.254.169.254/'},
            {},
        ):
            with self.subTest(config=config):
                with self.assertRaises(providers.InvalidConfiguration) as ctx:
                    AWS.validate_config(config)
                self.assertNotIn('AKIA', str(ctx.exception))
        self.assertEqual(
            AWS.validate_config(CONFIG | {'account_id': '123456789012'}),
            CONFIG | {'account_id': '123456789012'},
        )

    async def test_endpoint_is_an_operator_setting(self) -> None:
        self.sm.get_secret_value.return_value = {'SecretString': 'x'}
        await self._resolve()
        self.assertEqual(self.session.endpoints, [None, None])
        with mock.patch.dict(
            'os.environ',
            {'IMBI_SECRETS_AWS_ENDPOINT_URL': 'http://localstack:4566'},
        ):
            await self._resolve()
        self.assertEqual(
            self.session.endpoints[2:], ['http://localstack:4566'] * 2
        )

    def test_locator_rules(self) -> None:
        with self.assertRaises(providers.InvalidConfiguration):
            AWS.validate_locator(
                {
                    'secret_id': 's',
                    'version_stage': 'AWSCURRENT',
                    'version_id': uuid.uuid4().hex,
                },
                'static',
            )
        with self.assertRaises(providers.InvalidConfiguration):
            AWS.validate_locator({'secret_id': 's', 'arn': 'x'}, 'static')
        self.assertEqual(
            AWS.validate_locator({'secret_id': 's'}, 'rotated'),
            {'secret_id': 's'},
        )

    async def test_missing_capabilities(self) -> None:
        self.assertNotIn('dynamic_issuance', AWS.capabilities)
        with self.assertRaises(providers.BrokerError) as ctx:
            await AWS.renew(CONFIG, 'lease', 60)
        self.assertEqual(ctx.exception.code, 'provider_lease_not_renewable')
        with self.assertRaises(providers.BrokerError) as ctx:
            providers.get('vault')
        self.assertEqual(ctx.exception.code, 'operation_not_supported')

    def test_error_codes(self) -> None:
        self.assertEqual(len(providers.ERROR_STATUS), 18)
        self.assertTrue(
            providers.BrokerError('secret_provider_unavailable').retryable
        )
        with self.assertRaises(ValueError):
            providers.BrokerError('not_a_code')
