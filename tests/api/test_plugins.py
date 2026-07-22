"""Tests for the plugin infrastructure modules."""

from __future__ import annotations

import asyncio
import json
import typing
import unittest
from unittest import mock

if typing.TYPE_CHECKING:
    from imbi_common.plugins.registry import RegistryEntry


class ParseOptionsTestCase(unittest.TestCase):
    """The unified ``parse_options`` subsumes every input layer."""

    def test_none_yields_empty_dict(self) -> None:
        from imbi_api.plugins import parse_options

        self.assertEqual(parse_options(None), {})

    def test_dict_passes_through(self) -> None:
        from imbi_api.plugins import parse_options

        self.assertEqual(parse_options({'k': 'v'}), {'k': 'v'})

    def test_single_encoded_json_string(self) -> None:
        from imbi_api.plugins import parse_options

        self.assertEqual(parse_options(json.dumps({'k': 'v'})), {'k': 'v'})

    def test_raw_agtype_double_encoded_string(self) -> None:
        # AGE returns a string property as a JSON-quoted string, so a
        # stored ``'{"k": "v"}'`` round-trips as ``'"{\\"k\\": \\"v\\"}"'``.
        from imbi_api.plugins import parse_options

        raw = json.dumps(json.dumps({'k': 'v'}))
        self.assertEqual(parse_options(raw), {'k': 'v'})

    def test_malformed_json_yields_empty_dict(self) -> None:
        from imbi_api.plugins import parse_options

        self.assertEqual(parse_options('{not json'), {})

    def test_non_object_json_yields_empty_dict(self) -> None:
        from imbi_api.plugins import parse_options

        self.assertEqual(parse_options(json.dumps([1, 2, 3])), {})


class LifecycleTestCase(unittest.TestCase):
    def test_startup_load_plugins_logs(self) -> None:
        from imbi_common.plugins.registry import LoadResult

        from imbi_api.plugins import lifecycle

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_api.plugins.lifecycle.load_plugins',
                return_value=LoadResult(
                    loaded=['ssm'],
                    errors={},
                    skipped=[],
                ),
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.list_plugins',
                return_value=[],
            ),
        ):
            asyncio.run(lifecycle.startup_load_plugins(mock_db))

    def test_is_plugin_enabled_true(self) -> None:
        from imbi_api.plugins.lifecycle import is_plugin_enabled

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'enabled': True}]
        result = asyncio.run(is_plugin_enabled(mock_db, 'ssm'))
        self.assertTrue(result)

    def test_is_plugin_enabled_no_record(self) -> None:
        from imbi_api.plugins.lifecycle import is_plugin_enabled

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []
        result = asyncio.run(is_plugin_enabled(mock_db, 'ssm'))
        self.assertFalse(result)

    def test_get_enabled_map(self) -> None:
        from imbi_api.plugins.lifecycle import get_enabled_map

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {'slug': 'ssm', 'enabled': True},
            {'slug': 'logzio', 'enabled': False},
        ]
        result = asyncio.run(get_enabled_map(mock_db))
        self.assertEqual(result, {'ssm': True, 'logzio': False})

    def test_audit_unavailable_handles_error(self) -> None:
        from imbi_api.plugins import lifecycle

        mock_db = mock.AsyncMock()
        mock_db.execute.side_effect = RuntimeError('db error')

        with mock.patch(
            'imbi_api.plugins.lifecycle.list_plugins',
            return_value=[],
        ):
            asyncio.run(lifecycle.audit_unavailable(mock_db))


class ReloadHookTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_reload_hook_no_valkey(self) -> None:
        from imbi_api.plugins.reload import plugin_reload_hook

        with mock.patch(
            'imbi_api.plugins.reload.valkey.get_client',
            side_effect=RuntimeError('no valkey'),
        ):
            async with plugin_reload_hook(db=None):
                pass

    async def test_plugin_reload_hook_no_db(self) -> None:
        from imbi_api.plugins.reload import plugin_reload_hook

        mock_client = mock.MagicMock()
        with mock.patch(
            'imbi_api.plugins.reload.valkey.get_client',
            return_value=mock_client,
        ):
            async with plugin_reload_hook(db=None):
                pass

    async def test_publish_reload(self) -> None:
        from imbi_api.plugins import reload as reload_mod

        mock_client = mock.AsyncMock()
        derived = b'k' * 32

        with mock.patch.object(
            reload_mod, '_get_reload_key', return_value=derived
        ):
            await reload_mod.publish_reload(mock_client)

        mock_client.publish.assert_awaited_once()
        channel, payload = mock_client.publish.await_args.args
        self.assertEqual(channel, 'imbi:plugins:reload')
        self.assertTrue(reload_mod._verify(payload, derived))

    async def test_publish_reload_raises_without_key(self) -> None:
        from imbi_api.plugins import reload as reload_mod

        mock_client = mock.AsyncMock()
        with (
            mock.patch.object(
                reload_mod, '_get_reload_key', return_value=None
            ),
            self.assertRaises(RuntimeError),
        ):
            await reload_mod.publish_reload(mock_client)
        mock_client.publish.assert_not_awaited()


class InstallerTestCase(unittest.TestCase):
    def test_install_disabled_raises(self) -> None:
        from imbi_api.plugins import installer
        from imbi_api.plugins.installer import InstallError

        with mock.patch.object(installer, '_INSTALL_ENABLED', False):
            with self.assertRaises(InstallError) as ctx:
                asyncio.run(installer.install_package('imbi-plugin-ssm'))
        self.assertIn('disabled', str(ctx.exception))

    def test_install_success(self) -> None:
        from imbi_common.plugins.registry import LoadResult

        from imbi_api.plugins import installer

        mock_proc = mock.MagicMock()
        mock_proc.communicate = mock.AsyncMock(return_value=(b'ok', b''))
        mock_proc.returncode = 0

        async def _exec(*_a: object, **_k: object) -> mock.MagicMock:
            return mock_proc

        with (
            mock.patch.object(
                installer.asyncio, 'create_subprocess_exec', _exec
            ),
            mock.patch.object(
                installer,
                'reload_plugins',
                return_value=LoadResult(loaded=['ssm'], errors={}, skipped=[]),
            ),
        ):
            result = asyncio.run(
                installer.install_package('imbi-plugin-ssm', '1.2.3')
            )
        self.assertEqual(result.loaded, ['ssm'])

    def test_install_nonzero_exit_raises(self) -> None:
        from imbi_api.plugins import installer
        from imbi_api.plugins.installer import InstallError

        mock_proc = mock.MagicMock()
        mock_proc.communicate = mock.AsyncMock(return_value=(b'', b'boom'))
        mock_proc.returncode = 1

        async def _exec(*_a: object, **_k: object) -> mock.MagicMock:
            return mock_proc

        with mock.patch.object(
            installer.asyncio, 'create_subprocess_exec', _exec
        ):
            with self.assertRaises(InstallError) as ctx:
                asyncio.run(installer.install_package('imbi-plugin-ssm'))
        self.assertIn('failed', str(ctx.exception))

    def test_install_timeout_raises(self) -> None:
        from imbi_api.plugins import installer
        from imbi_api.plugins.installer import InstallError

        mock_proc = mock.MagicMock()
        mock_proc.communicate = mock.AsyncMock(side_effect=TimeoutError())
        mock_proc.kill = mock.MagicMock()
        # ``installer`` drains the child via ``await proc.wait()`` after
        # killing it on timeout to avoid leaking fds.
        mock_proc.wait = mock.AsyncMock(return_value=-9)

        async def _exec(*_a: object, **_k: object) -> mock.MagicMock:
            return mock_proc

        with mock.patch.object(
            installer.asyncio, 'create_subprocess_exec', _exec
        ):
            with self.assertRaises(InstallError) as ctx:
                asyncio.run(installer.install_package('imbi-plugin-ssm'))
        self.assertIn('timed out', str(ctx.exception))
        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_awaited_once()

    def test_uninstall_success(self) -> None:
        from imbi_common.plugins.registry import LoadResult

        from imbi_api.plugins import installer

        mock_proc = mock.MagicMock()
        mock_proc.communicate = mock.AsyncMock(return_value=(b'', b''))
        mock_proc.returncode = 0

        async def _exec(*_a: object, **_k: object) -> mock.MagicMock:
            return mock_proc

        with (
            mock.patch.object(
                installer.asyncio, 'create_subprocess_exec', _exec
            ),
            mock.patch.object(
                installer,
                'reload_plugins',
                return_value=LoadResult(loaded=[], errors={}, skipped=[]),
            ),
        ):
            result = asyncio.run(
                installer.uninstall_package('imbi-plugin-ssm')
            )
        self.assertEqual(result.loaded, [])

    def test_uninstall_disabled_raises(self) -> None:
        from imbi_api.plugins import installer
        from imbi_api.plugins.installer import InstallError

        with mock.patch.object(installer, '_INSTALL_ENABLED', False):
            with self.assertRaises(InstallError):
                asyncio.run(installer.uninstall_package('imbi-plugin-ssm'))

    def test_uninstall_nonzero_exit_raises(self) -> None:
        from imbi_api.plugins import installer
        from imbi_api.plugins.installer import InstallError

        mock_proc = mock.MagicMock()
        mock_proc.communicate = mock.AsyncMock(return_value=(b'', b'oops'))
        mock_proc.returncode = 1

        async def _exec(*_a: object, **_k: object) -> mock.MagicMock:
            return mock_proc

        with mock.patch.object(
            installer.asyncio, 'create_subprocess_exec', _exec
        ):
            with self.assertRaises(InstallError):
                asyncio.run(installer.uninstall_package('imbi-plugin-ssm'))

    def test_uninstall_timeout_raises(self) -> None:
        from imbi_api.plugins import installer
        from imbi_api.plugins.installer import InstallError

        mock_proc = mock.MagicMock()
        mock_proc.communicate = mock.AsyncMock(side_effect=TimeoutError())
        mock_proc.kill = mock.MagicMock()
        mock_proc.wait = mock.AsyncMock(return_value=-9)

        async def _exec(*_a: object, **_k: object) -> mock.MagicMock:
            return mock_proc

        with mock.patch.object(
            installer.asyncio, 'create_subprocess_exec', _exec
        ):
            with self.assertRaises(InstallError) as ctx:
                asyncio.run(installer.uninstall_package('imbi-plugin-ssm'))
        self.assertIn('timed out', str(ctx.exception))
        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_awaited_once()


