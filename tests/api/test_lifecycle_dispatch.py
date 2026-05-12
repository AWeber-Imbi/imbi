"""Tests for :mod:`imbi_api.plugins.lifecycle_dispatch`.

Covers fan-out happy path, NotImplementedError handling on unarchive,
plugin exceptions surfacing as ``status='failed'``, and ClickHouse
event errors not poisoning the response.
"""

import asyncio
import unittest
import unittest.mock as mock

import fastapi
from imbi_common.plugins.base import (
    ConfigurationPlugin,
    LifecyclePlugin,
    LifecycleResult,
    PluginManifest,
)
from imbi_common.plugins.registry import RegistryEntry

from imbi_api.plugins.lifecycle_dispatch import (
    LifecycleEvent,
    LifecycleInvocation,
    dispatch_lifecycle,
)
from imbi_api.plugins.resolution import ResolvedPlugin


def _make_lifecycle_entry(
    slug: str,
    *,
    archive_status: str = 'ok',
    unarchive_raises: type[BaseException] | None = NotImplementedError,
    archive_raises: type[BaseException] | None = None,
) -> RegistryEntry:
    class _FakeLifecycle(LifecyclePlugin):
        manifest = PluginManifest(
            slug=slug,
            name=slug,
            plugin_type='lifecycle',
        )

        async def on_project_archived(self, ctx, credentials):  # type: ignore[override]
            if archive_raises is not None:
                raise archive_raises('archive boom')
            return LifecycleResult(
                status=archive_status,  # type: ignore[arg-type]
                message='done',
                artifacts={'repo_url': 'https://github.com/o/r'},
            )

        async def on_project_unarchived(self, ctx, credentials):  # type: ignore[override]
            if unarchive_raises is not None:
                raise unarchive_raises('unarchive boom')
            return LifecycleResult(status='ok')

    return RegistryEntry(
        handler_cls=_FakeLifecycle,
        manifest=_FakeLifecycle.manifest,
        package_name=f'imbi-plugin-{slug}',
        package_version='1.0.0',
    )


def _make_auth() -> mock.MagicMock:
    auth = mock.MagicMock()
    auth.user = mock.MagicMock(id='user-1')
    auth.principal_name = 'tester'
    return auth


def _resolved(entry: RegistryEntry, plugin_id: str = 'p1') -> ResolvedPlugin:
    return ResolvedPlugin(
        plugin_id=plugin_id,
        plugin_slug=entry.manifest.slug,
        entry=entry,
        options={},
        identity_plugin_id=None,
    )


