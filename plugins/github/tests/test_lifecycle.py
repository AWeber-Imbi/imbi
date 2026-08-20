"""Smoke tests for the GitHub lifecycle capability handler.

Covers manifest shape, archive-in-place, transfer-then-archive,
idempotent skip when already archived (or already unarchived), the
brief unarchive-transfer-rearchive dance when transferring an already-
archived repo, the rename-on-transfer case, repo-resolution failure
from absent links, and the 401 -> PluginAuthenticationFailed path.
"""

import json
import unittest
import unittest.mock

import httpx
import respx

from imbi.common.plugins.base import (
    LifecycleCapability,
    PluginContext,
)
from imbi.common.plugins.errors import PluginAuthenticationFailed
from imbi.plugins.github.lifecycle import (
    _MAX_DESCRIPTION_CHARS,
    GitHubLifecycle,
    _normalize_description,
)
from imbi.plugins.github.plugin import GitHubPlugin


def _connection(
    flavor: str = 'github', host: str | None = None
) -> dict[str, object]:
    options: dict[str, object] = {'flavor': flavor}
    if host is not None:
        options['host'] = host
    return options


def _ctx(
    options: dict[str, object] | None = None,
    project_links: dict[str, str] | None = None,
    project_type_slugs: list[str] | None = None,
    *,
    project_slug: str = 'demo',
    previous_project_slug: str | None = None,
    project_name: str | None = None,
    project_description: str | None = None,
    project_ui_url: str | None = None,
    integration_slug: str | None = None,
    connection: dict[str, object] | None = None,
) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug=project_slug,
        org_slug='octo',
        capability_options=options or {},
        actor_user_id='u-1',
        project_links=(
            project_links
            if project_links is not None
            else {'github-repository': 'https://github.com/octo/demo'}
        ),
        project_type_slugs=project_type_slugs or [],
        previous_project_slug=previous_project_slug,
        project_name=project_name,
        project_description=project_description,
        project_ui_url=project_ui_url,
        integration_slug=integration_slug,
        integration_options=(
            connection if connection is not None else _connection()
        ),
    )


_CREDS = {'access_token': 'gho_test'}


def _lifecycle_cap():  # type: ignore[no-untyped-def]
    cap = GitHubPlugin.manifest.get_capability('lifecycle')
    assert cap is not None
    return cap


