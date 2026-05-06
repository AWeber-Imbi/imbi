"""Tests for the login-provider repository."""

from __future__ import annotations

import json
import typing
import unittest
from unittest import mock

from imbi_api.auth import login_providers


class _FakeDB:
    """Minimal DB stub that returns canned execute results.

    ``rows`` carry service-application rows; ``plugin_rows`` carry
    Plugin-node rows for the identity-plugin source.
    """

    def __init__(
        self,
        rows: list[dict[str, typing.Any]] | None = None,
        plugin_rows: list[dict[str, typing.Any]] | None = None,
    ) -> None:
        self.rows = rows or []
        self.plugin_rows = plugin_rows or []
        self.execute = mock.AsyncMock(side_effect=self._execute)

    async def _execute(
        self,
        query: typing.Any,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, typing.Any]]:
        params = params or {}
        slug = params.get('slug')
        is_plugin_query = 'Plugin' in str(query) and 'login_capable' in str(
            query
        )
        source = self.plugin_rows if is_plugin_query else self.rows
        if slug is not None:
            if is_plugin_query:
                return [
                    r for r in source if r['plugin']['plugin_slug'] == slug
                ]
            return [r for r in source if r['app']['slug'] == slug]
        return list(source)


def _plugin_row(
    plugin_slug: str,
    *,
    plugin_id: str = 'plug-1',
    label: str | None = None,
    used_as_login: bool = True,
) -> dict[str, typing.Any]:
    return {
        'plugin': {
            'id': plugin_id,
            'plugin_slug': plugin_slug,
            'label': label or plugin_slug,
            'login_capable': True,
            'used_as_login': used_as_login,
        }
    }


def _row(
    slug: str,
    *,
    oauth_app_type: str = 'google',
    usage: str = 'login',
    status: str = 'active',
    name: str = 'X',
    issuer_url: str | None = None,
    allowed_domains: list[str] | None = None,
) -> dict[str, typing.Any]:
    return {
        'app': {
            'slug': slug,
            'name': name,
            'oauth_app_type': oauth_app_type,
            'usage': usage,
            'status': status,
            'client_id': 'cid',
            'client_secret': 'enc:secret',
            'issuer_url': issuer_url,
            'allowed_domains': json.dumps(allowed_domains or []),
            'scopes': json.dumps([]),
        },
        'service': {
            'slug': 'svc',
            'authorization_endpoint': 'https://auth/authorize',
            'token_endpoint': 'https://auth/token',
            'revoke_endpoint': None,
        },
    }


class LoginProvidersRepoTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        login_providers.invalidate_cache()

    async def test_list_login_apps_empty(self) -> None:
        db = _FakeDB([])
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            rows = await login_providers.list_login_apps(db)  # type: ignore[arg-type]
        self.assertEqual(rows, [])

    async def test_list_login_apps_filters_enabled(self) -> None:
        db = _FakeDB(
            [
                _row('a', status='active'),
                _row('b', status='inactive'),
            ]
        )
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            all_rows = await login_providers.list_login_apps(db)  # type: ignore[arg-type]
            login_providers.invalidate_cache()
            active = await login_providers.list_login_apps(
                db,  # type: ignore[arg-type]
                enabled_only=True,
            )
        self.assertEqual({r.slug for r in all_rows}, {'a', 'b'})
        self.assertEqual({r.slug for r in active}, {'a'})

    async def test_get_login_app_returns_none_for_missing(self) -> None:
        db = _FakeDB([])
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            row = await login_providers.get_login_app(db, 'absent')  # type: ignore[arg-type]
        self.assertIsNone(row)

    async def test_get_login_app_returns_row(self) -> None:
        db = _FakeDB([_row('google', oauth_app_type='google')])
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            row = await login_providers.get_login_app(db, 'google')  # type: ignore[arg-type]
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.slug, 'google')
        self.assertEqual(row.oauth_app_type, 'google')
        self.assertEqual(row.token_endpoint, 'https://auth/token')

    async def test_cache_invalidation(self) -> None:
        db = _FakeDB([_row('google')])
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            first = await login_providers.get_login_app(db, 'google')  # type: ignore[arg-type]
            # Returns cached value even after rows are mutated.
            db.rows = []
            second = await login_providers.get_login_app(db, 'google')  # type: ignore[arg-type]
            self.assertIsNotNone(first)
            self.assertEqual(first, second)
            login_providers.invalidate_cache('google')
            third = await login_providers.get_login_app(db, 'google')  # type: ignore[arg-type]
        self.assertIsNone(third)


class IdentityPluginLoginSourceTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify the identity-plugin source merges into the login list."""

    def setUp(self) -> None:
        login_providers.invalidate_cache()

    async def test_list_includes_identity_plugin_rows(self) -> None:
        db = _FakeDB(
            rows=[],
            plugin_rows=[_plugin_row('oidc', plugin_id='p-1')],
        )
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            apps = await login_providers.list_login_apps(db)  # type: ignore[arg-type]
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0].slug, 'oidc')
        self.assertEqual(apps[0].source, 'identity_plugin')
        self.assertEqual(apps[0].oauth_app_type, 'identity_plugin')
        self.assertEqual(apps[0].plugin_id, 'p-1')

    async def test_get_prefers_identity_plugin_on_collision(self) -> None:
        db = _FakeDB(
            rows=[_row('oidc', oauth_app_type='oidc')],
            plugin_rows=[_plugin_row('oidc', plugin_id='p-99')],
        )
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            app = await login_providers.get_login_app(db, 'oidc')  # type: ignore[arg-type]
        assert app is not None
        self.assertEqual(app.source, 'identity_plugin')
        self.assertEqual(app.plugin_id, 'p-99')

    async def test_list_merges_both_sources(self) -> None:
        db = _FakeDB(
            rows=[_row('google', oauth_app_type='google')],
            plugin_rows=[_plugin_row('oidc', plugin_id='p-1')],
        )
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            apps = await login_providers.list_login_apps(db)  # type: ignore[arg-type]
        slugs = {a.slug: a.source for a in apps}
        self.assertEqual(
            slugs, {'google': 'service_app', 'oidc': 'identity_plugin'}
        )

    async def test_list_skips_plugin_rows_missing_id(self) -> None:
        """Plugin rows without plugin_slug or id are silently skipped."""
        db = _FakeDB(
            rows=[],
            plugin_rows=[
                {
                    'plugin': {
                        'id': '',
                        'plugin_slug': '',
                        'login_capable': True,
                        'used_as_login': True,
                    }
                },
                _plugin_row('okta', plugin_id='p-99'),
            ],
        )
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            apps = await login_providers.list_login_apps(db)  # type: ignore[arg-type]
        # Bad row dropped, good row kept.
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0].slug, 'okta')

    async def test_list_skips_app_rows_without_oauth_type(self) -> None:
        """Service-app rows missing oauth_app_type are silently skipped."""
        bad_row = {
            'app': {'slug': 'incomplete'},
            'service': None,
        }
        db = _FakeDB(
            rows=[bad_row, _row('google', oauth_app_type='google')],
        )
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            apps = await login_providers.list_login_apps(db)  # type: ignore[arg-type]
        slugs = [a.slug for a in apps]
        self.assertEqual(slugs, ['google'])
