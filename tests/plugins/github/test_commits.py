"""Tests for the GitHub commit / tag history sync webhook plugin."""

import typing
import unittest
from unittest import mock

import httpx
import respx
from imbi_common.models import CommitRecord, TagRecord
from imbi_common.plugins.base import PluginContext, ServicePlugin
from imbi_common.plugins.errors import PluginAuthenticationFailed

from imbi_plugin_github import commits

_ZERO = '0' * 40
_CREDS = {'access_token': 'gho_test'}
_INSERT = 'imbi_plugin_github.commits.clickhouse.insert'
_QUERY = 'imbi_plugin_github.commits.clickhouse.query'


def _await_args(m: mock.AsyncMock) -> tuple[typing.Any, ...]:
    assert m.await_args is not None
    return m.await_args.args


def _ctx(
    *,
    service_plugins: list[ServicePlugin] | None = None,
    service_endpoint: str | None = None,
) -> PluginContext:
    options: dict[str, object] = {'service_slug': 'github'}
    if service_endpoint is not None:
        options['service_endpoint'] = service_endpoint
    return PluginContext(
        project_id='proj-1',
        project_slug='proj',
        org_slug='octo',
        assignment_options=options,
        service_plugins=service_plugins or [],
        project_links={'github-repository': 'https://github.com/octo/demo'},
    )


def _push(
    *,
    before: str = 'a' * 40,
    after: str = 'b' * 40,
    ref: str = 'refs/heads/main',
    full_name: str = 'octo/demo',
    repo_url: str = 'https://api.github.com/repos/octo/demo',
) -> dict[str, object]:
    return {
        'before': before,
        'after': after,
        'ref': ref,
        'repository': {'full_name': full_name, 'url': repo_url},
    }


def _commit(sha: str, *, login: str = 'octocat') -> dict[str, object]:
    return {
        'sha': sha,
        'html_url': f'https://github.com/octo/demo/commit/{sha}',
        'author': {'login': login},
        'commit': {
            'message': 'Subject line\n\nbody',
            'author': {
                'name': 'Alice',
                'email': 'alice@example.com',
                'date': '2026-01-01T00:00:00Z',
            },
            'committer': {
                'name': 'Bob',
                'email': 'bob@example.com',
                'date': '2026-01-02T00:00:00Z',
            },
        },
    }


class ConfigTestCase(unittest.TestCase):
    def test_sync_commits_defaults(self) -> None:
        cfg = commits.SyncCommitsConfig()
        self.assertEqual(cfg.before_selector.path, '/before')
        self.assertEqual(cfg.after_selector.path, '/after')
        self.assertEqual(cfg.ref_selector.path, '/ref')
        self.assertEqual(cfg.repository_selector.path, '/repository/full_name')
        self.assertEqual(cfg.repo_api_url_selector.path, '/repository/url')
        self.assertIsNone(cfg.api_base_url)
        self.assertEqual(cfg.initial_limit, 100)

    def test_sync_tags_defaults(self) -> None:
        cfg = commits.SyncTagsConfig()
        self.assertEqual(cfg.ref_selector.path, '/ref')
        self.assertEqual(cfg.after_selector.path, '/after')
        self.assertFalse(cfg.reconcile_all)

    def test_selector_override_from_json(self) -> None:
        cfg = commits.SyncCommitsConfig.model_validate(
            {'after_selector': '/head', 'api_base_url': 'https://x/api/v3'}
        )
        self.assertEqual(cfg.after_selector.path, '/head')
        self.assertEqual(cfg.api_base_url, 'https://x/api/v3')