def _make_registry_entry(
    slug: str = 'ssm',
    kind: str = 'configuration',
) -> RegistryEntry:
    """Build a v3 RegistryEntry with a fake capability handler."""
    from imbi_common.plugins.base import (
        CAPABILITY_CONTRACTS,
        Capability,
        Plugin,
        PluginManifest,
    )
    from imbi_common.plugins.registry import RegistryEntry

    handler = type(f'_Fake{kind}', (CAPABILITY_CONTRACTS[kind],), {})
    manifest = PluginManifest(
        slug=slug,
        name=slug.upper(),
        auth_type='api_token',
        capabilities=[
            Capability(kind=kind, label=kind, handler=handler)  # type: ignore[arg-type]
        ],
    )

    class _FakePlugin(Plugin):
        pass

    _FakePlugin.manifest = manifest  # type: ignore[misc]

    return RegistryEntry(
        plugin_cls=_FakePlugin,
        manifest=manifest,
        package_name=f'imbi-plugin-{slug}',
        package_version='1.0.0',
    )


def _binding(
    *,
    integration_id: str = 'i1',
    slug: str = 'ssm-prod',
    plugin: str = 'ssm',
    source: str = 'project',
    default: bool = True,
    options: dict[str, typing.Any] | None = None,
) -> typing.Any:
    """Build a ``CapabilityBinding`` for the resolution helpers."""
    from imbi_api.plugins.assignments import CapabilityBinding

    return CapabilityBinding(
        integration={
            'id': integration_id,
            'slug': slug,
            'plugin': plugin,
        },
        source=source,  # type: ignore[arg-type]
        default=default,
        capability_options=options or {},
        env_payloads={},
        identity_integration_id=None,
    )


