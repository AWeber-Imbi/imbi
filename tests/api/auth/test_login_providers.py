"""Tests for the login-provider repository."""

from __future__ import annotations

import json
import typing
import unittest
from unittest import mock

from imbi_api.auth import login_providers


class _FakeDB:
    """Minimal DB stub that returns canned execute results."""

    def __init__(
        self, rows: list[dict[str, typing.Any]] | None = None
    ) -> None:
        self.rows = rows or []
        self.execute = mock.AsyncMock(side_effect=self._execute)

    async def _execute(
        self,
        query: typing.Any,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, typing.Any]]:
        params = params or {}
        slug = params.get('slug')
        if slug is not None:
            return [r for r in self.rows if r['app']['slug'] == slug]
        return list(self.rows)


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
