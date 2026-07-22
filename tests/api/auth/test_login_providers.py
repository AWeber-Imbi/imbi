"""Tests for the login-provider repository (Plugin Architecture v3).

A login provider is now an ``Integration`` node carrying a direct
``used_as_login=true`` property whose plugin declares a login-capable
``identity`` capability. The repository queries those Integrations,
hydrates them, resolves the plugin via ``get_plugin``, checks the
identity capability's ``login_capable`` hint plus ``capability_enabled``,
and decrypts the stored credentials into a flat :class:`LoginApp`.
"""

from __future__ import annotations

import typing
import unittest
from unittest import mock

from imbi.api.auth import login_providers
from imbi.common.plugins.base import (
    Capability,
    IdentityCapability,
    LogsCapability,
    Plugin,
    PluginManifest,
)
from imbi.common.plugins.errors import PluginNotFoundError
from imbi.common.plugins.registry import RegistryEntry


class _FakeIdentity(IdentityCapability):
    """Minimal identity handler; login_providers never instantiates it."""

    async def authorization_request(
        self, *args: typing.Any, **kwargs: typing.Any
    ) -> typing.Any:
        raise NotImplementedError

    async def exchange_code(
        self, *args: typing.Any, **kwargs: typing.Any
    ) -> typing.Any:
        raise NotImplementedError

    async def refresh(
        self, *args: typing.Any, **kwargs: typing.Any
    ) -> typing.Any:
        raise NotImplementedError


class _FakeLogs(LogsCapability):
    """Non-identity handler used to keep a manifest valid when it must
    declare a capability other than ``identity``."""

    async def search(
        self, *args: typing.Any, **kwargs: typing.Any
    ) -> typing.Any:
        raise NotImplementedError

    async def schema(
        self, *args: typing.Any, **kwargs: typing.Any
    ) -> typing.Any:
        raise NotImplementedError


class _FakePlugin(Plugin):
    """Concrete Plugin subclass to satisfy ``RegistryEntry.plugin_cls``."""


def _entry(
    plugin_slug: str = 'okta',
    *,
    login_capable: bool = True,
    has_identity: bool = True,
    auth_type: str = 'oidc',
) -> RegistryEntry:
    """Build a v3 registry entry whose manifest carries an identity
    capability with the ``login_capable`` hint."""
    capabilities: list[Capability] = []
    if has_identity:
        capabilities.append(
            Capability(
                kind='identity',
                label='Identity',
                hints={'login_capable': True} if login_capable else {},
                handler=_FakeIdentity,
            )
        )
    else:
        # A manifest must declare at least one capability; use a
        # non-identity one so the login source correctly skips it.
        capabilities.append(
            Capability(kind='logs', label='Logs', handler=_FakeLogs)
        )
    manifest = PluginManifest(
        slug=plugin_slug,
        name=plugin_slug.title(),
        auth_type=auth_type,  # type: ignore[arg-type]
        capabilities=capabilities,
    )
    return RegistryEntry(
        plugin_cls=_FakePlugin,
        manifest=manifest,
        package_name=f'imbi-plugin-{plugin_slug}',
        package_version='1.0.0',
    )


def _integration_row(
    slug: str,
    *,
    plugin: str = 'okta',
    name: str | None = None,
    status: str = 'active',
    integration_id: str | None = None,
    options: dict[str, typing.Any] | None = None,
    credentials: dict[str, str] | None = None,
    identity_enabled: bool = True,
) -> dict[str, typing.Any]:
    """Build hydrated ``Integration`` node props for a login provider."""
    return {
        'id': integration_id or f'int-{slug}',
        'slug': slug,
        'name': name or slug,
        'plugin': plugin,
        'status': status,
        'used_as_login': True,
        'options': options or {},
        'encrypted_credentials': credentials or {},
        'capabilities': {'identity': {'enabled': identity_enabled}},
    }


class _FakeDB:
    """DB stub returning ``Integration`` rows under the ``i`` column."""

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
        rows = self.rows
        if slug is not None:
            rows = [r for r in rows if r['slug'] == slug]
        return [{'i': row} for row in rows]


def _patch_resolution(
    entries: dict[str, RegistryEntry] | None = None,
) -> typing.Any:
    """Patch ``get_plugin``/``decrypt_integration_credentials`` on the
    ``login_providers`` module.

    ``get_plugin`` resolves per plugin slug from ``entries`` (default: a
    single login-capable ``okta`` plugin), raising
    :class:`PluginNotFoundError` for anything unknown.
    ``decrypt_integration_credentials`` round-trips the stored map.
    """
    registry = entries if entries is not None else {'okta': _entry('okta')}

    def _get_plugin(slug: str) -> RegistryEntry:
        try:
            return registry[slug]
        except KeyError as exc:
            raise PluginNotFoundError(slug) from exc

    return mock.patch.multiple(
        login_providers,
        get_plugin=_get_plugin,
        decrypt_integration_credentials=lambda creds: dict(creds or {}),
    )


class LoginProvidersRepoTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        login_providers.invalidate_cache()

    async def test_list_login_apps_empty(self) -> None:
        db = _FakeDB([])
        with _patch_resolution():
            rows = await login_providers.list_login_apps(db)  # type: ignore[arg-type]
        self.assertEqual(rows, [])

    async def test_list_login_apps_filters_enabled(self) -> None:
        db = _FakeDB(
            [
                _integration_row('a', status='active'),
                _integration_row('b', status='inactive'),
            ]
        )
        with _patch_resolution():
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
        with _patch_resolution():
            row = await login_providers.get_login_app(db, 'absent')  # type: ignore[arg-type]
        self.assertIsNone(row)

    async def test_get_login_app_returns_row(self) -> None:
        db = _FakeDB(
            [
                _integration_row(
                    'okta-prod',
                    plugin='okta',
                    options={
                        'oauth_app_type': 'oidc',
                        'token_endpoint': 'https://auth/token',
                        'issuer_url': 'https://auth',
                    },
                    credentials={'client_id': 'cid', 'client_secret': 'sec'},
                )
            ]
        )
        with _patch_resolution():
            row = await login_providers.get_login_app(db, 'okta-prod')  # type: ignore[arg-type]
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.slug, 'okta-prod')
        self.assertEqual(row.integration_id, 'int-okta-prod')
        self.assertEqual(row.oauth_app_type, 'oidc')
        self.assertEqual(row.token_endpoint, 'https://auth/token')
        self.assertEqual(row.client_id, 'cid')
        self.assertEqual(row.client_secret, 'sec')

    async def test_oauth_app_type_defaults_to_plugin_auth_type(self) -> None:
        """With no ``oauth_app_type`` option, the plugin's ``auth_type``
        is used."""
        db = _FakeDB([_integration_row('okta-prod', plugin='okta')])
        with _patch_resolution({'okta': _entry('okta', auth_type='oidc')}):
            row = await login_providers.get_login_app(db, 'okta-prod')  # type: ignore[arg-type]
        assert row is not None
        self.assertEqual(row.oauth_app_type, 'oidc')

    async def test_skips_plugin_without_identity_capability(self) -> None:
        db = _FakeDB([_integration_row('x', plugin='noident')])
        with _patch_resolution(
            {'noident': _entry('noident', has_identity=False)}
        ):
            rows = await login_providers.list_login_apps(db)  # type: ignore[arg-type]
        self.assertEqual(rows, [])

    async def test_skips_plugin_not_login_capable(self) -> None:
        db = _FakeDB([_integration_row('x', plugin='plain')])
        with _patch_resolution(
            {'plain': _entry('plain', login_capable=False)}
        ):
            rows = await login_providers.list_login_apps(db)  # type: ignore[arg-type]
        self.assertEqual(rows, [])

    async def test_skips_disabled_identity_capability(self) -> None:
        db = _FakeDB(
            [_integration_row('x', plugin='okta', identity_enabled=False)]
        )
        with _patch_resolution():
            rows = await login_providers.list_login_apps(db)  # type: ignore[arg-type]
        self.assertEqual(rows, [])

    async def test_skips_unknown_plugin(self) -> None:
        db = _FakeDB([_integration_row('x', plugin='ghost')])
        # Empty registry -> get_plugin raises PluginNotFoundError.
        with _patch_resolution({}):
            rows = await login_providers.list_login_apps(db)  # type: ignore[arg-type]
        self.assertEqual(rows, [])

    async def test_cache_invalidation(self) -> None:
        db = _FakeDB([_integration_row('okta-prod', plugin='okta')])
        with _patch_resolution():
            first = await login_providers.get_login_app(db, 'okta-prod')  # type: ignore[arg-type]
            # Returns cached value even after rows are mutated.
            db.rows = []
            second = await login_providers.get_login_app(db, 'okta-prod')  # type: ignore[arg-type]
            self.assertIsNotNone(first)
            self.assertEqual(first, second)
            login_providers.invalidate_cache('okta-prod')
            third = await login_providers.get_login_app(db, 'okta-prod')  # type: ignore[arg-type]
        self.assertIsNone(third)
