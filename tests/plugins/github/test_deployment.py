"""Smoke tests for the GitHub deployment plugins."""

import datetime
import json
import unittest

import httpx
import respx
from imbi_common.plugins.base import (
    DeploymentPlugin,
    PluginContext,
)

from imbi_plugin_github.deployment import (
    GitHubDeploymentPlugin,
    GitHubEnterpriseCloudDeploymentPlugin,
    GitHubEnterpriseServerDeploymentPlugin,
)


def _ctx(
    options: dict[str, object] | None = None,
    environment: str | None = None,
) -> PluginContext:
    base: dict[str, object] = {'owner': 'octo', 'repo': 'demo'}
    if options:
        base.update(options)
    return PluginContext(
        project_id='p',
        project_slug='proj',
        org_slug='octo',
        environment=environment,
        assignment_options=base,
        actor_user_id='u-1',
    )


_CREDS = {'access_token': 'gho_test'}


class ManifestTestCase(unittest.TestCase):
    def test_manifest_slugs(self) -> None:
        self.assertEqual(
            GitHubDeploymentPlugin.manifest.slug, 'github-deployment'
        )
        self.assertEqual(
            GitHubEnterpriseCloudDeploymentPlugin.manifest.slug,
            'github-deployment-ec',
        )
        self.assertEqual(
            GitHubEnterpriseServerDeploymentPlugin.manifest.slug,
            'github-deployment-es',
        )

    def test_all_subclass_deployment_plugin(self) -> None:
        for cls in (
            GitHubDeploymentPlugin,
            GitHubEnterpriseCloudDeploymentPlugin,
            GitHubEnterpriseServerDeploymentPlugin,
        ):
            self.assertIsInstance(cls(), DeploymentPlugin)
            self.assertEqual(cls.manifest.plugin_type, 'deployment')

    def test_owner_repo_required(self) -> None:
        plugin = GitHubDeploymentPlugin()
        with self.assertRaises(ValueError):
            plugin._owner_repo({})

    def test_token_required(self) -> None:
        with self.assertRaises(ValueError):
            GitHubDeploymentPlugin._token({})

    def test_token_accepts_token_alias(self) -> None:
        self.assertEqual(
            GitHubDeploymentPlugin._token({'token': 'abc'}), 'abc'
        )

    def test_api_base_dot_com(self) -> None:
        plugin = GitHubDeploymentPlugin()
        self.assertEqual(plugin._api_base({}), 'https://api.github.com')

    def test_api_base_ghec(self) -> None:
        plugin = GitHubEnterpriseCloudDeploymentPlugin()
        self.assertEqual(
            plugin._api_base({'host': 'tenant.ghe.com'}),
            'https://api.tenant.ghe.com',
        )

    def test_api_base_ghes(self) -> None:
        plugin = GitHubEnterpriseServerDeploymentPlugin()
        self.assertEqual(
            plugin._api_base({'host': 'github.example.com'}),
            'https://github.example.com/api/v3',
        )

    def test_ghec_rejects_non_tenant_host(self) -> None:
        plugin = GitHubEnterpriseCloudDeploymentPlugin()
        with self.assertRaises(ValueError):
            plugin._api_base({'host': 'github.example.com'})


class ListRefsTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_list_refs_default(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo/').mock(
            return_value=httpx.Response(200, json={'default_branch': 'main'})
        )
        respx.get('https://api.github.com/repos/octo/demo/branches/main').mock(
            return_value=httpx.Response(
                200, json={'commit': {'sha': 'sha-main'}}
            )
        )
        plugin = GitHubDeploymentPlugin()
        refs = await plugin.list_refs(_ctx(), _CREDS, kind='default')
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].name, 'main')
        self.assertTrue(refs[0].is_default)
        self.assertEqual(refs[0].sha, 'sha-main')

    @respx.mock
    async def test_list_refs_branches_skips_default(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo/').mock(
            return_value=httpx.Response(200, json={'default_branch': 'main'})
        )
        respx.get('https://api.github.com/repos/octo/demo/branches').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {'name': 'main', 'commit': {'sha': 'main-sha'}},
                    {'name': 'feature/x', 'commit': {'sha': 'fx-sha'}},
                    {'name': 'feature/y', 'commit': {'sha': 'fy-sha'}},
                ],
            )
        )
        plugin = GitHubDeploymentPlugin()
        refs = await plugin.list_refs(_ctx(), _CREDS, kind='branch')
        names = [r.name for r in refs]
        self.assertNotIn('main', names)
        self.assertEqual(len(refs), 2)

    @respx.mock
    async def test_list_refs_branch_uses_actual_default(self) -> None:
        # Repo's real default is 'master'; assignment_options says 'main'.
        # The branch list must hide 'master' (the real default) and keep
        # 'main' as a regular branch.
        respx.get('https://api.github.com/repos/octo/demo/').mock(
            return_value=httpx.Response(200, json={'default_branch': 'master'})
        )
        respx.get('https://api.github.com/repos/octo/demo/branches').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {'name': 'master', 'commit': {'sha': 'master-sha'}},
                    {'name': 'main', 'commit': {'sha': 'main-sha'}},
                ],
            )
        )
        plugin = GitHubDeploymentPlugin()
        refs = await plugin.list_refs(_ctx(), _CREDS, kind='branch')
        names = [r.name for r in refs]
        self.assertNotIn('master', names)
        self.assertIn('main', names)

    @respx.mock
    async def test_list_refs_branches_filters_by_query(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo/').mock(
            return_value=httpx.Response(200, json={'default_branch': 'main'})
        )
        respx.get('https://api.github.com/repos/octo/demo/branches').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {'name': 'feature/foo', 'commit': {'sha': 'a'}},
                    {'name': 'feature/bar', 'commit': {'sha': 'b'}},
                ],
            )
        )
        plugin = GitHubDeploymentPlugin()
        refs = await plugin.list_refs(
            _ctx(), _CREDS, kind='branch', query='foo'
        )
        self.assertEqual([r.name for r in refs], ['feature/foo'])

    @respx.mock
    async def test_list_refs_tags(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo/tags').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {'name': 'v1.0.0', 'commit': {'sha': 'tag-sha'}},
                ],
            )
        )
        plugin = GitHubDeploymentPlugin()
        refs = await plugin.list_refs(_ctx(), _CREDS, kind='tag')
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].kind, 'tag')
        self.assertEqual(refs[0].name, 'v1.0.0')


class CommitsTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_list_commits_marks_head_and_status(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo/commits').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'sha': 'a1b2c3d4e5',
                        'html_url': 'https://gh/c/a',
                        'commit': {
                            'message': 'Top\n\nbody',
                            'author': {
                                'name': 'Alice',
                                'date': '2026-01-01T00:00:00Z',
                            },
                        },
                    },
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/commits/a1b2c3d4e5/check-runs'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'check_runs': [
                        {'status': 'completed', 'conclusion': 'success'},
                        {'status': 'completed', 'conclusion': 'success'},
                    ]
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        commits = await plugin.list_commits(_ctx(), _CREDS, ref='main')
        self.assertEqual(len(commits), 1)
        self.assertTrue(commits[0].is_head)
        self.assertEqual(commits[0].ci_status, 'pass')
        self.assertEqual(commits[0].author, 'Alice')
        self.assertEqual(commits[0].short_sha, 'a1b2c3d')
        self.assertEqual(commits[0].message, 'Top')

    @respx.mock
    async def test_list_commits_check_runs_failure(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo/commits').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'sha': 'abc',
                        'commit': {
                            'message': 'msg',
                            'author': {'name': 'X', 'date': None},
                        },
                    },
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/commits/abc/check-runs'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'check_runs': [
                        {'status': 'completed', 'conclusion': 'failure'}
                    ]
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        commits = await plugin.list_commits(_ctx(), _CREDS, ref='main')
        self.assertEqual(commits[0].ci_status, 'fail')

    @respx.mock
    async def test_list_commits_check_runs_in_progress_is_unknown(
        self,
    ) -> None:
        # A mix of completed-success and still-running runs must not
        # be reported as ``pass`` — the commit hasn't actually passed
        # CI yet.
        respx.get('https://api.github.com/repos/octo/demo/commits').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'sha': 'abc',
                        'commit': {
                            'message': 'msg',
                            'author': {'name': 'X', 'date': None},
                        },
                    },
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/commits/abc/check-runs'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'check_runs': [
                        {
                            'status': 'completed',
                            'conclusion': 'success',
                        },
                        {'status': 'in_progress', 'conclusion': None},
                    ]
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        commits = await plugin.list_commits(_ctx(), _CREDS, ref='main')
        self.assertEqual(commits[0].ci_status, 'unknown')

    @respx.mock
    async def test_list_commits_check_runs_404_falls_back_unknown(
        self,
    ) -> None:
        respx.get('https://api.github.com/repos/octo/demo/commits').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'sha': 'abc',
                        'commit': {
                            'message': 'msg',
                            'author': {'name': 'X', 'date': None},
                        },
                    },
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/commits/abc/check-runs'
        ).mock(return_value=httpx.Response(404, json={}))
        plugin = GitHubDeploymentPlugin()
        commits = await plugin.list_commits(_ctx(), _CREDS, ref='main')
        self.assertEqual(commits[0].ci_status, 'unknown')

    @respx.mock
    async def test_resolve_committish(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo/commits/abc').mock(
            return_value=httpx.Response(
                200,
                json={
                    'sha': 'abc',
                    'commit': {
                        'message': 'fix',
                        'author': {
                            'name': 'B',
                            'date': '2026-02-02T03:04:05Z',
                        },
                    },
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        commit = await plugin.resolve_committish(_ctx(), _CREDS, 'abc')
        self.assertEqual(commit.sha, 'abc')
        self.assertEqual(commit.message, 'fix')


class CompareTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_compare_aggregates_diff(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/compare/base...head'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'ahead_by': 2,
                    'behind_by': 0,
                    'base_commit': {'sha': 'base-sha'},
                    'commits': [
                        {
                            'sha': 'c1',
                            'commit': {
                                'message': 'one',
                                'author': {'name': 'A', 'date': None},
                            },
                        },
                        {
                            'sha': 'c2',
                            'commit': {
                                'message': 'two',
                                'author': {'name': 'A', 'date': None},
                            },
                        },
                    ],
                    'files': [
                        {'additions': 3, 'deletions': 1},
                        {'additions': 0, 'deletions': 2},
                    ],
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        result = await plugin.compare(_ctx(), _CREDS, 'base', 'head')
        self.assertEqual(result.ahead, 2)
        self.assertEqual(result.behind, 0)
        self.assertEqual(len(result.commits), 2)
        self.assertEqual(result.files_changed, 2)
        self.assertEqual(result.additions, 3)
        self.assertEqual(result.deletions, 3)
        self.assertEqual(result.head_sha, 'c2')
        self.assertEqual(result.base_sha, 'base-sha')


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    ).isoformat()


class TriggerDeploymentTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_trigger_dispatch_default_workflow(self) -> None:
        dispatch = respx.post(
            'https://api.github.com/repos/octo/demo/actions/workflows/'
            'deploy.yml/dispatches'
        ).mock(return_value=httpx.Response(204))
        respx.get(
            'https://api.github.com/repos/octo/demo/actions/workflows/'
            'deploy.yml/runs'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'workflow_runs': [
                        {
                            'id': 999,
                            'html_url': 'https://gh/runs/999',
                            'created_at': _now_iso(),
                            'head_branch': 'main',
                            'head_sha': 'main-sha',
                        }
                    ]
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        run = await plugin.trigger_deployment(
            _ctx(environment='testing'),
            _CREDS,
            ref_or_sha='main',
        )
        self.assertEqual(run.run_id, '999')
        self.assertEqual(run.run_url, 'https://gh/runs/999')
        self.assertEqual(run.status, 'queued')
        self.assertTrue(dispatch.called)
        body = dispatch.calls.last.request.read().decode()
        self.assertIn('"ref":"main"', body)
        self.assertIn('"environment":"testing"', body)

    @respx.mock
    async def test_trigger_requires_environment(self) -> None:
        plugin = GitHubDeploymentPlugin()
        with self.assertRaises(ValueError):
            await plugin.trigger_deployment(_ctx(), _CREDS, 'main')

    @respx.mock
    async def test_trigger_uses_custom_workflow_and_inputs(self) -> None:
        dispatch = respx.post(
            'https://api.github.com/repos/octo/demo/actions/workflows/'
            'release.yml/dispatches'
        ).mock(return_value=httpx.Response(204))
        respx.get(
            'https://api.github.com/repos/octo/demo/actions/workflows/'
            'release.yml/runs'
        ).mock(return_value=httpx.Response(200, json={'workflow_runs': []}))
        plugin = GitHubDeploymentPlugin()
        ctx = _ctx(
            options={
                'workflow': 'release.yml',
                'environment_input': 'env',
                'ref_input': 'commit',
            },
            environment='staging',
        )
        run = await plugin.trigger_deployment(
            ctx,
            _CREDS,
            ref_or_sha='abc123',
        )
        self.assertEqual(run.run_id, '')
        body = dispatch.calls.last.request.read().decode()
        self.assertIn('"env":"staging"', body)
        self.assertIn('"commit":"abc123"', body)

    @respx.mock
    async def test_trigger_ignores_unrelated_concurrent_run(self) -> None:
        # Another dispatch (different branch) lands first.  We should
        # match the run whose ``head_branch`` matches our ref, not the
        # one that happens to be newest.
        respx.post(
            'https://api.github.com/repos/octo/demo/actions/workflows/'
            'deploy.yml/dispatches'
        ).mock(return_value=httpx.Response(204))
        respx.get(
            'https://api.github.com/repos/octo/demo/actions/workflows/'
            'deploy.yml/runs'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'workflow_runs': [
                        {
                            'id': 111,
                            'html_url': 'https://gh/runs/111',
                            'created_at': _now_iso(),
                            'head_branch': 'someone-else',
                            'head_sha': 'other-sha',
                        },
                        {
                            'id': 222,
                            'html_url': 'https://gh/runs/222',
                            'created_at': _now_iso(),
                            'head_branch': 'main',
                            'head_sha': 'main-sha',
                        },
                    ]
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        run = await plugin.trigger_deployment(
            _ctx(environment='testing'),
            _CREDS,
            ref_or_sha='main',
        )
        self.assertEqual(run.run_id, '222')

    @respx.mock
    async def test_trigger_ignores_run_created_before_dispatch(self) -> None:
        # A pre-existing run on the same branch should not be picked up.
        old = (
            datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=5)
        ).isoformat()
        respx.post(
            'https://api.github.com/repos/octo/demo/actions/workflows/'
            'deploy.yml/dispatches'
        ).mock(return_value=httpx.Response(204))
        respx.get(
            'https://api.github.com/repos/octo/demo/actions/workflows/'
            'deploy.yml/runs'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'workflow_runs': [
                        {
                            'id': 1,
                            'html_url': 'https://gh/runs/1',
                            'created_at': old,
                            'head_branch': 'main',
                            'head_sha': 'main-sha',
                        }
                    ]
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        run = await plugin.trigger_deployment(
            _ctx(environment='testing'),
            _CREDS,
            ref_or_sha='main',
        )
        self.assertEqual(run.run_id, '')

    @respx.mock
    async def test_trigger_inputs_cannot_override_env_or_ref(self) -> None:
        # Even if the caller supplies the reserved keys (or aliases of
        # them), ``ctx.environment`` and ``ref_or_sha`` must win.
        dispatch = respx.post(
            'https://api.github.com/repos/octo/demo/actions/workflows/'
            'deploy.yml/dispatches'
        ).mock(return_value=httpx.Response(204))
        respx.get(
            'https://api.github.com/repos/octo/demo/actions/workflows/'
            'deploy.yml/runs'
        ).mock(return_value=httpx.Response(200, json={'workflow_runs': []}))
        plugin = GitHubDeploymentPlugin()
        await plugin.trigger_deployment(
            _ctx(environment='production'),
            _CREDS,
            ref_or_sha='v1.2.3',
            inputs={
                'environment': 'staging',  # caller try to switch env
                'ref': 'feature/sneaky',  # caller try to switch ref
                'extra': 'kept',  # unrelated input is preserved
            },
        )
        body = dispatch.calls.last.request.read().decode()
        self.assertIn('"environment":"production"', body)
        self.assertNotIn('"environment":"staging"', body)
        # The ref input field — outer "ref" is the dispatch ref, not
        # the input.  Verify within the ``inputs`` object.
        self.assertIn('"extra":"kept"', body)
        # ``inputs.ref`` must point at the deploy ref, not the
        # caller-supplied override.
        payload = json.loads(body)
        self.assertEqual(payload['inputs']['ref'], 'v1.2.3')
        self.assertEqual(payload['inputs']['environment'], 'production')
        self.assertEqual(payload['inputs']['extra'], 'kept')


class ListRefsPaginationTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_list_branches_follows_next_link(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo/').mock(
            return_value=httpx.Response(200, json={'default_branch': 'main'})
        )
        branches_url = 'https://api.github.com/repos/octo/demo/branches'
        page2_link = f'{branches_url}?per_page=100&page=2'
        # Register the more-specific (page=2) matcher first; respx
        # matches first-registered-first and a subset matcher would
        # otherwise swallow the page=2 request.
        respx.get(branches_url, params={'per_page': '100', 'page': '2'}).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {'name': 'feat-c', 'commit': {'sha': 'c'}},
                ],
            )
        )
        respx.get(branches_url, params={'per_page': '100'}).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {'name': 'feat-a', 'commit': {'sha': 'a'}},
                    {'name': 'feat-b', 'commit': {'sha': 'b'}},
                ],
                headers={'Link': f'<{page2_link}>; rel="next"'},
            )
        )
        plugin = GitHubDeploymentPlugin()
        refs = await plugin.list_refs(_ctx(), _CREDS, kind='branch')
        names = sorted(r.name for r in refs)
        self.assertEqual(names, ['feat-a', 'feat-b', 'feat-c'])

    @respx.mock
    async def test_list_tags_follows_next_link(self) -> None:
        tags_url = 'https://api.github.com/repos/octo/demo/tags'
        page2_link = f'{tags_url}?per_page=100&page=2'
        respx.get(tags_url, params={'per_page': '100', 'page': '2'}).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {'name': 'v2.0.0', 'commit': {'sha': 'c'}},
                ],
            )
        )
        respx.get(tags_url, params={'per_page': '100'}).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {'name': 'v1.0.0', 'commit': {'sha': 'a'}},
                    {'name': 'v1.1.0', 'commit': {'sha': 'b'}},
                ],
                headers={
                    'Link': (
                        f'<{page2_link}>; rel="next", '
                        f'<{page2_link}>; rel="last"'
                    )
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        refs = await plugin.list_refs(_ctx(), _CREDS, kind='tag')
        names = sorted(r.name for r in refs)
        self.assertEqual(names, ['v1.0.0', 'v1.1.0', 'v2.0.0'])


class GetDeploymentStatusTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_status_in_progress(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/actions/runs/42'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'id': 42,
                    'status': 'in_progress',
                    'html_url': 'https://gh/runs/42',
                    'run_started_at': '2026-01-01T00:00:00Z',
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        run = await plugin.get_deployment_status(_ctx(), _CREDS, '42')
        self.assertEqual(run.status, 'in_progress')
        self.assertEqual(run.run_id, '42')
        self.assertIsNone(run.completed_at)

    @respx.mock
    async def test_status_success(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/actions/runs/42'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'id': 42,
                    'status': 'completed',
                    'conclusion': 'success',
                    'updated_at': '2026-01-01T01:00:00Z',
                    'run_started_at': '2026-01-01T00:00:00Z',
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        run = await plugin.get_deployment_status(_ctx(), _CREDS, '42')
        self.assertEqual(run.status, 'success')
        self.assertIsNotNone(run.completed_at)

    @respx.mock
    async def test_status_failure(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/actions/runs/42'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'id': 42,
                    'status': 'completed',
                    'conclusion': 'failure',
                    'updated_at': '2026-01-01T01:00:00Z',
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        run = await plugin.get_deployment_status(_ctx(), _CREDS, '42')
        self.assertEqual(run.status, 'failure')


class CheckStatusTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_check_status_pass(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/commits/v1.0.0/check-runs'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'check_runs': [
                        {'status': 'completed', 'conclusion': 'success'},
                    ]
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        status = await plugin.get_check_status(_ctx(), _CREDS, 'v1.0.0')
        self.assertEqual(status, 'pass')

    @respx.mock
    async def test_check_status_fail(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/commits/abc/check-runs'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'check_runs': [
                        {'status': 'completed', 'conclusion': 'failure'}
                    ]
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        status = await plugin.get_check_status(_ctx(), _CREDS, 'abc')
        self.assertEqual(status, 'fail')

    @respx.mock
    async def test_check_status_404_returns_unknown(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/commits/abc/check-runs'
        ).mock(return_value=httpx.Response(404, json={}))
        plugin = GitHubDeploymentPlugin()
        status = await plugin.get_check_status(_ctx(), _CREDS, 'abc')
        self.assertEqual(status, 'unknown')

    @respx.mock
    async def test_check_status_network_error_returns_unknown(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/commits/abc/check-runs'
        ).mock(side_effect=httpx.ConnectError('boom'))
        plugin = GitHubDeploymentPlugin()
        status = await plugin.get_check_status(_ctx(), _CREDS, 'abc')
        self.assertEqual(status, 'unknown')

    @respx.mock
    async def test_check_status_quotes_committish(self) -> None:
        # A tag like ``refs/tags/v1.0.0`` should be percent-encoded
        # so the URL stays inside ``/commits/.../check-runs``.
        respx.get(
            'https://api.github.com/repos/octo/demo/commits'
            '/refs%2Ftags%2Fv1.0.0/check-runs'
        ).mock(
            return_value=httpx.Response(
                200,
                json={'check_runs': []},
            )
        )
        plugin = GitHubDeploymentPlugin()
        status = await plugin.get_check_status(
            _ctx(), _CREDS, 'refs/tags/v1.0.0'
        )
        self.assertEqual(status, 'unknown')


class TagAndReleaseTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_create_tag_and_ref(self) -> None:
        respx.post('https://api.github.com/repos/octo/demo/git/tags').mock(
            return_value=httpx.Response(201, json={'sha': 'tag-obj-sha'})
        )
        respx.post('https://api.github.com/repos/octo/demo/git/refs').mock(
            return_value=httpx.Response(
                201,
                json={
                    'ref': 'refs/tags/v1.0.0',
                    'object': {'sha': 'tag-obj-sha'},
                    'url': 'https://api.github.com/.../refs/tags/v1.0.0',
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        info = await plugin.create_tag(
            _ctx(), _CREDS, 'commit-sha', 'v1.0.0', 'Release'
        )
        self.assertEqual(info.name, 'refs/tags/v1.0.0')
        self.assertEqual(info.sha, 'tag-obj-sha')

    @respx.mock
    async def test_create_release(self) -> None:
        respx.post('https://api.github.com/repos/octo/demo/releases').mock(
            return_value=httpx.Response(
                201,
                json={
                    'id': 12345,
                    'tag_name': 'v1.0.0',
                    'name': 'v1.0.0',
                    'html_url': 'https://gh/releases/12345',
                    'url': 'https://api.gh/.../releases/12345',
                    'prerelease': False,
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        info = await plugin.create_release(
            _ctx(),
            _CREDS,
            tag='v1.0.0',
            name='v1.0.0',
            body_markdown='## Notes',
        )
        self.assertEqual(info.id, '12345')
        self.assertEqual(info.tag, 'v1.0.0')
        self.assertFalse(info.prerelease)
