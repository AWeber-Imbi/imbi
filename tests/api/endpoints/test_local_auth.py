"""Tests for the local-auth admin endpoints and ``/auth/providers``."""

from __future__ import annotations

import datetime
import typing
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models
from imbi_api.auth import local_auth, login_providers
from imbi_api.domain import models as domain_models


def _build_app(
    permissions_set: set[str],
) -> tuple[typing.Any, mock.AsyncMock]:
    from imbi_api.auth import permissions

    test_app = app.create_app()

    user = models.User(
        email='admin@example.com',
        display_name='Admin',
        password_hash='$argon2id$hash',
        is_active=True,
        is_admin=False,
        is_service_account=False,
        created_at=datetime.datetime.now(datetime.UTC),
    )
    auth_context = permissions.AuthContext(
        user=user,
        session_id='test',
        auth_method='jwt',
        permissions=permissions_set,
    )

    async def _current_user() -> permissions.AuthContext:
        return auth_context

    test_app.dependency_overrides[permissions.get_current_user] = _current_user

    db = mock.AsyncMock(spec=graph.Graph)
    test_app.dependency_overrides[graph._inject_graph] = lambda: db
    return test_app, db


class _Rows:
    """Configurable singleton store for LocalAuthConfig."""

    def __init__(self) -> None:
        self.local: domain_models.LocalAuthConfig | None = None

    async def match(
        self,
        model: typing.Any,
        criteria: dict[str, typing.Any] | None = None,
        order_by: str | None = None,
    ) -> list[typing.Any]:
        if model is domain_models.LocalAuthConfig:
            return [self.local] if self.local is not None else []
        return []

    async def merge(
        self,
        node: typing.Any,
        match_on: list[str] | None = None,
    ) -> None:
        if isinstance(node, domain_models.LocalAuthConfig):
            self.local = node

    async def execute(
        self,
        query: typing.Any,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, typing.Any]]:
        # No login providers in this test fixture.
        return []


def _wire_db(db: mock.AsyncMock, rows: _Rows) -> None:
    db.match.side_effect = rows.match
    db.merge.side_effect = rows.merge
    db.execute.side_effect = rows.execute


def _reset_caches() -> None:
    local_auth._invalidate_cache()
    login_providers.invalidate_cache()


class AdminLocalAuthEndpointTestCase(unittest.TestCase):
    """``/admin/local-auth`` GET/PUT + permission gating."""

    def setUp(self) -> None:
        _reset_caches()
        self.test_app, self.db = _build_app(
            {'auth_providers:read', 'auth_providers:write'}
        )
        self.rows = _Rows()
        _wire_db(self.db, self.rows)
        self.client = testclient.TestClient(self.test_app)

    def test_get_default_when_no_row(self) -> None:
        response = self.client.get('/admin/local-auth')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['enabled'])
        self.assertIn('updated_at', body)

    def test_put_persists_and_round_trips(self) -> None:
        response = self.client.put(
            '/admin/local-auth',
            json={'enabled': False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['enabled'])
        # Subsequent GET reflects the persisted value
        get_response = self.client.get('/admin/local-auth')
        self.assertEqual(get_response.status_code, 200)
        self.assertFalse(get_response.json()['enabled'])

    def test_put_requires_write_permission(self) -> None:
        _reset_caches()
        read_only_app, read_only_db = _build_app({'auth_providers:read'})
        rows = _Rows()
        _wire_db(read_only_db, rows)
        client = testclient.TestClient(read_only_app)
        response = client.put('/admin/local-auth', json={'enabled': False})
        self.assertEqual(response.status_code, 403)

    def test_get_requires_read_permission(self) -> None:
        _reset_caches()
        no_perm_app, no_perm_db = _build_app(set())
        rows = _Rows()
        _wire_db(no_perm_db, rows)
        client = testclient.TestClient(no_perm_app)
        response = client.get('/admin/local-auth')
        self.assertEqual(response.status_code, 403)


class AuthProvidersLocalToggleTestCase(unittest.TestCase):
    """``/auth/providers`` honors the local-auth toggle."""

    def setUp(self) -> None:
        _reset_caches()
        self.test_app, self.db = _build_app(set())
        self.rows = _Rows()
        _wire_db(self.db, self.rows)
        self.client = testclient.TestClient(self.test_app)

    def test_local_present_when_enabled(self) -> None:
        self.rows.local = domain_models.LocalAuthConfig(enabled=True)
        response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        ids = [p['id'] for p in response.json()['providers']]
        self.assertIn('local', ids)

    def test_local_absent_when_disabled(self) -> None:
        self.rows.local = domain_models.LocalAuthConfig(enabled=False)
        response = self.client.get('/auth/providers')
        self.assertEqual(response.status_code, 200)
        ids = [p['id'] for p in response.json()['providers']]
        self.assertNotIn('local', ids)