class ApiBaseResolutionTestCase(unittest.TestCase):
    def _base(
        self,
        *,
        ctx: PluginContext,
        explicit: str | None = None,
        repo_url: str = 'https://api.github.com/repos/octo/demo',
    ) -> str | None:
        cfg = commits.SyncCommitsConfig()
        return commits._resolve_api_base(
            ctx,
            explicit,
            cfg.repo_api_url_selector,
            {'repository': {'url': repo_url}},
        )

    def test_explicit_override_wins(self) -> None:
        ctx = _ctx(service_plugins=[ServicePlugin(slug='github', options={})])
        self.assertEqual(
            'https://ghe.corp/api/v3',
            self._base(ctx=ctx, explicit='https://ghe.corp/api/v3/'),
        )

    def test_connected_plugin_github_com(self) -> None:
        ctx = _ctx(service_plugins=[ServicePlugin(slug='github', options={})])
        self.assertEqual('https://api.github.com', self._base(ctx=ctx))

    def test_connected_plugin_ghec(self) -> None:
        ctx = _ctx(
            service_plugins=[
                ServicePlugin(
                    slug='github-deployment-ec',
                    options={'host': 'tenant.ghe.com'},
                )
            ]
        )
        self.assertEqual('https://api.tenant.ghe.com', self._base(ctx=ctx))

    def test_connected_plugin_ghes(self) -> None:
        ctx = _ctx(
            service_plugins=[
                ServicePlugin(
                    slug='github-enterprise-server',
                    options={'host': 'ghe.example.com'},
                )
            ]
        )
        self.assertEqual('https://ghe.example.com/api/v3', self._base(ctx=ctx))

    def test_invalid_connected_plugin_host_falls_through(self) -> None:
        ctx = _ctx(
            service_plugins=[
                ServicePlugin(slug='github-deployment-es', options={}),
            ],
            service_endpoint='https://ghe.fallback/api/v3',
        )
        with self.assertLogs(commits.LOGGER, level='WARNING'):
            self.assertEqual(
                'https://ghe.fallback/api/v3', self._base(ctx=ctx)
            )

    def test_non_github_plugin_ignored(self) -> None:
        ctx = _ctx(
            service_plugins=[ServicePlugin(slug='sonarqube', options={})],
            service_endpoint='https://api.github.com',
        )
        self.assertEqual('https://api.github.com', self._base(ctx=ctx))

    def test_repo_url_last_resort_github(self) -> None:
        with self.assertLogs(commits.LOGGER, level='INFO'):
            self.assertEqual('https://api.github.com', self._base(ctx=_ctx()))

    def test_repo_url_last_resort_ghes(self) -> None:
        self.assertEqual(
            'https://ghe.corp/api/v3',
            self._base(
                ctx=_ctx(),
                repo_url='https://ghe.corp/api/v3/repos/octo/demo',
            ),
        )

    def test_unresolvable_returns_none(self) -> None:
        self.assertIsNone(self._base(ctx=_ctx(), repo_url='not-a-repo-url'))


class SyncCommitsTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_normal_compare_inserts_records(self) -> None:
        base, head = 'a' * 40, 'b' * 40
        respx.get(
            f'https://api.github.com/repos/octo/demo/compare/{base}...{head}'
        ).mock(
            return_value=httpx.Response(
                200, json={'commits': [_commit('c' * 40), _commit('d' * 40)]}
            )
        )
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_commits(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncCommitsConfig(),
                payload=_push(before=base, after=head),
            )
        insert.assert_awaited_once()
        table, records = _await_args(insert)
        self.assertEqual('commits', table)
        self.assertEqual(2, len(records))
        first = records[0]
        self.assertIsInstance(first, CommitRecord)
        self.assertEqual('c' * 40, first.sha)
        self.assertEqual('ccccccc', first.short_sha)
        self.assertEqual('main', first.ref)
        self.assertEqual('Alice', first.author_name)
        self.assertEqual('alice@example.com', first.author_email)
        self.assertEqual('octocat', first.author_login)
        self.assertEqual('Bob', first.committer_name)
        self.assertEqual('Subject line\n\nbody', first.message)
        self.assertIsNotNone(first.committed_at)

    async def test_zero_after_short_circuits(self) -> None:
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_commits(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncCommitsConfig(),
                payload=_push(after=_ZERO),
            )
        insert.assert_not_awaited()

    async def test_missing_owner_repo_short_circuits(self) -> None:
        payload = _push()
        del payload['repository']
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            with self.assertLogs(commits.LOGGER, level='WARNING'):
                await commits.sync_commits(
                    ctx=_ctx(),
                    credentials=_CREDS,
                    external_identifier='',
                    action_config=commits.SyncCommitsConfig(),
                    payload=payload,
                )
        insert.assert_not_awaited()

    @respx.mock
    async def test_new_branch_fallback_recent_commits(self) -> None:
        head = 'b' * 40
        respx.get('https://api.github.com/repos/octo/demo/commits').mock(
            return_value=httpx.Response(200, json=[_commit('e' * 40)])
        )
        with mock.patch(_QUERY, new=mock.AsyncMock(return_value=[])):
            with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
                await commits.sync_commits(
                    ctx=_ctx(),
                    credentials=_CREDS,
                    external_identifier='',
                    action_config=commits.SyncCommitsConfig(),
                    payload=_push(before=_ZERO, after=head),
                )
        insert.assert_awaited_once()
        _, records = _await_args(insert)
        self.assertEqual('e' * 40, records[0].sha)

    @respx.mock
    async def test_new_branch_fallback_uses_last_known_sha(self) -> None:
        last, head = 'f' * 40, 'b' * 40
        route = respx.get(
            f'https://api.github.com/repos/octo/demo/compare/{last}...{head}'
        ).mock(
            return_value=httpx.Response(
                200, json={'commits': [_commit('1' * 40)]}
            )
        )
        with mock.patch(
            _QUERY, new=mock.AsyncMock(return_value=[{'sha': last}])
        ):
            with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
                await commits.sync_commits(
                    ctx=_ctx(),
                    credentials=_CREDS,
                    external_identifier='',
                    action_config=commits.SyncCommitsConfig(),
                    payload=_push(before=_ZERO, after=head),
                )
        self.assertTrue(route.called)
        insert.assert_awaited_once()

    @respx.mock
    async def test_compare_pagination_collects_all_pages(self) -> None:
        base, head = 'a' * 40, 'b' * 40
        url = f'https://api.github.com/repos/octo/demo/compare/{base}...{head}'
        next_link = f'<{url}?page=2>; rel="next"'
        respx.get(url).mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={'commits': [_commit('1' * 40)]},
                    headers={'link': next_link},
                ),
                httpx.Response(200, json={'commits': [_commit('2' * 40)]}),
            ]
        )
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_commits(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncCommitsConfig(),
                payload=_push(before=base, after=head),
            )
        _, records = _await_args(insert)
        self.assertEqual(2, len(records))

    @respx.mock
    async def test_compare_truncation_logs(self) -> None:
        base, head = 'a' * 40, 'b' * 40
        url = f'https://api.github.com/repos/octo/demo/compare/{base}...{head}'
        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                json={'commits': [_commit('1' * 40)]},
                headers={'link': f'<{url}?page=2>; rel="next"'},
            )
        )
        with mock.patch.object(commits, '_MAX_COMPARE_PAGES', 1):
            with mock.patch(_INSERT, new=mock.AsyncMock()):
                with self.assertLogs(commits.LOGGER, level='WARNING') as cm:
                    await commits.sync_commits(
                        ctx=_ctx(),
                        credentials=_CREDS,
                        external_identifier='',
                        action_config=commits.SyncCommitsConfig(),
                        payload=_push(before=base, after=head),
                    )
        self.assertTrue(any('truncated' in line for line in cm.output))

    @respx.mock
    async def test_insert_failure_swallowed(self) -> None:
        base, head = 'a' * 40, 'b' * 40
        respx.get(
            f'https://api.github.com/repos/octo/demo/compare/{base}...{head}'
        ).mock(
            return_value=httpx.Response(
                200, json={'commits': [_commit('c' * 40)]}
            )
        )
        failing = mock.AsyncMock(side_effect=RuntimeError('clickhouse down'))
        with mock.patch(_INSERT, new=failing):
            with self.assertLogs(commits.LOGGER, level='ERROR'):
                await commits.sync_commits(
                    ctx=_ctx(),
                    credentials=_CREDS,
                    external_identifier='',
                    action_config=commits.SyncCommitsConfig(),
                    payload=_push(before=base, after=head),
                )

    async def test_missing_token_raises(self) -> None:
        with self.assertRaises(ValueError):
            commits._token({})


