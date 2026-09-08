"""Tests for the Iggy connectors configuration endpoints.

The shape these serve is a contract with a Rust deserializer that has no
field defaults, so the assertions here compare whole documents rather
than sampling keys: a dropped null is a runtime that refuses to start.
`ServedShapeMatchesStubTestCase` pins the same document against
`scripts/iggy_config_server.py`, the stand-in `compose.ci.yaml` serves,
so the two cannot drift apart.
"""

import importlib.util
import os
import pathlib
import types
import typing
import unittest
from unittest import mock

import httpx
from fastapi import testclient

from apps.api.tests import support
from imbi.api import settings
from imbi.api.endpoints import iggy_connectors
from imbi.common import iggy

CLICKHOUSE_URL = 'clickhouse+http://default:password@clickhouse:8123/imbi'
API_KEY = 'test-api-key'
OTHER_KEY = 'rotated-api-key'

TOPICS = {'events': ('gateway',)}

EXPECTED_SINK = {
    'key': 'events',
    'enabled': True,
    'version': 0,
    'name': 'ClickHouse sink: events',
    'path': '/opt/iggy/connectors/libiggy_connector_clickhouse_sink',
    'transforms': None,
    'streams': [
        {
            'stream': 'events',
            'topics': ['gateway'],
            'schema': 'json',
            'avro_schema_json': None,
            'avro_schema_path': None,
            'batch_length': 1000,
            'poll_interval': '250ms',
            'consumer_group': 'events',
        }
    ],
    'plugin_config_format': 'json',
    'plugin_config': {
        'url': 'http://clickhouse:8123',
        'database': 'imbi',
        'username': 'default',
        'password': 'password',
        'table': 'events',
        'insert_format': 'json_each_row',
        'timeout_seconds': 30,
        'max_retries': 3,
        'retry_delay': 1,
        'verbose_logging': False,
    },
    'verbose': False,
    'benchmark': False,
}


def load_stub() -> types.ModuleType:
    """Import `scripts/iggy_config_server.py` by path.

    It is a standalone script served from a bare python image, not part
    of any distribution, so there is no package to import it from.
    """
    path = pathlib.Path(__file__).parents[4] / 'scripts'
    spec = importlib.util.spec_from_file_location(
        'iggy_config_server', path / 'iggy_config_server.py'
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _EndpointTestCase(support.SharedAppTestCase):
    """Base that configures one api key and a known ClickHouse DSN."""

    env: typing.ClassVar[dict[str, str]] = {
        'CLICKHOUSE_URL': CLICKHOUSE_URL,
        'IMBI_IGGY_CONNECTORS_API_KEYS': API_KEY,
    }

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        settings.clear_caches()
        self.addCleanup(settings.clear_caches)
        self.prefix = (
            f'{settings.get_server_config().api_prefix}/iggy/connectors'
        )
        self.client = testclient.TestClient(self.test_app)
        self.addCleanup(self.client.close)
        self.headers = {'Authorization': f'Bearer {API_KEY}'}

    def get(self, path: str, **kwargs: object) -> httpx.Response:
        return self.client.get(f'{self.prefix}{path}', **kwargs)  # type: ignore[arg-type]


class ActiveConfigsTestCase(_EndpointTestCase):
    def test_shape_is_the_full_document(self) -> None:
        with mock.patch.object(iggy, 'TOPICS', TOPICS):
            response = self.get('/configs/active', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {'sinks': {'events': EXPECTED_SINK}, 'sources': {}},
        )

    def test_one_sink_per_stream(self) -> None:
        topics = {'events': ('gateway',), 'operations_log': ('api', 'ui')}
        with mock.patch.object(iggy, 'TOPICS', topics):
            response = self.get('/configs/active', headers=self.headers)
        sinks = response.json()['sinks']
        self.assertEqual(sorted(sinks), ['events', 'operations_log'])
        opslog = sinks['operations_log']
        self.assertEqual(opslog['key'], 'operations_log')
        self.assertEqual(opslog['plugin_config']['table'], 'operations_log')
        self.assertEqual(opslog['streams'][0]['topics'], ['api', 'ui'])
        self.assertEqual(
            opslog['streams'][0]['consumer_group'], 'operations_log'
        )

    def test_map_key_matches_the_key_field(self) -> None:
        with mock.patch.object(iggy, 'TOPICS', TOPICS):
            sinks = self.get('/configs/active', headers=self.headers).json()[
                'sinks'
            ]
        for key, sink in sinks.items():
            self.assertEqual(key, sink['key'])

    def test_nullable_fields_are_present_as_null(self) -> None:
        with mock.patch.object(iggy, 'TOPICS', TOPICS):
            sink = self.get('/configs/active', headers=self.headers).json()[
                'sinks'
            ]['events']
        self.assertIn('transforms', sink)
        self.assertIsNone(sink['transforms'])
        stream = sink['streams'][0]
        self.assertIn('avro_schema_json', stream)
        self.assertIsNone(stream['avro_schema_json'])
        self.assertIn('avro_schema_path', stream)
        self.assertIsNone(stream['avro_schema_path'])


class ActiveVersionsTestCase(_EndpointTestCase):
    def test_one_entry_per_sink(self) -> None:
        with mock.patch.object(iggy, 'TOPICS', TOPICS):
            response = self.get(
                '/configs/active/versions', headers=self.headers
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'sinks': {
                    'events': {
                        'version': 0,
                        'created_at': '1970-01-01T00:00:00Z',
                    }
                },
                'sources': {},
            },
        )


