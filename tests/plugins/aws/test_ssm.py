"""Tests for the aws-ssm ConfigurationPlugin."""

import json
import typing
import unittest

import httpx
import respx
from imbi_common.plugins.base import (
    ConfigKeyWithValue,
    ConfigurationPlugin,
    ConfigValue,
    PluginContext,
)
from imbi_common.plugins.errors import (
    PluginCredentialsMissing,
    PluginUnavailableError,
)

from imbi_plugin_aws.ssm import SsmPlugin

_SSM_URL = 'https://ssm.us-east-1.amazonaws.com/'


def _ctx(
    *,
    path_prefix: str = '/imbi/${environment}/${project_slug}/',
    environment: str | None = 'prod',
    region: str = 'us-east-1',
    extras: dict[str, object] | None = None,
) -> PluginContext:
    options: dict[str, object] = {
        'region': region,
        'path_prefix': path_prefix,
    }
    if extras:
        options.update(extras)
    return PluginContext(
        project_id='proj-1',
        project_slug='widget',
        org_slug='acme',
        environment=environment,
        assignment_options=options,
    )


def _creds() -> dict[str, str]:
    return {
        'aws_access_key_id': 'AKID',
        'aws_secret_access_key': 'sec',
    }


def _identity_creds() -> dict[str, str]:
    return {
        'aws_access_key_id': 'AKIASTS',
        'aws_secret_access_key': 'stssec',
        'aws_session_token': 'session',
        'aws_region': 'us-east-1',
    }


class ManifestTestCase(unittest.TestCase):
    def test_basics(self) -> None:
        plugin = SsmPlugin()
        self.assertIsInstance(plugin, ConfigurationPlugin)
        self.assertEqual(plugin.manifest.slug, 'aws-ssm')
        self.assertEqual(plugin.manifest.plugin_type, 'configuration')
        names = {dt.name for dt in plugin.manifest.data_types}
        self.assertEqual(names, {'string', 'string_list', 'secret'})


class PrefixValidationTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_missing_prefix_raises(self) -> None:
        plugin = SsmPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='s',
            org_slug='o',
            environment='prod',
            assignment_options={'region': 'us-east-1'},
        )
        with self.assertRaises(ValueError):
            await plugin.list_keys(ctx, _creds())

    async def test_root_prefix_rejected(self) -> None:
        plugin = SsmPlugin()
        with self.assertRaises(ValueError):
            await plugin.list_keys(_ctx(path_prefix='/'), _creds())

    async def test_relative_prefix_rejected(self) -> None:
        plugin = SsmPlugin()
        with self.assertRaises(ValueError):
            await plugin.list_keys(_ctx(path_prefix='imbi/'), _creds())


class CredentialsTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_missing_credentials_raises(self) -> None:
        plugin = SsmPlugin()
        with self.assertRaises(PluginCredentialsMissing):
            await plugin.list_keys(_ctx(), {})

    @respx.mock
    async def test_identity_extras_accepted(self) -> None:
        respx.post(_SSM_URL).mock(
            return_value=httpx.Response(200, json={'Parameters': []})
        )
        plugin = SsmPlugin()
        keys = await plugin.list_keys(_ctx(), _identity_creds())
        self.assertEqual(keys, [])


class ListKeysTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_paginates_describe_parameters(self) -> None:
        page1 = {
            'Parameters': [
                {
                    'Name': '/imbi/prod/widget/db/url',
                    'Type': 'String',
                    'LastModifiedDate': 1700000000.5,
                }
            ],
            'NextToken': 'next',
        }
        page2 = {
            'Parameters': [
                {
                    'Name': '/imbi/prod/widget/db/password',
                    'Type': 'SecureString',
                    'LastModifiedDate': 1700000100.5,
                }
            ]
        }
        responses = iter([page1, page2])

        def page_handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(200, json=next(responses))

        respx.post(_SSM_URL).mock(side_effect=page_handler)
        plugin = SsmPlugin()
        keys = await plugin.list_keys(_ctx(), _creds())
        self.assertEqual(
            sorted(k.key for k in keys),
            ['db/password', 'db/url'],
        )
        password = next(k for k in keys if k.key == 'db/password')
        self.assertTrue(password.secret)
        self.assertEqual(password.data_type, 'secret')
        url = next(k for k in keys if k.key == 'db/url')
        self.assertFalse(url.secret)
        self.assertIsNotNone(url.last_modified)


class GetValuesTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_subset_uses_get_parameters(self) -> None:
        captured: list[dict[str, typing.Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    'Parameters': [
                        {
                            'Name': '/imbi/prod/widget/db/url',
                            'Type': 'String',
                            'Value': 'postgres://...',
                            'LastModifiedDate': 1700000000.0,
                        }
                    ],
                    'InvalidParameters': ['/imbi/prod/widget/missing'],
                },
            )

        respx.post(_SSM_URL).mock(side_effect=handler)
        plugin = SsmPlugin()
        values = await plugin.get_values(
            _ctx(), _creds(), keys=['db/url', 'missing']
        )
        self.assertEqual(len(values), 1)
        self.assertIsInstance(values[0], ConfigKeyWithValue)
        self.assertEqual(values[0].key, 'db/url')
        self.assertEqual(values[0].value, 'postgres://...')
        self.assertEqual(captured[0]['WithDecryption'], True)
        self.assertEqual(
            sorted(captured[0]['Names']),
            ['/imbi/prod/widget/db/url', '/imbi/prod/widget/missing'],
        )

    @respx.mock
    async def test_missing_names_swallowed(self) -> None:
        respx.post(_SSM_URL).mock(
            return_value=httpx.Response(
                400,
                json={
                    '__type': 'ParameterNotFound',
                    'message': 'gone',
                },
            )
        )
        plugin = SsmPlugin()
        values = await plugin.get_values(_ctx(), _creds(), keys=['nope'])
        self.assertEqual(values, [])

    @respx.mock
    async def test_all_uses_get_parameters_by_path(self) -> None:
        captured: list[dict[str, typing.Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    'Parameters': [
                        {
                            'Name': '/imbi/prod/widget/featureA',
                            'Type': 'StringList',
                            'Value': 'a,b,c',
                            'LastModifiedDate': 1700000000.0,
                        }
                    ]
                },
            )

        respx.post(_SSM_URL).mock(side_effect=handler)
        plugin = SsmPlugin()
        values = await plugin.get_values(_ctx(), _creds())
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0].data_type, 'string_list')
        self.assertEqual(values[0].value, 'a,b,c')
        self.assertEqual(captured[0]['Path'], '/imbi/prod/widget/')


class SetValueTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_writes_then_reads_back(self) -> None:
        captured: list[dict[str, typing.Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            target = request.headers['x-amz-target']
            payload = json.loads(request.content)
            captured.append({'target': target, 'payload': payload})
            if target.endswith('PutParameter'):
                return httpx.Response(200, json={'Version': 1})
            if target.endswith('GetParameter'):
                return httpx.Response(
                    200,
                    json={
                        'Parameter': {
                            'Name': payload['Name'],
                            'Type': 'SecureString',
                            'Value': 'shh',
                            'LastModifiedDate': 1700000123.0,
                        }
                    },
                )
            return httpx.Response(500, text='unexpected')

        respx.post(_SSM_URL).mock(side_effect=handler)
        plugin = SsmPlugin()
        result = await plugin.set_value(
            _ctx(extras={'kms_key_id': 'alias/imbi'}),
            _creds(),
            'db/password',
            ConfigValue(data_type='secret', value='shh', secret=True),
        )
        self.assertTrue(result.secret)
        self.assertEqual(result.key, 'db/password')
        self.assertEqual(result.data_type, 'secret')
        put = next(c for c in captured if c['target'].endswith('PutParameter'))
        payload = put['payload']
        self.assertEqual(payload['Type'], 'SecureString')
        self.assertEqual(payload['Overwrite'], True)
        self.assertEqual(payload['KeyId'], 'alias/imbi')
        self.assertEqual(payload['Name'], '/imbi/prod/widget/db/password')

    async def test_relative_keys_only(self) -> None:
        plugin = SsmPlugin()
        with self.assertRaises(ValueError):
            await plugin.set_value(
                _ctx(),
                _creds(),
                '/abs/key',
                ConfigValue(data_type='string', value='x'),
            )

    async def test_unknown_data_type_raises(self) -> None:
        plugin = SsmPlugin()
        with self.assertRaises(ValueError):
            await plugin.set_value(
                _ctx(),
                _creds(),
                'k',
                ConfigValue(data_type='magic', value='x'),
            )


class DeleteKeyTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_idempotent_on_missing(self) -> None:
        respx.post(_SSM_URL).mock(
            return_value=httpx.Response(
                400,
                json={
                    '__type': 'ParameterNotFound',
                    'message': 'gone',
                },
            )
        )
        plugin = SsmPlugin()
        await plugin.delete_key(_ctx(), _creds(), 'k')

    @respx.mock
    async def test_propagates_other_validation_errors(self) -> None:
        respx.post(_SSM_URL).mock(
            return_value=httpx.Response(
                400,
                json={
                    '__type': 'ValidationException',
                    'message': 'bad name',
                },
            )
        )
        plugin = SsmPlugin()
        with self.assertRaises(ValueError):
            await plugin.delete_key(_ctx(), _creds(), 'k')

    @respx.mock
    async def test_throttling_maps_to_unavailable(self) -> None:
        respx.post(_SSM_URL).mock(
            return_value=httpx.Response(
                400,
                json={
                    '__type': 'ThrottlingException',
                    'message': 'slow down',
                },
            )
        )
        plugin = SsmPlugin()
        with self.assertRaises(PluginUnavailableError):
            await plugin.delete_key(_ctx(), _creds(), 'k')
