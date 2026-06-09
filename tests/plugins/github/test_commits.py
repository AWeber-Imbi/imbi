"""Tests for the GitHub commit / tag history sync webhook plugin."""

import base64
import time
import typing
import unittest
from unittest import mock

import httpx
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from imbi_common.models import CommitRecord, TagRecord
from imbi_common.plugins.base import PluginContext, ServicePlugin
from imbi_common.plugins.errors import (
    PluginAuthenticationFailed,
    PluginRateLimited,
)

from imbi_plugin_github import _app_auth, commits, deployment

_ZERO = '0' * 40
_CREDS = {'access_token': 'gho_test'}
_INSERT = 'imbi_plugin_github.commits.clickhouse.insert'
_QUERY = 'imbi_plugin_github.commits.clickhouse.query'


def _gen_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


# Generated once for the module; signing only needs a valid RSA key.
_APP_KEY_PEM = _gen_pem()
_FAR_FUTURE = '2099-01-01T00:00:00Z'


def _await_args(m: mock.AsyncMock) -> tuple[typing.Any, ...]:
    assert m.await_args is not None
    return m.await_args.args


def _ctx(
    *,
    service_plugins: list[ServicePlugin] | None = None,
    service_endpoint: str | None = None,
    resolve_user: commits.ResolveUser | None = None,
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
        resolve_user_by_identity=resolve_user,
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


def _event(body: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Wrap a push body in the event context handlers now receive."""
    return {
        'type': '',
        'third_party_service': '',
        'attributed_to': '',
        'metadata': {'headers': {}},
        'payload': body,
    }


def _commit(
    sha: str, *, login: str = 'octocat', author_id: int = 583231
) -> dict[str, object]:
    return {
        'sha': sha,
        'html_url': f'https://github.com/octo/demo/commit/{sha}',
        'author': {'login': login, 'id': author_id},
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


def _check_runs(
    conclusion: str | None = 'success', *, status: str = 'completed'
) -> dict[str, object]:
    """A ``/check-runs`` payload with a single run."""
    return {'check_runs': [{'status': status, 'conclusion': conclusion}]}


def _check_runs_url(sha: str) -> str:
    return f'https://api.github.com/repos/octo/demo/commits/{sha}/check-runs'


class ConfigTestCase(unittest.TestCase):
    def test_sync_commits_defaults(self) -> None:
        cfg = commits.SyncCommitsConfig()
        self.assertEqual(cfg.before_selector.path, '/payload/before')
        self.assertEqual(cfg.after_selector.path, '/payload/after')
        self.assertEqual(cfg.ref_selector.path, '/payload/ref')
        self.assertEqual(
            cfg.repository_selector.path, '/payload/repository/full_name'
        )
        self.assertEqual(
            cfg.repo_api_url_selector.path, '/payload/repository/url'
        )
        self.assertIsNone(cfg.api_base_url)
        self.assertEqual(cfg.initial_limit, 100)

    def test_sync_tags_defaults(self) -> None:
        cfg = commits.SyncTagsConfig()
        self.assertEqual(cfg.ref_selector.path, '/payload/ref')
        self.assertEqual(cfg.after_selector.path, '/payload/after')
        self.assertFalse(cfg.reconcile_all)

    def test_selector_override_from_json(self) -> None:
        cfg = commits.SyncCommitsConfig.model_validate(
            {
                'after_selector': '/payload/head',
                'api_base_url': 'https://x/api/v3',
            }
        )
        self.assertEqual(cfg.after_selector.path, '/payload/head')
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
            _event({'repository': {'url': repo_url}}),
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

    def test_own_commit_sync_slug_skipped_on_ghec(self) -> None:
        # A commit-sync entry's slug starts with "github" but has no host
        # option; it must not resolve to github.com on a GHEC service —
        # the real GHEC plugin behind it wins.
        ctx = _ctx(
            service_plugins=[
                ServicePlugin(slug='github-commit-sync', options={}),
                ServicePlugin(
                    slug='github-deployment-ec',
                    options={'host': 'tenant.ghe.com'},
                ),
            ]
        )
        self.assertEqual('https://api.tenant.ghe.com', self._base(ctx=ctx))

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
                event=_event(_push(before=base, after=head)),
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
                event=_event(_push(after=_ZERO)),
            )
        insert.assert_not_awaited()

    async def test_missing_owner_repo_short_circuits(self) -> None:
        body = _push()
        del body['repository']
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            with self.assertLogs(commits.LOGGER, level='WARNING'):
                await commits.sync_commits(
                    ctx=_ctx(),
                    credentials=_CREDS,
                    external_identifier='',
                    action_config=commits.SyncCommitsConfig(),
                    event=_event(body),
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
                    event=_event(_push(before=_ZERO, after=head)),
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
                    event=_event(_push(before=_ZERO, after=head)),
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
                event=_event(_push(before=base, after=head)),
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
                        event=_event(_push(before=base, after=head)),
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
                    event=_event(_push(before=base, after=head)),
                )

    async def test_missing_credentials_raises(self) -> None:
        with self.assertRaises(ValueError):
            await commits._resolve_bearer(
                {}, 'https://api.github.com', 'octo', 'demo'
            )


class SyncCommitsCiStatusTestCase(unittest.IsolatedAsyncioTestCase):
    """CI status hydration during ``sync_commits``."""

    def setUp(self) -> None:
        # The /check-runs 403 cache is process-wide module state on the
        # deployment plugin; clear it so a 403 recorded by one test can't
        # short-circuit hydration in another.
        deployment._CHECKS_DISABLED_TOKENS.clear()

    def _mock_compare(self, *shas: str) -> None:
        base, head = 'a' * 40, 'b' * 40
        respx.get(
            f'https://api.github.com/repos/octo/demo/compare/{base}...{head}'
        ).mock(
            return_value=httpx.Response(
                200, json={'commits': [_commit(s) for s in shas]}
            )
        )

    async def _run(self) -> list[CommitRecord]:
        base, head = 'a' * 40, 'b' * 40
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_commits(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncCommitsConfig(),
                event=_event(_push(before=base, after=head)),
            )
        _, records = _await_args(insert)
        return records

    @respx.mock
    async def test_hydrates_pass_and_fail(self) -> None:
        self._mock_compare('c' * 40, 'd' * 40)
        respx.get(_check_runs_url('c' * 40)).mock(
            return_value=httpx.Response(200, json=_check_runs('success'))
        )
        respx.get(_check_runs_url('d' * 40)).mock(
            return_value=httpx.Response(200, json=_check_runs('failure'))
        )
        records = await self._run()
        self.assertEqual('pass', records[0].ci_status)
        self.assertEqual('fail', records[1].ci_status)

    @respx.mock
    async def test_403_degrades_and_caches(self) -> None:
        self._mock_compare('c' * 40, 'd' * 40)
        route = respx.get(url__regex=r'.+/commits/.+/check-runs$').mock(
            return_value=httpx.Response(403)
        )
        records = await self._run()
        # Head probe 403s and records the repo as checks-disabled, so the
        # tail commit is never probed -- one call, both 'unknown'.
        self.assertEqual(1, route.call_count)
        self.assertEqual(
            ['unknown', 'unknown'], [r.ci_status for r in records]
        )

    @respx.mock
    async def test_in_progress_is_unknown(self) -> None:
        self._mock_compare('c' * 40)
        respx.get(_check_runs_url('c' * 40)).mock(
            return_value=httpx.Response(
                200, json=_check_runs(None, status='in_progress')
            )
        )
        records = await self._run()
        self.assertEqual('unknown', records[0].ci_status)

    @respx.mock
    async def test_network_error_degrades_to_unknown(self) -> None:
        self._mock_compare('c' * 40)
        respx.get(_check_runs_url('c' * 40)).mock(
            side_effect=httpx.ConnectError('boom')
        )
        records = await self._run()
        self.assertEqual('unknown', records[0].ci_status)

    @respx.mock
    async def test_non_403_http_error_degrades_to_unknown(self) -> None:
        # A non-200, non-403 response (e.g. 500) is not cached as
        # checks-disabled, so it degrades to 'unknown' per commit.
        self._mock_compare('c' * 40)
        respx.get(_check_runs_url('c' * 40)).mock(
            return_value=httpx.Response(500)
        )
        records = await self._run()
        self.assertEqual('unknown', records[0].ci_status)


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
                event=_event(self._tag_push(after=sha)),
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
                event=_event(self._tag_push(after=sha)),
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
        respx.get(
            'https://api.github.com/repos/octo/demo/git/matching-refs/tags'
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'ref': 'refs/tags/v1.2.3',
                        'object': {'sha': sha, 'type': 'commit'},
                    },
                    {
                        'ref': 'refs/tags/v1.0.0',
                        'object': {'sha': 'z' * 40, 'type': 'commit'},
                    },
                ],
            )
        )
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_tags(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncTagsConfig(reconcile_all=True),
                event=_event(self._tag_push(after=sha)),
            )
        _, records = _await_args(insert)
        names = {r.name for r in records}
        self.assertEqual({'v1.2.3', 'v1.0.0'}, names)
        urls = {r.name: r.url for r in records}
        self.assertEqual(
            {
                'v1.2.3': 'https://github.com/octo/demo/releases/tag/v1.2.3',
                'v1.0.0': 'https://github.com/octo/demo/releases/tag/v1.0.0',
            },
            urls,
        )

    @respx.mock
    async def test_reconcile_all_paginates(self) -> None:
        sha = 't' * 40
        respx.get(
            f'https://api.github.com/repos/octo/demo/git/tags/{sha}'
        ).mock(return_value=httpx.Response(404))
        url = 'https://api.github.com/repos/octo/demo/git/matching-refs/tags'
        respx.get(url).mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {
                            'ref': 'refs/tags/v1.2.3',
                            'object': {'sha': sha, 'type': 'commit'},
                        }
                    ],
                    headers={'link': f'<{url}?page=2>; rel="next"'},
                ),
                httpx.Response(
                    200,
                    json=[
                        {
                            'ref': 'refs/tags/v1.0.0',
                            'object': {'sha': 'z' * 40, 'type': 'commit'},
                        }
                    ],
                ),
            ]
        )
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_tags(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncTagsConfig(reconcile_all=True),
                event=_event(self._tag_push(after=sha)),
            )
        _, records = _await_args(insert)
        names = {r.name for r in records}
        self.assertEqual({'v1.2.3', 'v1.0.0'}, names)
        urls = {r.name: r.url for r in records}
        self.assertEqual(
            {
                'v1.2.3': 'https://github.com/octo/demo/releases/tag/v1.2.3',
                'v1.0.0': 'https://github.com/octo/demo/releases/tag/v1.0.0',
            },
            urls,
        )

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
                    event=_event(self._tag_push(after=sha)),
                )
        insert.assert_not_awaited()

    async def test_non_tag_ref_short_circuits(self) -> None:
        body = self._tag_push()
        body['ref'] = 'refs/heads/main'
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_tags(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncTagsConfig(),
                event=_event(body),
            )
        insert.assert_not_awaited()

    async def test_tag_delete_short_circuits(self) -> None:
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_tags(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncTagsConfig(),
                event=_event(self._tag_push(after=_ZERO)),
            )
        insert.assert_not_awaited()


class ManifestTestCase(unittest.TestCase):
    def test_manifest(self) -> None:
        manifest = commits.GitHubCommitSyncPlugin.manifest
        self.assertEqual('github-commit-sync', manifest.slug)
        self.assertEqual('webhook', manifest.plugin_type)
        self.assertEqual(
            ['access_token', 'app_id', 'private_key', 'installation_id'],
            [c.name for c in manifest.credentials],
        )
        self.assertTrue(
            all(not c.required for c in manifest.credentials),
            'all auth credentials are optional (PAT or App mode)',
        )

    def test_actions(self) -> None:
        descriptors = commits.GitHubCommitSyncPlugin.actions()
        names = [d.name for d in descriptors]
        self.assertEqual(['sync_commits', 'sync_tags'], names)
        # ImportString validation resolved the callables at construction.
        self.assertIs(descriptors[0].callable, commits.sync_commits)
        self.assertIs(descriptors[1].callable, commits.sync_tags)


class PrivateKeyTestCase(unittest.TestCase):
    def test_raw_pem_passthrough(self) -> None:
        self.assertEqual(
            _APP_KEY_PEM.strip(), _app_auth._load_private_key(_APP_KEY_PEM)
        )

    def test_base64_pem_decoded(self) -> None:
        b64 = base64.b64encode(_APP_KEY_PEM.encode()).decode()
        self.assertEqual(_APP_KEY_PEM, _app_auth._load_private_key(b64))

    def test_garbage_raises(self) -> None:
        with self.assertRaises(ValueError):
            _app_auth._load_private_key('not a key at all !!!')

    def test_base64_of_non_pem_raises(self) -> None:
        b64 = base64.b64encode(b'just some bytes').decode()
        with self.assertRaises(ValueError):
            _app_auth._load_private_key(b64)


class TokenDeadlineTestCase(unittest.TestCase):
    def test_missing_expiry_uses_default_ttl(self) -> None:
        # No expires_at -> a positive deadline (default ~55m) is returned.
        self.assertGreater(_app_auth._token_deadline(None), 0.0)

    def test_unparseable_expiry_uses_default_ttl(self) -> None:
        self.assertGreater(_app_auth._token_deadline('not-a-date'), 0.0)


class ResolveBearerTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_pat_preferred_over_app(self) -> None:
        # A PAT short-circuits before any App minting / network call.
        token = await commits._resolve_bearer(
            {'access_token': 'gho_x', 'app_id': '971', 'private_key': 'k'},
            'https://api.github.com',
            'octo',
            'demo',
        )
        self.assertEqual('gho_x', token)


class AppAuthSyncTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _app_auth.reset_cache()

    def tearDown(self) -> None:
        _app_auth.reset_cache()

    def _app_creds(
        self, *, installation_id: str | None = '42'
    ) -> dict[str, str]:
        creds = {'app_id': '971', 'private_key': _APP_KEY_PEM}
        if installation_id is not None:
            creds['installation_id'] = installation_id
        return creds

    def _mock_token(self, token: str = 'ghs_minted') -> respx.Route:
        return respx.post(
            'https://api.github.com/app/installations/42/access_tokens'
        ).mock(
            return_value=httpx.Response(
                201, json={'token': token, 'expires_at': _FAR_FUTURE}
            )
        )

    def _mock_compare(self) -> respx.Route:
        base, head = 'a' * 40, 'b' * 40
        return respx.get(
            f'https://api.github.com/repos/octo/demo/compare/{base}...{head}'
        ).mock(
            return_value=httpx.Response(
                200, json={'commits': [_commit('c' * 40)]}
            )
        )

    @respx.mock
    async def test_app_mints_and_uses_token(self) -> None:
        token_route = self._mock_token()
        compare = self._mock_compare()
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_commits(
                ctx=_ctx(),
                credentials=self._app_creds(),
                external_identifier='',
                action_config=commits.SyncCommitsConfig(),
                event=_event(_push()),
            )
        insert.assert_awaited_once()
        self.assertEqual(1, token_route.call_count)
        self.assertEqual(
            'Bearer ghs_minted',
            compare.calls.last.request.headers['authorization'],
        )

    @respx.mock
    async def test_explicit_installation_skips_discovery(self) -> None:
        discovery = respx.get(
            'https://api.github.com/repos/octo/demo/installation'
        )
        self._mock_token()
        self._mock_compare()
        with mock.patch(_INSERT, new=mock.AsyncMock()):
            await commits.sync_commits(
                ctx=_ctx(),
                credentials=self._app_creds(installation_id='42'),
                external_identifier='',
                action_config=commits.SyncCommitsConfig(),
                event=_event(_push()),
            )
        self.assertFalse(discovery.called)

    @respx.mock
    async def test_discovers_installation_when_absent(self) -> None:
        discovery = respx.get(
            'https://api.github.com/repos/octo/demo/installation'
        ).mock(return_value=httpx.Response(200, json={'id': 42}))
        token_route = self._mock_token()
        self._mock_compare()
        with mock.patch(_INSERT, new=mock.AsyncMock()):
            await commits.sync_commits(
                ctx=_ctx(),
                credentials=self._app_creds(installation_id=None),
                external_identifier='',
                action_config=commits.SyncCommitsConfig(),
                event=_event(_push()),
            )
        self.assertEqual(1, discovery.call_count)
        self.assertEqual(1, token_route.call_count)

    @respx.mock
    async def test_token_cached_across_calls(self) -> None:
        token_route = self._mock_token()
        self._mock_compare()
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            for _ in range(2):
                await commits.sync_commits(
                    ctx=_ctx(),
                    credentials=self._app_creds(),
                    external_identifier='',
                    action_config=commits.SyncCommitsConfig(),
                    event=_event(_push()),
                )
        self.assertEqual(2, insert.await_count)
        # Minted once, reused on the second delivery.
        self.assertEqual(1, token_route.call_count)

    @respx.mock
    async def test_discovered_installation_and_token_cached(self) -> None:
        discovery = respx.get(
            'https://api.github.com/repos/octo/demo/installation'
        ).mock(return_value=httpx.Response(200, json={'id': 42}))
        token_route = self._mock_token()
        self._mock_compare()
        with mock.patch(_INSERT, new=mock.AsyncMock()):
            for _ in range(2):
                await commits.sync_commits(
                    ctx=_ctx(),
                    credentials=self._app_creds(installation_id=None),
                    external_identifier='',
                    action_config=commits.SyncCommitsConfig(),
                    event=_event(_push()),
                )
        # Discovery and minting both happen once, then served from cache.
        self.assertEqual(1, discovery.call_count)
        self.assertEqual(1, token_route.call_count)

    @respx.mock
    async def test_stale_cached_install_rediscovered_on_404(self) -> None:
        # Seed the install cache with a now-stale id, then make minting
        # against it 404 (uninstall/reinstall). The token call should
        # evict the stale id, rediscover, and mint against the new one.
        _app_auth._INSTALL_CACHE[
            ('971', 'https://api.github.com', 'octo', 'demo')
        ] = '7'
        stale = respx.post(
            'https://api.github.com/app/installations/7/access_tokens'
        ).mock(return_value=httpx.Response(404, json={'message': 'gone'}))
        discovery = respx.get(
            'https://api.github.com/repos/octo/demo/installation'
        ).mock(return_value=httpx.Response(200, json={'id': 42}))
        fresh = self._mock_token()
        token = await _app_auth.installation_token(
            base='https://api.github.com',
            app_id='971',
            private_key=_APP_KEY_PEM,
            installation_id=None,
            owner='octo',
            repo='demo',
        )
        self.assertEqual('ghs_minted', token)
        self.assertEqual(1, stale.call_count)
        self.assertEqual(1, discovery.call_count)
        self.assertEqual(1, fresh.call_count)
        self.assertEqual(
            '42',
            _app_auth._INSTALL_CACHE[
                ('971', 'https://api.github.com', 'octo', 'demo')
            ],
        )

    @respx.mock
    async def test_base64_private_key_accepted(self) -> None:
        self._mock_token()
        self._mock_compare()
        creds = self._app_creds()
        creds['private_key'] = base64.b64encode(_APP_KEY_PEM.encode()).decode()
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_commits(
                ctx=_ctx(),
                credentials=creds,
                external_identifier='',
                action_config=commits.SyncCommitsConfig(),
                event=_event(_push()),
            )
        insert.assert_awaited_once()


class HostForContextTestCase(unittest.TestCase):
    def test_resolves_from_connected_github_plugin(self) -> None:
        ctx = _ctx(service_plugins=[ServicePlugin(slug='github', options={})])
        self.assertEqual('github.com', commits._resolve_host_for_context(ctx))

    def test_skips_own_slug_for_ghec(self) -> None:
        # A commit-sync entry must not be read as github.com on a GHEC
        # service; the real GHEC plugin behind it wins.
        ctx = _ctx(
            service_plugins=[
                ServicePlugin(slug='github-commit-sync', options={}),
                ServicePlugin(
                    slug='github-deployment-ec',
                    options={'host': 'tenant.ghe.com'},
                ),
            ]
        )
        self.assertEqual(
            'tenant.ghe.com', commits._resolve_host_for_context(ctx)
        )

    def test_no_github_plugin_returns_none(self) -> None:
        ctx = _ctx(service_plugins=[ServicePlugin(slug='sonarqube')])
        self.assertIsNone(commits._resolve_host_for_context(ctx))


class SyncAllHistoryTestCase(unittest.IsolatedAsyncioTestCase):
    _REPO = 'https://api.github.com/repos/octo/demo'

    def _ctx(self) -> PluginContext:
        return _ctx(service_plugins=[ServicePlugin(slug='github', options={})])

    def _mock_default_branch(self, branch: str = 'main') -> respx.Route:
        return respx.get(self._REPO).mock(
            return_value=httpx.Response(200, json={'default_branch': branch})
        )

    @respx.mock
    async def test_records_full_history_and_tags(self) -> None:
        self._mock_default_branch()
        commit_route = respx.get(f'{self._REPO}/commits').mock(
            return_value=httpx.Response(
                200, json=[_commit('c' * 40), _commit('d' * 40)]
            )
        )
        respx.get(f'{self._REPO}/git/matching-refs/tags').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'ref': 'refs/tags/v1.0.0',
                        'object': {'sha': 'z' * 40, 'type': 'commit'},
                    },
                    {
                        'ref': 'refs/tags/v1.1.0',
                        'object': {'sha': 'y' * 40, 'type': 'commit'},
                    },
                ],
            )
        )
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            result = await commits.GitHubCommitSyncPlugin().sync_all_history(
                ctx=self._ctx(), credentials=_CREDS
            )
        self.assertEqual((2, 2), result)
        self.assertEqual(
            'main', commit_route.calls.last.request.url.params['sha']
        )
        self.assertEqual(2, insert.await_count)
        tables = {call.args[0] for call in insert.await_args_list}
        self.assertEqual({'commits', 'tags'}, tables)
        commit_call = next(
            c for c in insert.await_args_list if c.args[0] == 'commits'
        )
        records = commit_call.args[1]
        self.assertIsInstance(records[0], CommitRecord)
        self.assertEqual('main', records[0].ref)
        tag_call = next(
            c for c in insert.await_args_list if c.args[0] == 'tags'
        )
        urls = {r.name: r.url for r in tag_call.args[1]}
        self.assertEqual(
            {
                'v1.0.0': 'https://github.com/octo/demo/releases/tag/v1.0.0',
                'v1.1.0': 'https://github.com/octo/demo/releases/tag/v1.1.0',
            },
            urls,
        )

    @respx.mock
    async def test_bounds_ci_status_to_recent_commits(self) -> None:
        deployment._CHECKS_DISABLED_TOKENS.clear()
        self._mock_default_branch()
        respx.get(f'{self._REPO}/commits').mock(
            return_value=httpx.Response(
                200, json=[_commit('c' * 40), _commit('d' * 40)]
            )
        )
        respx.get(f'{self._REPO}/git/matching-refs/tags').mock(
            return_value=httpx.Response(200, json=[])
        )
        ci_route = respx.get(url__regex=r'.+/commits/.+/check-runs$').mock(
            return_value=httpx.Response(200, json=_check_runs('success'))
        )
        with mock.patch.object(commits, '_BACKFILL_CI_LIMIT', 1):
            with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
                await commits.GitHubCommitSyncPlugin().sync_all_history(
                    ctx=self._ctx(), credentials=_CREDS
                )
        # Only the most-recent commit is hydrated; the rest stay 'unknown'.
        self.assertEqual(1, ci_route.call_count)
        commit_call = next(
            c for c in insert.await_args_list if c.args[0] == 'commits'
        )
        records = commit_call.args[1]
        self.assertEqual('pass', records[0].ci_status)
        self.assertEqual('unknown', records[1].ci_status)

    @respx.mock
    async def test_rate_limit_beyond_cap_propagates(self) -> None:
        # The backfill path must NOT swallow PluginRateLimited: it
        # propagates to the host's queue, which pauses until the reset
        # and keeps the job queued rather than failing it.
        respx.get(self._REPO).mock(
            return_value=httpx.Response(
                403,
                headers={
                    'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': str(int(time.time()) + 10_000),
                },
            )
        )
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            with self.assertRaises(PluginRateLimited) as caught:
                await commits.GitHubCommitSyncPlugin().sync_all_history(
                    ctx=self._ctx(), credentials=_CREDS
                )
        self.assertGreater(caught.exception.retry_at, time.time() + 9_000)
        insert.assert_not_awaited()

    @respx.mock
    async def test_paginates_commits(self) -> None:
        self._mock_default_branch()
        url = f'{self._REPO}/commits'
        respx.get(url).mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[_commit('1' * 40)],
                    headers={'link': f'<{url}?page=2>; rel="next"'},
                ),
                httpx.Response(200, json=[_commit('2' * 40)]),
            ]
        )
        respx.get(f'{self._REPO}/git/matching-refs/tags').mock(
            return_value=httpx.Response(200, json=[])
        )
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            (
                commits_recorded,
                tags_recorded,
            ) = await commits.GitHubCommitSyncPlugin().sync_all_history(
                ctx=self._ctx(), credentials=_CREDS
            )
        self.assertEqual(2, commits_recorded)
        self.assertEqual(0, tags_recorded)
        # Only the commits insert ran; the empty tag list short-circuits.
        insert.assert_awaited_once()

    @respx.mock
    async def test_history_truncation_logs(self) -> None:
        self._mock_default_branch()
        url = f'{self._REPO}/commits'
        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                json=[_commit('1' * 40)],
                headers={'link': f'<{url}?page=2>; rel="next"'},
            )
        )
        respx.get(f'{self._REPO}/git/matching-refs/tags').mock(
            return_value=httpx.Response(200, json=[])
        )
        with mock.patch.object(commits, '_MAX_HISTORY_PAGES', 1):
            with mock.patch(_INSERT, new=mock.AsyncMock()):
                with self.assertLogs(commits.LOGGER, level='WARNING') as cm:
                    await commits.GitHubCommitSyncPlugin().sync_all_history(
                        ctx=self._ctx(), credentials=_CREDS
                    )
        self.assertTrue(any('truncated history' in x for x in cm.output))

    @respx.mock
    async def test_no_github_host_raises(self) -> None:
        with self.assertRaises(ValueError):
            await commits.GitHubCommitSyncPlugin().sync_all_history(
                ctx=_ctx(), credentials=_CREDS
            )

    @respx.mock
    async def test_clickhouse_failure_swallowed(self) -> None:
        self._mock_default_branch()
        respx.get(f'{self._REPO}/commits').mock(
            return_value=httpx.Response(200, json=[_commit('c' * 40)])
        )
        respx.get(f'{self._REPO}/git/matching-refs/tags').mock(
            return_value=httpx.Response(200, json=[])
        )
        failing = mock.AsyncMock(side_effect=RuntimeError('clickhouse down'))
        with mock.patch(_INSERT, new=failing):
            with self.assertLogs(commits.LOGGER, level='ERROR'):
                result = await (
                    commits.GitHubCommitSyncPlugin().sync_all_history(
                        ctx=self._ctx(), credentials=_CREDS
                    )
                )
        self.assertEqual((0, 0), result)

    @respx.mock
    async def test_app_auth_mints_token(self) -> None:
        _app_auth.reset_cache()
        self.addCleanup(_app_auth.reset_cache)
        token_route = respx.post(
            'https://api.github.com/app/installations/42/access_tokens'
        ).mock(
            return_value=httpx.Response(
                201, json={'token': 'ghs_minted', 'expires_at': _FAR_FUTURE}
            )
        )
        self._mock_default_branch()
        respx.get(f'{self._REPO}/commits').mock(
            return_value=httpx.Response(200, json=[_commit('c' * 40)])
        )
        respx.get(f'{self._REPO}/git/matching-refs/tags').mock(
            return_value=httpx.Response(200, json=[])
        )
        creds = {
            'app_id': '971',
            'private_key': _APP_KEY_PEM,
            'installation_id': '42',
        }
        with mock.patch(_INSERT, new=mock.AsyncMock()):
            await commits.GitHubCommitSyncPlugin().sync_all_history(
                ctx=self._ctx(), credentials=creds
            )
        self.assertEqual(1, token_route.call_count)

    @respx.mock
    async def test_annotated_tags_enriched_with_metadata(self) -> None:
        self._mock_default_branch()
        respx.get(f'{self._REPO}/commits').mock(
            return_value=httpx.Response(200, json=[_commit('c' * 40)])
        )
        tag_sha = 'a' * 40
        respx.get(f'{self._REPO}/git/matching-refs/tags').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'ref': 'refs/tags/v2.0.0',
                        'object': {'sha': tag_sha, 'type': 'tag'},
                    }
                ],
            )
        )
        respx.get(f'{self._REPO}/git/tags/{tag_sha}').mock(
            return_value=httpx.Response(
                200,
                json={
                    'message': 'Release 2.0.0',
                    'tagger': {
                        'name': 'Rel Bot',
                        'email': 'rel@example.com',
                        'date': '2026-02-01T00:00:00Z',
                    },
                },
            )
        )
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.GitHubCommitSyncPlugin().sync_all_history(
                ctx=self._ctx(), credentials=_CREDS
            )
        tag_call = next(
            c for c in insert.await_args_list if c.args[0] == 'tags'
        )
        record = tag_call.args[1][0]
        self.assertEqual('Release 2.0.0', record.message)
        self.assertEqual('Rel Bot', record.tagger_name)
        self.assertIsNotNone(record.tagged_at)
        self.assertEqual(
            'https://github.com/octo/demo/releases/tag/v2.0.0', record.url
        )


class WebBaseTestCase(unittest.TestCase):
    def test_web_base_flavors(self) -> None:
        self.assertEqual(
            'https://github.com',
            commits._web_base('https://api.github.com'),
        )
        self.assertEqual(
            'https://tenant.ghe.com',
            commits._web_base('https://api.tenant.ghe.com'),
        )
        self.assertEqual(
            'https://ghe.example.com',
            commits._web_base('https://ghe.example.com/api/v3'),
        )


class ThrottleWaitTestCase(unittest.TestCase):
    """Unit coverage for :func:`commits._throttle_wait` header parsing."""

    def test_retry_after_honored(self) -> None:
        resp = httpx.Response(403, headers={'retry-after': '12'})
        self.assertEqual(12.0, commits._throttle_wait(resp))

    def test_retry_after_malformed_floors(self) -> None:
        resp = httpx.Response(429, headers={'retry-after': 'soon'})
        self.assertEqual(
            commits._SECONDARY_LIMIT_WAIT_SECONDS,
            commits._throttle_wait(resp),
        )

    def test_primary_limit_waits_until_reset(self) -> None:
        reset = int(time.time()) + 30
        resp = httpx.Response(
            403,
            headers={
                'x-ratelimit-remaining': '0',
                'x-ratelimit-reset': str(reset),
            },
        )
        wait = commits._throttle_wait(resp)
        assert wait is not None
        self.assertGreater(wait, 25.0)
        self.assertLessEqual(wait, 31.0 + commits._RESET_BUFFER_SECONDS)

    def test_primary_limit_without_reset_floors(self) -> None:
        resp = httpx.Response(403, headers={'x-ratelimit-remaining': '0'})
        self.assertEqual(
            commits._SECONDARY_LIMIT_WAIT_SECONDS,
            commits._throttle_wait(resp),
        )

    def test_non_ratelimit_403_falls_through(self) -> None:
        resp = httpx.Response(403, json={'message': 'Not accessible'})
        self.assertIsNone(commits._throttle_wait(resp))

    def test_secondary_limit_body_without_headers_floors(self) -> None:
        resp = httpx.Response(
            403,
            json={
                'message': (
                    'You have exceeded a secondary rate limit. Please wait '
                    'a few minutes before you try again.'
                )
            },
        )
        self.assertEqual(
            commits._SECONDARY_LIMIT_WAIT_SECONDS,
            commits._throttle_wait(resp),
        )

    def test_healthy_response_no_wait(self) -> None:
        resp = httpx.Response(200, headers={'x-ratelimit-remaining': '4999'})
        self.assertIsNone(commits._throttle_wait(resp))

    def test_exhausted_2xx_yields_preemptive_wait(self) -> None:
        reset = int(time.time()) + 10
        resp = httpx.Response(
            200,
            headers={
                'x-ratelimit-remaining': '0',
                'x-ratelimit-reset': str(reset),
            },
        )
        self.assertIsNotNone(commits._throttle_wait(resp))


class RequestTestCase(unittest.IsolatedAsyncioTestCase):
    """Pause/resume behavior of :func:`commits._request`."""

    @staticmethod
    def _client(first: httpx.Response, *rest: httpx.Response) -> mock.Mock:
        # A single response is repeated enough times to outlast the
        # retry loop; an explicit sequence is replayed verbatim.
        responses = (
            [first, *rest]
            if rest
            else [first] * (commits._MAX_THROTTLE_RETRIES + 2)
        )
        client = mock.Mock()
        client.request = mock.AsyncMock(side_effect=responses)
        return client

    async def test_reactive_retry_then_success(self) -> None:
        client = self._client(
            httpx.Response(403, headers={'retry-after': '7'}),
            httpx.Response(200, json={'ok': True}),
        )
        with mock.patch.object(
            commits.asyncio, 'sleep', new=mock.AsyncMock()
        ) as slept:
            resp = await commits._request(client, 'GET', '/x', max_wait=60.0)
        self.assertEqual(200, resp.status_code)
        slept.assert_awaited_once_with(7.0)
        self.assertEqual(2, client.request.await_count)

    async def test_preemptive_pause_on_exhausted_2xx(self) -> None:
        reset = int(time.time()) + 5
        client = self._client(
            httpx.Response(
                200,
                headers={
                    'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': str(reset),
                },
                json={'ok': True},
            ),
        )
        with mock.patch.object(
            commits.asyncio, 'sleep', new=mock.AsyncMock()
        ) as slept:
            resp = await commits._request(client, 'GET', '/x', max_wait=60.0)
        self.assertEqual(200, resp.status_code)
        slept.assert_awaited_once()
        # The good response is returned, not retried.
        self.assertEqual(1, client.request.await_count)

    async def test_wait_exceeding_cap_raises_rate_limited(self) -> None:
        reset = int(time.time()) + 10_000
        client = self._client(
            httpx.Response(
                403,
                headers={
                    'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': str(reset),
                },
            ),
        )
        with mock.patch.object(
            commits.asyncio, 'sleep', new=mock.AsyncMock()
        ) as slept:
            with self.assertRaises(PluginRateLimited) as caught:
                await commits._request(client, 'GET', '/x', max_wait=60.0)
        # Bails to the host without sleeping, carrying the resume time.
        self.assertGreater(caught.exception.retry_at, time.time() + 9_000)
        slept.assert_not_awaited()
        self.assertEqual(1, client.request.await_count)

    async def test_retries_exhausted_raises_rate_limited(self) -> None:
        client = self._client(
            httpx.Response(429, headers={'retry-after': '1'})
        )
        with mock.patch.object(
            commits.asyncio, 'sleep', new=mock.AsyncMock()
        ) as slept:
            with self.assertRaises(PluginRateLimited):
                await commits._request(client, 'GET', '/x', max_wait=60.0)
        self.assertEqual(commits._MAX_THROTTLE_RETRIES, slept.await_count)
        self.assertEqual(
            commits._MAX_THROTTLE_RETRIES + 1, client.request.await_count
        )


class SyncCommitsThrottleTestCase(unittest.IsolatedAsyncioTestCase):
    """End-to-end: a throttled compare pauses then resumes."""

    @respx.mock
    async def test_compare_resumes_after_throttle(self) -> None:
        base, head = 'a' * 40, 'b' * 40
        url = f'https://api.github.com/repos/octo/demo/compare/{base}...{head}'
        respx.get(url).mock(
            side_effect=[
                httpx.Response(403, headers={'retry-after': '3'}),
                httpx.Response(200, json={'commits': [_commit('1' * 40)]}),
            ]
        )
        with mock.patch.object(
            commits.asyncio, 'sleep', new=mock.AsyncMock()
        ) as slept:
            with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
                await commits.sync_commits(
                    ctx=_ctx(),
                    credentials=_CREDS,
                    external_identifier='',
                    action_config=commits.SyncCommitsConfig(),
                    event=_event(_push(before=base, after=head)),
                )
        slept.assert_awaited_once_with(3.0)
        insert.assert_awaited_once()
        _, records = _await_args(insert)
        self.assertEqual(1, len(records))

    @respx.mock
    async def test_rate_limited_beyond_cap_is_swallowed(self) -> None:
        # A reset further out than the webhook cap makes _request raise
        # PluginRateLimited; the webhook action swallows it (a later push
        # re-syncs) rather than letting it 5xx the gateway.
        base, head = 'a' * 40, 'b' * 40
        url = f'https://api.github.com/repos/octo/demo/compare/{base}...{head}'
        respx.get(url).mock(
            return_value=httpx.Response(
                403,
                headers={
                    'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': str(int(time.time()) + 10_000),
                },
            )
        )
        with mock.patch.object(commits.asyncio, 'sleep', new=mock.AsyncMock()):
            with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
                await commits.sync_commits(
                    ctx=_ctx(),
                    credentials=_CREDS,
                    external_identifier='',
                    action_config=commits.SyncCommitsConfig(),
                    event=_event(_push(before=base, after=head)),
                )
        insert.assert_not_awaited()

    @respx.mock
    async def test_tags_rate_limited_beyond_cap_is_swallowed(self) -> None:
        # Mirror of the sync_commits swallow path for the tags webhook:
        # a reset further out than the cap makes _request raise
        # PluginRateLimited, which sync_tags swallows (a later push
        # re-syncs) rather than letting it 5xx the gateway.
        sha = 't' * 40
        respx.get(
            f'https://api.github.com/repos/octo/demo/git/tags/{sha}'
        ).mock(
            return_value=httpx.Response(
                403,
                headers={
                    'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': str(int(time.time()) + 10_000),
                },
            )
        )
        push = {
            'ref': 'refs/tags/v1.2.3',
            'after': sha,
            'repository': {
                'full_name': 'octo/demo',
                'url': 'https://api.github.com/repos/octo/demo',
            },
        }
        with mock.patch.object(commits.asyncio, 'sleep', new=mock.AsyncMock()):
            with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
                await commits.sync_tags(
                    ctx=_ctx(),
                    credentials=_CREDS,
                    external_identifier='',
                    action_config=commits.SyncTagsConfig(),
                    event=_event(push),
                )
        insert.assert_not_awaited()


class ResolveUserCacheTestCase(unittest.IsolatedAsyncioTestCase):
    """LRU caching of commit-author identity resolution."""

    def setUp(self) -> None:
        commits._USER_CACHE.clear()

    async def test_hits_cached_misses_requeried(self) -> None:
        resolver = mock.AsyncMock(
            side_effect=lambda s: 'a@e.com' if s == '1' else None
        )
        base = 'https://api.github.com'
        self.assertEqual(
            'a@e.com', await commits._resolve_user(resolver, base, '1')
        )
        self.assertIsNone(await commits._resolve_user(resolver, base, '2'))
        # The hit is served from cache on repeat; the miss is re-queried
        # so a contributor who links their identity later is eventually
        # resolved instead of being memoized as unresolved.
        self.assertEqual(
            'a@e.com', await commits._resolve_user(resolver, base, '1')
        )
        self.assertIsNone(await commits._resolve_user(resolver, base, '2'))
        self.assertEqual(3, resolver.await_count)
        self.assertIn((base, '1'), commits._USER_CACHE)
        self.assertNotIn((base, '2'), commits._USER_CACHE)

    async def test_key_scoped_by_base(self) -> None:
        resolver = mock.AsyncMock(return_value='x@e.com')
        await commits._resolve_user(resolver, 'https://api.github.com', '42')
        await commits._resolve_user(resolver, 'https://ghe.corp/api/v3', '42')
        # Same subject, different host -> two distinct lookups (a GitHub
        # id is only unique per host).
        self.assertEqual(2, resolver.await_count)

    async def test_lru_eviction(self) -> None:
        resolver = mock.AsyncMock(return_value='e@e.com')
        with mock.patch.object(commits, '_USER_CACHE_MAX', 2):
            await commits._resolve_user(resolver, 'b', '1')
            await commits._resolve_user(resolver, 'b', '2')
            await commits._resolve_user(resolver, 'b', '3')
        self.assertNotIn(('b', '1'), commits._USER_CACHE)
        self.assertIn(('b', '3'), commits._USER_CACHE)

    async def test_author_users_dedups_and_drops_misses(self) -> None:
        resolver = mock.AsyncMock(
            side_effect=lambda s: 'dev@e.com' if s == '7' else None
        )
        raw: list[dict[str, typing.Any]] = [
            {'author': {'id': 7}},
            {'author': {'id': 7}},  # duplicate id
            {'author': {'id': 8}},  # resolves to a miss
            {'author': None},  # unlinked commit
            {},  # no author key
        ]
        out = await commits._resolve_author_users(raw, resolver, 'base')
        self.assertEqual({'7': 'dev@e.com'}, out)
        # Distinct ids 7 and 8 only -- the duplicate is collapsed.
        self.assertEqual(2, resolver.await_count)

    async def test_author_users_skips_resolver_errors(self) -> None:
        def _resolve(subject: str) -> str:
            if subject == '9':
                raise RuntimeError('identity store unavailable')
            return 'ok@e.com'

        resolver = mock.AsyncMock(side_effect=_resolve)
        raw: list[dict[str, typing.Any]] = [
            {'author': {'id': 9}},  # resolver raises -> skipped
            {'author': {'id': 10}},  # resolves normally
        ]
        # A failing lookup is best-effort: it is logged and dropped, the
        # other authors still resolve, and the sync is not aborted.
        out = await commits._resolve_author_users(raw, resolver, 'base')
        self.assertEqual({'10': 'ok@e.com'}, out)

    async def test_author_users_without_resolver_is_empty(self) -> None:
        out = await commits._resolve_author_users(
            [{'author': {'id': 1}}], None, 'base'
        )
        self.assertEqual({}, out)


class AuthorAttributionTestCase(unittest.IsolatedAsyncioTestCase):
    """End-to-end author -> Imbi user attribution on the sync actions."""

    _REPO = 'https://api.github.com/repos/octo/demo'

    def setUp(self) -> None:
        commits._USER_CACHE.clear()

    @respx.mock
    async def test_sync_commits_stamps_author_user(self) -> None:
        base, head = 'a' * 40, 'b' * 40
        respx.get(f'{self._REPO}/compare/{base}...{head}').mock(
            return_value=httpx.Response(
                200, json={'commits': [_commit('c' * 40, author_id=42)]}
            )
        )
        resolver = mock.AsyncMock(return_value='dev@example.com')
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_commits(
                ctx=_ctx(resolve_user=resolver),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncCommitsConfig(),
                event=_event(_push(before=base, after=head)),
            )
        _, records = _await_args(insert)
        self.assertEqual('dev@example.com', records[0].author_user)
        resolver.assert_awaited_once_with('42')

    @respx.mock
    async def test_sync_commits_without_resolver_leaves_blank(self) -> None:
        base, head = 'a' * 40, 'b' * 40
        respx.get(f'{self._REPO}/compare/{base}...{head}').mock(
            return_value=httpx.Response(
                200, json={'commits': [_commit('c' * 40)]}
            )
        )
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.sync_commits(
                ctx=_ctx(),
                credentials=_CREDS,
                external_identifier='',
                action_config=commits.SyncCommitsConfig(),
                event=_event(_push(before=base, after=head)),
            )
        _, records = _await_args(insert)
        self.assertEqual('', records[0].author_user)

    @respx.mock
    async def test_full_history_resolves_each_author_once(self) -> None:
        respx.get(self._REPO).mock(
            return_value=httpx.Response(200, json={'default_branch': 'main'})
        )
        # Two commits by the same author + one by another.
        respx.get(f'{self._REPO}/commits').mock(
            return_value=httpx.Response(
                200,
                json=[
                    _commit('c' * 40, author_id=42),
                    _commit('d' * 40, author_id=42),
                    _commit('e' * 40, author_id=99),
                ],
            )
        )
        respx.get(f'{self._REPO}/git/matching-refs/tags').mock(
            return_value=httpx.Response(200, json=[])
        )
        resolver = mock.AsyncMock(
            side_effect=lambda s: 'dev@example.com' if s == '42' else None
        )
        ctx = _ctx(
            service_plugins=[ServicePlugin(slug='github', options={})],
            resolve_user=resolver,
        )
        with mock.patch(_INSERT, new=mock.AsyncMock()) as insert:
            await commits.GitHubCommitSyncPlugin().sync_all_history(
                ctx=ctx, credentials=_CREDS
            )
        commit_call = next(
            c for c in insert.await_args_list if c.args[0] == 'commits'
        )
        by_sha = {r.sha: r.author_user for r in commit_call.args[1]}
        self.assertEqual('dev@example.com', by_sha['c' * 40])
        self.assertEqual('dev@example.com', by_sha['d' * 40])
        self.assertEqual('', by_sha['e' * 40])
        # Two distinct authors -> two lookups despite three commits.
        self.assertEqual(
            {'42', '99'}, {c.args[0] for c in resolver.await_args_list}
        )
