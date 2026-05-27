"""Tests for the plugin infrastructure modules."""

from __future__ import annotations

import asyncio
import json
import typing
import unittest
from unittest import mock

import fastapi

if typing.TYPE_CHECKING:
    from imbi_common.plugins.registry import RegistryEntry


class AssignmentsTestCase(unittest.TestCase):
    def test_validate_one_default_per_tab_ok(self) -> None:
        from imbi_api.plugins.assignments import (
            PluginAssignmentRow,
            validate_one_default_per_tab,
        )

        rows: list[PluginAssignmentRow] = [
            PluginAssignmentRow(
                plugin_id='p1',
                tab='configuration',
                default=True,
                options={},
            ),
            PluginAssignmentRow(
                plugin_id='p2',
                tab='logs',
                default=True,
                options={},
            ),
        ]
        validate_one_default_per_tab(rows)

    def test_validate_two_defaults_same_tab_raises(self) -> None:
        from imbi_api.plugins.assignments import (
            PluginAssignmentRow,
            validate_one_default_per_tab,
        )

        rows: list[PluginAssignmentRow] = [
            PluginAssignmentRow(
                plugin_id='p1',
                tab='configuration',
                default=True,
                options={},
            ),
            PluginAssignmentRow(
                plugin_id='p2',
                tab='configuration',
                default=True,
                options={},
            ),
        ]
        with self.assertRaises(ValueError):
            validate_one_default_per_tab(rows)

    def test_validate_no_default_raises(self) -> None:
        from imbi_api.plugins.assignments import (
            PluginAssignmentRow,
            validate_one_default_per_tab,
        )

        rows: list[PluginAssignmentRow] = [
            PluginAssignmentRow(
                plugin_id='p1',
                tab='configuration',
                default=False,
                options={},
            ),
        ]
        with self.assertRaises(ValueError):
            validate_one_default_per_tab(rows)


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
    required_creds: bool = False,
    auth_type: typing.Literal[
        'api_token', 'oauth2', 'oidc', 'aws-iam-ic'
    ] = 'api_token',
) -> RegistryEntry:
    """Build a RegistryEntry with a fake handler for resolution tests."""
    from imbi_common.plugins.base import (
        ConfigurationPlugin,
        CredentialField,
        PluginManifest,
    )
    from imbi_common.plugins.registry import RegistryEntry

    class _Fake(ConfigurationPlugin):
        manifest = PluginManifest(
            slug=slug,
            name=slug.upper(),
            plugin_type='configuration',
            auth_type=auth_type,
            credentials=(
                [CredentialField(name='token', label='Token', required=True)]
                if required_creds
                else []
            ),
        )

        async def list_keys(self, ctx, credentials):  # type: ignore[override]
            return []

        async def get_values(self, ctx, credentials, keys=None):  # type: ignore[override]
            return []

        async def set_value(self, ctx, credentials, key, value):  # type: ignore[override]
            raise NotImplementedError

        async def delete_key(self, ctx, credentials, key):  # type: ignore[override]
            return None

    return RegistryEntry(
        handler_cls=_Fake,
        manifest=_Fake.manifest,
        package_name=f'imbi-plugin-{slug}',
        package_version='1.0.0',
    )


