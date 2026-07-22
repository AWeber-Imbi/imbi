"""Tests for the global login-provider (auth provider) endpoints."""

import datetime
import typing
from unittest import mock

from fastapi import testclient

from apps.api.tests import support
from imbi.api import models
from imbi.api.auth import password, permissions
from imbi.common import graph
from imbi.common.plugins.base import (
    Capability,
    IdentityCapability,
    Plugin,
    PluginManifest,
)
from imbi.common.plugins.registry import RegistryEntry


class _FakeIdentity(IdentityCapability):
    pass


class _FakePlugin(Plugin):
    pass


def _identity_manifest(login_capable: bool = True) -> PluginManifest:
    return PluginManifest(
        slug='google',
        name='Google',
        capabilities=[
            Capability(
                kind='identity',
                label='Identity',
                handler=_FakeIdentity,
                hints={'login_capable': login_capable},
            )
        ],
    )


def _entry(manifest: PluginManifest) -> RegistryEntry:
    return support.registry_entry(manifest, plugin_cls=_FakePlugin)


def _node(slug: str = 'google', **over: typing.Any) -> dict[str, object]:
    """A hydrated org-less login-provider Integration node."""
    node: dict[str, typing.Any] = {
        'id': 'abc123',
        'plugin': 'google',
        'name': 'Google',
        'slug': slug,
        'status': 'active',
        'options': {},
        'capabilities': {'identity': {'enabled': True, 'options': {}}},
        'links': {},
        'identifiers': {},
        'encrypted_credentials': {},
        'organization': None,
        'team': None,
    }
    node.update(over)
    return node


