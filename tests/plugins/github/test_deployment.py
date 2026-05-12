"""Smoke tests for the GitHub deployment plugins."""

import json
import time
import unittest

import httpx
import respx
from imbi_common.plugins.base import (
    DeploymentPlugin,
    PluginContext,
)
from imbi_common.plugins.errors import PluginAuthenticationFailed

from imbi_plugin_github.deployment import (
    GitHubDeploymentPlugin,
    GitHubEnterpriseCloudDeploymentPlugin,
    GitHubEnterpriseServerDeploymentPlugin,
)


def _ctx(
    options: dict[str, object] | None = None,
    environment: str | None = None,
    environment_config: dict[str, object] | None = None,
) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug='proj',
        org_slug='octo',
        environment=environment,
        assignment_options=options or {},
        environment_config=environment_config or {},
        actor_user_id='u-1',
        project_links={'github-repository': 'https://github.com/octo/demo'},
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

    def test_all_declare_deploys_via_edge(self) -> None:
        # Every concrete subclass needs the DEPLOYS_VIA declaration so
        # admins can wire up per-env config from the plugin-edge UI for
        # any GitHub flavor (.com / GHEC / GHES).
        for cls in (
            GitHubDeploymentPlugin,
            GitHubEnterpriseCloudDeploymentPlugin,
            GitHubEnterpriseServerDeploymentPlugin,
        ):
            edge = next(
                (
                    e
                    for e in cls.manifest.edge_labels
                    if e.name == 'DEPLOYS_VIA'
                ),
                None,
            )
            self.assertIsNotNone(
                edge, f'{cls.__name__} missing DEPLOYS_VIA edge'
            )
            assert edge is not None
            self.assertEqual(set(edge.from_labels), {'ProjectType', 'Project'})
            self.assertEqual(edge.to_labels, ['Environment'])
            self.assertIn('action', edge.properties)
            self.assertEqual(edge.properties['payload'], 'dict[str, str]')
            self.assertIn('identity_plugin_id', edge.properties)
            # Properties from the prior workflow_dispatch design must
            # not be carried forward.
            self.assertNotIn('workflow', edge.properties)
            self.assertNotIn('inputs', edge.properties)

    def test_owner_repo_required(self) -> None:
        plugin = GitHubDeploymentPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            assignment_options={},
        )
        with self.assertRaises(ValueError):
            plugin._owner_repo(ctx)

    def test_owner_repo_derived_from_project_link(self) -> None:
        plugin = GitHubDeploymentPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            assignment_options={},
            project_links={
                'github-repository': 'https://github.com/octo/demo'
            },
        )
        self.assertEqual(plugin._owner_repo(ctx), ('octo', 'demo'))

    def test_owner_repo_derived_strips_dot_git(self) -> None:
        plugin = GitHubDeploymentPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            assignment_options={},
            project_links={
                'github-repository': 'https://github.com/octo/demo.git'
            },
        )
        self.assertEqual(plugin._owner_repo(ctx), ('octo', 'demo'))

    def test_owner_repo_derived_for_ghec_tenant(self) -> None:
        plugin = GitHubEnterpriseCloudDeploymentPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            assignment_options={'host': 'aweber.ghe.com'},
            project_links={
                'github-repository': 'https://aweber.ghe.com/apis/account'
            },
        )
        self.assertEqual(plugin._owner_repo(ctx), ('apis', 'account'))

    def test_owner_repo_ignores_link_for_other_host(self) -> None:
        plugin = GitHubDeploymentPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            assignment_options={},
            project_links={
                'gitlab-repository': 'https://gitlab.com/octo/demo'
            },
        )
        with self.assertRaises(ValueError):
            plugin._owner_repo(ctx)

    def test_owner_repo_falls_back_to_project_type(self) -> None:
        plugin = GitHubDeploymentPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='account',
            org_slug='octo',
            assignment_options={},
            project_type_slugs=['apis'],
        )
        self.assertEqual(plugin._owner_repo(ctx), ('apis', 'account'))

    def test_owner_repo_link_wins_over_project_type(self) -> None:
        plugin = GitHubDeploymentPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='account',
            org_slug='octo',
            assignment_options={},
            project_links={
                'github-repository': 'https://github.com/from-link/repo'
            },
            project_type_slugs=['apis'],
        )
        self.assertEqual(plugin._owner_repo(ctx), ('from-link', 'repo'))

    def test_owner_repo_prefers_explicit_repo_link(self) -> None:
        """Explicit ``github-repository`` link key wins over other
        same-host links, even when it appears later in dict order."""
        plugin = GitHubDeploymentPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            assignment_options={},
            project_links={
                'docs': 'https://github.com/other-org/other-repo',
                'github-repository': 'https://github.com/correct/repo',
            },
        )
        self.assertEqual(plugin._owner_repo(ctx), ('correct', 'repo'))

    def test_owner_repo_rejects_orgs_path(self) -> None:
        """``github.com/orgs/<org>`` is not a repository URL — fall
        through to the project_type fallback rather than binding to
        ``orgs/<org>``."""
        plugin = GitHubDeploymentPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='account',
            org_slug='octo',
            assignment_options={},
            project_links={'github-org': 'https://github.com/orgs/octo'},
            project_type_slugs=['apis'],
        )
        self.assertEqual(plugin._owner_repo(ctx), ('apis', 'account'))

    def test_owner_repo_rejects_marketplace_path(self) -> None:
        plugin = GitHubDeploymentPlugin()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            assignment_options={},
            project_links={
                'marketplace': 'https://github.com/marketplace/actions/checkout'
            },
        )
        with self.assertRaises(ValueError):
            plugin._owner_repo(ctx)

    def test_record_checks_disabled_evicts_expired(self) -> None:
        """``_record_checks_disabled`` must sweep stale entries before
        inserting; otherwise the cache grows unbounded."""
        from imbi_plugin_github import deployment as dep

        # Re-bind into the module so the helper writes into a sandbox we
        # can inspect, then restore on teardown.
        original = dep._CHECKS_DISABLED_TOKENS
        dep._CHECKS_DISABLED_TOKENS = {
            'stale-key': time.monotonic()
            - dep._CHECKS_DISABLED_TTL_SECONDS
            - 1,
            'fresh-key': time.monotonic(),
        }
        try:
            dep._record_checks_disabled(
                {'access_token': 'gho_record'}, 'github.com', 'octo', 'demo'
            )
            # The stale entry is gone; the fresh one and the new key remain.
            self.assertNotIn('stale-key', dep._CHECKS_DISABLED_TOKENS)
            self.assertIn('fresh-key', dep._CHECKS_DISABLED_TOKENS)
            self.assertEqual(len(dep._CHECKS_DISABLED_TOKENS), 2)
        finally:
            dep._CHECKS_DISABLED_TOKENS = original

    def test_record_checks_disabled_skips_when_no_token(self) -> None:
        from imbi_plugin_github import deployment as dep

        original = dict(dep._CHECKS_DISABLED_TOKENS)
        dep._record_checks_disabled({}, 'github.com', 'octo', 'demo')
        self.assertEqual(dep._CHECKS_DISABLED_TOKENS, original)

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
        respx.get('https://api.github.com/repos/octo/demo').mock(
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
        respx.get('https://api.github.com/repos/octo/demo').mock(
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
        respx.get('https://api.github.com/repos/octo/demo').mock(
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
        respx.get('https://api.github.com/repos/octo/demo').mock(
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


class TriggerDeploymentTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_trigger_creates_deployment(self) -> None:
        deploy = respx.post(
            'https://api.github.com/repos/octo/demo/deployments'
        ).mock(
            return_value=httpx.Response(
                201,
                json={
                    'id': 9999,
                    'environment': 'testing',
                    'ref': 'main',
                    'url': (
                        'https://api.github.com/repos/octo/demo/'
                        'deployments/9999'
                    ),
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        run = await plugin.trigger_deployment(
            _ctx(environment='testing'),
            _CREDS,
            ref_or_sha='main',
        )
        self.assertEqual(run.run_id, '9999')
        # No ``run_url`` until the deploy workflow posts a status with
        # a ``log_url`` — verified separately by GetDeploymentStatus.
        self.assertIsNone(run.run_url)
        self.assertEqual(run.status, 'queued')
        self.assertTrue(deploy.called)
        body = json.loads(deploy.calls.last.request.read())
        self.assertEqual(body['ref'], 'main')
        self.assertEqual(body['environment'], 'testing')
        self.assertFalse(body['auto_merge'])
        self.assertEqual(body['required_contexts'], [])
        self.assertEqual(body['payload'], {})

    @respx.mock
    async def test_trigger_requires_environment(self) -> None:
        plugin = GitHubDeploymentPlugin()
        with self.assertRaises(ValueError):
            await plugin.trigger_deployment(_ctx(), _CREDS, 'main')

    @respx.mock
    async def test_trigger_uses_environment_config_payload(self) -> None:
        # The DEPLOYS_VIA edge supplies the deployment payload via
        # ``ctx.environment_config['payload']``.  Caller-supplied
        # ``inputs`` are the base; env_config keys override them.
        deploy = respx.post(
            'https://api.github.com/repos/octo/demo/deployments'
        ).mock(return_value=httpx.Response(201, json={'id': 1, 'url': ''}))
        plugin = GitHubDeploymentPlugin()
        ctx = _ctx(
            environment='production',
            environment_config={
                'payload': {
                    'cluster': 'prod-east',
                    'feature_flag': 'on',
                }
            },
        )
        await plugin.trigger_deployment(
            ctx,
            _CREDS,
            ref_or_sha='v1.2.3',
            inputs={'cluster': 'WILL-LOSE', 'extra': 'kept'},
        )
        body = json.loads(deploy.calls.last.request.read())
        self.assertEqual(body['ref'], 'v1.2.3')
        self.assertEqual(body['environment'], 'production')
        self.assertEqual(
            body['payload'],
            {'cluster': 'prod-east', 'feature_flag': 'on', 'extra': 'kept'},
        )

    @respx.mock
    async def test_trigger_ignores_non_dict_env_payload(self) -> None:
        # A malformed edge property (string instead of dict) should not
        # crash the plugin — we drop it and fall back to caller inputs.
        deploy = respx.post(
            'https://api.github.com/repos/octo/demo/deployments'
        ).mock(return_value=httpx.Response(201, json={'id': 2, 'url': ''}))
        plugin = GitHubDeploymentPlugin()
        ctx = _ctx(
            environment='staging',
            environment_config={'payload': 'not-a-dict'},
        )
        await plugin.trigger_deployment(
            ctx, _CREDS, ref_or_sha='v1.0.0', inputs={'k': 'v'}
        )
        body = json.loads(deploy.calls.last.request.read())
        self.assertEqual(body['payload'], {'k': 'v'})


class ListRefsPaginationTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_list_branches_follows_next_link(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
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
    async def test_status_empty_returns_queued(self) -> None:
        # Deployment was created but no workflow has posted a status
        # yet — Imbi treats that as still queued.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/42/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        plugin = GitHubDeploymentPlugin()
        run = await plugin.get_deployment_status(_ctx(), _CREDS, '42')
        self.assertEqual(run.status, 'queued')
        self.assertEqual(run.run_id, '42')
        self.assertIsNone(run.run_url)
        self.assertIsNone(run.completed_at)

    @respx.mock
    async def test_status_in_progress_carries_log_url(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/42/statuses'
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'state': 'in_progress',
                        'created_at': '2026-01-01T00:00:00Z',
                        'log_url': 'https://gh/runs/42',
                    }
                ],
            )
        )
        plugin = GitHubDeploymentPlugin()
        run = await plugin.get_deployment_status(_ctx(), _CREDS, '42')
        self.assertEqual(run.status, 'in_progress')
        self.assertEqual(run.run_url, 'https://gh/runs/42')
        self.assertIsNone(run.completed_at)

    @respx.mock
    async def test_status_success_sets_completed_at(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/42/statuses'
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'state': 'success',
                        'created_at': '2026-01-01T00:00:00Z',
                        'updated_at': '2026-01-01T01:00:00Z',
                        'log_url': 'https://gh/runs/42',
                    }
                ],
            )
        )
        plugin = GitHubDeploymentPlugin()
        run = await plugin.get_deployment_status(_ctx(), _CREDS, '42')
        self.assertEqual(run.status, 'success')
        self.assertIsNotNone(run.completed_at)

    @respx.mock
    async def test_status_picks_newest_first_entry(self) -> None:
        # GitHub returns statuses newest-first.  Older states must not
        # override the latest one.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/42/statuses'
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {'state': 'failure', 'updated_at': '2026-01-01T02:00:00Z'},
                    {'state': 'in_progress'},
                    {'state': 'pending'},
                ],
            )
        )
        plugin = GitHubDeploymentPlugin()
        run = await plugin.get_deployment_status(_ctx(), _CREDS, '42')
        self.assertEqual(run.status, 'failure')

    @respx.mock
    async def test_status_inactive_maps_to_cancelled(self) -> None:
        # ``inactive`` means a newer deployment for the same env
        # superseded this one — Imbi treats it as cancelled, not failed.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/42/statuses'
        ).mock(
            return_value=httpx.Response(
                200,
                json=[{'state': 'inactive'}],
            )
        )
        plugin = GitHubDeploymentPlugin()
        run = await plugin.get_deployment_status(_ctx(), _CREDS, '42')
        self.assertEqual(run.status, 'cancelled')


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