class ResolutionTestCase(unittest.TestCase):
    """Branch coverage for ``resolve_plugin``."""

    def test_project_not_found_returns_404(self) -> None:
        from fastapi import HTTPException

        from imbi_api.plugins.resolution import resolve_plugin

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(resolve_plugin(mock_db, 'p1', 'configuration', None))
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn('Project not found', ctx.exception.detail)

    def test_no_plugins_assigned_returns_404(self) -> None:
        from fastapi import HTTPException

        from imbi_api.plugins.resolution import resolve_plugin

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {'proj_plugins': '[]', 'pt_plugins': '[]'}
        ]
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(resolve_plugin(mock_db, 'p1', 'configuration', None))
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn('No plugin assigned', ctx.exception.detail)

    def test_single_plugin_resolves(self) -> None:
        from imbi_api.plugins.resolution import resolve_plugin

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'proj_plugins': '[]',
                'pt_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'ssm',
                            'options': '{}',
                            'default': True,
                            'src': 'project_type',
                        }
                    ]
                ),
            }
        ]
        entry = _make_registry_entry('ssm')
        with (
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin', return_value=entry
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.is_plugin_enabled',
                new=mock.AsyncMock(return_value=True),
            ),
        ):
            resolved = asyncio.run(
                resolve_plugin(mock_db, 'proj1', 'configuration', None)
            )
        self.assertEqual(resolved.plugin_id, 'p1')
        self.assertEqual(resolved.plugin_slug, 'ssm')
        self.assertEqual(resolved.options, {})

    def test_project_overrides_project_type_default(self) -> None:
        from imbi_api.plugins.resolution import resolve_plugin

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'pt_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'ssm',
                            'edge_options': '{}',
                            'plugin_options': '{}',
                            'default': True,
                            'src': 'project_type',
                        }
                    ]
                ),
                'proj_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'ssm',
                            'edge_options': '{"region": "us-east-1"}',
                            'plugin_options': '{}',
                            'default': True,
                            'src': 'project',
                        }
                    ]
                ),
            }
        ]
        with (
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
                resolve_plugin(mock_db, 'proj1', 'configuration', None)
            )
        self.assertEqual(resolved.options, {'region': 'us-east-1'})

    def test_multi_plugin_no_default_returns_400(self) -> None:
        from fastapi import HTTPException

        from imbi_api.plugins.resolution import resolve_plugin

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'pt_plugins': '[]',
                'proj_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'ssm',
                            'options': '{}',
                            'default': False,
                            'src': 'project',
                        },
                        {
                            'id': 'p2',
                            'slug': 'ssm',
                            'options': '{}',
                            'default': False,
                            'src': 'project',
                        },
                    ]
                ),
            }
        ]
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                resolve_plugin(mock_db, 'proj1', 'configuration', None)
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn('source', ctx.exception.detail)

    def test_multi_plugin_picks_default(self) -> None:
        from imbi_api.plugins.resolution import resolve_plugin

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'pt_plugins': '[]',
                'proj_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'ssm',
                            'options': '{}',
                            'default': False,
                            'src': 'project',
                        },
                        {
                            'id': 'p2',
                            'slug': 'ssm',
                            'options': '{}',
                            'default': True,
                            'src': 'project',
                        },
                    ]
                ),
            }
        ]
        with (
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
                resolve_plugin(mock_db, 'proj1', 'configuration', None)
            )
        self.assertEqual(resolved.plugin_id, 'p2')

    def test_source_param_picks_specific_plugin(self) -> None:
        from imbi_api.plugins.resolution import resolve_plugin

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'pt_plugins': '[]',
                'proj_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'ssm',
                            'options': '{}',
                            'default': True,
                            'src': 'project',
                        },
                        {
                            'id': 'p2',
                            'slug': 'ssm',
                            'options': '{}',
                            'default': False,
                            'src': 'project',
                        },
                    ]
                ),
            }
        ]
        with (
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
                resolve_plugin(mock_db, 'proj1', 'configuration', 'p2')
            )
        self.assertEqual(resolved.plugin_id, 'p2')

    def test_unknown_source_returns_404(self) -> None:
        from fastapi import HTTPException

        from imbi_api.plugins.resolution import resolve_plugin

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'pt_plugins': '[]',
                'proj_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'ssm',
                            'options': '{}',
                            'default': True,
                            'src': 'project',
                        }
                    ]
                ),
            }
        ]
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                resolve_plugin(mock_db, 'proj1', 'configuration', 'unknown')
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_plugin_slug_not_in_registry_raises_unavailable(self) -> None:
        from imbi_common.plugins.errors import (
            PluginNotFoundError,
            PluginUnavailableError,
        )

        from imbi_api.plugins.resolution import resolve_plugin

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'pt_plugins': '[]',
                'proj_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'gone',
                            'options': '{}',
                            'default': True,
                            'src': 'project',
                        }
                    ]
                ),
            }
        ]
        with mock.patch(
            'imbi_api.plugins.resolution.get_plugin',
            side_effect=PluginNotFoundError('gone'),
        ):
            with self.assertRaises(PluginUnavailableError):
                asyncio.run(
                    resolve_plugin(mock_db, 'proj1', 'configuration', None)
                )

    def test_disabled_plugin_raises_unavailable(self) -> None:
        from imbi_common.plugins.errors import PluginUnavailableError

        from imbi_api.plugins.resolution import resolve_plugin

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'proj_plugins': '[]',
                'pt_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'ssm',
                            'options': '{}',
                            'default': True,
                            'src': 'project_type',
                        }
                    ]
                ),
            }
        ]
        with (
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin',
                return_value=_make_registry_entry('ssm'),
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.is_plugin_enabled',
                new=mock.AsyncMock(return_value=False),
            ),
        ):
            with self.assertRaises(PluginUnavailableError):
                asyncio.run(
                    resolve_plugin(mock_db, 'proj1', 'configuration', None)
                )

    def test_resolve_all_skips_disabled_plugins(self) -> None:
        from imbi_api.plugins.resolution import resolve_all_plugins

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'proj_plugins': '[]',
                'pt_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'on',
                            'options': '{}',
                            'default': True,
                            'src': 'project_type',
                        },
                        {
                            'id': 'p2',
                            'slug': 'off',
                            'options': '{}',
                            'default': True,
                            'src': 'project_type',
                        },
                    ]
                ),
            }
        ]
        with (
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin',
                side_effect=lambda slug: _make_registry_entry(slug),
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.get_enabled_map',
                new=mock.AsyncMock(return_value={'on': True, 'off': False}),
            ),
        ):
            resolved = asyncio.run(
                resolve_all_plugins(mock_db, 'proj1', 'configuration')
            )
        self.assertEqual({r.plugin_slug for r in resolved}, {'on'})