class ManifestTestCase(unittest.TestCase):
    def test_manifest_slug(self) -> None:
        self.assertEqual(GitHubPlugin.manifest.slug, 'github')

    def test_is_lifecycle_capability(self) -> None:
        cap = _lifecycle_cap()
        self.assertTrue(issubclass(cap.handler, LifecycleCapability))
        self.assertIs(cap.handler, GitHubLifecycle)

    def test_archive_target_org_option(self) -> None:
        # The transfer-on-archive option is the load-bearing setting for
        # this capability.
        names = {opt.name for opt in _lifecycle_cap().options}
        self.assertIn('archive_target_org', names)

    def test_create_org_and_org_mapping_options(self) -> None:
        opts = {opt.name: opt for opt in _lifecycle_cap().options}
        self.assertIn('create_org', opts)
        self.assertEqual(opts['create_org'].type, 'string')
        self.assertIn('org_mapping', opts)
        self.assertEqual(opts['org_mapping'].type, 'mapping')

    def test_create_visibility_option_has_no_manifest_default(self) -> None:
        # The default is flavor-dependent, so it must be resolved by the
        # handler -- a manifest default gets pre-filled into the stored
        # options by the admin wizard and would defeat that.
        opts = {opt.name: opt for opt in _lifecycle_cap().options}
        self.assertIn('create_visibility', opts)
        self.assertIsNone(opts['create_visibility'].default)
        self.assertEqual(
            opts['create_visibility'].choices,
            ['private', 'internal', 'public'],
        )

    def test_no_host_option(self) -> None:
        # Host now comes from the Integration's flavor/host options, not a
        # per-capability option on the lifecycle capability itself.
        names = {opt.name for opt in _lifecycle_cap().options}
        self.assertNotIn('host', names)

    def test_lifecycle_events_includes_all_supported(self) -> None:
        # The ``lifecycle_events`` hint drives UI affordance gating (e.g.
        # the "Also delete the repository" checkbox).
        expected = {
            'created',
            'updated',
            'archived',
            'unarchived',
            'deleted',
            'relocated',
        }
        self.assertEqual(
            set(_lifecycle_cap().hints['lifecycle_events']), expected
        )


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

        plugin = GitHubLifecycle()
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

        plugin = GitHubLifecycle()
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

        plugin = GitHubLifecycle()
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

        plugin = GitHubLifecycle()
        with unittest.mock.patch(
            'imbi.plugins.github.lifecycle.asyncio.sleep'
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

        plugin = GitHubLifecycle()
        with unittest.mock.patch(
            'imbi.plugins.github.lifecycle.asyncio.sleep'
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

        plugin = GitHubLifecycle()
        with unittest.mock.patch(
            'imbi.plugins.github.lifecycle.asyncio.sleep'
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

        plugin = GitHubLifecycle()
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

        plugin = GitHubLifecycle()
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

        plugin = GitHubLifecycle()
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
        plugin = GitHubLifecycle()
        with self.assertRaises(ValueError):
            await plugin.on_project_archived(_ctx(project_links={}), _CREDS)

    async def test_archive_requires_access_token(self) -> None:
        plugin = GitHubLifecycle()
        with self.assertRaises(ValueError):
            await plugin.on_project_archived(_ctx(), {})

    @respx.mock
    async def test_archive_401_raises_authentication_failed(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(401, json={'message': 'Bad creds'})
        )
        plugin = GitHubLifecycle()
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

        plugin = GitHubLifecycle()
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

        plugin = GitHubLifecycle()
        result = await plugin.on_project_unarchived(_ctx(), _CREDS)

        self.assertEqual(result.status, 'skipped')
        self.assertEqual(patch_route.calls.call_count, 0)


class HostResolutionTestCase(unittest.TestCase):
    def test_github_com_resolves_from_connection(self) -> None:
        plugin = GitHubLifecycle()
        self.assertEqual(
            plugin._resolve_host(_ctx(connection=_connection('github'))),
            'github.com',
        )

    def test_ghec_requires_tenant_host(self) -> None:
        plugin = GitHubLifecycle()
        self.assertEqual(
            plugin._resolve_host(
                _ctx(connection=_connection('ghec', 'tenant.ghe.com'))
            ),
            'tenant.ghe.com',
        )
        with self.assertRaises(ValueError):
            plugin._resolve_host(
                _ctx(connection=_connection('ghec', 'github.example.com'))
            )

    def test_ghes_accepts_any_host(self) -> None:
        plugin = GitHubLifecycle()
        self.assertEqual(
            plugin._resolve_host(
                _ctx(connection=_connection('ghes', 'ghe.example.com'))
            ),
            'ghe.example.com',
        )

    def test_missing_connection_raises(self) -> None:
        # A context with no github-connection sibling cannot resolve a
        # host and must raise an operator-facing ValueError.
        plugin = GitHubLifecycle()
        with self.assertRaises(ValueError):
            plugin._resolve_host(_ctx(connection={}))


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

        plugin = GitHubLifecycle()
        result = await plugin.on_project_archived(
            _ctx(
                connection=_connection('ghec', 'tenant.ghe.com'),
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
        plugin = GitHubLifecycle()
        result = await plugin.on_project_archived(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertEqual(patch_route.calls.call_count, 1)
        self.assertEqual(
            result.artifacts['repo_url'], 'https://github.com/octo/renamed'
        )
        reloc = ctx.link_writeback
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
        plugin = GitHubLifecycle()
        result = await plugin.on_project_unarchived(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertEqual(patch_route.calls.call_count, 1)
        reloc = ctx.link_writeback
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
        plugin = GitHubLifecycle()
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
        plugin = GitHubLifecycle()
        await plugin.on_project_archived(ctx, _CREDS)
        self.assertIsNone(ctx.link_writeback)

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
        plugin = GitHubLifecycle()
        result = await plugin.on_project_archived(ctx, _CREDS)
        self.assertEqual(result.status, 'ok')
        self.assertIsNone(ctx.link_writeback)


class CreateTestCase(unittest.IsolatedAsyncioTestCase):
    """``on_project_created`` provisions the repo and writes the link."""

    @respx.mock
    async def test_create_happy_path_uses_org_mapping(self) -> None:
        # Project-type mapping wins over ``create_org``; the repo is
        # created at the mapped org and the link writeback carries the
        # canonical ``html_url`` GitHub returned.
        respx.get('https://api.github.com/repos/aweber-apis/demo').mock(
            return_value=httpx.Response(404, json={'message': 'Not Found'})
        )
        create_route = respx.post(
            'https://api.github.com/orgs/aweber-apis/repos'
        ).mock(
            return_value=httpx.Response(
                201,
                json={
                    'name': 'demo',
                    'html_url': 'https://github.com/aweber-apis/demo',
                    'owner': {'login': 'aweber-apis'},
                },
            )
        )

        ctx = _ctx(
            options={
                'create_org': 'fallback',
                'org_mapping': {'api-service': 'aweber-apis'},
            },
            project_links={},
            project_type_slugs=['api-service'],
            project_description='An example API',
            project_ui_url='https://imbi.example.com/projects/p',
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_created(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertEqual(create_route.calls.call_count, 1)
        self.assertEqual(
            json.loads(create_route.calls.last.request.read()),
            {
                'name': 'demo',
                'description': 'An example API',
                'homepage': 'https://imbi.example.com/projects/p',
                # ``github`` flavor, no option set -> public, the only
                # visibility github.com shares with the enterprise hosts.
                'visibility': 'public',
                'private': False,
            },
        )
        self.assertIsNotNone(ctx.link_writeback)
        assert ctx.link_writeback is not None
        self.assertEqual(ctx.link_writeback.link_key, 'github-repository')
        self.assertEqual(
            ctx.link_writeback.new_url,
            'https://github.com/aweber-apis/demo',
        )

    @respx.mock
    async def test_create_falls_back_to_template(self) -> None:
        # No mapping match → expand the ``create_org`` template.
        respx.get('https://api.github.com/repos/aweber-api-service/demo').mock(
            return_value=httpx.Response(404, json={'message': 'Not Found'})
        )
        create_route = respx.post(
            'https://api.github.com/orgs/aweber-api-service/repos'
        ).mock(
            return_value=httpx.Response(
                201,
                json={
                    'name': 'demo',
                    'html_url': ('https://github.com/aweber-api-service/demo'),
                },
            )
        )

        ctx = _ctx(
            options={'create_org': 'aweber-${project_type_slug}'},
            project_links={},
            project_type_slugs=['api-service'],
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_created(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertEqual(create_route.calls.call_count, 1)

    @respx.mock
    async def test_create_honors_configured_visibility(self) -> None:
        respx.get('https://api.github.com/repos/aweber-apis/demo').mock(
            return_value=httpx.Response(404, json={'message': 'Not Found'})
        )
        create_route = respx.post(
            'https://api.github.com/orgs/aweber-apis/repos'
        ).mock(
            return_value=httpx.Response(
                201,
                json={
                    'name': 'demo',
                    'html_url': 'https://github.com/aweber-apis/demo',
                },
            )
        )
        ctx = _ctx(
            options={
                'org_mapping': {'api-service': 'aweber-apis'},
                'create_visibility': 'private',
            },
            project_links={},
            project_type_slugs=['api-service'],
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_created(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        body = json.loads(create_route.calls.last.request.read())
        # The option overrides the ``internal`` default.
        self.assertEqual(body['visibility'], 'private')
        self.assertIs(body['private'], True)

    async def _create_on(
        self, flavor: str, host: str, api_base: str
    ) -> dict[str, object]:
        """Run a create against one flavor, returning the POST body."""
        respx.get(f'{api_base}/repos/aweber-apis/demo').mock(
            return_value=httpx.Response(404, json={'message': 'Not Found'})
        )
        create_route = respx.post(f'{api_base}/orgs/aweber-apis/repos').mock(
            return_value=httpx.Response(
                201,
                json={
                    'name': 'demo',
                    'html_url': f'https://{host}/aweber-apis/demo',
                },
            )
        )
        ctx = _ctx(
            options={'org_mapping': {'api-service': 'aweber-apis'}},
            project_links={},
            project_type_slugs=['api-service'],
            connection=_connection(flavor, host),
        )
        result = await GitHubLifecycle().on_project_created(ctx, _CREDS)
        self.assertEqual(result.status, 'ok')
        body: dict[str, object] = json.loads(
            create_route.calls.last.request.read()
        )
        return body

    @respx.mock
    async def test_create_defaults_to_internal_on_ghec(self) -> None:
        # An unset option on an enterprise host means ``internal``, not
        # the ``public`` default that github.com gets.
        body = await self._create_on(
            'ghec', 'tenant.ghe.com', 'https://api.tenant.ghe.com'
        )
        self.assertEqual(body['visibility'], 'internal')
        self.assertIs(body['private'], True)

    @respx.mock
    async def test_create_defaults_to_internal_on_ghes(self) -> None:
        body = await self._create_on(
            'ghes', 'github.example.com', 'https://github.example.com/api/v3'
        )
        self.assertEqual(body['visibility'], 'internal')
        self.assertIs(body['private'], True)

    @respx.mock
    async def test_create_surfaces_github_validation_detail(self) -> None:
        # A 422 from GitHub (e.g. org policy forbids the visibility) must
        # name the reason -- ``raise_for_status`` alone hides the body.
        respx.get('https://api.github.com/repos/aweber-apis/demo').mock(
            return_value=httpx.Response(404, json={'message': 'Not Found'})
        )
        respx.post('https://api.github.com/orgs/aweber-apis/repos').mock(
            return_value=httpx.Response(
                422,
                json={
                    'message': 'Repository creation failed.',
                    'errors': [
                        {
                            'resource': 'Repository',
                            'field': 'visibility',
                            'message': "Visibility can't be public",
                        }
                    ],
                },
            )
        )
        ctx = _ctx(
            options={
                'org_mapping': {'api-service': 'aweber-apis'},
                'create_visibility': 'public',
            },
            project_links={},
            project_type_slugs=['api-service'],
        )
        plugin = GitHubLifecycle()
        with self.assertRaises(RuntimeError) as raised:
            await plugin.on_project_created(ctx, _CREDS)

        message = str(raised.exception)
        self.assertIn('aweber-apis/demo', message)
        self.assertIn('visibility=public', message)
        self.assertIn('Repository creation failed.', message)
        self.assertIn("visibility: Visibility can't be public", message)

    async def test_create_skips_when_no_target_org_configured(self) -> None:
        # Neither mapping nor template -> clean skip rather than HTTP.
        ctx = _ctx(
            options={},
            project_links={},
            project_type_slugs=['api-service'],
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_created(ctx, _CREDS)
        self.assertEqual(result.status, 'skipped')
        self.assertIn('No target org', result.message or '')
        self.assertIsNone(ctx.link_writeback)

    @respx.mock
    async def test_create_idempotent_when_repo_exists(self) -> None:
        # Re-running a create for a repo that already exists adopts the
        # existing URL via a link writeback and reports ``skipped``.
        respx.get('https://api.github.com/repos/aweber-apis/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'name': 'demo',
                    'html_url': 'https://github.com/aweber-apis/demo',
                    'owner': {'login': 'aweber-apis'},
                },
            )
        )
        create_route = respx.post(
            'https://api.github.com/orgs/aweber-apis/repos'
        ).mock(return_value=httpx.Response(201, json={}))

        ctx = _ctx(
            options={'org_mapping': {'api-service': 'aweber-apis'}},
            project_links={},
            project_type_slugs=['api-service'],
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_created(ctx, _CREDS)
        self.assertEqual(result.status, 'skipped')
        self.assertIn('already exists', result.message or '')
        self.assertEqual(create_route.calls.call_count, 0)
        self.assertIsNotNone(ctx.link_writeback)


class ServiceWritebackTestCase(unittest.IsolatedAsyncioTestCase):
    """When bound to a third-party service, hooks emit a ServiceWriteback
    (EXISTS_IN edge + dashboard link) instead of the legacy LinkWriteback.
    """

    @respx.mock
    async def test_create_emits_service_writeback(self) -> None:
        respx.get('https://api.github.com/repos/aweber-apis/demo').mock(
            return_value=httpx.Response(404, json={'message': 'Not Found'})
        )
        respx.post('https://api.github.com/orgs/aweber-apis/repos').mock(
            return_value=httpx.Response(
                201,
                json={
                    'id': 134741,
                    'name': 'demo',
                    'html_url': 'https://github.com/aweber-apis/demo',
                    'owner': {'login': 'aweber-apis'},
                },
            )
        )
        ctx = _ctx(
            options={'org_mapping': {'api-service': 'aweber-apis'}},
            project_links={},
            project_type_slugs=['api-service'],
            integration_slug='github',
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_created(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        # legacy link writeback is NOT used when bound to a service
        self.assertIsNone(ctx.link_writeback)
        wb = ctx.service_writeback
        assert wb is not None
        self.assertEqual(wb.identifier, '134741')
        self.assertEqual(
            wb.canonical_url,
            'https://api.github.com/repositories/134741',
        )
        self.assertEqual(
            wb.dashboard_links,
            {'github': 'https://github.com/aweber-apis/demo'},
        )

    @respx.mock
    async def test_create_falls_back_to_link_without_id(self) -> None:
        # No numeric id in the payload -> legacy LinkWriteback even when
        # bound to a service (can't build the id-based canonical URL).
        respx.get('https://api.github.com/repos/aweber-apis/demo').mock(
            return_value=httpx.Response(404, json={'message': 'Not Found'})
        )
        respx.post('https://api.github.com/orgs/aweber-apis/repos').mock(
            return_value=httpx.Response(
                201,
                json={
                    'name': 'demo',
                    'html_url': 'https://github.com/aweber-apis/demo',
                },
            )
        )
        ctx = _ctx(
            options={'org_mapping': {'api-service': 'aweber-apis'}},
            project_links={},
            project_type_slugs=['api-service'],
            integration_slug='github',
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_created(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertIsNone(ctx.service_writeback)
        assert ctx.link_writeback is not None
        self.assertEqual(ctx.link_writeback.link_key, 'github-repository')


class UpdateTestCase(unittest.IsolatedAsyncioTestCase):
    """``on_project_updated`` syncs slug/description/homepage to the repo."""

    @respx.mock
    async def test_update_syncs_all_three_fields_in_one_patch(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={
                    'name': 'demo',
                    'owner': {'login': 'octo'},
                },
            )
        )
        patch_route = respx.patch(
            'https://api.github.com/repos/octo/demo'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'name': 'demo',
                    'html_url': 'https://github.com/octo/demo',
                    'owner': {'login': 'octo'},
                },
            )
        )

        ctx = _ctx(
            project_description='New description',
            project_ui_url='https://imbi.example.com/projects/p',
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_updated(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertEqual(patch_route.calls.call_count, 1)
        body = patch_route.calls.last.request.read()
        self.assertIn(b'"name":"demo"', body)
        self.assertIn(b'"description":"New description"', body)
        self.assertIn(
            b'"homepage":"https://imbi.example.com/projects/p"', body
        )
        # Recorded even though nothing was renamed -- this assertion
        # used to require the opposite, which is what left the repo link
        # unwritten on the ordinary path (issue #254, defect 3).
        assert ctx.link_writeback is not None
        self.assertEqual(
            ctx.link_writeback.new_url, 'https://github.com/octo/demo'
        )
        self.assertIsNone(ctx.link_writeback.old_owner_repo)

    @respx.mock
    async def test_update_omits_unknown_description_and_homepage(
        self,
    ) -> None:
        # The ``/lifecycle/sync`` dispatch path leaves
        # ``project_description`` / ``project_ui_url`` unpopulated.  An
        # unknown value must be absent from the PATCH body -- sending
        # ``""`` would wipe whatever the repo had (issue #254, defect 4).
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={'name': 'demo', 'owner': {'login': 'octo'}},
            )
        )
        patch_route = respx.patch(
            'https://api.github.com/repos/octo/demo'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'name': 'demo',
                    'html_url': 'https://github.com/octo/demo',
                    'owner': {'login': 'octo'},
                },
            )
        )

        ctx = _ctx(project_description=None, project_ui_url=None)
        plugin = GitHubLifecycle()
        result = await plugin.on_project_updated(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        body = json.loads(patch_route.calls.last.request.read())
        self.assertEqual(body, {'name': 'demo'})

    @respx.mock
    async def test_update_sends_empty_description_when_cleared(self) -> None:
        # An explicit empty string is a deliberate clear and must still
        # reach GitHub -- only ``None`` (unknown) is omitted.
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={'name': 'demo', 'owner': {'login': 'octo'}},
            )
        )
        patch_route = respx.patch(
            'https://api.github.com/repos/octo/demo'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'name': 'demo',
                    'html_url': 'https://github.com/octo/demo',
                    'owner': {'login': 'octo'},
                },
            )
        )

        ctx = _ctx(project_description='', project_ui_url='')
        plugin = GitHubLifecycle()
        result = await plugin.on_project_updated(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        body = json.loads(patch_route.calls.last.request.read())
        self.assertEqual(
            body, {'name': 'demo', 'description': '', 'homepage': ''}
        )

    @respx.mock
    async def test_update_records_writeback_when_slug_changes(self) -> None:
        # A slug rename PATCHes ``name`` to the new value; the response
        # carries the new ``html_url`` and the plugin stashes the
        # writeback for the host to persist.
        respx.get('https://api.github.com/repos/octo/demo-old').mock(
            return_value=httpx.Response(
                200,
                json={
                    'name': 'demo-old',
                    'owner': {'login': 'octo'},
                },
            )
        )
        respx.patch('https://api.github.com/repos/octo/demo-old').mock(
            return_value=httpx.Response(
                200,
                json={
                    'name': 'demo-new',
                    'html_url': 'https://github.com/octo/demo-new',
                    'owner': {'login': 'octo'},
                },
            )
        )

        ctx = _ctx(
            project_slug='demo-new',
            previous_project_slug='demo-old',
            project_links={
                'github-repository': 'https://github.com/octo/demo-old',
            },
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_updated(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertIsNotNone(ctx.link_writeback)
        assert ctx.link_writeback is not None
        self.assertEqual(
            ctx.link_writeback.new_url,
            'https://github.com/octo/demo-new',
        )
        self.assertEqual(ctx.link_writeback.old_owner_repo, 'octo/demo-old')
        self.assertEqual(ctx.link_writeback.new_owner_repo, 'octo/demo-new')

    @respx.mock
    async def test_update_falls_back_to_previous_slug_without_link(
        self,
    ) -> None:
        # No stored link → resolve from ``<project_type_slug>/<previous_slug>``
        # so a slug-rename still finds the pre-rename repo on GitHub.
        respx.get('https://api.github.com/repos/api-service/demo-old').mock(
            return_value=httpx.Response(
                200,
                json={
                    'name': 'demo-old',
                    'owner': {'login': 'api-service'},
                },
            )
        )
        respx.patch('https://api.github.com/repos/api-service/demo-old').mock(
            return_value=httpx.Response(
                200,
                json={
                    'name': 'demo-new',
                    'html_url': ('https://github.com/api-service/demo-new'),
                },
            )
        )

        ctx = _ctx(
            project_slug='demo-new',
            previous_project_slug='demo-old',
            project_links={},
            project_type_slugs=['api-service'],
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_updated(ctx, _CREDS)
        self.assertEqual(result.status, 'ok')


class DeleteTestCase(unittest.IsolatedAsyncioTestCase):
    """``on_project_deleted`` removes the backing repository."""

    @respx.mock
    async def test_delete_happy_path(self) -> None:
        delete_route = respx.delete(
            'https://api.github.com/repos/octo/demo'
        ).mock(return_value=httpx.Response(204))

        plugin = GitHubLifecycle()
        result = await plugin.on_project_deleted(_ctx(), _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertEqual(delete_route.calls.call_count, 1)

    @respx.mock
    async def test_delete_already_gone_is_skipped(self) -> None:
        respx.delete('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(404, json={'message': 'Not Found'})
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_deleted(_ctx(), _CREDS)
        self.assertEqual(result.status, 'skipped')
        self.assertIn('already gone', result.message or '')

    async def test_delete_without_resolvable_repo_is_skipped(self) -> None:
        # No link, no project type → clean skip (rather than a hard
        # failure) since there's nothing to act on.
        ctx = _ctx(project_links={}, project_type_slugs=[])
        plugin = GitHubLifecycle()
        result = await plugin.on_project_deleted(ctx, _CREDS)
        self.assertEqual(result.status, 'skipped')


class RelocateTestCase(unittest.IsolatedAsyncioTestCase):
    """``on_project_relocated`` transfers the repo to the resolved org."""

    @respx.mock
    async def test_relocate_transfers_repo_and_records_writeback(
        self,
    ) -> None:
        transfer_route = respx.post(
            'https://api.github.com/repos/octo/demo/transfer'
        ).mock(
            return_value=httpx.Response(
                202,
                json={
                    'name': 'demo',
                    'html_url': 'https://github.com/aweber-apis/demo',
                    'owner': {'login': 'aweber-apis'},
                },
            )
        )

        ctx = _ctx(
            options={'org_mapping': {'api-service': 'aweber-apis'}},
            project_type_slugs=['api-service'],
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_relocated(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertEqual(transfer_route.calls.call_count, 1)
        self.assertEqual(
            transfer_route.calls.last.request.read(),
            b'{"new_owner":"aweber-apis"}',
        )
        self.assertIsNotNone(ctx.link_writeback)
        assert ctx.link_writeback is not None
        self.assertEqual(
            ctx.link_writeback.new_url,
            'https://github.com/aweber-apis/demo',
        )
        self.assertEqual(ctx.link_writeback.old_owner_repo, 'octo/demo')
        self.assertEqual(ctx.link_writeback.new_owner_repo, 'aweber-apis/demo')

    async def test_relocate_skips_when_no_target_resolved(self) -> None:
        ctx = _ctx(options={}, project_type_slugs=['api-service'])
        plugin = GitHubLifecycle()
        result = await plugin.on_project_relocated(ctx, _CREDS)
        self.assertEqual(result.status, 'skipped')
        self.assertIn('No relocation target', result.message or '')

    async def test_relocate_skips_when_already_at_target(self) -> None:
        # Current owner == target org → no transfer, clean skip.
        ctx = _ctx(
            options={'org_mapping': {'api-service': 'octo'}},
            project_type_slugs=['api-service'],
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_relocated(ctx, _CREDS)
        self.assertEqual(result.status, 'skipped')
        self.assertIn('already at the target', result.message or '')


class ResolveRelocationTargetTestCase(unittest.IsolatedAsyncioTestCase):
    """``resolve_relocation_target`` derives the target locally."""

    async def test_returns_target_from_mapping(self) -> None:
        ctx = _ctx(
            options={'org_mapping': {'api-service': 'aweber-apis'}},
            project_type_slugs=['api-service'],
        )
        plugin = GitHubLifecycle()
        target = await plugin.resolve_relocation_target(ctx, _CREDS)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.link_key, 'github-repository')
        self.assertEqual(target.identifier, 'aweber-apis/demo')

    async def test_returns_target_from_template_when_mapping_misses(
        self,
    ) -> None:
        ctx = _ctx(
            options={'create_org': 'aweber-${project_type_slug}'},
            project_type_slugs=['api-service'],
            project_links={},
        )
        plugin = GitHubLifecycle()
        target = await plugin.resolve_relocation_target(ctx, _CREDS)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.identifier, 'aweber-api-service/demo')

    async def test_returns_none_when_no_org_configured(self) -> None:
        ctx = _ctx(options={}, project_type_slugs=['api-service'])
        plugin = GitHubLifecycle()
        target = await plugin.resolve_relocation_target(ctx, _CREDS)
        self.assertIsNone(target)


class NormalizeDescriptionTestCase(unittest.TestCase):
    """``_normalize_description`` clamps to GitHub's 350-char cap."""

    def test_none_passes_through(self) -> None:
        # ``None`` is "unknown", not "empty" -- collapsing the two is
        # what wiped repo descriptions in issue #254.
        self.assertIsNone(_normalize_description(None))

    def test_empty_string_passes_through(self) -> None:
        self.assertEqual(_normalize_description(''), '')

    def test_exactly_at_the_limit_is_untouched(self) -> None:
        value = 'a' * _MAX_DESCRIPTION_CHARS
        self.assertEqual(_normalize_description(value), value)

    def test_one_over_the_limit_is_clamped(self) -> None:
        value = 'a' * (_MAX_DESCRIPTION_CHARS + 1)
        result = _normalize_description(value)
        assert result is not None
        self.assertEqual(len(result), _MAX_DESCRIPTION_CHARS)
        self.assertTrue(result.endswith('\u2026'))

    def test_clamps_on_a_word_boundary(self) -> None:
        value = ('word ' * 100).strip()
        result = _normalize_description(value)
        assert result is not None
        self.assertLessEqual(len(result), _MAX_DESCRIPTION_CHARS)
        self.assertTrue(result.endswith('word\u2026'))
        self.assertNotIn('wor\u2026', result)

    def test_single_token_longer_than_the_limit_is_hard_cut(self) -> None:
        # No space to break on, so the ellipsis lands mid-token rather
        # than the function returning nothing.
        value = 'x' * 500
        result = _normalize_description(value)
        self.assertEqual(result, 'x' * (_MAX_DESCRIPTION_CHARS - 1) + '\u2026')

    def test_counts_characters_not_bytes(self) -> None:
        # GitHub's limit is on characters; a multi-byte description at
        # the limit must survive untouched.
        value = '\u00e9' * _MAX_DESCRIPTION_CHARS
        self.assertEqual(_normalize_description(value), value)

    def test_strips_whitespace_before_the_ellipsis(self) -> None:
        value = 'a' * 340 + '          ' + 'b' * 50
        result = _normalize_description(value)
        assert result is not None
        self.assertEqual(result, 'a' * 340 + '\u2026')


class DescriptionClampTestCase(unittest.IsolatedAsyncioTestCase):
    """Both the create and the update path clamp the description."""

    @respx.mock
    async def test_create_clamps_an_over_long_description(self) -> None:
        # An 817-char description used to fail the whole POST with
        # "description cannot be more than 350 characters", costing the
        # repo over a cosmetic field (issue #254, defect 1).
        create_route = respx.post(
            'https://api.github.com/orgs/aweber-apis/repos'
        ).mock(
            return_value=httpx.Response(
                201,
                json={
                    'id': 42,
                    'name': 'demo',
                    'html_url': 'https://github.com/aweber-apis/demo',
                    'owner': {'login': 'aweber-apis'},
                },
            )
        )
        respx.get('https://api.github.com/repos/aweber-apis/demo').mock(
            return_value=httpx.Response(404)
        )

        ctx = _ctx(
            options={'create_org': 'aweber-apis'},
            project_links={},
            project_description='word ' * 200,
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_created(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        body = json.loads(create_route.calls.last.request.read())
        self.assertLessEqual(len(body['description']), _MAX_DESCRIPTION_CHARS)
        self.assertTrue(body['description'].endswith('\u2026'))

    @respx.mock
    async def test_update_clamps_an_over_long_description(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                200,
                json={'name': 'demo', 'owner': {'login': 'octo'}},
            )
        )
        patch_route = respx.patch(
            'https://api.github.com/repos/octo/demo'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'name': 'demo',
                    'html_url': 'https://github.com/octo/demo',
                    'owner': {'login': 'octo'},
                },
            )
        )

        ctx = _ctx(project_description='word ' * 200)
        plugin = GitHubLifecycle()
        result = await plugin.on_project_updated(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        body = json.loads(patch_route.calls.last.request.read())
        self.assertLessEqual(len(body['description']), _MAX_DESCRIPTION_CHARS)


class UpdateUpsertTestCase(unittest.IsolatedAsyncioTestCase):
    """``on_project_updated`` provisions a repo it finds missing.

    ``on_project_created`` is reachable only from the project-create
    endpoint, so before this an update was the sole event that could
    repair a failed creation -- and it 404'd instead (issue #254,
    defect 2).
    """

    @staticmethod
    def _created_response() -> httpx.Response:
        return httpx.Response(
            201,
            json={
                'id': 7,
                'name': 'demo',
                'html_url': 'https://github.com/aweber-apis/demo',
                'owner': {'login': 'aweber-apis'},
            },
        )

    @respx.mock
    async def test_creates_when_the_repo_is_missing(self) -> None:
        respx.get('https://api.github.com/repos/aweber-apis/demo').mock(
            return_value=httpx.Response(404)
        )
        create_route = respx.post(
            'https://api.github.com/orgs/aweber-apis/repos'
        ).mock(return_value=self._created_response())

        ctx = _ctx(
            options={'create_org': 'aweber-apis'},
            project_links={
                'github-repository': 'https://github.com/aweber-apis/demo'
            },
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_updated(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertEqual(create_route.calls.call_count, 1)
        self.assertEqual(
            result.artifacts['repo_url'],
            'https://github.com/aweber-apis/demo',
        )
        self.assertIsNotNone(ctx.link_writeback)

    @respx.mock
    async def test_refuses_when_the_link_disagrees_with_the_org(
        self,
    ) -> None:
        # Creating at the configured org while the link still names the
        # old one is an org migration, not a sync.
        respx.get('https://api.github.com/repos/old-org/demo').mock(
            return_value=httpx.Response(404)
        )
        create_route = respx.post(
            'https://api.github.com/orgs/new-org/repos'
        ).mock(return_value=self._created_response())

        ctx = _ctx(
            options={'create_org': 'new-org'},
            project_links={
                'github-repository': 'https://github.com/old-org/demo'
            },
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_updated(ctx, _CREDS)

        self.assertEqual(result.status, 'failed')
        self.assertEqual(create_route.calls.call_count, 0)
        assert result.message is not None
        self.assertIn('old-org/demo', result.message)
        self.assertIn('new-org', result.message)

    @respx.mock
    async def test_creates_at_the_configured_org_not_the_type_slug(
        self,
    ) -> None:
        # With no link the lookup owner is a *project type* slug read as
        # a GitHub org.  It has no authority, so it must not veto
        # provisioning -- and must not be provisioned into either.
        respx.get('https://api.github.com/repos/api-service/demo').mock(
            return_value=httpx.Response(404)
        )
        create_route = respx.post(
            'https://api.github.com/orgs/aweber-apis/repos'
        ).mock(return_value=self._created_response())

        ctx = _ctx(
            options={'create_org': 'aweber-apis'},
            project_links={},
            project_type_slugs=['api-service'],
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_updated(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertEqual(create_route.calls.call_count, 1)
        # The type slug was read once, to look for the repo, and never
        # used as a creation target.
        self.assertEqual(
            [
                call.request.url.path
                for call in respx.calls
                if 'api-service' in call.request.url.path
            ],
            ['/repos/api-service/demo'],
        )

    @respx.mock
    async def test_skips_when_no_org_is_configured(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(404)
        )

        ctx = _ctx(options={})
        plugin = GitHubLifecycle()
        result = await plugin.on_project_updated(ctx, _CREDS)

        # Same status and message ``on_project_created`` gives, so one
        # misconfiguration cannot read two ways.
        self.assertEqual(result.status, 'skipped')
        created = await plugin.on_project_created(_ctx(options={}), _CREDS)
        self.assertEqual(result.message, created.message)

    @respx.mock
    async def test_non_404_lookup_does_not_provision(self) -> None:
        # A 403 means "cannot see it", not "it is not there".
        respx.get('https://api.github.com/repos/aweber-apis/demo').mock(
            return_value=httpx.Response(403, json={'message': 'nope'})
        )
        create_route = respx.post(
            'https://api.github.com/orgs/aweber-apis/repos'
        ).mock(return_value=self._created_response())

        ctx = _ctx(
            options={'create_org': 'aweber-apis'},
            project_links={
                'github-repository': 'https://github.com/aweber-apis/demo'
            },
        )
        plugin = GitHubLifecycle()
        with self.assertRaises(httpx.HTTPStatusError):
            await plugin.on_project_updated(ctx, _CREDS)
        self.assertEqual(create_route.calls.call_count, 0)

    @respx.mock
    async def test_reconciles_a_create_race(self) -> None:
        # Someone created the repo between the 404 and the POST.  GitHub
        # answers 422; the repo is adopted rather than reported failed.
        respx.get('https://api.github.com/repos/aweber-apis/demo').mock(
            side_effect=[
                httpx.Response(404),
                httpx.Response(
                    200,
                    json={
                        'id': 9,
                        'name': 'demo',
                        'html_url': 'https://github.com/aweber-apis/demo',
                        'owner': {'login': 'aweber-apis'},
                    },
                ),
            ]
        )
        respx.post('https://api.github.com/orgs/aweber-apis/repos').mock(
            return_value=httpx.Response(
                422, json={'message': 'Repository creation failed.'}
            )
        )

        ctx = _ctx(
            options={'create_org': 'aweber-apis'},
            project_links={
                'github-repository': 'https://github.com/aweber-apis/demo'
            },
        )
        plugin = GitHubLifecycle()
        result = await plugin.on_project_updated(ctx, _CREDS)

        self.assertEqual(result.status, 'ok')
        self.assertEqual(
            result.artifacts['repo_url'],
            'https://github.com/aweber-apis/demo',
        )

    @respx.mock
    async def test_a_real_422_still_fails(self) -> None:
        respx.get('https://api.github.com/repos/aweber-apis/demo').mock(
            return_value=httpx.Response(404)
        )
        respx.post('https://api.github.com/orgs/aweber-apis/repos').mock(
            return_value=httpx.Response(
                422,
                json={
                    'message': 'Repository creation failed.',
                    'errors': [{'message': 'name is invalid'}],
                },
            )
        )

        ctx = _ctx(
            options={'create_org': 'aweber-apis'},
            project_links={
                'github-repository': 'https://github.com/aweber-apis/demo'
            },
        )
        plugin = GitHubLifecycle()
        with self.assertRaises(RuntimeError) as caught:
            await plugin.on_project_updated(ctx, _CREDS)
        self.assertIn('name is invalid', str(caught.exception))
