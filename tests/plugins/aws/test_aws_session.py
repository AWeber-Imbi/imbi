"""Tests for the shared aws_session helper."""

import datetime
import unittest

import httpx
import respx
from imbi_common.plugins.errors import (
    PluginCredentialsMissing,
    PluginTimeoutError,
    PluginUnavailableError,
)

from imbi_plugin_aws import aws_session


class ResolveCredentialsTestCase(unittest.TestCase):
    def test_static_keys_with_explicit_region(self) -> None:
        creds = aws_session.resolve_credentials(
            {
                'aws_access_key_id': 'AKIA',
                'aws_secret_access_key': 'secret',
            },
            region='us-east-1',
        )
        self.assertEqual(creds.access_key_id, 'AKIA')
        self.assertEqual(creds.secret_access_key, 'secret')
        self.assertEqual(creds.region, 'us-east-1')
        self.assertIsNone(creds.session_token)

    def test_identity_extras_provide_region_and_session(self) -> None:
        creds = aws_session.resolve_credentials(
            {
                'aws_access_key_id': 'AKIA',
                'aws_secret_access_key': 'secret',
                'aws_session_token': 'tok',
                'aws_region': 'us-west-2',
            }
        )
        self.assertEqual(creds.region, 'us-west-2')
        self.assertEqual(creds.session_token, 'tok')

    def test_explicit_region_overrides_extras(self) -> None:
        creds = aws_session.resolve_credentials(
            {
                'aws_access_key_id': 'AKIA',
                'aws_secret_access_key': 'secret',
                'aws_region': 'us-east-1',
            },
            region='eu-west-1',
        )
        self.assertEqual(creds.region, 'eu-west-1')

    def test_missing_both_keys_raises(self) -> None:
        with self.assertRaises(PluginCredentialsMissing):
            aws_session.resolve_credentials({}, region='us-east-1')

    def test_missing_one_key_raises(self) -> None:
        with self.assertRaises(PluginCredentialsMissing):
            aws_session.resolve_credentials(
                {'aws_access_key_id': 'AKIA'}, region='us-east-1'
            )

    def test_missing_region_raises(self) -> None:
        with self.assertRaises(PluginCredentialsMissing):
            aws_session.resolve_credentials(
                {
                    'aws_access_key_id': 'AKIA',
                    'aws_secret_access_key': 'secret',
                }
            )

    def test_identity_extra_supplies_keys_when_credentials_empty(
        self,
    ) -> None:
        from imbi_common.plugins.base import (
            IdentityCredentials,
            PluginContext,
        )

        ctx = PluginContext(
            project_id='p',
            project_slug='s',
            org_slug='o',
            environment='prod',
            assignment_options={},
            identity=IdentityCredentials(
                access_token='oidc',
                extra={
                    'aws_access_key_id': 'STS',
                    'aws_secret_access_key': 'sts-secret',
                    'aws_session_token': 'sts-token',
                    'aws_region': 'us-east-2',
                },
            ),
        )
        creds = aws_session.resolve_credentials({}, ctx=ctx)
        self.assertEqual(creds.access_key_id, 'STS')
        self.assertEqual(creds.secret_access_key, 'sts-secret')
        self.assertEqual(creds.session_token, 'sts-token')
        self.assertEqual(creds.region, 'us-east-2')

    def test_identity_extra_overrides_static_keys(self) -> None:
        from imbi_common.plugins.base import (
            IdentityCredentials,
            PluginContext,
        )

        ctx = PluginContext(
            project_id='p',
            project_slug='s',
            org_slug='o',
            environment='prod',
            assignment_options={},
            identity=IdentityCredentials(
                access_token='oidc',
                extra={
                    'aws_access_key_id': 'STS',
                    'aws_secret_access_key': 'sts-secret',
                    'aws_region': 'us-east-2',
                },
            ),
        )
        creds = aws_session.resolve_credentials(
            {
                'aws_access_key_id': 'STATIC',
                'aws_secret_access_key': 'static-secret',
            },
            region='eu-west-1',
            ctx=ctx,
        )
        # STS takes precedence over static; assignment region wins.
        self.assertEqual(creds.access_key_id, 'STS')
        self.assertEqual(creds.region, 'eu-west-1')