class ResolveAllPluginsTestCase(unittest.TestCase):
    """Branch coverage for ``resolve_all_plugins`` (lifecycle fan-out)."""

    def test_empty_when_no_records(self) -> None:
        from imbi_api.plugins.resolution import resolve_all_plugins

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []
        result = asyncio.run(resolve_all_plugins(mock_db, 'p1', 'lifecycle'))
        self.assertEqual(result, [])

    def test_empty_when_no_plugins_assigned(self) -> None:
        from imbi_api.plugins.resolution import resolve_all_plugins

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {'proj_plugins': '[]', 'pt_plugins': '[]'}
        ]
        result = asyncio.run(resolve_all_plugins(mock_db, 'p1', 'lifecycle'))
        self.assertEqual(result, [])

    def test_returns_all_assigned_plugins(self) -> None:
        from imbi_api.plugins.resolution import resolve_all_plugins

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'pt_plugins': '[]',
                'proj_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'github-lifecycle',
                            'edge_options': '{}',
                            'plugin_options': '{}',
                            'default': True,
                            'src': 'project',
                        },
                        {
                            'id': 'p2',
                            'slug': 'aws-lifecycle',
                            'edge_options': '{}',
                            'plugin_options': '{}',
                            'default': False,
                            'src': 'project',
                        },
                    ]
                ),
            }
        ]
        entry_a = _make_registry_entry('github-lifecycle')
        entry_b = _make_registry_entry('aws-lifecycle')
        entries = {'github-lifecycle': entry_a, 'aws-lifecycle': entry_b}
        with (
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin',
                side_effect=lambda slug: entries[slug],
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.get_enabled_map',
                new=mock.AsyncMock(
                    return_value={
                        'github-lifecycle': True,
                        'aws-lifecycle': True,
                    }
                ),
            ),
        ):
            result = asyncio.run(
                resolve_all_plugins(mock_db, 'proj1', 'lifecycle')
            )
        self.assertEqual(len(result), 2)
        slugs = {r.plugin_slug for r in result}
        self.assertEqual(slugs, {'github-lifecycle', 'aws-lifecycle'})

    def test_skips_unregistered_plugin(self) -> None:
        from imbi_common.plugins.errors import PluginNotFoundError

        from imbi_api.plugins.resolution import resolve_all_plugins

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'pt_plugins': '[]',
                'proj_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'present',
                            'edge_options': '{}',
                            'plugin_options': '{}',
                            'default': True,
                            'src': 'project',
                        },
                        {
                            'id': 'p2',
                            'slug': 'gone',
                            'edge_options': '{}',
                            'plugin_options': '{}',
                            'default': False,
                            'src': 'project',
                        },
                    ]
                ),
            }
        ]
        entry = _make_registry_entry('present')

        def _get(slug: str):
            if slug == 'present':
                return entry
            raise PluginNotFoundError(slug)

        with (
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin',
                side_effect=_get,
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.get_enabled_map',
                new=mock.AsyncMock(
                    return_value={'present': True, 'gone': True}
                ),
            ),
        ):
            result = asyncio.run(
                resolve_all_plugins(mock_db, 'proj1', 'lifecycle')
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].plugin_slug, 'present')

    def test_project_overrides_project_type(self) -> None:
        from imbi_api.plugins.resolution import resolve_all_plugins

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'pt_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'github-lifecycle',
                            'edge_options': '{"archive_target_org": "type"}',
                            'plugin_options': '{}',
                            'default': True,
                            'src': 'project_type',
                        }
                    ]
                ),
                'proj_plugins': json.dumps(
                    [
                        {
                            'id': 'p1',
                            'slug': 'github-lifecycle',
                            'edge_options': '{"archive_target_org": "proj"}',
                            'plugin_options': '{}',
                            'default': True,
                            'src': 'project',
                        }
                    ]
                ),
            }
        ]
        entry = _make_registry_entry('github-lifecycle')
        with (
            mock.patch(
                'imbi_api.plugins.resolution.get_plugin', return_value=entry
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle.get_enabled_map',
                new=mock.AsyncMock(return_value={'github-lifecycle': True}),
            ),
        ):
            result = asyncio.run(
                resolve_all_plugins(mock_db, 'proj1', 'lifecycle')
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].options['archive_target_org'], 'proj')


