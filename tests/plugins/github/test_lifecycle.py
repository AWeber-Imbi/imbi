"""Smoke tests for the GitHub lifecycle plugins.

Covers manifest shape, archive-in-place, transfer-then-archive,
idempotent skip when already archived (or already unarchived), the
brief unarchive-transfer-rearchive dance when transferring an already-
archived repo, the rename-on-transfer case, repo-resolution failure
from absent links, and the 401 -> PluginAuthenticationFailed path.
"""

import unittest
import unittest.mock

import httpx
import respx
from imbi_common.plugins.base import (
    LifecyclePlugin,
    PluginContext,
)
from imbi_common.plugins.errors import PluginAuthenticationFailed

from imbi_plugin_github.lifecycle import (
    GitHubEnterpriseCloudLifecyclePlugin,
    GitHubEnterpriseServerLifecyclePlugin,
    GitHubLifecyclePlugin,
)


def _ctx(
    options: dict[str, object] | None = None,
    project_links: dict[str, str] | None = None,
    project_type_slugs: list[str] | None = None,
) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug='demo',
        org_slug='octo',
        assignment_options=options or {},
        actor_user_id='u-1',
        project_links=(
            project_links
            if project_links is not None
            else {'github-repository': 'https://github.com/octo/demo'}
        ),
        project_type_slugs=project_type_slugs or [],
    )


_CREDS = {'access_token': 'gho_test'}


class ManifestTestCase(unittest.TestCase):
    def test_manifest_slugs(self) -> None:
        self.assertEqual(
            GitHubLifecyclePlugin.manifest.slug, 'github-lifecycle'
        )
        self.assertEqual(
            GitHubEnterpriseCloudLifecyclePlugin.manifest.slug,
            'github-lifecycle-ec',
        )
        self.assertEqual(
            GitHubEnterpriseServerLifecyclePlugin.manifest.slug,
            'github-lifecycle-es',
        )

    def test_all_subclass_lifecycle_plugin(self) -> None:
        for cls in (
            GitHubLifecyclePlugin,
            GitHubEnterpriseCloudLifecyclePlugin,
            GitHubEnterpriseServerLifecyclePlugin,
        ):
            self.assertIsInstance(cls(), LifecyclePlugin)
            self.assertEqual(cls.manifest.plugin_type, 'lifecycle')

    def test_archive_target_org_option(self) -> None:
        # The transfer-on-archive option is the load-bearing setting for
        # this plugin family — assert it is exposed by every flavor.
        for cls in (
            GitHubLifecyclePlugin,
            GitHubEnterpriseCloudLifecyclePlugin,
            GitHubEnterpriseServerLifecyclePlugin,
        ):
            names = {opt.name for opt in cls.manifest.options}
            self.assertIn('archive_target_org', names)


class ArchiveTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_archive_in_place(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': False,
                    'owner': {'login': 'octo'},
                    'name': 'demo',
                },
            )
        )
        patch_route = respx.patch(
            'https://api.github.com/repos/octo/demo'
        ).mock(return_value=httpx.Response(200, json={}))

        plugin = GitHubLifecyclePlugin()
        result = await plugin.on_project_archived(_ctx(), _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertIn('Archived', result.message or '')
        self.assertEqual(
            result.artifacts['repo_url'], 'https://github.com/octo/demo'
        )
        # Exactly one PATCH, with archived=true
        self.assertEqual(patch_route.calls.call_count, 1)
        self.assertEqual(
            patch_route.calls.last.request.read(),
            b'{"archived":true}',
        )

    @respx.mock
    async def test_archive_already_archived_is_skipped(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': True,
                    'owner': {'login': 'octo'},
                    'name': 'demo',
                },
            )
        )
        patch_route = respx.patch(
            'https://api.github.com/repos/octo/demo'
        ).mock(return_value=httpx.Response(200, json={}))

        plugin = GitHubLifecyclePlugin()
        result = await plugin.on_project_archived(_ctx(), _CREDS)

        self.assertEqual(result.status, 'skipped')
        self.assertIn('already archived', result.message or '')
        self.assertEqual(patch_route.calls.call_count, 0)

    @respx.mock
    async def test_archive_transfer_then_archive(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': False,
                    'owner': {'login': 'octo'},
                    'name': 'demo',
                },
            )
        )
        transfer_route = respx.post(
            'https://api.github.com/repos/octo/demo/transfer'
        ).mock(
            return_value=httpx.Response(
                202,
                json={'name': 'demo', 'owner': {'login': 'octo-archive'}},
            )
        )
        archive_route = respx.patch(
            'https://api.github.com/repos/octo-archive/demo'
        ).mock(return_value=httpx.Response(200, json={}))

        plugin = GitHubLifecyclePlugin()
        result = await plugin.on_project_archived(
            _ctx(options={'archive_target_org': 'octo-archive'}),
            _CREDS,
        )

        self.assertEqual(result.status, 'ok')
        self.assertEqual(transfer_route.calls.call_count, 1)
        self.assertEqual(
            transfer_route.calls.last.request.read(),
            b'{"new_owner":"octo-archive"}',
        )
        self.assertEqual(archive_route.calls.call_count, 1)
        self.assertEqual(
            result.artifacts['repo_url'],
            'https://github.com/octo-archive/demo',
        )

    @respx.mock
    async def test_archive_transfer_retries_settle_404(self) -> None:
        # GitHub's transfer is async (202); the repo is briefly
        # unreachable at the destination, so the first archive PATCH
        # 404s.  The plugin must retry and succeed once it settles.
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': False,
                    'owner': {'login': 'octo'},
                    'name': 'demo',
                },
            )
        )
        respx.post('https://api.github.com/repos/octo/demo/transfer').mock(
            return_value=httpx.Response(
                202,
                json={'name': 'demo', 'owner': {'login': 'octo-archive'}},
            )
        )
        archive_route = respx.patch(
            'https://api.github.com/repos/octo-archive/demo'
        ).mock(
            side_effect=[
                httpx.Response(404, json={'message': 'Not Found'}),
                httpx.Response(404, json={'message': 'Not Found'}),
                httpx.Response(200, json={}),
            ]
        )

        plugin = GitHubLifecyclePlugin()
        with unittest.mock.patch(
            'imbi_plugin_github.lifecycle.asyncio.sleep'
        ) as sleep:
            result = await plugin.on_project_archived(
                _ctx(options={'archive_target_org': 'octo-archive'}),
                _CREDS,
            )

        self.assertEqual(result.status, 'ok')
        self.assertEqual(archive_route.calls.call_count, 3)
        # Two failed attempts → two backoff sleeps before success.
        self.assertEqual(sleep.await_count, 2)

    @respx.mock
    async def test_archive_transfer_exhausts_retries_on_persistent_404(
        self,
    ) -> None:
        # If the transfer never settles within the retry budget the
        # final 404 must propagate so the dispatcher records a failure.
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': False,
                    'owner': {'login': 'octo'},
                    'name': 'demo',
                },
            )
        )
        respx.post('https://api.github.com/repos/octo/demo/transfer').mock(
            return_value=httpx.Response(
                202,
                json={'name': 'demo', 'owner': {'login': 'octo-archive'}},
            )
        )
        archive_route = respx.patch(
            'https://api.github.com/repos/octo-archive/demo'
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))

        plugin = GitHubLifecyclePlugin()
        with unittest.mock.patch(
            'imbi_plugin_github.lifecycle.asyncio.sleep'
        ) as sleep:
            with self.assertRaises(httpx.HTTPStatusError):
                await plugin.on_project_archived(
                    _ctx(options={'archive_target_org': 'octo-archive'}),
                    _CREDS,
                )

        # Three backoffs configured → four total attempts.
        self.assertEqual(archive_route.calls.call_count, 4)
        self.assertEqual(sleep.await_count, 3)

    @respx.mock
    async def test_archive_transfer_does_not_retry_non_404(self) -> None:
        # A non-404 (e.g. permissions) is a real failure: raise at once.
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': False,
                    'owner': {'login': 'octo'},
                    'name': 'demo',
                },
            )
        )
        respx.post('https://api.github.com/repos/octo/demo/transfer').mock(
            return_value=httpx.Response(
                202,
                json={'name': 'demo', 'owner': {'login': 'octo-archive'}},
            )
        )
        archive_route = respx.patch(
            'https://api.github.com/repos/octo-archive/demo'
        ).mock(return_value=httpx.Response(403, json={'message': 'Forbidden'}))

        plugin = GitHubLifecyclePlugin()
        with unittest.mock.patch(
            'imbi_plugin_github.lifecycle.asyncio.sleep'
        ) as sleep:
            with self.assertRaises(httpx.HTTPStatusError):
                await plugin.on_project_archived(
                    _ctx(options={'archive_target_org': 'octo-archive'}),
                    _CREDS,
                )

        self.assertEqual(archive_route.calls.call_count, 1)
        self.assertEqual(sleep.await_count, 0)

    @respx.mock
    async def test_archive_transfer_when_already_archived(self) -> None:
        # GitHub forbids transferring archived repos, so the plugin must
        # briefly unarchive, transfer, and re-archive at the destination.
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': True,
                    'owner': {'login': 'octo'},
                    'name': 'demo',
                },
            )
        )
        unarchive_source = respx.patch(
            'https://api.github.com/repos/octo/demo'
        ).mock(return_value=httpx.Response(200, json={}))
        transfer_route = respx.post(
            'https://api.github.com/repos/octo/demo/transfer'
        ).mock(
            return_value=httpx.Response(
                202,
                json={'name': 'demo', 'owner': {'login': 'octo-archive'}},
            )
        )
        rearchive = respx.patch(
            'https://api.github.com/repos/octo-archive/demo'
        ).mock(return_value=httpx.Response(200, json={}))

        plugin = GitHubLifecyclePlugin()
        result = await plugin.on_project_archived(
            _ctx(options={'archive_target_org': 'octo-archive'}),
            _CREDS,
        )

        self.assertEqual(result.status, 'ok')
        # 1x PATCH at source (unarchive), 1x transfer, 1x PATCH at dest
        self.assertEqual(unarchive_source.calls.call_count, 1)
        self.assertEqual(
            unarchive_source.calls.last.request.read(),
            b'{"archived":false}',
        )
        self.assertEqual(transfer_route.calls.call_count, 1)
        self.assertEqual(rearchive.calls.call_count, 1)
        self.assertEqual(
            rearchive.calls.last.request.read(),
            b'{"archived":true}',
        )

    @respx.mock
    async def test_archive_transfer_honors_renamed_repo(self) -> None:
        # GitHub may rename a transferred repo if the destination org
        # already has one by that name.  The post-transfer PATCH must
        # target the new name.
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': False,
                    'owner': {'login': 'octo'},
                    'name': 'demo',
                },
            )
        )
        respx.post('https://api.github.com/repos/octo/demo/transfer').mock(
            return_value=httpx.Response(
                202,
                json={
                    'name': 'demo-renamed',
                    'owner': {'login': 'octo-archive'},
                },
            )
        )
        rename_archive = respx.patch(
            'https://api.github.com/repos/octo-archive/demo-renamed'
        ).mock(return_value=httpx.Response(200, json={}))

        plugin = GitHubLifecyclePlugin()
        result = await plugin.on_project_archived(
            _ctx(options={'archive_target_org': 'octo-archive'}),
            _CREDS,
        )

        self.assertEqual(result.status, 'ok')
        self.assertEqual(rename_archive.calls.call_count, 1)
        self.assertIn('demo-renamed', result.artifacts['repo_url'])

    @respx.mock
    async def test_archive_target_org_matches_current_owner_no_transfer(
        self,
    ) -> None:
        # Repo already lives at the configured target org → no transfer.
        respx.get('https://api.github.com/repos/octo-archive/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': False,
                    'owner': {'login': 'octo-archive'},
                    'name': 'demo',
                },
            )
        )
        archive_route = respx.patch(
            'https://api.github.com/repos/octo-archive/demo'
        ).mock(return_value=httpx.Response(200, json={}))
        # If a transfer were attempted, the unmocked route would 404
        transfer_route = respx.post(
            'https://api.github.com/repos/octo-archive/demo/transfer'
        )

        plugin = GitHubLifecyclePlugin()
        result = await plugin.on_project_archived(
            _ctx(
                options={'archive_target_org': 'octo-archive'},
                project_links={
                    'github-repository': 'https://github.com/octo-archive/demo',
                },
            ),
            _CREDS,
        )

        self.assertEqual(result.status, 'ok')
        self.assertEqual(archive_route.calls.call_count, 1)
        self.assertEqual(transfer_route.calls.call_count, 0)

    @respx.mock
    async def test_archive_raises_on_missing_link(self) -> None:
        plugin = GitHubLifecyclePlugin()
        with self.assertRaises(ValueError):
            await plugin.on_project_archived(_ctx(project_links={}), _CREDS)

    async def test_archive_requires_access_token(self) -> None:
        plugin = GitHubLifecyclePlugin()
        with self.assertRaises(ValueError):
            await plugin.on_project_archived(_ctx(), {})

    @respx.mock
    async def test_archive_401_raises_authentication_failed(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(401, json={'message': 'Bad creds'})
        )
        plugin = GitHubLifecyclePlugin()
        with self.assertRaises(PluginAuthenticationFailed):
            await plugin.on_project_archived(_ctx(), _CREDS)


class UnarchiveTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_unarchive_happy_path(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': True,
                    'owner': {'login': 'octo'},
                    'name': 'demo',
                },
            )
        )
        patch_route = respx.patch(
            'https://api.github.com/repos/octo/demo'
        ).mock(return_value=httpx.Response(200, json={}))

        plugin = GitHubLifecyclePlugin()
        result = await plugin.on_project_unarchived(_ctx(), _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertEqual(patch_route.calls.call_count, 1)
        self.assertEqual(
            patch_route.calls.last.request.read(),
            b'{"archived":false}',
        )

    @respx.mock
    async def test_unarchive_when_not_archived_is_skipped(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': False,
                    'owner': {'login': 'octo'},
                    'name': 'demo',
                },
            )
        )
        patch_route = respx.patch(
            'https://api.github.com/repos/octo/demo'
        ).mock(return_value=httpx.Response(200, json={}))

        plugin = GitHubLifecyclePlugin()
        result = await plugin.on_project_unarchived(_ctx(), _CREDS)

        self.assertEqual(result.status, 'skipped')
        self.assertEqual(patch_route.calls.call_count, 0)


class HostResolutionTestCase(unittest.TestCase):
    def test_github_com_ignores_host_option(self) -> None:
        self.assertEqual(
            GitHubLifecyclePlugin._resolve_host({'host': 'ignored'}),
            'github.com',
        )

    def test_ghec_requires_tenant_host(self) -> None:
        plugin = GitHubEnterpriseCloudLifecyclePlugin()
        self.assertEqual(
            plugin._resolve_host({'host': 'tenant.ghe.com'}),
            'tenant.ghe.com',
        )
        with self.assertRaises(ValueError):
            plugin._resolve_host({'host': 'github.example.com'})

    def test_ghes_accepts_any_host(self) -> None:
        plugin = GitHubEnterpriseServerLifecyclePlugin()
        self.assertEqual(
            plugin._resolve_host({'host': 'ghe.example.com'}),
            'ghe.example.com',
        )


class GhecApiBaseTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_ghec_archive_hits_tenant_api(self) -> None:
        # The GHEC API base is ``https://api.<tenant>.ghe.com`` — make
        # sure the lifecycle plugin composes its URLs the same way as
        # the deployment plugin so admins do not have to configure two
        # different hosts.
        respx.get('https://api.tenant.ghe.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': False,
                    'owner': {'login': 'octo'},
                    'name': 'demo',
                },
            )
        )
        respx.patch('https://api.tenant.ghe.com/repos/octo/demo').mock(
            return_value=httpx.Response(200, json={})
        )

        plugin = GitHubEnterpriseCloudLifecyclePlugin()
        result = await plugin.on_project_archived(
            _ctx(
                options={'host': 'tenant.ghe.com'},
                project_links={
                    'github-repository': ('https://tenant.ghe.com/octo/demo'),
                },
            ),
            _CREDS,
        )
        self.assertEqual(result.status, 'ok')
        self.assertEqual(
            result.artifacts['repo_url'],
            'https://tenant.ghe.com/octo/demo',
        )


class RenameRelocationTestCase(unittest.IsolatedAsyncioTestCase):
    """A repo renamed outside Imbi: the stale path 301s to the by-id form,
    the client follows it, and the canonical owner/repo are adopted and
    reported on ``ctx`` for the host to self-heal the link.
    """

    @respx.mock
    async def test_archive_follows_rename_and_reports_relocation(
        self,
    ) -> None:
        # Stale path 301s to the canonical /repositories/{id}; the repo's
        # current name is ``renamed``.
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                301,
                headers={
                    'location': 'https://api.github.com/repositories/123'
                },
            )
        )
        respx.get('https://api.github.com/repositories/123').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': False,
                    'owner': {'login': 'octo'},
                    'name': 'renamed',
                    'html_url': 'https://github.com/octo/renamed',
                },
            )
        )
        # Archive targets the canonical name we adopted from the payload.
        patch_route = respx.patch(
            'https://api.github.com/repos/octo/renamed'
        ).mock(return_value=httpx.Response(200, json={}))

        ctx = _ctx()
        plugin = GitHubLifecyclePlugin()
        result = await plugin.on_project_archived(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertEqual(patch_route.calls.call_count, 1)
        self.assertEqual(
            result.artifacts['repo_url'], 'https://github.com/octo/renamed'
        )
        reloc = ctx.repository_relocation
        assert reloc is not None
        self.assertEqual(reloc.link_key, 'github-repository')
        self.assertEqual(reloc.new_url, 'https://github.com/octo/renamed')
        self.assertEqual(reloc.old_owner_repo, 'octo/demo')
        self.assertEqual(reloc.new_owner_repo, 'octo/renamed')

    @respx.mock
    async def test_unarchive_follows_rename_and_reports_relocation(
        self,
    ) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                301,
                headers={
                    'location': 'https://api.github.com/repositories/123'
                },
            )
        )
        respx.get('https://api.github.com/repositories/123').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': True,
                    'owner': {'login': 'octo'},
                    'name': 'renamed',
                    'html_url': 'https://github.com/octo/renamed',
                },
            )
        )
        patch_route = respx.patch(
            'https://api.github.com/repos/octo/renamed'
        ).mock(return_value=httpx.Response(200, json={}))

        ctx = _ctx()
        plugin = GitHubLifecyclePlugin()
        result = await plugin.on_project_unarchived(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertEqual(patch_route.calls.call_count, 1)
        reloc = ctx.repository_relocation
        assert reloc is not None
        self.assertEqual(reloc.new_owner_repo, 'octo/renamed')

    @respx.mock
    async def test_archive_skip_uses_canonical_owner_in_artifact(
        self,
    ) -> None:
        # External rename moved the repo to a new owner *and* it is already
        # archived, so we hit the skip path. The artifact URL must reflect
        # the canonical owner/repo, not the stale link-derived owner.
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                301,
                headers={
                    'location': 'https://api.github.com/repositories/123'
                },
            )
        )
        respx.get('https://api.github.com/repositories/123').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': True,
                    'owner': {'login': 'octo-new'},
                    'name': 'renamed',
                    'html_url': 'https://github.com/octo-new/renamed',
                },
            )
        )

        ctx = _ctx()
        plugin = GitHubLifecyclePlugin()
        result = await plugin.on_project_archived(ctx, _CREDS)

        self.assertEqual(result.status, 'skipped')
        self.assertEqual(
            result.artifacts['repo_url'],
            'https://github.com/octo-new/renamed',
        )

    @respx.mock
    async def test_no_relocation_when_not_renamed(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': False,
                    'owner': {'login': 'octo'},
                    'name': 'demo',
                },
            )
        )
        respx.patch('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(200, json={})
        )
        ctx = _ctx()
        plugin = GitHubLifecyclePlugin()
        await plugin.on_project_archived(ctx, _CREDS)
        self.assertIsNone(ctx.repository_relocation)

    @respx.mock
    async def test_intentional_transfer_is_not_reported_as_relocation(
        self,
    ) -> None:
        # Repo is found at its stored location (no external rename), then
        # we transfer it to the archive org. That intentional move must
        # NOT be reported as a relocation.
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'archived': False,
                    'owner': {'login': 'octo'},
                    'name': 'demo',
                },
            )
        )
        respx.post('https://api.github.com/repos/octo/demo/transfer').mock(
            return_value=httpx.Response(202, json={'name': 'demo'})
        )
        respx.patch('https://api.github.com/repos/archives/demo').mock(
            return_value=httpx.Response(200, json={})
        )
        ctx = _ctx(options={'archive_target_org': 'archives'})
        plugin = GitHubLifecyclePlugin()
        result = await plugin.on_project_archived(ctx, _CREDS)
        self.assertEqual(result.status, 'ok')
        self.assertIsNone(ctx.repository_relocation)
