"""Tests for :mod:`imbi_api.plugins.lifecycle_dispatch`.

Covers fan-out happy path, NotImplementedError handling on unarchive,
plugin exceptions surfacing as ``status='failed'``, and ClickHouse
event errors not poisoning the response.
"""

import asyncio
import typing
import unittest
import unittest.mock as mock

import fastapi
from imbi_common.plugins.base import (
    ConfigurationPlugin,
    LifecyclePlugin,
    LifecycleResult,
    LinkWriteback,
    PluginContext,
    PluginManifest,
    ServiceWriteback,
)
from imbi_common.plugins.registry import RegistryEntry

from imbi_api.plugins.lifecycle_dispatch import (
    LifecycleContextBundle,
    LifecycleEvent,
    LifecycleInvocation,
    build_lifecycle_context_bundle,
    dispatch_lifecycle,
)
from imbi_api.plugins.resolution import ResolvedPlugin


def _make_lifecycle_entry(
    slug: str,
    *,
    archive_status: str = 'ok',
    unarchive_raises: type[BaseException] | None = None,
    archive_raises: type[BaseException] | None = None,
) -> RegistryEntry:
    """Build a registry entry for a synthetic lifecycle plugin.

    ``unarchive_raises`` defaults to ``None`` so the fixture inherits the
    base ``LifecyclePlugin.on_project_unarchived`` stub (which raises
    :class:`NotImplementedError`); the dispatcher detects the missing
    hook by identity and reports ``status='skipped'`` without invoking.
    Pass an exception class to install an *implemented* override that
    raises -- exercising the runtime-failure path.
    """

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

    if unarchive_raises is not None:
        _exc = unarchive_raises

        async def _on_unarchived(self, ctx, credentials):  # type: ignore[no-untyped-def]
            raise _exc('unarchive boom')

        _FakeLifecycle.on_project_unarchived = _on_unarchived  # type: ignore[method-assign]

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

    def test_archive_persists_link_writeback(self) -> None:
        # A lifecycle plugin that reports a link writeback on ctx
        # triggers a persist of the stored link via update_project_link.
        class _Reloc(LifecyclePlugin):
            manifest = PluginManifest(
                slug='gh', name='gh', plugin_type='lifecycle'
            )

            async def on_project_archived(self, ctx, credentials):  # type: ignore[override]
                ctx.link_writeback = LinkWriteback(
                    link_key='github-repository',
                    new_url='https://github.com/octo/renamed',
                    old_owner_repo='octo/demo',
                    new_owner_repo='octo/renamed',
                )
                return LifecycleResult(status='ok', message='done')

            async def on_project_unarchived(self, ctx, credentials):  # type: ignore[override]
                raise NotImplementedError

        entry = RegistryEntry(
            handler_cls=_Reloc,
            manifest=_Reloc.manifest,
            package_name='imbi-plugin-gh',
            package_version='1.0.0',
        )
        with mock.patch(
            'imbi_api.endpoints._helpers.update_project_link',
            new=mock.AsyncMock(return_value=True),
        ) as update_link:
            results, _ = self._run([_resolved(entry)])
        self.assertEqual(results[0].status, 'ok')
        update_link.assert_awaited_once()
        # persist_link_writeback(db, ctx) -> update_project_link(
        #     db, project_id, link_key, new_url)
        args = update_link.await_args.args
        self.assertEqual(args[2], 'github-repository')
        self.assertEqual(args[3], 'https://github.com/octo/renamed')

    def test_archive_persists_service_writeback(self) -> None:
        # A lifecycle plugin that reports a service writeback on ctx
        # triggers an EXISTS_IN upsert + dashboard-link merge against the
        # plugin's bound third-party service.
        class _Svc(LifecyclePlugin):
            manifest = PluginManifest(
                slug='gh', name='gh', plugin_type='lifecycle'
            )

            async def on_project_archived(self, ctx, credentials):  # type: ignore[override]
                ctx.service_writeback = ServiceWriteback(
                    identifier='134741',
                    canonical_url='https://api.x.ghe.com/repositories/134741',
                    dashboard_links={
                        'github-enterprise-cloud': 'https://x.ghe.com/o/r'
                    },
                )
                return LifecycleResult(status='ok', message='done')

            async def on_project_unarchived(self, ctx, credentials):  # type: ignore[override]
                raise NotImplementedError

        entry = RegistryEntry(
            handler_cls=_Svc,
            manifest=_Svc.manifest,
            package_name='imbi-plugin-gh',
            package_version='1.0.0',
        )
        resolved = ResolvedPlugin(
            plugin_id='p1',
            plugin_slug='gh',
            entry=entry,
            options={},
            third_party_service_slug='github-enterprise-cloud',
        )
        with (
            mock.patch(
                'imbi_api.endpoints._helpers._merge_exists_in',
                new=mock.AsyncMock(),
            ) as merge_edge,
            mock.patch(
                'imbi_api.endpoints._helpers.merge_project_links',
                new=mock.AsyncMock(return_value=True),
            ) as merge_links,
        ):
            results, _ = self._run([resolved])
        self.assertEqual(results[0].status, 'ok')
        merge_edge.assert_awaited_once()
        # _merge_exists_in(db, org, project, slug, identifier, canonical_url)
        args = merge_edge.await_args.args
        self.assertEqual(args[1], 'org-1')
        self.assertEqual(args[2], 'proj-1')
        self.assertEqual(args[3], 'github-enterprise-cloud')
        self.assertEqual(args[4], '134741')
        self.assertEqual(args[5], 'https://api.x.ghe.com/repositories/134741')
        merge_links.assert_awaited_once()
        self.assertEqual(
            merge_links.await_args.kwargs['add'],
            {'github-enterprise-cloud': 'https://x.ghe.com/o/r'},
        )

    def test_service_writeback_remove_deletes_edge(self) -> None:
        class _Svc(LifecyclePlugin):
            manifest = PluginManifest(
                slug='gh', name='gh', plugin_type='lifecycle'
            )

            async def on_project_archived(self, ctx, credentials):  # type: ignore[override]
                ctx.service_writeback = ServiceWriteback(
                    identifier='1',
                    canonical_url='https://api.x/1',
                    dashboard_links={
                        'github-enterprise-cloud': 'https://x/o/r'
                    },
                    remove=True,
                )
                return LifecycleResult(status='ok')

            async def on_project_unarchived(self, ctx, credentials):  # type: ignore[override]
                raise NotImplementedError

        entry = RegistryEntry(
            handler_cls=_Svc,
            manifest=_Svc.manifest,
            package_name='imbi-plugin-gh',
            package_version='1.0.0',
        )
        resolved = ResolvedPlugin(
            plugin_id='p1',
            plugin_slug='gh',
            entry=entry,
            options={},
            third_party_service_slug='github-enterprise-cloud',
        )
        with (
            mock.patch(
                'imbi_api.endpoints._helpers._delete_exists_in',
                new=mock.AsyncMock(),
            ) as delete_edge,
            mock.patch(
                'imbi_api.endpoints._helpers.merge_project_links',
                new=mock.AsyncMock(return_value=True),
            ) as merge_links,
        ):
            results, _ = self._run([resolved])
        self.assertEqual(results[0].status, 'ok')
        delete_edge.assert_awaited_once()
        self.assertEqual(
            delete_edge.await_args.args[3], 'github-enterprise-cloud'
        )
        # remove path drops the dashboard keys, not adds them
        self.assertIn('remove', merge_links.await_args.kwargs)

    def test_emits_one_clickhouse_call_for_multiple_plugins(self) -> None:
        """H17: N plugins → 1 ClickHouse insert (rows batched)."""
        entries = [
            _resolved(_make_lifecycle_entry(f'gh-{i}')) for i in range(3)
        ]
        results, insert = self._run(entries)
        self.assertEqual(len(results), 3)
        insert.assert_awaited_once()
        args = insert.call_args.args
        self.assertEqual(args[0], 'events')
        rows = args[1]
        self.assertEqual(len(rows), 3)

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


