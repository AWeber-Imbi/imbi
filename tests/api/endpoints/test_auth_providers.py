"""Tests for the /admin/auth-providers admin endpoints."""

from __future__ import annotations

import datetime
import json
import typing
import unittest
from unittest import mock

import psycopg
from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models
from imbi_api.auth import login_providers


class _FakeEncryptor:
    def encrypt(self, value: str | None) -> str | None:
        if value is None:
            return None
        return f'enc:{value}'

    def decrypt(self, value: str | None) -> str | None:
        if value is None:
            return None
        return value.removeprefix('enc:')


def _patch_encryptor() -> typing.Any:
    return mock.patch(
        'imbi_common.auth.encryption.TokenEncryption.get_instance',
        return_value=_FakeEncryptor(),
    )


def _build_app(
    permissions_set: set[str], *, is_admin: bool = False
) -> tuple[typing.Any, mock.AsyncMock]:
    from imbi_api.auth import permissions

    test_app = app.create_app()
    user = models.User(
        email='admin@example.com',
        display_name='Admin',
        password_hash='$argon2id$hash',
        is_active=True,
        is_admin=is_admin,
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


def _row(
    slug: str = 'google',
    *,
    usage: str = 'login',
    oauth_app_type: str = 'google',
) -> dict[str, typing.Any]:
    return {
        'app': {
            'slug': slug,
            'name': 'Google',
            'usage': usage,
            'oauth_app_type': oauth_app_type,
            'client_id': 'cid',
            'client_secret': 'enc:keep',
            'issuer_url': None,
            'allowed_domains': json.dumps([]),
            'scopes': json.dumps([]),
            'status': 'active',
            'description': None,
        },
        'service': {
            'slug': 'svc',
            'name': 'SVC',
            'authorization_endpoint': 'https://auth/authorize',
            'token_endpoint': 'https://auth/token',
            'revoke_endpoint': None,
        },
        'organization': {'slug': 'eng', 'name': 'Engineering'},
    }


class AuthProvidersEndpointTestCase(unittest.TestCase):
    def setUp(self) -> None:
        login_providers.invalidate_cache()
        self.test_app, self.db = _build_app(
            {'auth_providers:read', 'auth_providers:write'}
        )
        self.client = testclient.TestClient(self.test_app)

    def test_list_requires_permission(self) -> None:
        no_perm_app, _ = _build_app(set())
        client = testclient.TestClient(no_perm_app)
        response = client.get('/admin/auth-providers')
        self.assertEqual(response.status_code, 403)

    def test_list_returns_rows(self) -> None:
        self.db.execute.return_value = [
            _row('google'),
            _row('github', oauth_app_type='github'),
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get('/admin/auth-providers')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual({r['slug'] for r in body}, {'google', 'github'})

    def test_get_missing_returns_404(self) -> None:
        self.db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get('/admin/auth-providers/nope')
        self.assertEqual(response.status_code, 404)

    def test_get_integration_only_returns_404(self) -> None:
        self.db.execute.return_value = [_row('integ', usage='integration')]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get('/admin/auth-providers/integ')
        self.assertEqual(response.status_code, 404)

    def test_delete_refuses_both(self) -> None:
        self.db.execute.return_value = [_row('google', usage='both')]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.delete('/admin/auth-providers/google')
        self.assertEqual(response.status_code, 409)

    def test_delete_login_succeeds(self) -> None:
        self.db.execute.side_effect = [
            [_row('google', usage='login')],
            [],  # delete query
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.delete('/admin/auth-providers/google')
        self.assertEqual(response.status_code, 204)

    def test_create_requires_write(self) -> None:
        ro_app, _ = _build_app({'auth_providers:read'})
        client = testclient.TestClient(ro_app)
        response = client.post(
            '/admin/auth-providers',
            json={
                'org_slug': 'eng',
                'third_party_service_slug': 'svc',
                'slug': 'google',
                'name': 'Google',
                'oauth_app_type': 'google',
                'client_id': 'cid',
                'client_secret': 'shh',
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_blank_secret_preserves_existing(self) -> None:
        # PUT with blank client_secret should keep the encrypted value.
        existing = _row('google', usage='login')
        self.db.execute.side_effect = [
            [existing],  # initial fetch
            [],  # update SET
            [existing],  # re-fetch
        ]
        with (
            _patch_encryptor(),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.put(
                '/admin/auth-providers/google',
                json={
                    'name': 'Google Renamed',
                    'oauth_app_type': 'google',
                    'client_id': 'cid',
                    'client_secret': '',
                    'usage': 'login',
                },
            )
        self.assertEqual(response.status_code, 200)
        # The middle execute call should NOT include a client_secret param,
        # confirming we didn't overwrite it with the empty string.
        update_call_args = self.db.execute.call_args_list[1]
        params = update_call_args.args[1]
        self.assertNotIn('client_secret', params)

    def test_get_returns_full_response(self) -> None:
        self.db.execute.return_value = [_row('google', usage='login')]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get('/admin/auth-providers/google')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['slug'], 'google')
        self.assertEqual(body['organization_slug'], 'eng')
        self.assertEqual(body['third_party_service_slug'], 'svc')
        self.assertTrue(body['has_secret'])

    def test_create_new_row(self) -> None:
        # No existing row, then a CREATE returns the new app.
        new = _row('google', usage='login')
        self.db.execute.side_effect = [
            [],  # _FETCH_BY_SLUG initial check
            [new],  # CREATE
        ]
        with (
            _patch_encryptor(),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.post(
                '/admin/auth-providers',
                json={
                    'org_slug': 'eng',
                    'third_party_service_slug': 'svc',
                    'slug': 'google',
                    'name': 'Google',
                    'oauth_app_type': 'google',
                    'client_id': 'cid',
                    'client_secret': 'shh',
                },
            )
        self.assertEqual(response.status_code, 201)

    def test_create_promotes_existing_row(self) -> None:
        # Existing row → promote path: fetch returns row, SET, re-fetch.
        existing = _row('google', usage='integration')
        promoted = _row('google', usage='login')
        self.db.execute.side_effect = [
            [existing],  # _FETCH_BY_SLUG initial check
            [],  # SET
            [promoted],  # re-fetch
        ]
        with (
            _patch_encryptor(),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.post(
                '/admin/auth-providers',
                json={
                    'org_slug': 'eng',
                    'third_party_service_slug': 'svc',
                    'slug': 'google',
                    'name': 'Google',
                    'oauth_app_type': 'google',
                    'client_id': 'cid',
                    'client_secret': 'shh',
                    'usage': 'login',
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['usage'], 'login')

    def test_create_unique_violation_returns_409(self) -> None:
        self.db.execute.side_effect = [
            [],  # initial fetch — no existing
            psycopg.errors.UniqueViolation('dup'),  # CREATE
        ]
        with (
            _patch_encryptor(),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.post(
                '/admin/auth-providers',
                json={
                    'org_slug': 'eng',
                    'third_party_service_slug': 'svc',
                    'slug': 'google',
                    'name': 'Google',
                    'oauth_app_type': 'google',
                    'client_id': 'cid',
                    'client_secret': 'shh',
                },
            )
        self.assertEqual(response.status_code, 409)

    def test_create_missing_org_or_service_returns_404(self) -> None:
        self.db.execute.side_effect = [
            [],  # initial fetch — no existing
            [],  # CREATE returned nothing — org/service missing
        ]
        with (
            _patch_encryptor(),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.post(
                '/admin/auth-providers',
                json={
                    'org_slug': 'missing',
                    'third_party_service_slug': 'missing',
                    'slug': 'google',
                    'name': 'Google',
                    'oauth_app_type': 'google',
                    'client_id': 'cid',
                    'client_secret': 'shh',
                },
            )
        self.assertEqual(response.status_code, 404)

    def test_create_oidc_requires_issuer_url(self) -> None:
        # validate_login_app_fields rejects OIDC without issuer_url.
        response = self.client.post(
            '/admin/auth-providers',
            json={
                'org_slug': 'eng',
                'third_party_service_slug': 'svc',
                'slug': 'okta',
                'name': 'Okta',
                'oauth_app_type': 'oidc',
                'client_id': 'cid',
                'client_secret': 'shh',
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_update_with_explicit_secret_encrypts(self) -> None:
        existing = _row('google', usage='login')
        self.db.execute.side_effect = [
            [existing],  # initial fetch
            [],  # update SET
            [existing],  # re-fetch
        ]
        with (
            _patch_encryptor(),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.put(
                '/admin/auth-providers/google',
                json={
                    'name': 'Google',
                    'oauth_app_type': 'google',
                    'client_id': 'cid',
                    'client_secret': 'new-secret',
                    'usage': 'login',
                },
            )
        self.assertEqual(response.status_code, 200)
        update_call_args = self.db.execute.call_args_list[1]
        params = update_call_args.args[1]
        self.assertEqual(params['client_secret'], 'enc:new-secret')

    def test_update_missing_returns_404(self) -> None:
        self.db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.put(
                '/admin/auth-providers/missing',
                json={
                    'name': 'X',
                    'oauth_app_type': 'google',
                    'client_id': 'cid',
                    'client_secret': '',
                    'usage': 'login',
                },
            )
        self.assertEqual(response.status_code, 404)

    def test_update_integration_only_returns_404(self) -> None:
        self.db.execute.return_value = [_row('integ', usage='integration')]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.put(
                '/admin/auth-providers/integ',
                json={
                    'name': 'X',
                    'oauth_app_type': 'google',
                    'client_id': 'cid',
                    'client_secret': '',
                    'usage': 'login',
                },
            )
        self.assertEqual(response.status_code, 404)

    def test_delete_missing_returns_404(self) -> None:
        self.db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.delete('/admin/auth-providers/missing')
        self.assertEqual(response.status_code, 404)

    def test_delete_integration_only_returns_404(self) -> None:
        self.db.execute.return_value = [_row('integ', usage='integration')]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.delete('/admin/auth-providers/integ')
        self.assertEqual(response.status_code, 404)

    def test_promote_to_both_succeeds(self) -> None:
        existing = _row('google', usage='login')
        promoted = _row('google', usage='both')
        self.db.execute.side_effect = [
            [existing],  # initial fetch
            [],  # SET
            [promoted],  # re-fetch
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/admin/auth-providers/google/promote-to-both'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['usage'], 'both')

    def test_promote_to_both_rejects_wrong_state(self) -> None:
        self.db.execute.return_value = [_row('google', usage='both')]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/admin/auth-providers/google/promote-to-both'
            )
        self.assertEqual(response.status_code, 409)

    def test_promote_missing_returns_404(self) -> None:
        self.db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/admin/auth-providers/missing/promote-to-both'
            )
        self.assertEqual(response.status_code, 404)

    def test_demote_to_login_succeeds(self) -> None:
        existing = _row('google', usage='both')
        demoted = _row('google', usage='login')
        self.db.execute.side_effect = [
            [existing],  # initial fetch
            [],  # SET
            [demoted],  # re-fetch
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/admin/auth-providers/google/demote-to-login'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['usage'], 'login')

    def test_demote_to_login_rejects_wrong_state(self) -> None:
        self.db.execute.return_value = [_row('google', usage='login')]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/admin/auth-providers/google/demote-to-login'
            )
        self.assertEqual(response.status_code, 409)

    def test_create_collision_under_different_service_returns_409(
        self,
    ) -> None:
        # Existing row's parent svc/org differs from the request — must 409.
        existing = _row('google', usage='login')
        # The default `_row` uses svc='svc', org='eng'. POST a different
        # parent so the collision guard fires.
        self.db.execute.side_effect = [
            [existing],  # initial fetch finds the row
        ]
        with (
            _patch_encryptor(),
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
        ):
            response = self.client.post(
                '/admin/auth-providers',
                json={
                    'org_slug': 'other-org',
                    'third_party_service_slug': 'other-svc',
                    'slug': 'google',
                    'name': 'Google',
                    'oauth_app_type': 'google',
                    'client_id': 'cid',
                    'client_secret': 'shh',
                    'usage': 'login',
                },
            )
        self.assertEqual(response.status_code, 409)
        # Update SET must NOT have been issued.
        self.assertEqual(self.db.execute.call_count, 1)