class AuthenticationFailureTestCase(unittest.IsolatedAsyncioTestCase):
    """The deployment client converts 401 responses into
    :class:`PluginAuthenticationFailed` so the host's retry-with-
    refresh layer can recover from a token that expired between the
    sweeper's last refresh and the user's request.
    """

    @respx.mock
    async def test_401_on_repo_get_raises_authentication_failed(
        self,
    ) -> None:
        respx.get('https://api.github.com/repos/octo/demo').mock(
            return_value=httpx.Response(
                401, json={'message': 'Bad credentials'}
            )
        )
        plugin = GitHubDeploymentPlugin()
        with self.assertRaises(PluginAuthenticationFailed):
            await plugin.list_refs(_ctx(), _CREDS, kind='default')

    @respx.mock
    async def test_401_on_deployment_raises_authentication_failed(
        self,
    ) -> None:
        respx.post('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(401, json={'message': 'token expired'})
        )
        plugin = GitHubDeploymentPlugin()
        with self.assertRaises(PluginAuthenticationFailed):
            await plugin.trigger_deployment(
                _ctx(environment='production'),
                _CREDS,
                'main',
            )


class ListWorkflowsTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_list_workflows_parses_active_entries(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/actions/workflows'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'total_count': 2,
                    'workflows': [
                        {
                            'id': 161335,
                            'name': 'CI',
                            'path': '.github/workflows/ci.yml',
                            'state': 'active',
                        },
                        {
                            'id': 161336,
                            'name': 'Deploy',
                            'path': '.github/workflows/deploy.yml',
                            'state': 'active',
                        },
                    ],
                },
            )
        )
        plugin = GitHubDeploymentPlugin()
        workflows = await plugin.list_workflows(_ctx(), _CREDS)
        self.assertEqual(
            [w.path for w in workflows],
            [
                '.github/workflows/ci.yml',
                '.github/workflows/deploy.yml',
            ],
        )
        self.assertEqual(workflows[0].id, '161335')
        self.assertEqual(workflows[0].name, 'CI')
        self.assertEqual(workflows[0].state, 'active')

    @respx.mock
    async def test_list_workflows_empty_response(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/actions/workflows'
        ).mock(
            return_value=httpx.Response(
                200, json={'total_count': 0, 'workflows': []}
            )
        )
        plugin = GitHubDeploymentPlugin()
        self.assertEqual(await plugin.list_workflows(_ctx(), _CREDS), [])