class SignRequestTestCase(unittest.TestCase):
    def test_authorization_header_is_deterministic(self) -> None:
        creds = aws_session.AwsCredentials(
            access_key_id='AKIDEXAMPLE',
            secret_access_key='wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY',
            session_token=None,
            region='us-east-1',
        )
        now = datetime.datetime(2024, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)
        headers = aws_session.sign_request(
            method='POST',
            url='https://ssm.us-east-1.amazonaws.com/',
            headers={
                'Content-Type': 'application/x-amz-json-1.1',
                'X-Amz-Target': 'AmazonSSM.DescribeParameters',
            },
            body=b'{}',
            service='ssm',
            credentials=creds,
            now=now,
        )
        self.assertIn('Authorization', headers)
        self.assertTrue(
            headers['Authorization'].startswith('AWS4-HMAC-SHA256 ')
        )
        self.assertIn(
            'Credential=AKIDEXAMPLE/20240102/us-east-1/ssm/aws4_request',
            headers['Authorization'],
        )
        self.assertEqual(headers['x-amz-date'], '20240102T030405Z')
        self.assertEqual(headers['host'], 'ssm.us-east-1.amazonaws.com')
        self.assertNotIn('x-amz-security-token', headers)

    def test_session_token_included_when_present(self) -> None:
        creds = aws_session.AwsCredentials(
            access_key_id='AKID',
            secret_access_key='secret',
            session_token='session-token',
            region='us-east-1',
        )
        headers = aws_session.sign_request(
            method='POST',
            url='https://logs.us-east-1.amazonaws.com/',
            headers={'Content-Type': 'application/x-amz-json-1.1'},
            body=b'{}',
            service='logs',
            credentials=creds,
            now=datetime.datetime(2024, 6, 1, 12, 0, 0, tzinfo=datetime.UTC),
        )
        self.assertEqual(headers['x-amz-security-token'], 'session-token')
        self.assertIn('x-amz-security-token', headers['Authorization'])


class CallAwsJsonTestCase(unittest.IsolatedAsyncioTestCase):
    def _creds(self) -> aws_session.AwsCredentials:
        return aws_session.AwsCredentials(
            access_key_id='AKID',
            secret_access_key='secret',
            session_token=None,
            region='us-east-1',
        )

    @respx.mock
    async def test_returns_decoded_json_on_200(self) -> None:
        route = respx.post('https://ssm.us-east-1.amazonaws.com/').mock(
            return_value=httpx.Response(200, json={'ok': True})
        )
        result = await aws_session.call_aws_json(
            service='ssm',
            action='DescribeParameters',
            body={'foo': 'bar'},
            credentials=self._creds(),
            error_map={},
        )
        self.assertEqual(result, {'ok': True})
        self.assertTrue(route.called)
        request = route.calls.last.request
        self.assertEqual(
            request.headers['x-amz-target'], 'AmazonSSM.DescribeParameters'
        )

    @respx.mock
    async def test_400_with_known_code_raises_mapped_error(self) -> None:
        respx.post('https://ssm.us-east-1.amazonaws.com/').mock(
            return_value=httpx.Response(
                400,
                json={
                    '__type': 'com.amazonaws.ssm#ParameterAlreadyExists',
                    'message': 'already',
                },
            )
        )
        with self.assertRaises(ValueError):
            await aws_session.call_aws_json(
                service='ssm',
                action='PutParameter',
                body={},
                credentials=self._creds(),
                error_map={'ParameterAlreadyExists': ValueError},
            )

    @respx.mock
    async def test_500_falls_back_to_unavailable(self) -> None:
        respx.post('https://logs.us-east-1.amazonaws.com/').mock(
            return_value=httpx.Response(503, text='boom')
        )
        with self.assertRaises(PluginUnavailableError):
            await aws_session.call_aws_json(
                service='logs',
                action='StartQuery',
                body={},
                credentials=aws_session.AwsCredentials(
                    'AKID', 'sec', None, 'us-east-1'
                ),
                error_map={},
            )

    @respx.mock
    async def test_timeout_maps_to_plugin_timeout(self) -> None:
        respx.post('https://ssm.us-east-1.amazonaws.com/').mock(
            side_effect=httpx.ReadTimeout('slow')
        )
        with self.assertRaises(PluginTimeoutError):
            await aws_session.call_aws_json(
                service='ssm',
                action='DescribeParameters',
                body={},
                credentials=self._creds(),
                error_map={},
            )