class ResolutionTestCase(unittest.TestCase):
    """Branch coverage for ``resolve_capability``."""

    def test_project_not_found_returns_404(self) -> None:
        from fastapi import HTTPException

        from imbi_api.plugins.resolution import resolve_capability

        mock_db = mock.AsyncMock()
        with mock.patch(
            'imbi_api.plugins.resolution.effective_bindings',
            new=mock.AsyncMock(side_effect=LookupError('p1')),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    resolve_capability(mock_db, 'p1', 'configuration', None)
                )
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn('Project not found', ctx.exception.detail)

    def test_no_integrations_bound_returns_404(self) -> None:
        from fastapi import HTTPException

        from imbi_api.plugins.resolution import resolve_capability

        mock_db = mock.AsyncMock()
        with mock.patch(
            'imbi_api.plugins.resolution.effective_bindings',
            new=mock.AsyncMock(return_value=[]),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    resolve_capability(mock_db, 'p1', 'configuration', None)
                )
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn('No integration', ctx.exception.detail)

    def test_single_integration_resolves(self) -> None:
        from imbi_api.plugins.resolution import resolve_capability

        mock_db = mock.AsyncMock()
        entry = _make_registry_entry('ssm')
        with (
            mock.patch(
                'imbi_api.plugins.resolution.effective_bindings',
                new=mock.AsyncMock(
                    return_value=[_binding(options={'region': 'us-east-1'})]
                ),
            ),
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin', return_value=entry
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.is_plugin_enabled',
                new=mock.AsyncMock(return_value=True),
            ),
        ):
            resolved = asyncio.run(
                resolve_capability(mock_db, 'proj1', 'configuration', None)
            )
        self.assertEqual(resolved.integration_id, 'i1')
        self.assertEqual(resolved.plugin_slug, 'ssm')
        self.assertEqual(resolved.kind, 'configuration')
        self.assertEqual(resolved.capability_options, {'region': 'us-east-1'})
        self.assertIs(
            resolved.capability_cls,
            entry.manifest.get_capability('configuration').handler,
        )

    def test_disabled_integration_filtered_returns_404(self) -> None:
        from fastapi import HTTPException

        from imbi_api.plugins.resolution import resolve_capability

        mock_db = mock.AsyncMock()
        with (
            mock.patch(
                'imbi_api.plugins.resolution.effective_bindings',
                new=mock.AsyncMock(return_value=[_binding()]),
            ),
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin',
                return_value=_make_registry_entry('ssm'),
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.is_plugin_enabled',
                new=mock.AsyncMock(return_value=False),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    resolve_capability(mock_db, 'proj1', 'configuration', None)
                )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_source_matches_integration_id_or_slug(self) -> None:
        from imbi_api.plugins.resolution import resolve_capability

        bindings = [
            _binding(integration_id='i1', slug='a', default=False),
            _binding(integration_id='i2', slug='b', default=False),
        ]
        for source, want in (('b', 'i2'), ('i2', 'i2'), ('i1', 'i1')):
            with (
                mock.patch(
                    'imbi_api.plugins.resolution.effective_bindings',
                    new=mock.AsyncMock(return_value=bindings),
                ),
                mock.patch(
                    'imbi_api.plugins.resolution.get_plugin',
                    return_value=_make_registry_entry('ssm'),
                ),
                mock.patch(
                    'imbi_api.plugins.lifecycle.is_plugin_enabled',
                    new=mock.AsyncMock(return_value=True),
                ),
            ):
                resolved = asyncio.run(
                    resolve_capability(
                        mock.AsyncMock(), 'proj1', 'configuration', source
                    )
                )
            self.assertEqual(resolved.integration_id, want)

    def test_multi_no_default_returns_400(self) -> None:
        from fastapi import HTTPException

        from imbi_api.plugins.resolution import resolve_capability

        mock_db = mock.AsyncMock()
        bindings = [
            _binding(integration_id='i1', slug='a', default=False),
            _binding(integration_id='i2', slug='b', default=False),
        ]
        with (
            mock.patch(
                'imbi_api.plugins.resolution.effective_bindings',
                new=mock.AsyncMock(return_value=bindings),
            ),
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin',
                return_value=_make_registry_entry('ssm'),
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.is_plugin_enabled',
                new=mock.AsyncMock(return_value=True),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    resolve_capability(mock_db, 'proj1', 'configuration', None)
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn('source', ctx.exception.detail)

    def test_multi_picks_project_default(self) -> None:
        from imbi_api.plugins.resolution import resolve_capability

        mock_db = mock.AsyncMock()
        bindings = [
            _binding(integration_id='i1', slug='a', default=False),
            _binding(integration_id='i2', slug='b', default=True),
        ]
        with (
            mock.patch(
                'imbi_api.plugins.resolution.effective_bindings',
                new=mock.AsyncMock(return_value=bindings),
            ),
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin',
                return_value=_make_registry_entry('ssm'),
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.is_plugin_enabled',
                new=mock.AsyncMock(return_value=True),
            ),
        ):
            resolved = asyncio.run(
                resolve_capability(mock_db, 'proj1', 'configuration', None)
            )
        self.assertEqual(resolved.integration_id, 'i2')

    def test_source_picks_specific_integration(self) -> None:
        from imbi_api.plugins.resolution import resolve_capability

        mock_db = mock.AsyncMock()
        bindings = [
            _binding(integration_id='i1', slug='a', default=True),
            _binding(integration_id='i2', slug='b', default=False),
        ]
        with (
            mock.patch(
                'imbi_api.plugins.resolution.effective_bindings',
                new=mock.AsyncMock(return_value=bindings),
            ),
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin',
                return_value=_make_registry_entry('ssm'),
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.is_plugin_enabled',
                new=mock.AsyncMock(return_value=True),
            ),
        ):
            resolved = asyncio.run(
                resolve_capability(mock_db, 'proj1', 'configuration', 'b')
            )
        self.assertEqual(resolved.integration_id, 'i2')

    def test_unknown_source_returns_404(self) -> None:
        from fastapi import HTTPException

        from imbi_api.plugins.resolution import resolve_capability

        mock_db = mock.AsyncMock()
        with (
            mock.patch(
                'imbi_api.plugins.resolution.effective_bindings',
                new=mock.AsyncMock(return_value=[_binding(slug='a')]),
            ),
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin',
                return_value=_make_registry_entry('ssm'),
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.is_plugin_enabled',
                new=mock.AsyncMock(return_value=True),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    resolve_capability(
                        mock_db, 'proj1', 'configuration', 'unknown'
                    )
                )
        self.assertEqual(ctx.exception.status_code, 404)