class CredentialsTestCase(unittest.TestCase):
    """Branch coverage for ``get_plugin_credentials``."""

    def test_empty_no_required_returns_empty_dict(self) -> None:
        from imbi_api.plugins.credentials import get_plugin_credentials

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []
        entry = _make_registry_entry('ssm', required_creds=False)
        creds = asyncio.run(get_plugin_credentials(mock_db, 'p1', entry))
        self.assertEqual(creds, {})

    def test_missing_required_raises(self) -> None:
        from imbi_common.plugins.errors import PluginCredentialsMissing

        from imbi_api.plugins.credentials import get_plugin_credentials

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'creds': None}]
        entry = _make_registry_entry('ssm', required_creds=True)
        with self.assertRaises(PluginCredentialsMissing) as ctx:
            asyncio.run(get_plugin_credentials(mock_db, 'p1', entry))
        self.assertIn('token', str(ctx.exception))

    def test_decrypt_returns_dict(self) -> None:
        from imbi_api.plugins.credentials import get_plugin_credentials

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'creds': '"ENCRYPTED"'}]

        encryptor = mock.MagicMock()
        encryptor.decrypt.return_value = json.dumps({'token': 'abc'})
        entry = _make_registry_entry('ssm', required_creds=True)
        with mock.patch(
            'imbi_api.plugins.credentials.TokenEncryption.get_instance',
            return_value=encryptor,
        ):
            creds = asyncio.run(get_plugin_credentials(mock_db, 'p1', entry))
        self.assertEqual(creds, {'token': 'abc'})

    def test_decrypt_returns_empty_string_yields_no_creds(self) -> None:
        from imbi_common.plugins.errors import PluginCredentialsMissing

        from imbi_api.plugins.credentials import get_plugin_credentials

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [{'creds': '"ENCRYPTED"'}]
        encryptor = mock.MagicMock()
        encryptor.decrypt.return_value = ''
        entry = _make_registry_entry('ssm', required_creds=True)
        with mock.patch(
            'imbi_api.plugins.credentials.TokenEncryption.get_instance',
            return_value=encryptor,
        ):
            with self.assertRaises(PluginCredentialsMissing):
                asyncio.run(get_plugin_credentials(mock_db, 'p1', entry))

    def test_oauth2_unlinked_plugin_raises(self) -> None:
        from imbi_common.plugins.errors import PluginCredentialsMissing

        from imbi_api.plugins.credentials import get_plugin_credentials

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = []
        entry = _make_registry_entry('github', auth_type='oauth2')
        with self.assertRaises(PluginCredentialsMissing) as ctx:
            asyncio.run(get_plugin_credentials(mock_db, 'p1', entry))
        self.assertIn('not linked to a ServiceApplication', str(ctx.exception))

    def test_oauth2_linked_plugin_returns_decrypted(self) -> None:
        from imbi_api.plugins.credentials import get_plugin_credentials

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'client_id': '"my-client-id"',
                'client_secret': '"ENCRYPTED-SECRET"',
            }
        ]
        encryptor = mock.MagicMock()
        encryptor.decrypt.return_value = 'plaintext-secret'
        entry = _make_registry_entry('github', auth_type='oauth2')
        with mock.patch(
            'imbi_api.plugins.credentials.TokenEncryption.get_instance',
            return_value=encryptor,
        ):
            creds = asyncio.run(get_plugin_credentials(mock_db, 'p1', entry))
        self.assertEqual(
            creds,
            {'client_id': 'my-client-id', 'client_secret': 'plaintext-secret'},
        )

    def test_oauth2_decrypt_failure_raises_missing(self) -> None:
        from imbi_common.plugins.errors import PluginCredentialsMissing

        from imbi_api.plugins.credentials import get_plugin_credentials

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {
                'client_id': '"my-client-id"',
                'client_secret': '"ENCRYPTED-SECRET"',
            }
        ]
        encryptor = mock.MagicMock()
        encryptor.decrypt.side_effect = RuntimeError('boom')
        entry = _make_registry_entry('github', auth_type='oauth2')
        with mock.patch(
            'imbi_api.plugins.credentials.TokenEncryption.get_instance',
            return_value=encryptor,
        ):
            with self.assertRaises(PluginCredentialsMissing) as ctx:
                asyncio.run(get_plugin_credentials(mock_db, 'p1', entry))
        self.assertIn('could not be decrypted', str(ctx.exception))

    def test_oauth2_missing_client_id_raises(self) -> None:
        from imbi_common.plugins.errors import PluginCredentialsMissing

        from imbi_api.plugins.credentials import get_plugin_credentials

        mock_db = mock.AsyncMock()
        mock_db.execute.return_value = [
            {'client_id': None, 'client_secret': '"ENCRYPTED"'}
        ]
        entry = _make_registry_entry('github', auth_type='oauth2')
        with self.assertRaises(PluginCredentialsMissing) as ctx:
            asyncio.run(get_plugin_credentials(mock_db, 'p1', entry))
        self.assertIn('client_id or client_secret', str(ctx.exception))