class WidenedEventNotImplementedTestCase(unittest.TestCase):
    """The new lifecycle events skip when a plugin doesn't implement them.

    Only ``archived`` is a required hook on :class:`LifecyclePlugin`; the
    rest of the events resolve to ``status='skipped'`` when the plugin
    doesn't implement them, so plugins can opt into per-event support
    incrementally without breaking the dispatch.
    """

    def _run_with_bare_plugin(
        self, event: LifecycleEvent
    ) -> LifecycleInvocation:
        class _Bare(LifecyclePlugin):
            manifest = PluginManifest(
                slug='bare', name='bare', plugin_type='lifecycle'
            )

            async def on_project_archived(self, ctx, credentials):  # type: ignore[override]
                return LifecycleResult(status='ok')

            async def on_project_unarchived(self, ctx, credentials):  # type: ignore[override]
                raise NotImplementedError

        entry = RegistryEntry(
            handler_cls=_Bare,
            manifest=_Bare.manifest,
            package_name='imbi-plugin-bare',
            package_version='1.0.0',
        )
        resolved = ResolvedPlugin(
            plugin_id='p1',
            plugin_slug='bare',
            entry=entry,
            options={},
            identity_plugin_id=None,
        )
        mock_db = mock.AsyncMock()
        auth = _make_auth()
        with (
            mock.patch(
                'imbi_api.plugins.lifecycle_dispatch.resolve_all_plugins',
                mock.AsyncMock(return_value=[resolved]),
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
            ch_get.return_value.insert = mock.AsyncMock()
            results = asyncio.run(
                dispatch_lifecycle(mock_db, 'proj-1', 'org-1', event, auth)
            )
        return results[0]

    def test_created_not_implemented_is_skipped(self) -> None:
        inv = self._run_with_bare_plugin('created')
        self.assertEqual(inv.status, 'skipped')
        self.assertIn('on_project_created', inv.message or '')

    def test_updated_not_implemented_is_skipped(self) -> None:
        inv = self._run_with_bare_plugin('updated')
        self.assertEqual(inv.status, 'skipped')
        self.assertIn('on_project_updated', inv.message or '')

    def test_deleted_not_implemented_is_skipped(self) -> None:
        inv = self._run_with_bare_plugin('deleted')
        self.assertEqual(inv.status, 'skipped')
        self.assertIn('on_project_deleted', inv.message or '')

    def test_relocated_not_implemented_is_skipped(self) -> None:
        inv = self._run_with_bare_plugin('relocated')
        self.assertEqual(inv.status, 'skipped')
        self.assertIn('on_project_relocated', inv.message or '')


class BundleAndContextPropagationTestCase(unittest.TestCase):
    """The dispatcher honours pre-fetched bundles and the new ctx kwargs."""

    def _capture_ctx(
        self,
        *,
        event: LifecycleEvent,
        bundle: LifecycleContextBundle | None = None,
        **dispatch_kwargs: typing.Any,
    ) -> mock.MagicMock:
        captured: dict[str, PluginContext] = {}

        class _Capture(LifecyclePlugin):
            manifest = PluginManifest(
                slug='cap', name='cap', plugin_type='lifecycle'
            )

            async def on_project_created(self, ctx, credentials):  # type: ignore[override]
                captured['ctx'] = ctx
                return LifecycleResult(status='ok')

            async def on_project_updated(self, ctx, credentials):  # type: ignore[override]
                captured['ctx'] = ctx
                return LifecycleResult(status='ok')

            async def on_project_deleted(self, ctx, credentials):  # type: ignore[override]
                captured['ctx'] = ctx
                return LifecycleResult(status='ok')

            async def on_project_archived(self, ctx, credentials):  # type: ignore[override]
                return LifecycleResult(status='ok')

            async def on_project_unarchived(self, ctx, credentials):  # type: ignore[override]
                raise NotImplementedError

        entry = RegistryEntry(
            handler_cls=_Capture,
            manifest=_Capture.manifest,
            package_name='imbi-plugin-cap',
            package_version='1.0.0',
        )
        resolved = ResolvedPlugin(
            plugin_id='p1',
            plugin_slug='cap',
            entry=entry,
            options={},
            identity_plugin_id=None,
        )
        mock_db = mock.AsyncMock()
        auth = _make_auth()
        slugs_lookup = mock.AsyncMock(return_value=('fetched', 'team-x'))
        links_lookup = mock.AsyncMock(return_value={})
        types_lookup = mock.AsyncMock(return_value=[])
        with (
            mock.patch(
                'imbi_api.plugins.lifecycle_dispatch.resolve_all_plugins',
                mock.AsyncMock(return_value=[resolved]),
            ),
            mock.patch(
                'imbi_api.endpoints._helpers.lookup_project_slugs',
                slugs_lookup,
            ),
            mock.patch(
                'imbi_api.endpoints._helpers.lookup_project_links',
                links_lookup,
            ),
            mock.patch(
                'imbi_api.endpoints._helpers.lookup_project_type_slugs',
                types_lookup,
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
            ch_get.return_value.insert = mock.AsyncMock()
            asyncio.run(
                dispatch_lifecycle(
                    mock_db,
                    'proj-1',
                    'org-1',
                    event,
                    auth,
                    bundle=bundle,
                    **dispatch_kwargs,
                )
            )
        return mock.MagicMock(
            ctx=captured.get('ctx'),
            slugs_lookup=slugs_lookup,
            links_lookup=links_lookup,
            types_lookup=types_lookup,
        )

    def test_provided_bundle_bypasses_helper_lookups(self) -> None:
        bundle = LifecycleContextBundle(
            project_slug='captured-slug',
            team_slug='captured-team',
            project_links={'github-repository': 'https://x'},
            project_type_slugs=['api-service'],
        )
        out = self._capture_ctx(event='deleted', bundle=bundle)
        # Bundle short-circuits the three helpers entirely.
        out.slugs_lookup.assert_not_called()
        out.links_lookup.assert_not_called()
        out.types_lookup.assert_not_called()
        # And the captured ctx mirrors the bundle.
        self.assertEqual(out.ctx.project_slug, 'captured-slug')
        self.assertEqual(out.ctx.team_slug, 'captured-team')
        self.assertEqual(
            out.ctx.project_links, {'github-repository': 'https://x'}
        )
        self.assertEqual(out.ctx.project_type_slugs, ['api-service'])

    def test_updated_propagates_previous_slug_and_metadata(self) -> None:
        out = self._capture_ctx(
            event='updated',
            previous_project_slug='old-slug',
            project_name='New Name',
            project_description='New description',
            project_ui_url='https://imbi.example.com/projects/proj-1',
        )
        self.assertEqual(out.ctx.previous_project_slug, 'old-slug')
        self.assertEqual(out.ctx.project_name, 'New Name')
        self.assertEqual(out.ctx.project_description, 'New description')
        self.assertEqual(
            out.ctx.project_ui_url,
            'https://imbi.example.com/projects/proj-1',
        )

    def test_propagates_previous_team_slug(self) -> None:
        # dispatch packs ``previous_team_slug`` onto the context
        # regardless of event; the relocated endpoint path supplies it.
        out = self._capture_ctx(
            event='updated',
            previous_team_slug='platform',
        )
        self.assertEqual(out.ctx.previous_team_slug, 'platform')


class BuildLifecycleContextBundleTestCase(unittest.TestCase):
    """:func:`build_lifecycle_context_bundle` packages the three lookups."""

    def test_packages_slug_team_links_and_type_slugs(self) -> None:
        mock_db = mock.AsyncMock()
        with (
            mock.patch(
                'imbi_api.endpoints._helpers.lookup_project_slugs',
                mock.AsyncMock(return_value=('my-api', 'platform')),
            ),
            mock.patch(
                'imbi_api.endpoints._helpers.lookup_project_links',
                mock.AsyncMock(
                    return_value={'github-repository': 'https://gh/o/r'},
                ),
            ),
            mock.patch(
                'imbi_api.endpoints._helpers.lookup_project_type_slugs',
                mock.AsyncMock(return_value=['api-service', 'consumer']),
            ),
        ):
            bundle = asyncio.run(
                build_lifecycle_context_bundle(mock_db, 'proj-1')
            )
        self.assertEqual(bundle.project_slug, 'my-api')
        self.assertEqual(bundle.team_slug, 'platform')
        self.assertEqual(
            bundle.project_links, {'github-repository': 'https://gh/o/r'}
        )
        self.assertEqual(
            bundle.project_type_slugs, ['api-service', 'consumer']
        )