class SingleSinkTestCase(_EndpointTestCase):
    def test_configs_returns_an_array(self) -> None:
        with mock.patch.object(iggy, 'TOPICS', TOPICS):
            response = self.get('/sinks/events/configs', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [EXPECTED_SINK])

    def test_active_returns_one_config(self) -> None:
        with mock.patch.object(iggy, 'TOPICS', TOPICS):
            response = self.get(
                '/sinks/events/configs/active', headers=self.headers
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), EXPECTED_SINK)

    def test_version_zero_returns_one_config(self) -> None:
        with mock.patch.object(iggy, 'TOPICS', TOPICS):
            response = self.get(
                '/sinks/events/configs/0', headers=self.headers
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), EXPECTED_SINK)

    def test_unknown_sink_is_absent(self) -> None:
        with mock.patch.object(iggy, 'TOPICS', TOPICS):
            for path in (
                '/sinks/nope/configs',
                '/sinks/nope/configs/active',
                '/sinks/nope/configs/0',
            ):
                with self.subTest(path=path):
                    response = self.get(path, headers=self.headers)
                    self.assertEqual(response.status_code, 404)

    def test_unknown_version_is_absent(self) -> None:
        with mock.patch.object(iggy, 'TOPICS', TOPICS):
            response = self.get(
                '/sinks/events/configs/7', headers=self.headers
            )
        self.assertEqual(response.status_code, 404)


class AuthTestCase(_EndpointTestCase):
    def test_missing_header_is_rejected(self) -> None:
        self.assertEqual(self.get('/configs/active').status_code, 401)

    def test_wrong_key_is_rejected(self) -> None:
        response = self.get(
            '/configs/active', headers={'Authorization': 'Bearer wrong'}
        )
        self.assertEqual(response.status_code, 401)

    def test_wrong_scheme_is_rejected(self) -> None:
        response = self.get(
            '/configs/active', headers={'Authorization': f'Basic {API_KEY}'}
        )
        self.assertEqual(response.status_code, 401)

    def test_bearer_is_case_insensitive(self) -> None:
        response = self.get(
            '/configs/active', headers={'Authorization': f'bearer {API_KEY}'}
        )
        self.assertEqual(response.status_code, 200)

    def test_every_route_is_guarded(self) -> None:
        for path in (
            '/configs/active',
            '/configs/active/versions',
            '/sinks/events/configs',
            '/sinks/events/configs/active',
            '/sinks/events/configs/0',
        ):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status_code, 401)


class RotationTestCase(_EndpointTestCase):
    env: typing.ClassVar[dict[str, str]] = {
        'CLICKHOUSE_URL': CLICKHOUSE_URL,
        'IMBI_IGGY_CONNECTORS_API_KEYS': f'{API_KEY}, {OTHER_KEY}',
    }

    def test_both_keys_are_accepted(self) -> None:
        for key in (API_KEY, OTHER_KEY):
            with self.subTest(key=key):
                response = self.get(
                    '/configs/active',
                    headers={'Authorization': f'Bearer {key}'},
                )
                self.assertEqual(response.status_code, 200)


