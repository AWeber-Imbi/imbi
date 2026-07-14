"""Tests for project configuration plugin endpoints.

These tests run against the real Valkey and ClickHouse instances
provisioned by ``docker compose up`` (started via ``just test``). The
plugin handler and the AGE graph are still mocked — neither has a
test-friendly fixture today (plugin packages are not installed in the
test env, and Cypher mutations require seeded graph data) — but cache
hits/invalidations and audit-log writes are exercised end-to-end.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import typing
import unittest
import uuid
from unittest import mock

from fastapi import testclient
from imbi_common import clickhouse as imbi_clickhouse
from imbi_common import graph
from imbi_common import settings as imbi_settings
from imbi_common.plugins.base import (
    Capability,
    ConfigKey,
    ConfigKeyWithValue,
    ConfigurationCapability,
    Plugin,
    PluginContext,
    PluginManifest,
)
from imbi_common.plugins.registry import RegistryEntry
from valkey import asyncio as valkey_asyncio

from imbi_api import app, models
from imbi_api.auth import password, permissions
from imbi_api.plugins.resolution import ResolvedCapability


class _FakeConfigurationHandler(ConfigurationCapability):
    async def list_keys(self, ctx, credentials):  # type: ignore[override]
        return [
            ConfigKey(
                key='/foo',
                data_type='string',
                last_modified=datetime.datetime(
                    2026, 1, 1, tzinfo=datetime.UTC
                ),
                secret=False,
            )
        ]

    async def get_values(self, ctx, credentials, keys=None):  # type: ignore[override]
        return [
            ConfigKeyWithValue(
                key='/foo',
                data_type='string',
                last_modified=None,
                secret=False,
                value='bar',
            )
        ]

    async def set_value(self, ctx, credentials, key, value):  # type: ignore[override]
        return ConfigKey(
            key=key,
            data_type=value.data_type,
            last_modified=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            secret=value.secret,
        )

    async def delete_key(self, ctx, credentials, key):  # type: ignore[override]
        return None


class _FakePlugin(Plugin):
    pass


def _entry() -> RegistryEntry:
    return RegistryEntry(
        plugin_cls=_FakePlugin,
        manifest=PluginManifest(
            slug='ssm',
            name='SSM',
            capabilities=[
                Capability(
                    kind='configuration',
                    label='Configuration',
                    handler=_FakeConfigurationHandler,
                )
            ],
        ),
        package_name='imbi-plugin-ssm',
        package_version='1.0.0',
    )


def _resolved(plugin_id: str) -> ResolvedCapability:
    entry = _entry()
    return ResolvedCapability(
        integration_id=plugin_id,
        integration_slug='ssm-prod',
        plugin_slug='ssm',
        kind='configuration',
        entry=entry,
        capability_cls=entry.manifest.get_capability('configuration').handler,
        integration={'id': plugin_id, 'slug': 'ssm-prod', 'plugin': 'ssm'},
        integration_options={},
        capability_options={},
        encrypted_credentials={},
    )


def _short_id() -> str:
    """Random short id so cache keys / audit rows don't collide."""
    return uuid.uuid4().hex[:12]