class DispatchLifecycleTestCase(unittest.TestCase):
    """Branch coverage for :func:`dispatch_lifecycle`."""

    def _run(
        self,
        resolved_list: list[ResolvedPlugin],
        *,
        event: LifecycleEvent = 'archived',
    ) -> tuple[list[LifecycleInvocation], mock.AsyncMock]:
        mock_db = mock.AsyncMock()
        auth = _make_auth()
        with (
            mock.patch(
                'imbi_api.plugins.lifecycle_dispatch.resolve_all_plugins',
                mock.AsyncMock(return_value=resolved_list),
            ),
            mock.patch(
                'imbi_api.endpoints._helpers.lookup_project_slugs',
                mock.AsyncMock(return_value=('p-slug', 't-slug')),
            ),
            mock.patch(
                'imbi_api.endpoints._helpers.lookup_project_links',
                mock.AsyncMock(return_value={}),
            ),
            mock.patch(
                'imbi_api.endpoints._helpers.lookup_project_type_slugs',
                mock.AsyncMock(return_value=[]),
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle_dispatch.call_with_identity_retry',
                new=_passthrough_identity_retry,
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle_dispatch._resolve_credentials',
                mock.AsyncMock(return_value={'access_token': 'tok'}),
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle_dispatch.ch_client.Clickhouse.'
                'get_instance'
            ) as ch_get,
        ):
            ch_get.return_value.insert = mock.AsyncMock()
            return asyncio.run(
                dispatch_lifecycle(mock_db, 'proj-1', 'org-1', event, auth)
            ), ch_get.return_value.insert

    def test_empty_when_no_plugins_assigned(self) -> None:
        results, _ = self._run([])
        self.assertEqual(results, [])

    def test_archive_happy_path(self) -> None:
        entry = _make_lifecycle_entry('gh')
        results, insert = self._run([_resolved(entry)])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, 'ok')
        self.assertEqual(results[0].plugin_slug, 'gh')
        self.assertEqual(
            results[0].artifacts, {'repo_url': 'https://github.com/o/r'}
        )
        insert.assert_awaited_once()

    def test_unarchive_not_implemented_is_skipped(self) -> None:
        entry = _make_lifecycle_entry('gh')
        results, _ = self._run([_resolved(entry)], event='unarchived')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, 'skipped')
        self.assertIn('on_project_unarchived', results[0].message or '')

    def test_archive_not_implemented_is_failed(self) -> None:
        # Archive is the plugin's primary contract: a missing
        # implementation is a real failure, not a skip.
        entry = _make_lifecycle_entry('gh', archive_raises=NotImplementedError)
        results, _ = self._run([_resolved(entry)])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, 'failed')
        self.assertIn('NotImplementedError', results[0].message or '')

    def test_plugin_exception_surfaces_failed(self) -> None:
        entry = _make_lifecycle_entry('gh', archive_raises=RuntimeError)
        results, _ = self._run([_resolved(entry)])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, 'failed')
        self.assertIn('RuntimeError', results[0].message or '')

    def test_http_exception_surfaces_failed(self) -> None:
        entry = _make_lifecycle_entry('gh')

        # Override the plugin handler at the registry to raise HTTPException
        # mid-call by patching the method on the registry's class.
        class _Raises(LifecyclePlugin):
            manifest = entry.manifest

            async def on_project_archived(  # type: ignore[override]
                self, ctx, credentials
            ):
                raise fastapi.HTTPException(
                    status_code=401,
                    detail={
                        'error': 'identity_required',
                        'plugin_id': 'ident',
                    },
                )

        broken = RegistryEntry(
            handler_cls=_Raises,
            manifest=entry.manifest,
            package_name=entry.package_name,
            package_version=entry.package_version,
        )
        results, _ = self._run([_resolved(broken)])
        self.assertEqual(results[0].status, 'failed')
        self.assertIn('identity_required', results[0].message or '')

    def test_clickhouse_failure_does_not_poison_response(self) -> None:
        entry = _make_lifecycle_entry('gh')
        mock_db = mock.AsyncMock()
        auth = _make_auth()
        with (
            mock.patch(
                'imbi_api.plugins.lifecycle_dispatch.resolve_all_plugins',
                mock.AsyncMock(return_value=[_resolved(entry)]),
            ),
            mock.patch(
                'imbi_api.endpoints._helpers.lookup_project_slugs',
                mock.AsyncMock(return_value=('p', 't')),
            ),
            mock.patch(
                'imbi_api.endpoints._helpers.lookup_project_links',
                mock.AsyncMock(return_value={}),
            ),
            mock.patch(
                'imbi_api.endpoints._helpers.lookup_project_type_slugs',
                mock.AsyncMock(return_value=[]),
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle_dispatch.call_with_identity_retry',
                new=_passthrough_identity_retry,
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle_dispatch._resolve_credentials',
                mock.AsyncMock(return_value={'access_token': 't'}),
            ),
            mock.patch(
                'imbi_api.plugins.lifecycle_dispatch.ch_client.Clickhouse.'
                'get_instance'
            ) as ch_get,
        ):
            ch_get.return_value.insert = mock.AsyncMock(
                side_effect=RuntimeError('clickhouse down')
            )
            results = asyncio.run(
                dispatch_lifecycle(
                    mock_db, 'proj-1', 'org-1', 'archived', auth
                )
            )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, 'ok')


async def _passthrough_identity_retry(
    db, ctx, resolved, auth, *, fn, identity_options=None, attached=False
):
    """Stub that skips identity hydration entirely."""
    del db, resolved, auth, identity_options, attached
    return await fn(ctx)


class LifecycleInvocationSerializationTestCase(unittest.TestCase):
    def test_round_trip(self) -> None:
        inv = LifecycleInvocation(
            plugin_id='p1',
            plugin_slug='gh',
            status='ok',
            message='done',
            artifacts={'k': 'v'},
        )
        restored = LifecycleInvocation.model_validate(inv.model_dump())
        self.assertEqual(restored.status, 'ok')
        self.assertEqual(restored.artifacts['k'], 'v')


class ConfigurationPluginIsNotLifecycle(unittest.TestCase):
    """Sanity: only LifecyclePlugin handlers should be invoked by dispatch."""

    def test_configuration_plugin_no_archive_method(self) -> None:
        self.assertFalse(hasattr(ConfigurationPlugin, 'on_project_archived'))