class ResolveAllCapabilitiesTestCase(unittest.TestCase):
    """Branch coverage for ``resolve_all_capabilities`` (fan-out)."""

    def test_empty_when_no_bindings(self) -> None:
        from imbi_api.plugins.resolution import resolve_all_capabilities

        mock_db = mock.AsyncMock()
        with mock.patch(
            'imbi_api.plugins.resolution.effective_bindings',
            new=mock.AsyncMock(return_value=[]),
        ):
            result = asyncio.run(
                resolve_all_capabilities(mock_db, 'p1', 'lifecycle')
            )
        self.assertEqual(result, [])

    def test_returns_all_enabled_integrations(self) -> None:
        from imbi_api.plugins.resolution import resolve_all_capabilities

        mock_db = mock.AsyncMock()
        bindings = [
            _binding(integration_id='i1', slug='gh', plugin='github'),
            _binding(integration_id='i2', slug='aws', plugin='aws'),
        ]
        entries = {
            'github': _make_registry_entry('github', kind='lifecycle'),
            'aws': _make_registry_entry('aws', kind='lifecycle'),
        }
        with (
            mock.patch(
                'imbi_api.plugins.resolution.effective_bindings',
                new=mock.AsyncMock(return_value=bindings),
            ),
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin',
                side_effect=lambda slug: entries[slug],
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.is_plugin_enabled',
                new=mock.AsyncMock(return_value=True),
            ),
        ):
            result = asyncio.run(
                resolve_all_capabilities(mock_db, 'proj1', 'lifecycle')
            )
        self.assertEqual({r.plugin_slug for r in result}, {'github', 'aws'})

    def test_skips_disabled_integrations(self) -> None:
        from imbi_api.plugins.resolution import resolve_all_capabilities

        mock_db = mock.AsyncMock()
        bindings = [
            _binding(integration_id='i1', slug='on', plugin='on'),
            _binding(integration_id='i2', slug='off', plugin='off'),
        ]
        with (
            mock.patch(
                'imbi_api.plugins.resolution.effective_bindings',
                new=mock.AsyncMock(return_value=bindings),
            ),
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin',
                side_effect=lambda slug: _make_registry_entry(
                    slug, kind='lifecycle'
                ),
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.is_plugin_enabled',
                new=mock.AsyncMock(side_effect=lambda db, slug: slug == 'on'),
            ),
        ):
            result = asyncio.run(
                resolve_all_capabilities(mock_db, 'proj1', 'lifecycle')
            )
        self.assertEqual({r.plugin_slug for r in result}, {'on'})

    def test_skips_unregistered_plugin(self) -> None:
        from imbi_common.plugins.errors import PluginNotFoundError

        from imbi_api.plugins.resolution import resolve_all_capabilities

        mock_db = mock.AsyncMock()
        bindings = [
            _binding(integration_id='i1', slug='present', plugin='present'),
            _binding(integration_id='i2', slug='gone', plugin='gone'),
        ]
        entry = _make_registry_entry('present', kind='lifecycle')

        def _get(slug: str) -> typing.Any:
            if slug == 'present':
                return entry
            raise PluginNotFoundError(slug)

        with (
            mock.patch(
                'imbi_api.plugins.resolution.effective_bindings',
                new=mock.AsyncMock(return_value=bindings),
            ),
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin', side_effect=_get
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.is_plugin_enabled',
                new=mock.AsyncMock(return_value=True),
            ),
        ):
            result = asyncio.run(
                resolve_all_capabilities(mock_db, 'proj1', 'lifecycle')
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].plugin_slug, 'present')