class ProjectConfigurationEndpointTestCase(unittest.TestCase):
    """End-to-end tests with real Valkey + ClickHouse.

    Mock patches MUST be applied INSIDE the TestClient context. Patching
    ``valkey.get_client`` outside the TestClient context applies the mock
    during lifespan startup, where the score-worker hook also calls
    ``valkey.get_client()`` and would receive the test's AsyncMock. The
    score-worker task then loops against the fake client and never exits,
    causing pytest to hang indefinitely.
    """

    @classmethod
    def setUpClass(cls) -> None:
        # Ensure ClickHouse has the ``operations_log`` table for the
        # audit-write assertions. Locally the table is left over from
        # ``imbi-api setup``; in CI the fresh container needs an
        # explicit schema bootstrap.
        async def _ensure_schema() -> None:
            ch = imbi_clickhouse.client.Clickhouse()
            await ch.initialize()
            try:
                await ch.setup_schema()
            finally:
                await ch.aclose()

        asyncio.run(_ensure_schema())

    def setUp(self) -> None:
        self.test_app = app.create_app()
        self.test_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={
                'project:configuration:read',
                'project:configuration:read_secrets',
                'project:configuration:write',
            },
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        # Default: project-slug lookup returns no rows → audit writes
        # use empty project_slug. Tests that care can override.
        self.mock_db.execute.return_value = []
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

        self.plugin_id = f'p-{_short_id()}'
        self.project_id = f'proj-{_short_id()}'
        self._cache_keys_to_clean: list[str] = []

    # NOTE: cache cleanup is performed inside each test (while the
    # ``TestClient`` lifespan is active) — ``valkey.get_client()`` is
    # only valid between lifespan startup and shutdown. Unique
    # ``plugin_id`` / ``project_id`` per test keep us hermetic anyway.

    def _track_cache_key(self, key: str) -> None:
        self._cache_keys_to_clean.append(key)

    def _list_cache_key(
        self,
        source: str | None = None,
        environment: str | None = None,
    ) -> str:
        src = source or '_'
        env = environment or '_'
        key = (
            f'imbi:plugin-cache:{self.plugin_id}:{self.project_id}'
            f':{src}:{env}:list'
        )
        self._track_cache_key(key)
        return key

    # ``imbi_common.valkey.get_client()`` returns a singleton bound to
    # the lifespan's event loop, which is unusable from our own
    # ``asyncio.run`` (the connection pool's futures live on a different
    # loop). Open a fresh short-lived client for each cache touch
    # instead — pointed at the same Valkey instance by reading the URL
    # from the same settings the app uses.
    async def _read_cache(self, key: str) -> str | None:
        client = valkey_asyncio.Valkey.from_url(
            str(imbi_settings.Valkey().url)
        )
        try:
            value = await client.get(key)
        finally:
            await client.aclose()
        if isinstance(value, bytes):
            return value.decode('utf-8')
        return value

    async def _seed_cache(self, key: str, payload: object) -> None:
        client = valkey_asyncio.Valkey.from_url(
            str(imbi_settings.Valkey().url)
        )
        try:
            await client.setex(key, 60, json.dumps(payload))
        finally:
            await client.aclose()

    async def _query_audit(
        self,
        project_id: str,
        recorded_after: datetime.datetime,
    ) -> list[dict[str, typing.Any]]:
        # Same loop-binding caveat as the cache helpers: spin up a
        # dedicated ClickHouse client for the test's loop instead of
        # reusing the singleton from the lifespan.
        ch = imbi_clickhouse.client.Clickhouse()
        await ch.initialize()
        try:
            rows: list[dict[str, typing.Any]] = await ch.query(
                'SELECT id, project_id, project_slug, environment_slug,'
                ' entry_type, description, recorded_by, plugin_slug'
                ' FROM operations_log FINAL'
                ' WHERE project_id = {pid:String}'
                '   AND recorded_at >= {after:DateTime64(3)}'
                ' ORDER BY recorded_at',
                {'pid': project_id, 'after': recorded_after},
            )
        finally:
            await ch.aclose()
        return rows

    # ----- list / cache behaviour ------------------------------------

    def test_get_configuration_credentials_missing(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            with (
                mock.patch(
                    'imbi_api.endpoints.project_configuration.resolve_capability',
                    return_value=_resolved(self.plugin_id),
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.decrypt_integration_credentials',
                    return_value={},
                ),
            ):
                response = client.get(
                    f'/organizations/myorg/projects/{self.project_id}'
                    '/configuration/'
                )
        self.assertEqual(response.status_code, 503)

    def test_get_configuration_cache_miss_writes(self) -> None:
        cache_key = self._list_cache_key()
        with testclient.TestClient(self.test_app) as client:
            with (
                mock.patch(
                    'imbi_api.endpoints.project_configuration.resolve_capability',
                    return_value=_resolved(self.plugin_id),
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.decrypt_integration_credentials',
                    return_value={'token': 'x'},
                ),
            ):
                response = client.get(
                    f'/organizations/myorg/projects/{self.project_id}'
                    '/configuration/'
                )
            # Read the cache while the lifespan is still active —
            # ``valkey.get_client()`` raises after the context exits.
            cached = asyncio.run(self._read_cache(cache_key))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['key'], '/foo')
        self.assertIsNotNone(cached)
        cached_payload = json.loads(typing.cast(str, cached))
        self.assertEqual(cached_payload[0]['key'], '/foo')

    def test_get_configuration_cache_hit(self) -> None:
        cache_key = self._list_cache_key()
        with testclient.TestClient(self.test_app) as client:
            asyncio.run(
                self._seed_cache(
                    cache_key,
                    [
                        {
                            'key': '/cached',
                            'data_type': 'string',
                            'last_modified': None,
                            'secret': False,
                        }
                    ],
                )
            )
            with (
                mock.patch(
                    'imbi_api.endpoints.project_configuration.resolve_capability',
                    return_value=_resolved(self.plugin_id),
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.decrypt_integration_credentials',
                    return_value={'token': 'x'},
                ),
            ):
                response = client.get(
                    f'/organizations/myorg/projects/{self.project_id}'
                    '/configuration/'
                )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data[0]['key'], '/cached')

    def test_cache_key_scoped_by_source_and_environment(self) -> None:
        # The default-context cache must NOT serve a request that
        # specifies a different ``source``/``environment``.
        default_key = self._list_cache_key()
        scoped_key = self._list_cache_key(
            source='other-plugin', environment='prod'
        )
        with testclient.TestClient(self.test_app) as client:
            asyncio.run(
                self._seed_cache(
                    default_key,
                    [
                        {
                            'key': '/from-default',
                            'data_type': 'string',
                            'last_modified': None,
                            'secret': False,
                        }
                    ],
                )
            )
            with (
                mock.patch(
                    'imbi_api.endpoints.project_configuration.resolve_capability',
                    return_value=_resolved(self.plugin_id),
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.decrypt_integration_credentials',
                    return_value={'token': 'x'},
                ),
            ):
                response = client.get(
                    f'/organizations/myorg/projects/{self.project_id}'
                    '/configuration/?source=other-plugin&environment=prod'
                )
            scoped_cached = asyncio.run(self._read_cache(scoped_key))
        # Should hit the plugin (not the cached /from-default entry).
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['key'], '/foo')
        # And it must have populated the scoped key.
        self.assertIsNotNone(scoped_cached)

    def test_context_includes_project_type_slugs(self) -> None:
        # The plugin context must carry the project's type slugs so
        # option templates like ``${project_type_slug}`` expand — an
        # empty list expands to '' and produces invalid paths (e.g. an
        # SSM path_prefix of ``/pse//imbi``).
        self._list_cache_key()  # register for cleanup; ensures fresh id
        captured: list[PluginContext] = []

        class _RecordingHandler(_FakeConfigurationHandler):
            async def list_keys(self, ctx, credentials):  # type: ignore[override]
                captured.append(ctx)
                return await super().list_keys(ctx, credentials)

        entry = RegistryEntry(
            plugin_cls=_FakePlugin,
            manifest=PluginManifest(
                slug='ssm',
                name='SSM',
                capabilities=[
                    Capability(
                        kind='configuration',
                        label='Configuration',
                        handler=_RecordingHandler,
                    )
                ],
            ),
            package_name='imbi-plugin-ssm',
            package_version='1.0.0',
        )
        resolved = ResolvedCapability(
            integration_id=self.plugin_id,
            integration_slug='ssm-prod',
            plugin_slug='ssm',
            kind='configuration',
            entry=entry,
            capability_cls=_RecordingHandler,
            integration={
                'id': self.plugin_id,
                'slug': 'ssm-prod',
                'plugin': 'ssm',
            },
            integration_options={},
            capability_options={},
            encrypted_credentials={},
        )

        async def _execute(
            query: str,
            params: dict[str, typing.Any],
            columns: list[str] | None = None,
        ) -> list[dict[str, typing.Any]]:
            if 'ProjectType' in query:
                return [{'slug': 'apis'}, {'slug': 'consumer-apis'}]
            return [{'slug': 'my-project', 'team_slug': 'my-team'}]

        self.mock_db.execute.side_effect = _execute
        with testclient.TestClient(self.test_app) as client:
            with (
                mock.patch(
                    'imbi_api.endpoints.project_configuration.resolve_capability',
                    return_value=resolved,
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.decrypt_integration_credentials',
                    return_value={'token': 'x'},
                ),
            ):
                response = client.get(
                    f'/organizations/myorg/projects/{self.project_id}'
                    '/configuration/'
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(captured), 1)
        self.assertEqual(
            captured[0].project_type_slugs, ['apis', 'consumer-apis']
        )
        self.assertEqual(captured[0].project_slug, 'my-project')
        self.assertEqual(captured[0].team_slug, 'my-team')

    # ----- value fetch ------------------------------------------------

    def test_fetch_values(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            with (
                mock.patch(
                    'imbi_api.endpoints.project_configuration.resolve_capability',
                    return_value=_resolved(self.plugin_id),
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.decrypt_integration_credentials',
                    return_value={'token': 'x'},
                ),
            ):
                response = client.post(
                    f'/organizations/myorg/projects/{self.project_id}'
                    '/configuration/values:fetch',
                    json={'keys': ['/foo']},
                )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data[0]['value'], 'bar')

    def test_fetch_values_credentials_missing(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            with (
                mock.patch(
                    'imbi_api.endpoints.project_configuration.resolve_capability',
                    return_value=_resolved(self.plugin_id),
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.decrypt_integration_credentials',
                    return_value={},
                ),
            ):
                response = client.post(
                    f'/organizations/myorg/projects/{self.project_id}'
                    '/configuration/values:fetch',
                    json={'keys': ['/foo']},
                )
        self.assertEqual(response.status_code, 503)

    # ----- set / delete + audit + cache invalidation -----------------

    def test_set_configuration_value(self) -> None:
        # Seed both default and scoped cache entries — the write must
        # invalidate every (source, environment) variant.
        default_key = self._list_cache_key()
        scoped_key = self._list_cache_key(source='alt', environment='staging')

        # Stub project-slug lookup so the audit row carries a real slug.
        self.mock_db.execute.return_value = [{'slug': 'fake-slug'}]
        before = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            seconds=5
        )

        with testclient.TestClient(self.test_app) as client:
            asyncio.run(
                self._seed_cache(default_key, [{'key': '/old', 'sentinel': 1}])
            )
            asyncio.run(
                self._seed_cache(scoped_key, [{'key': '/old', 'sentinel': 2}])
            )
            with (
                mock.patch(
                    'imbi_api.endpoints.project_configuration.resolve_capability',
                    return_value=_resolved(self.plugin_id),
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.decrypt_integration_credentials',
                    return_value={'token': 'x'},
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration.graph'
                    '.parse_agtype',
                    return_value='fake-slug',
                ),
            ):
                response = client.put(
                    f'/organizations/myorg/projects/{self.project_id}'
                    '/configuration/foo?environment=production',
                    json={
                        'data_type': 'string',
                        'value': 'bar',
                        'secret': False,
                    },
                )
            cache_after_default = asyncio.run(self._read_cache(default_key))
            cache_after_scoped = asyncio.run(self._read_cache(scoped_key))
            rows = asyncio.run(self._query_audit(self.project_id, before))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['key'], 'foo')
        # Both cache variants must have been wiped.
        self.assertIsNone(cache_after_default)
        self.assertIsNone(cache_after_scoped)
        # Real audit row must exist with the canonical schema.
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['project_id'], self.project_id)
        self.assertEqual(row['project_slug'], 'fake-slug')
        self.assertEqual(row['environment_slug'], 'production')
        self.assertEqual(row['entry_type'], 'Configured')
        self.assertEqual(row['recorded_by'], 'admin@example.com')
        self.assertEqual(row['plugin_slug'], 'ssm')
        description = json.loads(row['description'])
        self.assertEqual(description['action'], 'set_value')
        self.assertEqual(description['plugin_slug'], 'ssm')
        self.assertEqual(description['key'], 'foo')
        self.assertEqual(description['data_type'], 'string')
        self.assertFalse(description['secret'])

    def test_set_configuration_value_credentials_missing(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            with (
                mock.patch(
                    'imbi_api.endpoints.project_configuration.resolve_capability',
                    return_value=_resolved(self.plugin_id),
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.decrypt_integration_credentials',
                    return_value={},
                ),
            ):
                response = client.put(
                    f'/organizations/myorg/projects/{self.project_id}'
                    '/configuration/foo',
                    json={
                        'data_type': 'string',
                        'value': 'bar',
                        'secret': False,
                    },
                )
        self.assertEqual(response.status_code, 503)

    def test_set_configuration_value_audit_failure_propagates(self) -> None:
        # Audit failures must NOT be swallowed: a successful plugin
        # write that fails to be recorded leaves operations_log silently
        # inconsistent. ``raise_server_exceptions=False`` lets the
        # TestClient surface the resulting 500 instead of re-raising.
        with testclient.TestClient(
            self.test_app, raise_server_exceptions=False
        ) as client:
            with (
                mock.patch(
                    'imbi_api.endpoints.project_configuration.resolve_capability',
                    return_value=_resolved(self.plugin_id),
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.decrypt_integration_credentials',
                    return_value={'token': 'x'},
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration.clickhouse'
                    '.client.Clickhouse.get_instance',
                    side_effect=RuntimeError('CH down'),
                ),
            ):
                response = client.put(
                    f'/organizations/myorg/projects/{self.project_id}'
                    '/configuration/foo',
                    json={
                        'data_type': 'string',
                        'value': 'bar',
                        'secret': True,
                    },
                )
        self.assertEqual(response.status_code, 500)

    def test_delete_configuration_key(self) -> None:
        cache_key = self._list_cache_key()
        before = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            seconds=5
        )

        with testclient.TestClient(self.test_app) as client:
            asyncio.run(self._seed_cache(cache_key, [{'sentinel': True}]))
            with (
                mock.patch(
                    'imbi_api.endpoints.project_configuration.resolve_capability',
                    return_value=_resolved(self.plugin_id),
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.decrypt_integration_credentials',
                    return_value={'token': 'x'},
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration.graph'
                    '.parse_agtype',
                    return_value='',
                ),
            ):
                response = client.delete(
                    f'/organizations/myorg/projects/{self.project_id}'
                    '/configuration/foo'
                )
            cache_after = asyncio.run(self._read_cache(cache_key))
            rows = asyncio.run(self._query_audit(self.project_id, before))
        self.assertEqual(response.status_code, 204)
        # Cache invalidated.
        self.assertIsNone(cache_after)
        # Audit row landed with action=delete_key.
        self.assertEqual(len(rows), 1)
        description = json.loads(rows[0]['description'])
        self.assertEqual(description['action'], 'delete_key')
        self.assertEqual(rows[0]['entry_type'], 'Configured')

    def test_delete_configuration_key_credentials_missing(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            with (
                mock.patch(
                    'imbi_api.endpoints.project_configuration.resolve_capability',
                    return_value=_resolved(self.plugin_id),
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.decrypt_integration_credentials',
                    return_value={},
                ),
            ):
                response = client.delete(
                    f'/organizations/myorg/projects/{self.project_id}'
                    '/configuration/foo'
                )
        self.assertEqual(response.status_code, 503)

    def test_invalidate_cache_swallows_errors(self) -> None:
        from imbi_api.endpoints.project_configuration import (
            _invalidate_cache,
        )

        async def _run() -> None:
            with mock.patch(
                'imbi_api.endpoints.project_configuration.valkey.get_client',
                side_effect=RuntimeError('no valkey'),
            ):
                # Should not raise.
                await _invalidate_cache(self.plugin_id, self.project_id)

        asyncio.run(_run())

    def test_get_configuration_cache_read_error_swallowed(self) -> None:
        # Replace ``valkey.get_client`` returns a broken client whose
        # ``get`` blows up. The endpoint must ignore the failure and
        # proceed to the plugin.
        broken = mock.AsyncMock()
        broken.get.side_effect = RuntimeError('bad cache')
        with testclient.TestClient(self.test_app) as client:
            with (
                mock.patch(
                    'imbi_api.endpoints.project_configuration.resolve_capability',
                    return_value=_resolved(self.plugin_id),
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.decrypt_integration_credentials',
                    return_value={'token': 'x'},
                ),
                mock.patch(
                    'imbi_api.endpoints.project_configuration'
                    '.valkey.get_client',
                    return_value=broken,
                ),
            ):
                response = client.get(
                    f'/organizations/myorg/projects/{self.project_id}'
                    '/configuration/'
                )
        self.assertEqual(response.status_code, 200)
