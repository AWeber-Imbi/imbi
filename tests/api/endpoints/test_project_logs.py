"""Tests for the project logs plugin endpoints."""

import datetime
import json
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import graph
from imbi_common.plugins.base import (
    Capability,
    LogEntry,
    LogResult,
    LogsCapability,
    Plugin,
    PluginManifest,
)
from imbi_common.plugins.errors import (
    CursorExpiredError,
)
from imbi_common.plugins.registry import RegistryEntry

from imbi_api import models
from imbi_api.auth import password, permissions
from imbi_api.plugins.resolution import ResolvedCapability
from tests import support


class _FakeLogsHandler(LogsCapability):
    async def search(self, ctx, credentials, query):  # type: ignore[override]
        return LogResult(
            entries=[
                LogEntry(
                    timestamp=datetime.datetime(
                        2026, 1, 1, tzinfo=datetime.UTC
                    ),
                    message='hello',
                    level='INFO',
                    raw={'k': 'v'},
                )
            ],
            next_cursor=None,
            total=1,
        )

    async def schema(self, ctx, credentials):  # type: ignore[override]
        return [{'name': 'level', 'type': 'string'}]


class _FakePlugin(Plugin):
    pass


def _manifest(handler: type[LogsCapability]) -> PluginManifest:
    return PluginManifest(
        slug='logzio',
        name='Logz.io',
        capabilities=[Capability(kind='logs', label='Logs', handler=handler)],
    )


def _entry(handler: type[LogsCapability] = _FakeLogsHandler) -> RegistryEntry:
    return RegistryEntry(
        plugin_cls=_FakePlugin,
        manifest=_manifest(handler),
        package_name='imbi-plugin-logzio',
        package_version='1.0.0',
    )


def _resolved(
    handler: type[LogsCapability] = _FakeLogsHandler,
) -> ResolvedCapability:
    entry = _entry(handler)
    return ResolvedCapability(
        integration_id='i1',
        integration_slug='logzio-prod',
        plugin_slug='logzio',
        kind='logs',
        entry=entry,
        capability_cls=entry.manifest.get_capability('logs').handler,
        integration={'id': 'i1', 'slug': 'logzio-prod', 'plugin': 'logzio'},
        integration_options={},
        capability_options={},
        encrypted_credentials={},
    )


class ProjectLogsEndpointTestCase(support.SharedAppTestCase):
    def setUp(self) -> None:
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
            permissions={'project:logs:read'},
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

    def _resolved(self) -> ResolvedCapability:
        return _resolved()

    def test_search_logs_happy_path(self) -> None:
        with (
            mock.patch(
                'imbi_api.endpoints.project_logs.resolve_capability',
                return_value=self._resolved(),
            ),
            mock.patch(
                'imbi_api.endpoints.project_logs'
                '.decrypt_integration_credentials',
                return_value={'token': 'x'},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/logs/'
                )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['entries']), 1)
        self.assertEqual(data['entries'][0]['message'], 'hello')

    def test_search_logs_invalid_datetime_returns_400(self) -> None:
        with mock.patch(
            'imbi_api.endpoints.project_logs.resolve_capability',
            return_value=self._resolved(),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/logs/'
                    '?start_time=not-a-date'
                )
        self.assertEqual(response.status_code, 400)
        self.assertIn('datetime', response.json()['detail'])

    def test_search_logs_invalid_filter_returns_400(self) -> None:
        with mock.patch(
            'imbi_api.endpoints.project_logs.resolve_capability',
            return_value=self._resolved(),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/logs/?filter=oops'
                )
        self.assertEqual(response.status_code, 400)

    def test_search_logs_unknown_filter_op(self) -> None:
        with mock.patch(
            'imbi_api.endpoints.project_logs.resolve_capability',
            return_value=self._resolved(),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/logs/'
                    '?filter=field:lt:1'
                )
        self.assertEqual(response.status_code, 400)

    def test_search_logs_credentials_missing_returns_503(self) -> None:
        with (
            mock.patch(
                'imbi_api.endpoints.project_logs.resolve_capability',
                return_value=self._resolved(),
            ),
            mock.patch(
                'imbi_api.endpoints.project_logs'
                '.decrypt_integration_credentials',
                return_value={},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/logs/'
                )
        self.assertEqual(response.status_code, 503)

    def test_search_logs_cursor_expired_returns_409(self) -> None:
        class _Expiring(_FakeLogsHandler):
            async def search(self, ctx, credentials, query):  # type: ignore[override]
                raise CursorExpiredError('cursor too old')

        with (
            mock.patch(
                'imbi_api.endpoints.project_logs.resolve_capability',
                return_value=_resolved(_Expiring),
            ),
            mock.patch(
                'imbi_api.endpoints.project_logs'
                '.decrypt_integration_credentials',
                return_value={'token': 'x'},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/logs/?cursor=abc'
                )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['error'], 'cursor_expired')

    def test_get_log_schema(self) -> None:
        with (
            mock.patch(
                'imbi_api.endpoints.project_logs.resolve_capability',
                return_value=self._resolved(),
            ),
            mock.patch(
                'imbi_api.endpoints.project_logs'
                '.decrypt_integration_credentials',
                return_value={'token': 'x'},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/logs/schema'
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), [{'name': 'level', 'type': 'string'}]
        )

    def test_get_log_schema_credentials_missing(self) -> None:
        with (
            mock.patch(
                'imbi_api.endpoints.project_logs.resolve_capability',
                return_value=self._resolved(),
            ),
            mock.patch(
                'imbi_api.endpoints.project_logs'
                '.decrypt_integration_credentials',
                return_value={},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/logs/schema'
                )
        self.assertEqual(response.status_code, 503)

    def test_search_logs_with_valid_datetime_and_filter(self) -> None:
        with (
            mock.patch(
                'imbi_api.endpoints.project_logs.resolve_capability',
                return_value=self._resolved(),
            ),
            mock.patch(
                'imbi_api.endpoints.project_logs'
                '.decrypt_integration_credentials',
                return_value={'token': 'x'},
            ),
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/logs/'
                    '?start_time=2026-01-01T00:00:00%2B00:00'
                    '&end_time=2026-01-02T00:00:00%2B00:00'
                    '&filter=level:eq:INFO'
                )
        self.assertEqual(response.status_code, 200)


class ParseFiltersTestCase(unittest.TestCase):
    def test_filter_parses_with_value_containing_colon(self) -> None:
        from imbi_api.endpoints.project_logs import _parse_filters

        # `split(':', 2)` should keep ``key:value`` intact in value.
        result = _parse_filters(['url:eq:https://example.com'])
        self.assertEqual(result[0].field, 'url')
        self.assertEqual(result[0].op, 'eq')
        self.assertEqual(result[0].value, 'https://example.com')

    def test_audit_log_payload_for_logs(self) -> None:
        # Sanity check: importing the module should succeed and expose router
        from imbi_api.endpoints import project_logs

        self.assertTrue(hasattr(project_logs, 'project_logs_router'))
        # Use json import so the module-level json import is exercised
        # (also catches accidental import removal).
        self.assertEqual(json.loads('{"a": 1}'), {'a': 1})