class UnconfiguredTestCase(_EndpointTestCase):
    env: typing.ClassVar[dict[str, str]] = {
        'CLICKHOUSE_URL': CLICKHOUSE_URL,
        'IMBI_IGGY_CONNECTORS_API_KEYS': '',
    }

    def setUp(self) -> None:
        super().setUp()
        iggy_connectors._warned_unconfigured = False
        self.addCleanup(
            setattr, iggy_connectors, '_warned_unconfigured', False
        )

    def test_serves_nothing_without_a_key(self) -> None:
        with self.assertLogs(iggy_connectors.LOGGER, 'ERROR') as logs:
            response = self.get('/configs/active', headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertIn('IMBI_IGGY_CONNECTORS_API_KEYS', logs.output[0])

    def test_the_warning_is_logged_once(self) -> None:
        with self.assertLogs(iggy_connectors.LOGGER, 'ERROR'):
            self.get('/configs/active')
        with self.assertNoLogs(iggy_connectors.LOGGER, 'ERROR'):
            self.assertEqual(self.get('/configs/active').status_code, 503)


class WriteRoutesTestCase(_EndpointTestCase):
    """Versions are code, so nothing here accepts a write.

    Only the GETs are registered, which is what makes Starlette answer
    405 for the create, activate and delete routes in the contract.
    """

    def test_writes_are_not_allowed(self) -> None:
        cases = (
            ('post', '/sinks/events/configs'),
            ('put', '/sinks/events/configs/active'),
            ('delete', '/sinks/events/configs'),
        )
        for method, path in cases:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(
                    f'{self.prefix}{path}', headers=self.headers
                )
                self.assertEqual(response.status_code, 405)


class OpenAPITestCase(_EndpointTestCase):
    def test_routes_are_not_published(self) -> None:
        paths = self.client.get('/openapi.json').json()['paths']
        self.assertFalse(
            [path for path in paths if 'iggy' in path],
            'the connector configuration must stay out of the schema',
        )


class ClickHouseUrlTestCase(unittest.TestCase):
    """The DSN is read exactly as `Clickhouse._connect` reads it."""

    def config(self, url: str) -> dict[str, object]:
        with mock.patch.dict(os.environ, {'CLICKHOUSE_URL': url}):
            return iggy_connectors.clickhouse_plugin_config('events')

    def test_full_dsn(self) -> None:
        config = self.config(CLICKHOUSE_URL)
        self.assertEqual(config['url'], 'http://clickhouse:8123')
        self.assertEqual(config['database'], 'imbi')
        self.assertEqual(config['username'], 'default')
        self.assertEqual(config['password'], 'password')

    def test_defaults_when_the_dsn_omits_them(self) -> None:
        # ClickHouseDsn defaults the port to 9000, so an unported DSN
        # points the sink where the direct client already points.
        config = self.config('clickhouse+http://clickhouse')
        self.assertEqual(config['url'], 'http://clickhouse:9000')
        self.assertEqual(config['database'], 'internal')
        self.assertEqual(config['username'], 'default')
        self.assertEqual(config['password'], '')

    def test_explicit_port(self) -> None:
        config = self.config('clickhouse+http://ch:9999/db')
        self.assertEqual(config['url'], 'http://ch:9999')
        self.assertEqual(config['database'], 'db')

    def test_secure_scheme_selects_https(self) -> None:
        config = self.config('clickhouses://user:pw@ch:8443/db')
        self.assertEqual(config['url'], 'https://ch:8443')

    def test_table_is_the_stream(self) -> None:
        with mock.patch.dict(os.environ, {'CLICKHOUSE_URL': CLICKHOUSE_URL}):
            config = iggy_connectors.clickhouse_plugin_config('operations_log')
        self.assertEqual(config['table'], 'operations_log')


class ServedShapeMatchesStubTestCase(_EndpointTestCase):
    """`compose.ci.yaml` serves the stub; the runtime must see one shape."""

    def test_stub_serves_what_the_endpoint_serves(self) -> None:
        with mock.patch.object(iggy, 'TOPICS', TOPICS):
            served = self.get('/configs/active', headers=self.headers).json()
        stub = load_stub()
        env = {
            'IGGY_TOPICS': ';'.join(
                f'{stream}={",".join(names)}'
                for stream, names in TOPICS.items()
            ),
            'CLICKHOUSE_URL': 'http://clickhouse:8123',
            'CLICKHOUSE_DATABASE': 'imbi',
            'CLICKHOUSE_USERNAME': 'default',
            'CLICKHOUSE_PASSWORD': 'password',
        }
        with mock.patch.dict(os.environ, env):
            self.assertEqual(stub.active_configs(), served)
