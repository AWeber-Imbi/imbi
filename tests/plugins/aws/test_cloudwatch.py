"""Tests for the aws-cloudwatch-logs LogsPlugin."""

import datetime
import json
import typing
import unittest
import unittest.mock

import httpx
import respx
from imbi_common.plugins.base import (
    LogFilter,
    LogQuery,
    LogsPlugin,
    PluginContext,
)
from imbi_common.plugins.errors import (
    CursorExpiredError,
    PluginCredentialsMissing,
    PluginTimeoutError,
    PluginUnavailableError,
)

from imbi_plugin_aws import cloudwatch as cw_module
from imbi_plugin_aws.cloudwatch import CloudWatchLogsPlugin
from imbi_plugin_aws.query import encode_cursor, query_fingerprint

_LOGS_URL = 'https://logs.us-east-1.amazonaws.com/'
_GLOB_PATTERN = '/aws/rds/${project_slug}-*/postgresql'


def _ctx(extras: dict[str, object] | None = None) -> PluginContext:
    options: dict[str, object] = {
        'region': 'us-east-1',
        'log_group_names': '/imbi/${environment}/${project_slug}',
        'poll_interval_ms': 0,
        'timeout_seconds': 5,
    }
    if extras:
        options.update(extras)
    return PluginContext(
        project_id='proj-1',
        project_slug='widget',
        org_slug='acme',
        environment='prod',
        assignment_options=options,
    )


def _creds() -> dict[str, str]:
    return {
        'aws_access_key_id': 'AKID',
        'aws_secret_access_key': 'sec',
    }


def _query(cursor: str | None = None, limit: int = 2) -> LogQuery:
    return LogQuery(
        start_time=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
        end_time=datetime.datetime(2024, 1, 2, tzinfo=datetime.UTC),
        filters=[LogFilter(field='level', op='eq', value='ERROR')],
        limit=limit,
        cursor=cursor,
    )


class ManifestTestCase(unittest.TestCase):
    def test_basics(self) -> None:
        plugin = CloudWatchLogsPlugin()
        self.assertIsInstance(plugin, LogsPlugin)
        self.assertEqual(plugin.manifest.slug, 'aws-cloudwatch-logs')
        self.assertEqual(plugin.manifest.plugin_type, 'logs')


class CredentialsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_missing_credentials_raises(self) -> None:
        plugin = CloudWatchLogsPlugin()
        with self.assertRaises(PluginCredentialsMissing):
            await plugin.search(_ctx(), {}, _query())

    async def test_missing_log_groups_raises(self) -> None:
        plugin = CloudWatchLogsPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='s',
            org_slug='o',
            environment='prod',
            assignment_options={'region': 'us-east-1'},
        )
        with self.assertRaises(ValueError):
            await plugin.search(ctx, _creds(), _query())


class SearchTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_happy_path(self) -> None:
        captured: list[dict[str, typing.Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            target = request.headers['x-amz-target']
            payload = json.loads(request.content)
            captured.append({'target': target, 'payload': payload})
            if target.endswith('StartQuery'):
                return httpx.Response(200, json={'queryId': 'q-1'})
            if target.endswith('GetQueryResults'):
                return httpx.Response(
                    200,
                    json={
                        'status': 'Complete',
                        'results': [
                            [
                                {
                                    'field': '@timestamp',
                                    'value': '2024-01-02 11:59:59.000',
                                },
                                {
                                    'field': '@message',
                                    'value': 'oops',
                                },
                                {
                                    'field': '@logStream',
                                    'value': 'stream-a',
                                },
                                {'field': 'level', 'value': 'ERROR'},
                            ],
                            [
                                {
                                    'field': '@timestamp',
                                    'value': '2024-01-02 11:30:00.000',
                                },
                                {
                                    'field': '@message',
                                    'value': 'oops 2',
                                },
                                {
                                    'field': '@logStream',
                                    'value': 'stream-b',
                                },
                                {'field': 'level', 'value': 'ERROR'},
                            ],
                        ],
                        'statistics': {
                            'recordsMatched': 42,
                            'recordsScanned': 1000,
                        },
                    },
                )
            return httpx.Response(500, text='unexpected')

        respx.post(_LOGS_URL).mock(side_effect=handler)
        plugin = CloudWatchLogsPlugin()
        result = await plugin.search(_ctx(), _creds(), _query(limit=2))
        self.assertEqual(len(result.entries), 2)
        self.assertEqual(result.total, 42)
        self.assertIsNotNone(result.next_cursor)
        first_entry = result.entries[0]
        self.assertEqual(first_entry.message, 'oops')
        self.assertEqual(first_entry.level, 'ERROR')
        # StartQuery payload assembled correctly.
        start = next(c for c in captured if c['target'].endswith('StartQuery'))
        payload = start['payload']
        self.assertEqual(payload['logGroupNames'], ['/imbi/prod/widget'])
        self.assertIn('filter level = "ERROR"', payload['queryString'])

    @respx.mock
    async def test_partial_page_no_next_cursor(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            target = request.headers['x-amz-target']
            if target.endswith('StartQuery'):
                return httpx.Response(200, json={'queryId': 'q-1'})
            return httpx.Response(
                200,
                json={
                    'status': 'Complete',
                    'results': [
                        [
                            {
                                'field': '@timestamp',
                                'value': '2024-01-02 11:00:00',
                            },
                            {'field': '@message', 'value': 'one'},
                            {
                                'field': '@logStream',
                                'value': 's',
                            },
                        ]
                    ],
                    'statistics': {'recordsMatched': 1},
                },
            )

        respx.post(_LOGS_URL).mock(side_effect=handler)
        plugin = CloudWatchLogsPlugin()
        result = await plugin.search(_ctx(), _creds(), _query(limit=10))
        self.assertEqual(len(result.entries), 1)
        self.assertIsNone(result.next_cursor)

    @respx.mock
    async def test_cursor_narrows_end_time(self) -> None:
        captured: list[dict[str, typing.Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            target = request.headers['x-amz-target']
            payload = json.loads(request.content)
            captured.append({'target': target, 'payload': payload})
            if target.endswith('StartQuery'):
                return httpx.Response(200, json={'queryId': 'q-1'})
            return httpx.Response(
                200,
                json={'status': 'Complete', 'results': [], 'statistics': {}},
            )

        respx.post(_LOGS_URL).mock(side_effect=handler)
        plugin = CloudWatchLogsPlugin()
        # Build a fingerprint matching the plugin's exact query.
        ctx = _ctx()
        log_groups = ['/imbi/prod/widget']
        # Reproduce the exact query string the plugin will assemble.
        from imbi_plugin_aws.query import build_query

        q = _query(limit=2)
        query_string = build_query(
            base_filter=None,
            filters=q.filters,
            limit=2,
            fields=['@timestamp', '@message', '@logStream', 'level'],
        )
        fp = query_fingerprint(
            query_string=query_string, log_group_names=log_groups
        )
        cursor = encode_cursor(
            last_seen=datetime.datetime(
                2024, 1, 2, 11, 0, 0, tzinfo=datetime.UTC
            ),
            fingerprint=fp,
        )
        await plugin.search(ctx, _creds(), _query(cursor=cursor, limit=2))
        start = next(c for c in captured if c['target'].endswith('StartQuery'))
        # 2024-01-02 11:00:00 UTC = 1704193200; minus 1ms rounds to same sec.
        self.assertEqual(start['payload']['endTime'], 1704193199)

    @respx.mock
    async def test_invalid_cursor_raises(self) -> None:
        plugin = CloudWatchLogsPlugin()
        with self.assertRaises(CursorExpiredError):
            await plugin.search(
                _ctx(),
                _creds(),
                _query(cursor='not-a-cursor', limit=2),
            )

    @respx.mock
    async def test_failed_status_raises_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            target = request.headers['x-amz-target']
            if target.endswith('StartQuery'):
                return httpx.Response(200, json={'queryId': 'q-1'})
            return httpx.Response(
                200,
                json={'status': 'Failed', 'results': [], 'statistics': {}},
            )

        respx.post(_LOGS_URL).mock(side_effect=handler)
        plugin = CloudWatchLogsPlugin()
        with self.assertRaises(PluginUnavailableError):
            await plugin.search(_ctx(), _creds(), _query())

    @respx.mock
    async def test_timeout_calls_stop_query(self) -> None:
        actions: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            target = request.headers['x-amz-target']
            actions.append(target)
            if target.endswith('StartQuery'):
                return httpx.Response(200, json={'queryId': 'q-1'})
            if target.endswith('GetQueryResults'):
                return httpx.Response(
                    200,
                    json={
                        'status': 'Running',
                        'results': [],
                        'statistics': {},
                    },
                )
            if target.endswith('StopQuery'):
                return httpx.Response(200, json={'success': True})
            return httpx.Response(500, text='unexpected')

        respx.post(_LOGS_URL).mock(side_effect=handler)
        plugin = CloudWatchLogsPlugin()
        with self.assertRaises(PluginTimeoutError):
            await plugin.search(
                _ctx(extras={'timeout_seconds': 0}),
                _creds(),
                _query(),
            )
        self.assertTrue(any(a.endswith('StopQuery') for a in actions))


class _FakeValkey:
    """In-memory stand-in for ``imbi_common.valkey.get_client()``."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gets: list[str] = []
        self.sets: list[tuple[str, int, str]] = []
        self.deletes: list[tuple[str, ...]] = []

    async def get(self, key: str) -> str | None:
        self.gets.append(key)
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.sets.append((key, ttl, value))
        self.store[key] = value

    async def delete(self, *keys: str) -> int:
        self.deletes.append(keys)
        for k in keys:
            self.store.pop(k, None)
        return len(keys)


def _patch_valkey(client: _FakeValkey | None) -> typing.Any:
    return unittest.mock.patch.object(
        cw_module, '_try_get_valkey', return_value=client
    )


class ResolveModeTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_glob_resolves_via_describe_log_groups(self) -> None:
        captured: list[dict[str, typing.Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            target = request.headers['x-amz-target']
            payload = json.loads(request.content)
            captured.append({'target': target, 'payload': payload})
            if target.endswith('DescribeLogGroups'):
                return httpx.Response(
                    200,
                    json={
                        'logGroups': [
                            {'logGroupName': '/aws/rds/widget-1/postgresql'},
                            {'logGroupName': '/aws/rds/widget-2/postgresql'},
                            {'logGroupName': '/aws/rds/widget-1/audit'},
                        ]
                    },
                )
            if target.endswith('StartQuery'):
                return httpx.Response(200, json={'queryId': 'q-1'})
            if target.endswith('GetQueryResults'):
                return httpx.Response(
                    200,
                    json={
                        'status': 'Complete',
                        'results': [],
                        'statistics': {},
                    },
                )
            return httpx.Response(500, text='unexpected')

        respx.post(_LOGS_URL).mock(side_effect=handler)
        with _patch_valkey(None):
            plugin = CloudWatchLogsPlugin()
            result = await plugin.search(
                _ctx(
                    extras={
                        'log_group_names': _GLOB_PATTERN,
                    }
                ),
                _creds(),
                _query(),
            )
        describe = next(
            c for c in captured if c['target'].endswith('DescribeLogGroups')
        )
        self.assertEqual(
            describe['payload']['logGroupNamePrefix'], '/aws/rds/widget-'
        )
        start = next(c for c in captured if c['target'].endswith('StartQuery'))
        self.assertEqual(
            start['payload']['logGroupNames'],
            [
                '/aws/rds/widget-1/postgresql',
                '/aws/rds/widget-2/postgresql',
            ],
        )
        self.assertEqual(result.warnings, [])

    @respx.mock
    async def test_empty_resolve_short_circuits_with_warning(self) -> None:
        respx.post(_LOGS_URL).mock(
            return_value=httpx.Response(200, json={'logGroups': []})
        )
        with _patch_valkey(None):
            plugin = CloudWatchLogsPlugin()
            result = await plugin.search(
                _ctx(
                    extras={
                        'log_group_names': '/aws/rds/${project_slug}-*/x',
                    }
                ),
                _creds(),
                _query(),
            )
        self.assertEqual(result.entries, [])
        self.assertEqual(result.total, 0)
        self.assertTrue(
            any('No log groups matched' in w for w in result.warnings)
        )

    @respx.mock
    async def test_truncates_to_50_with_warning(self) -> None:
        groups = [
            {'logGroupName': f'/aws/rds/widget-{i:02d}/postgresql'}
            for i in range(75)
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            target = request.headers['x-amz-target']
            if target.endswith('DescribeLogGroups'):
                return httpx.Response(200, json={'logGroups': groups})
            if target.endswith('StartQuery'):
                return httpx.Response(200, json={'queryId': 'q-1'})
            if target.endswith('GetQueryResults'):
                return httpx.Response(
                    200,
                    json={
                        'status': 'Complete',
                        'results': [],
                        'statistics': {},
                    },
                )
            return httpx.Response(500, text='unexpected')

        respx.post(_LOGS_URL).mock(side_effect=handler)
        captured: list[dict[str, typing.Any]] = []

        async def capture_handler(
            request: httpx.Request,
        ) -> httpx.Response:
            captured.append(
                {
                    'target': request.headers['x-amz-target'],
                    'payload': json.loads(request.content),
                }
            )
            return handler(request)

        respx.post(_LOGS_URL).mock(side_effect=capture_handler)

        with _patch_valkey(None):
            plugin = CloudWatchLogsPlugin()
            result = await plugin.search(
                _ctx(
                    extras={
                        'log_group_names': _GLOB_PATTERN,
                    }
                ),
                _creds(),
                _query(),
            )
        start = next(c for c in captured if c['target'].endswith('StartQuery'))
        self.assertEqual(len(start['payload']['logGroupNames']), 50)
        # Stable ordering — alphabetical truncation.
        self.assertEqual(
            start['payload']['logGroupNames'][0],
            '/aws/rds/widget-00/postgresql',
        )
        self.assertEqual(len(result.warnings), 1)
        self.assertIn('matched 75 log groups', result.warnings[0])

    @respx.mock
    async def test_valkey_cache_hit_skips_describe(self) -> None:
        targets: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            target = request.headers['x-amz-target']
            targets.append(target)
            if target.endswith('StartQuery'):
                return httpx.Response(200, json={'queryId': 'q-1'})
            if target.endswith('GetQueryResults'):
                return httpx.Response(
                    200,
                    json={
                        'status': 'Complete',
                        'results': [],
                        'statistics': {},
                    },
                )
            return httpx.Response(500, text='unexpected describe')

        respx.post(_LOGS_URL).mock(side_effect=handler)

        fake = _FakeValkey()
        # Pre-seed the cache key. Pattern after expansion:
        # /aws/rds/widget-*/postgresql
        from imbi_plugin_aws.aws_session import AwsCredentials

        creds = AwsCredentials(
            access_key_id='AKID',
            secret_access_key='sec',
            session_token=None,
            region='us-east-1',
        )
        cache_key = cw_module._resolve_cache_key(
            creds, '/aws/rds/widget-*/postgresql', account_id=None
        )
        fake.store[cache_key] = json.dumps(['/aws/rds/widget-1/postgresql'])

        with _patch_valkey(fake):
            plugin = CloudWatchLogsPlugin()
            await plugin.search(
                _ctx(
                    extras={
                        'log_group_names': _GLOB_PATTERN,
                    }
                ),
                _creds(),
                _query(),
            )
        self.assertNotIn('Logs_20140328.DescribeLogGroups', targets)
        self.assertIn(cache_key, fake.gets)

    @respx.mock
    async def test_valkey_cache_miss_writes_setex(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            target = request.headers['x-amz-target']
            if target.endswith('DescribeLogGroups'):
                return httpx.Response(
                    200,
                    json={
                        'logGroups': [
                            {'logGroupName': '/aws/rds/widget-1/postgresql'},
                        ]
                    },
                )
            if target.endswith('StartQuery'):
                return httpx.Response(200, json={'queryId': 'q-1'})
            if target.endswith('GetQueryResults'):
                return httpx.Response(
                    200,
                    json={
                        'status': 'Complete',
                        'results': [],
                        'statistics': {},
                    },
                )
            return httpx.Response(500, text='unexpected')

        respx.post(_LOGS_URL).mock(side_effect=handler)
        fake = _FakeValkey()
        with _patch_valkey(fake):
            plugin = CloudWatchLogsPlugin()
            await plugin.search(
                _ctx(
                    extras={
                        'log_group_names': _GLOB_PATTERN,
                    }
                ),
                _creds(),
                _query(),
            )
        self.assertEqual(len(fake.sets), 1)
        _key, ttl, value = fake.sets[0]
        self.assertEqual(ttl, 300)
        self.assertEqual(json.loads(value), ['/aws/rds/widget-1/postgresql'])


class SourceModeTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_prefix_emits_source_clause_no_log_group_names(self) -> None:
        captured: list[dict[str, typing.Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            target = request.headers['x-amz-target']
            payload = json.loads(request.content)
            captured.append({'target': target, 'payload': payload})
            if target.endswith('StartQuery'):
                return httpx.Response(200, json={'queryId': 'q-1'})
            if target.endswith('GetQueryResults'):
                return httpx.Response(
                    200,
                    json={
                        'status': 'Complete',
                        'results': [],
                        'statistics': {},
                    },
                )
            return httpx.Response(500, text='unexpected')

        respx.post(_LOGS_URL).mock(side_effect=handler)
        with _patch_valkey(None):
            plugin = CloudWatchLogsPlugin()
            await plugin.search(
                _ctx(
                    extras={
                        'log_group_names': (
                            'prefix:/aws/lambda/${project_slug}-, '
                            'prefix:/aws/ecs/${project_slug}/'
                        ),
                    }
                ),
                _creds(),
                _query(),
            )
        start = next(c for c in captured if c['target'].endswith('StartQuery'))
        self.assertNotIn('logGroupNames', start['payload'])
        expected_clause = (
            'SOURCE logGroups(namePrefix: ['
            "'/aws/lambda/widget-', '/aws/ecs/widget/'])"
        )
        self.assertIn(expected_clause, start['payload']['queryString'])

    async def test_more_than_five_prefix_entries_raises(self) -> None:
        plugin = CloudWatchLogsPlugin()
        ctx = _ctx(
            extras={
                'log_group_names': ', '.join(
                    f'prefix:/p{i}/' for i in range(6)
                ),
            }
        )
        with (
            _patch_valkey(None),
            self.assertRaisesRegex(ValueError, 'capped at 5'),
        ):
            await plugin.search(ctx, _creds(), _query())

    async def test_mixing_prefix_with_literal_raises(self) -> None:
        plugin = CloudWatchLogsPlugin()
        ctx = _ctx(
            extras={
                'log_group_names': 'prefix:/p/, /aws/lambda/widget',
            }
        )
        with (
            _patch_valkey(None),
            self.assertRaisesRegex(ValueError, 'cannot combine'),
        ):
            await plugin.search(ctx, _creds(), _query())


class CacheBustTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_resource_not_found_busts_cache_and_retries(self) -> None:
        # Simulate: cached resolve names a deleted log group; first
        # StartQuery 400s with ResourceNotFoundException; resolver
        # re-runs DescribeLogGroups and retry succeeds.
        from imbi_plugin_aws.aws_session import AwsCredentials

        creds = AwsCredentials(
            access_key_id='AKID',
            secret_access_key='sec',
            session_token=None,
            region='us-east-1',
        )
        cache_key = cw_module._resolve_cache_key(
            creds, '/aws/rds/widget-*/postgresql', account_id=None
        )
        fake = _FakeValkey()
        fake.store[cache_key] = json.dumps(
            ['/aws/rds/widget-deleted/postgresql']
        )

        start_calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            target = request.headers['x-amz-target']
            if target.endswith('DescribeLogGroups'):
                return httpx.Response(
                    200,
                    json={
                        'logGroups': [
                            {'logGroupName': '/aws/rds/widget-1/postgresql'},
                        ]
                    },
                )
            if target.endswith('StartQuery'):
                start_calls.append(1)
                if len(start_calls) == 1:
                    return httpx.Response(
                        400,
                        json={
                            '__type': 'ResourceNotFoundException',
                            'message': 'gone',
                        },
                    )
                return httpx.Response(200, json={'queryId': 'q-2'})
            if target.endswith('GetQueryResults'):
                return httpx.Response(
                    200,
                    json={
                        'status': 'Complete',
                        'results': [],
                        'statistics': {},
                    },
                )
            return httpx.Response(500, text='unexpected')

        respx.post(_LOGS_URL).mock(side_effect=handler)

        with _patch_valkey(fake):
            plugin = CloudWatchLogsPlugin()
            result = await plugin.search(
                _ctx(
                    extras={
                        'log_group_names': _GLOB_PATTERN,
                    }
                ),
                _creds(),
                _query(),
            )
        # Cache was deleted at least once.
        self.assertTrue(any(cache_key in keys for keys in fake.deletes))
        # Two StartQuery attempts.
        self.assertEqual(len(start_calls), 2)
        self.assertEqual(result.entries, [])


class SchemaTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_returns_baseline_on_describe_failure(self) -> None:
        respx.post(_LOGS_URL).mock(
            return_value=httpx.Response(
                400,
                json={
                    '__type': 'AccessDeniedException',
                    'message': 'no',
                },
            )
        )
        plugin = CloudWatchLogsPlugin()
        schema = await plugin.schema(_ctx(), _creds())
        names = [s['name'] for s in schema]
        self.assertIn('@timestamp', names)
        self.assertIn('level', names)

    @respx.mock
    async def test_enriches_with_log_groups(self) -> None:
        respx.post(_LOGS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    'logGroups': [
                        {'logGroupName': '/aws/rds/postgresql'},
                        {'logGroupName': '/aws/lambda/widget'},
                    ]
                },
            )
        )
        plugin = CloudWatchLogsPlugin()
        schema = await plugin.schema(_ctx(), _creds())
        enriched = next(s for s in schema if s.get('choices'))
        self.assertIn('/aws/rds/postgresql', enriched['choices'])