class ReloadSubscriberTestCase(unittest.IsolatedAsyncioTestCase):
    """Test the pubsub subscriber loop in plugins.reload."""

    def _make_signed_payload(self, key: bytes, *, age: int = 0) -> bytes:
        import time

        from imbi_api.plugins import reload as reload_mod

        ts = int(time.time()) - age
        nonce = 'abc123'
        sig = reload_mod._sign(ts, nonce, key)
        return f'{ts}:{nonce}:{sig}'.encode()

    async def test_subscribe_processes_message_and_reloads(self) -> None:
        from imbi_api.plugins import reload as reload_mod

        pubsub = mock.MagicMock()
        pubsub.subscribe = mock.AsyncMock()
        pubsub.unsubscribe = mock.AsyncMock()
        client = mock.MagicMock()
        client.pubsub = mock.MagicMock(return_value=pubsub)
        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []
        derived = b'k' * 32
        payload = self._make_signed_payload(derived)
        stop = asyncio.Event()
        calls: list[int] = []

        async def _wait_for(*_a: object, **_k: object) -> object:
            calls.append(1)
            # First call delivers a message; second iteration we stop.
            if len(calls) == 1:
                return {'type': 'message', 'data': payload}
            stop.set()
            raise TimeoutError()

        with (
            mock.patch.object(
                reload_mod.asyncio, 'wait_for', side_effect=_wait_for
            ),
            mock.patch.object(
                reload_mod, '_get_reload_key', return_value=derived
            ),
            mock.patch.object(reload_mod, 'reload_plugins') as reload_p,
            mock.patch.object(
                reload_mod, 'audit_unavailable', mock.AsyncMock()
            ) as audit,
        ):
            await reload_mod._subscribe_reload(client, mock_db, stop)

        reload_p.assert_called_once()
        audit.assert_awaited()
        pubsub.unsubscribe.assert_awaited()

    async def _run_subscribe_with_payload(
        self,
        payload: object,
        *,
        key: bytes | None = b'k' * 32,
    ) -> tuple[mock.MagicMock, mock.AsyncMock]:
        """Drive one iteration of the subscriber and return reload mocks."""
        from imbi_api.plugins import reload as reload_mod

        pubsub = mock.MagicMock()
        pubsub.subscribe = mock.AsyncMock()
        pubsub.unsubscribe = mock.AsyncMock()
        client = mock.MagicMock()
        client.pubsub = mock.MagicMock(return_value=pubsub)
        mock_db = mock.AsyncMock()
        stop = asyncio.Event()
        calls: list[int] = []

        async def _wait_for(*_a: object, **_k: object) -> object:
            calls.append(1)
            if len(calls) == 1:
                return {'type': 'message', 'data': payload}
            stop.set()
            raise TimeoutError()

        with (
            mock.patch.object(
                reload_mod.asyncio, 'wait_for', side_effect=_wait_for
            ),
            mock.patch.object(reload_mod, '_get_reload_key', return_value=key),
            mock.patch.object(reload_mod, 'reload_plugins') as reload_p,
            mock.patch.object(
                reload_mod, 'audit_unavailable', mock.AsyncMock()
            ) as audit,
        ):
            await reload_mod._subscribe_reload(client, mock_db, stop)
        return reload_p, audit

    async def test_subscribe_rejects_unsigned_payload(self) -> None:
        reload_p, audit = await self._run_subscribe_with_payload(b'reload')
        reload_p.assert_not_called()
        audit.assert_not_awaited()

    async def test_subscribe_rejects_bad_signature(self) -> None:
        derived = b'k' * 32
        payload = self._make_signed_payload(derived).replace(b'abc123', b'xxx')
        reload_p, audit = await self._run_subscribe_with_payload(
            payload, key=derived
        )
        reload_p.assert_not_called()
        audit.assert_not_awaited()

    async def test_subscribe_rejects_stale_timestamp(self) -> None:
        derived = b'k' * 32
        payload = self._make_signed_payload(derived, age=3600)
        reload_p, audit = await self._run_subscribe_with_payload(
            payload, key=derived
        )
        reload_p.assert_not_called()
        audit.assert_not_awaited()

    async def test_subscribe_drops_when_key_unavailable(self) -> None:
        derived = b'k' * 32
        payload = self._make_signed_payload(derived)
        reload_p, audit = await self._run_subscribe_with_payload(
            payload, key=None
        )
        reload_p.assert_not_called()
        audit.assert_not_awaited()

    def test_subscribe_handles_cancelled(self) -> None:
        from imbi_api.plugins import reload as reload_mod

        pubsub = mock.MagicMock()
        pubsub.subscribe = mock.AsyncMock()
        pubsub.unsubscribe = mock.AsyncMock()
        client = mock.MagicMock()
        client.pubsub = mock.MagicMock(return_value=pubsub)
        mock_db = mock.AsyncMock()

        async def _run() -> None:
            stop = asyncio.Event()

            async def _raise_cancel(*_a: object, **_k: object) -> object:
                raise asyncio.CancelledError

            with mock.patch.object(
                reload_mod.asyncio, 'wait_for', side_effect=_raise_cancel
            ):
                await reload_mod._subscribe_reload(client, mock_db, stop)
            pubsub.unsubscribe.assert_awaited()

        asyncio.run(_run())

    def test_subscribe_skips_none_message(self) -> None:
        from imbi_api.plugins import reload as reload_mod

        pubsub = mock.MagicMock()
        pubsub.subscribe = mock.AsyncMock()
        pubsub.unsubscribe = mock.AsyncMock()
        client = mock.MagicMock()
        client.pubsub = mock.MagicMock(return_value=pubsub)
        mock_db = mock.AsyncMock()

        async def _run() -> None:
            stop = asyncio.Event()
            calls: list[int] = []

            async def _wait_for(*_a: object, **_k: object) -> object:
                calls.append(1)
                if len(calls) == 1:
                    return None
                stop.set()
                raise TimeoutError()

            with (
                mock.patch.object(
                    reload_mod.asyncio, 'wait_for', side_effect=_wait_for
                ),
                mock.patch.object(reload_mod, 'reload_plugins') as reload_p,
            ):
                await reload_mod._subscribe_reload(client, mock_db, stop)
            reload_p.assert_not_called()

        asyncio.run(_run())

    def test_plugin_reload_hook_starts_and_stops_task(self) -> None:
        from imbi_api.plugins import reload as reload_mod

        client = mock.MagicMock()
        pubsub = mock.MagicMock()
        pubsub.subscribe = mock.AsyncMock()
        pubsub.unsubscribe = mock.AsyncMock()
        client.pubsub = mock.MagicMock(return_value=pubsub)
        mock_db = mock.AsyncMock()

        async def _fake_subscribe(
            _client: object, _db: object, stop: asyncio.Event
        ) -> None:
            await stop.wait()

        async def _run() -> None:
            with (
                mock.patch(
                    'imbi_api.plugins.reload.valkey.get_client',
                    return_value=client,
                ),
                mock.patch.object(
                    reload_mod, '_subscribe_reload', _fake_subscribe
                ),
            ):
                async with reload_mod.plugin_reload_hook(db=mock_db):
                    pass

        asyncio.run(_run())