class SyncTagsTestCase(unittest.IsolatedAsyncioTestCase):
    def _tag_push(self, *, after: str = 't' * 40) -> dict[str, object]:
        return {
            'ref': 'refs/tags/v1.2.3',
            'after': after,
            'repository': {
                'full_name': 'octo/demo',
                'url': 'https://api.github.com/repos/octo/demo',
            },
        }

    @respx.mock
    async def test_lightweight_tag_inserts(self) -> None:
        sha = 't' * 40
        respx.get(
            f'https://api.github.com/repos/octo/demo/git/tags/{sha}'
        ).mock(return_value=httpx.Response(404))
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_tags(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncTagsConfig(),
                payload=self._tag_push(after=sha),
            )
        table, records = _await_args(insert)
        self.assertEqual('tags', table)
        self.assertEqual(1, len(records))
        self.assertIsInstance(records[0], TagRecord)
        self.assertEqual('v1.2.3', records[0].name)
        self.assertEqual(sha, records[0].sha)
        self.assertEqual('', records[0].message)

    @respx.mock
    async def test_annotated_tag_metadata(self) -> None:
        sha = 't' * 40
        respx.get(
            f'https://api.github.com/repos/octo/demo/git/tags/{sha}'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'message': 'Release 1.2.3',
                    'tagger': {
                        'name': 'Rel Bot',
                        'email': 'rel@example.com',
                        'date': '2026-02-01T00:00:00Z',
                    },
                },
            )
        )
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_tags(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncTagsConfig(),
                payload=self._tag_push(after=sha),
            )
        _, records = _await_args(insert)
        self.assertEqual('Release 1.2.3', records[0].message)
        self.assertEqual('Rel Bot', records[0].tagger_name)
        self.assertIsNotNone(records[0].tagged_at)

    @respx.mock
    async def test_reconcile_all_adds_full_list(self) -> None:
        sha = 't' * 40
        respx.get(
            f'https://api.github.com/repos/octo/demo/git/tags/{sha}'
        ).mock(return_value=httpx.Response(404))
        respx.get('https://api.github.com/repos/octo/demo/tags').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {'name': 'v1.2.3', 'commit': {'sha': sha}},
                    {'name': 'v1.0.0', 'commit': {'sha': 'z' * 40}},
                ],
            )
        )
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_tags(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncTagsConfig(reconcile_all=True),
                payload=self._tag_push(after=sha),
            )
        _, records = _await_args(insert)
        names = {r.name for r in records}
        self.assertEqual({'v1.2.3', 'v1.0.0'}, names)

    @respx.mock
    async def test_reconcile_all_paginates(self) -> None:
        sha = 't' * 40
        respx.get(
            f'https://api.github.com/repos/octo/demo/git/tags/{sha}'
        ).mock(return_value=httpx.Response(404))
        url = 'https://api.github.com/repos/octo/demo/tags'
        respx.get(url).mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[{'name': 'v1.2.3', 'commit': {'sha': sha}}],
                    headers={'link': f'<{url}?page=2>; rel="next"'},
                ),
                httpx.Response(
                    200,
                    json=[{'name': 'v1.0.0', 'commit': {'sha': 'z' * 40}}],
                ),
            ]
        )
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_tags(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncTagsConfig(reconcile_all=True),
                payload=self._tag_push(after=sha),
            )
        _, records = _await_args(insert)
        names = {r.name for r in records}
        self.assertEqual({'v1.2.3', 'v1.0.0'}, names)

    @respx.mock
    async def test_401_raises_authentication_failed(self) -> None:
        sha = 't' * 40
        respx.get(
            f'https://api.github.com/repos/octo/demo/git/tags/{sha}'
        ).mock(return_value=httpx.Response(401, json={'message': 'Bad creds'}))
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            with self.assertRaises(PluginAuthenticationFailed):
                await commits.sync_tags(
                    ctx=_ctx(),
                    credentials=_CREDS,
                    external_identifier='',
                    action_config=commits.SyncTagsConfig(),
                    payload=self._tag_push(after=sha),
                )
        insert.assert_not_awaited()

    async def test_non_tag_ref_short_circuits(self) -> None:
        payload = self._tag_push()
        payload['ref'] = 'refs/heads/main'
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_tags(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncTagsConfig(),
                payload=payload,
            )
        insert.assert_not_awaited()

    async def test_tag_delete_short_circuits(self) -> None:
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_tags(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncTagsConfig(),
                payload=self._tag_push(after=_ZERO),
            )
        insert.assert_not_awaited()


class ManifestTestCase(unittest.TestCase):
    def test_manifest(self) -> None:
        manifest = commits.GitHubCommitSyncPlugin.manifest
        self.assertEqual('github-commit-sync', manifest.slug)
        self.assertEqual('webhook', manifest.plugin_type)
        self.assertEqual(
            ['access_token'], [c.name for c in manifest.credentials]
        )

    def test_actions(self) -> None:
        descriptors = commits.GitHubCommitSyncPlugin.actions()
        names = [d.name for d in descriptors]
        self.assertEqual(['sync_commits', 'sync_tags'], names)
        # ImportString validation resolved the callables at construction.
        self.assertIs(descriptors[0].callable, commits.sync_commits)
        self.assertIs(descriptors[1].callable, commits.sync_tags)
