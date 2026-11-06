"""Tests for the ``aws_sts`` identity source (WIF plan 4.2).

AssumeRole is a mock session and GetWebIdentityToken is an httpx mock
transport: no AWS call leaves the test.
"""

import contextlib
import functools
import typing
import unittest
import urllib.parse
from collections import abc
from unittest import mock

import httpx
from botocore import (  # pyright: ignore[reportMissingTypeStubs]
    exceptions as botocore_exceptions,
)

from imbi.common.plugins import identity, secrets
from imbi.plugins.aws import plugin, secrets_manager, web_identity

ROLE = 'arn:aws:iam::123456789012:role/imbi-identity'
CONFIG = {'region': 'us-east-1', 'role_arn': ROLE}
NS = 'https://sts.amazonaws.com/doc/2011-06-15/'
OK = (
    f'<GetWebIdentityTokenResponse xmlns="{NS}"><GetWebIdentityTokenResult>'
    '<WebIdentityToken>eyJ.jwt.sig</WebIdentityToken>'
    '<Expiration>2026-11-06T00:05:00Z</Expiration>'
    '</GetWebIdentityTokenResult></GetWebIdentityTokenResponse>'
)


def _fault(code: str) -> str:
    return (
        f'<ErrorResponse xmlns="{NS}"><Error><Type>Sender</Type>'
        f'<Code>{code}</Code><Message>raw provider text</Message>'
        '</Error></ErrorResponse>'
    )


def _request(seconds: int = 300) -> identity.IdentityRequest:
    return identity.IdentityRequest(
        organization_id='org',
        audience='https://api.anthropic.com',
        tags={'imbi_org': 'org', 'imbi_agent': 'agent-1'},
        duration_seconds=seconds,
    )


async def _assume_role(**kwargs: typing.Any) -> dict[str, typing.Any]:
    """A role whose trust policy requires the ExternalId."""
    if kwargs['ExternalId'].startswith('imbi:probe-'):
        raise botocore_exceptions.ClientError(
            {'Error': {'Code': 'AccessDenied'}}, 'AssumeRole'
        )
    return {
        'Credentials': {
            'AccessKeyId': 'AKIA',
            'SecretAccessKey': 'secret',
            'SessionToken': 'token',
        }
    }


class AwsStsIdentityTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.source = web_identity.AwsStsIdentity()
        self.sts = mock.AsyncMock()
        self.sts.assume_role.side_effect = _assume_role

        @contextlib.asynccontextmanager
        async def client(
            service: str, **_: typing.Any
        ) -> abc.AsyncGenerator[mock.AsyncMock]:
            yield self.sts

        session = mock.Mock(return_value=mock.Mock(client=client))
        self.requests: list[httpx.Request] = []
        self.reply = httpx.Response(200, text=OK)
        for patcher in (
            mock.patch.object(secrets_manager.aioboto3, 'Session', session),
            mock.patch.object(
                web_identity.httpx,
                'AsyncClient',
                functools.partial(
                    httpx.AsyncClient,
                    transport=httpx.MockTransport(self._handle),
                ),
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.reply

    async def _reason(self) -> identity.IdentityError:
        with self.assertRaises(identity.IdentityError) as ctx:
            await self.source.identity_token(CONFIG, _request())
        self.assertNotIn('raw provider text', str(ctx.exception))
        return ctx.exception

    async def test_signed_request_with_core_claims(self) -> None:
        token = await self.source.identity_token(CONFIG, _request())
        self.assertEqual(token, 'eyJ.jwt.sig')
        assumed = self.sts.assume_role.call_args.kwargs
        self.assertEqual(assumed['ExternalId'], 'imbi:org')
        self.assertEqual(assumed['RoleSessionName'], 'imbi-workload-identity')
        self.assertEqual(assumed['DurationSeconds'], 900)
        request = self.requests[0]
        self.assertEqual(
            str(request.url), 'https://sts.us-east-1.amazonaws.com/'
        )
        self.assertEqual(
            dict(urllib.parse.parse_qsl(request.content.decode())),
            {
                'Action': 'GetWebIdentityToken',
                'Version': '2011-06-15',
                'Audience.member.1': 'https://api.anthropic.com',
                'SigningAlgorithm': 'RS256',
                'DurationSeconds': '300',
                'Tags.member.1.Key': 'imbi_agent',
                'Tags.member.1.Value': 'agent-1',
                'Tags.member.2.Key': 'imbi_org',
                'Tags.member.2.Value': 'org',
            },
        )
        self.assertIn(
            '/us-east-1/sts/aws4_request',
            request.headers['Authorization'],
        )
        self.assertEqual(request.headers['X-Amz-Security-Token'], 'token')

    async def test_session_outlives_the_jwt(self) -> None:
        await self.source.identity_token(CONFIG, _request(3600))
        self.assertEqual(
            self.sts.assume_role.call_args.kwargs['DurationSeconds'], 3900
        )

    async def test_sts_errors_are_reason_codes(self) -> None:
        for status, code, reason, retryable in (
            (
                403,
                'SessionDurationEscalation',
                'session_duration_escalation',
                False,
            ),
            (
                403,
                'OutboundWebIdentityFederationDisabled',
                'federation_disabled',
                False,
            ),
            (400, 'Throttling', 'throttled', True),
            (503, 'InternalFailure', 'unavailable', True),
            (400, 'SomethingNew', 'provider_error', False),
        ):
            with self.subTest(code=code):
                self.reply = httpx.Response(status, text=_fault(code))
                error = await self._reason()
                self.assertEqual(error.reason, reason)
                self.assertEqual(error.retryable, retryable)
        self.reply = httpx.Response(200, text='not xml')
        self.assertEqual((await self._reason()).reason, 'unreachable')

    async def test_assume_role_refused(self) -> None:
        self.sts.assume_role.side_effect = botocore_exceptions.ClientError(
            {
                'Error': {
                    'Code': 'AccessDenied',
                    'Message': 'raw provider text',
                }
            },
            'AssumeRole',
        )
        self.assertEqual((await self._reason()).reason, 'access_denied')
        self.assertEqual(self.requests, [])

    async def test_check_config_requires_the_external_id(self) -> None:
        await self.source.check_config(CONFIG, 'org')
        self.sts.assume_role.side_effect = None
        self.sts.assume_role.return_value = {'Credentials': {}}
        with self.assertRaises(secrets.InvalidConfiguration) as ctx:
            await self.source.check_config(CONFIG, 'org')
        self.assertEqual(
            ctx.exception.code, 'role_does_not_require_external_id'
        )

    def test_validate_config_refuses_keys(self) -> None:
        self.assertEqual(self.source.validate_config(CONFIG), CONFIG)
        with self.assertRaises(secrets.InvalidConfiguration):
            self.source.validate_config(
                CONFIG | {'aws_secret_access_key': 'x'}
            )

    def test_endpoint(self) -> None:
        self.assertEqual(
            web_identity._endpoint('cn-north-1'),  # pyright: ignore[reportPrivateUsage]
            'https://sts.cn-north-1.amazonaws.com.cn/',
        )
        with mock.patch.dict(
            'os.environ', {'IMBI_SECRETS_AWS_ENDPOINT_URL': 'http://ls:4566'}
        ):
            self.assertEqual(
                web_identity._endpoint('us-east-1'),  # pyright: ignore[reportPrivateUsage]
                'http://ls:4566',
            )

    def test_manifest_declares_the_source(self) -> None:
        manifest = plugin.AWSPlugin.manifest
        self.assertIn(web_identity.AwsStsIdentity, manifest.identity_sources)