class PatchPluginConfigurationTestCase(unittest.IsolatedAsyncioTestCase):
    """Compare-and-swap behavior of ``patch_plugin_configuration`` (M19)."""

    def _encryptor(self, decrypted: str | None = None) -> mock.MagicMock:
        enc = mock.MagicMock()
        enc.encrypt.return_value = 'CIPHER'
        if decrypted is not None:
            enc.decrypt.return_value = decrypted
        return enc

    def _db_with(
        self, *, read: list[dict[str, object]], writes: list[list[object]]
    ) -> mock.AsyncMock:
        """Build a mock graph whose execute branches on read vs CAS write.

        ``read`` is the row list returned for the SELECT; ``writes`` is a
        FIFO of the row lists returned for each CAS ``SET`` attempt.
        """
        pending = list(writes)

        def fake_execute(query: str, params=None, columns=None):  # type: ignore[no-untyped-def]
            if 'SET p.plugin_configuration' in query:
                return pending.pop(0)
            return read

        db = mock.AsyncMock()
        db.execute.side_effect = fake_execute
        return db

    async def test_first_attempt_success_no_prior_blob(self) -> None:
        from imbi_api.plugins.credentials import patch_plugin_configuration

        db = self._db_with(read=[{'creds': None}], writes=[[{'p': {}}]])
        with mock.patch(
            'imbi_api.plugins.credentials.TokenEncryption.get_instance',
            return_value=self._encryptor(),
        ):
            populated = await patch_plugin_configuration(
                db, 'p1', {'token': 'abc'}
            )
        self.assertEqual(populated, ['token'])
        write_call = next(
            c
            for c in db.execute.call_args_list
            if 'SET p.plugin_configuration' in c.args[0]
        )
        self.assertEqual(write_call.args[1]['expected'], '')
        self.assertEqual(write_call.args[1]['blob'], 'CIPHER')

    async def test_merges_onto_existing_blob(self) -> None:
        from imbi_api.plugins.credentials import patch_plugin_configuration

        db = self._db_with(read=[{'creds': '"OLD"'}], writes=[[{'p': {}}]])
        with mock.patch(
            'imbi_api.plugins.credentials.TokenEncryption.get_instance',
            return_value=self._encryptor(decrypted=json.dumps({'a': '1'})),
        ):
            populated = await patch_plugin_configuration(db, 'p1', {'b': '2'})
        self.assertEqual(sorted(populated), ['a', 'b'])
        write_call = next(
            c
            for c in db.execute.call_args_list
            if 'SET p.plugin_configuration' in c.args[0]
        )
        # CAS witness is the ciphertext we read, not a re-encryption.
        self.assertEqual(write_call.args[1]['expected'], 'OLD')

    async def test_empty_value_removes_field(self) -> None:
        from imbi_api.plugins.credentials import patch_plugin_configuration

        db = self._db_with(read=[{'creds': '"OLD"'}], writes=[[{'p': {}}]])
        with mock.patch(
            'imbi_api.plugins.credentials.TokenEncryption.get_instance',
            return_value=self._encryptor(
                decrypted=json.dumps({'a': '1', 'b': '2'})
            ),
        ):
            populated = await patch_plugin_configuration(
                db, 'p1', {'a': None, 'b': ''}
            )
        self.assertEqual(populated, [])

    async def test_lost_cas_retries_then_succeeds(self) -> None:
        from imbi_api.plugins.credentials import patch_plugin_configuration

        db = self._db_with(read=[{'creds': None}], writes=[[], [{'p': {}}]])
        with mock.patch(
            'imbi_api.plugins.credentials.TokenEncryption.get_instance',
            return_value=self._encryptor(),
        ):
            populated = await patch_plugin_configuration(
                db, 'p1', {'token': 'abc'}
            )
        self.assertEqual(populated, ['token'])
        writes = [
            c
            for c in db.execute.call_args_list
            if 'SET p.plugin_configuration' in c.args[0]
        ]
        self.assertEqual(len(writes), 2)

    async def test_exhausted_retries_raises_409(self) -> None:
        from imbi_api.plugins.credentials import patch_plugin_configuration

        db = self._db_with(read=[{'creds': None}], writes=[[], [], []])
        with mock.patch(
            'imbi_api.plugins.credentials.TokenEncryption.get_instance',
            return_value=self._encryptor(),
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                await patch_plugin_configuration(db, 'p1', {'token': 'abc'})
        self.assertEqual(ctx.exception.status_code, 409)


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