class AuthProvidersEndpointTestCase(support.SharedAppTestCase):
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
            permissions={
                'integration:create',
                'integration:read',
                'integration:update',
                'integration:delete',
            },
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
        self.client = testclient.TestClient(self.test_app)

    def _patch_encryptor(self) -> typing.Any:
        encryptor = mock.Mock()
        encryptor.encrypt.side_effect = lambda v: f'enc:{v}'
        token = mock.Mock()
        token.get_instance.return_value = encryptor
        return mock.patch(
            'imbi.api.endpoints.auth_providers.TokenEncryption', token
        )

    # -- list / get ------------------------------------------------------

    def test_list_login_providers(self) -> None:
        self.mock_db.execute.return_value = [{'integration': _node()}]
        response = self.client.get('/login-providers/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'google')
        self.assertIsNone(data[0]['organization'])

    def test_get_login_provider(self) -> None:
        self.mock_db.execute.return_value = [{'integration': _node()}]
        response = self.client.get('/login-providers/google')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['slug'], 'google')

    def test_get_login_provider_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.get('/login-providers/missing')
        self.assertEqual(response.status_code, 404)

    # -- create ----------------------------------------------------------

    def test_create_login_provider(self) -> None:
        self.mock_db.execute.return_value = [{'integration': _node()}]
        with (
            _MultiPatch(_entry(_identity_manifest())),
            self._patch_encryptor(),
        ):
            response = self.client.post(
                '/login-providers/',
                json={
                    'plugin': 'google',
                    'name': 'Google',
                    'slug': 'google',
                    'credentials': {'client_id': 'cid'},
                    'capabilities': {'identity': {'enabled': True}},
                },
            )
        self.assertEqual(response.status_code, 201)
        params = self.mock_db.execute.call_args.args[1]
        # An id is generated and no organization edge is created.
        self.assertIn('id', params)
        self.assertTrue(params['id'])
        self.assertEqual(
            params['encrypted_credentials'], {'client_id': 'enc:cid'}
        )

    def test_create_login_provider_not_login_capable(self) -> None:
        with _MultiPatch(_entry(_identity_manifest(login_capable=False))):
            response = self.client.post(
                '/login-providers/',
                json={'plugin': 'google', 'name': 'Google', 'slug': 'google'},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('login-capable', response.json()['detail'])

    # -- update ----------------------------------------------------------

    def test_update_login_provider_merges(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'integration': _node()}],
            [{'integration': _node(options={'hd': 'example.com'})}],
        ]
        response = self.client.patch(
            '/login-providers/google',
            json={'options': {'hd': 'example.com'}},
        )
        self.assertEqual(response.status_code, 200)

    def test_update_login_provider_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.patch(
            '/login-providers/missing', json={'name': 'x'}
        )
        self.assertEqual(response.status_code, 404)

    def test_update_login_provider_vanishes_returns_404(self) -> None:
        # The initial lookup succeeds but the org-less scoped update matches
        # nothing (concurrent delete / organization-owned) -> 404, not 500.
        self.mock_db.execute.side_effect = [
            [{'integration': _node()}],  # initial lookup
            [],  # scoped update matched no org-less row
        ]
        response = self.client.patch(
            '/login-providers/google',
            json={'options': {'hd': 'example.com'}},
        )
        self.assertEqual(response.status_code, 404)

    # -- credentials -----------------------------------------------------

    def test_update_credentials(self) -> None:
        with mock.patch(
            'imbi.api.endpoints.auth_providers.patch_integration_credentials',
            return_value=['client_id'],
        ) as patch_creds:
            response = self.client.put(
                '/login-providers/google/credentials',
                json={'credentials': {'client_id': 'cid'}},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'credential_fields': ['client_id']})
        # org_slug is None for a global login provider.
        self.assertIsNone(patch_creds.call_args.args[2])

    # -- used-as-login ---------------------------------------------------

    def test_set_used_as_login_promotes(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'integration': _node(used_as_login=True)}],  # promote target
            [],  # demote org-less others
        ]
        with mock.patch(
            'imbi.api.endpoints.auth_providers.login_repo.invalidate_cache'
        ) as invalidate:
            response = self.client.put(
                '/login-providers/google/used-as-login',
                json={'used_as_login': True},
            )
        self.assertEqual(response.status_code, 200)
        invalidate.assert_called_once()
        self.assertTrue(response.json()['used_as_login'])

    def test_set_used_as_login_not_found(self) -> None:
        self.mock_db.execute.side_effect = [[], []]
        with mock.patch(
            'imbi.api.endpoints.auth_providers.login_repo.invalidate_cache'
        ):
            response = self.client.put(
                '/login-providers/missing/used-as-login',
                json={'used_as_login': True},
            )
        self.assertEqual(response.status_code, 404)

    def test_set_used_as_login_missing_target_does_not_demote(self) -> None:
        # A missing (or organization-owned) target must 404 before demoting
        # any active provider, so the existing SSO provider stays enabled.
        self.mock_db.execute.side_effect = [[]]
        with mock.patch(
            'imbi.api.endpoints.auth_providers.login_repo.invalidate_cache'
        ) as invalidate:
            response = self.client.put(
                '/login-providers/missing/used-as-login',
                json={'used_as_login': True},
            )
        self.assertEqual(response.status_code, 404)
        # Only the promote query ran; demotion was never issued.
        self.assertEqual(self.mock_db.execute.call_count, 1)
        invalidate.assert_not_called()

    # -- delete ----------------------------------------------------------

    def test_delete_login_provider(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 1}]
        with mock.patch(
            'imbi.api.endpoints.auth_providers.login_repo.invalidate_cache'
        ):
            response = self.client.delete('/login-providers/google')
        self.assertEqual(response.status_code, 204)

    def test_delete_login_provider_not_found(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 0}]
        with mock.patch(
            'imbi.api.endpoints.auth_providers.login_repo.invalidate_cache'
        ):
            response = self.client.delete('/login-providers/missing')
        self.assertEqual(response.status_code, 404)


class _MultiPatch:
    """Patch ``get_plugin`` in both modules create/validate consult."""

    def __init__(self, entry: RegistryEntry) -> None:
        self._patches = [
            mock.patch(
                'imbi.api.endpoints.auth_providers.get_plugin',
                return_value=entry,
            ),
            mock.patch(
                'imbi.api.endpoints.integrations.get_plugin',
                return_value=entry,
            ),
        ]

    def __enter__(self) -> None:
        for p in self._patches:
            p.start()

    def __exit__(self, *exc: object) -> None:
        for p in self._patches:
            p.stop()
