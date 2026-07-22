"""Smoke tests for the GitHub deployment capability handler."""

import asyncio
import datetime
import json
import time
import unittest

import httpx
import respx

from imbi.common.plugins.base import (
    DeploymentCapability,
    PluginContext,
)
from imbi.common.plugins.errors import PluginAuthenticationFailed
from imbi.plugins.github.deployment import (
    GitHubDeployment,
    _repo_root_from_redirect,
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
    environment: str | None = None,
    environment_config: dict[str, object] | None = None,
    connection: dict[str, object] | None = None,
) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug='proj',
        org_slug='octo',
        environment=environment,
        capability_options=options or {},
        environment_config=environment_config or {},
        actor_user_id='u-1',
        project_links={'github-repository': 'https://github.com/octo/demo'},
        integration_options=connection
        if connection is not None
        else _connection(),
    )


_CREDS = {'access_token': 'gho_test'}


class ManifestTestCase(unittest.TestCase):
    def test_manifest_slug(self) -> None:
        self.assertEqual(GitHubPlugin.manifest.slug, 'github')

    def test_subclasses_deployment_capability(self) -> None:
        cap = GitHubPlugin.manifest.get_capability('deployment')
        assert cap is not None
        self.assertTrue(issubclass(cap.handler, DeploymentCapability))
        self.assertIs(cap.handler, GitHubDeployment)

    def test_advertises_supports_deployment_sync(self) -> None:
        cap = GitHubPlugin.manifest.get_capability('deployment')
        assert cap is not None
        self.assertTrue(
            cap.hints.get('supports_deployment_sync'),
            'deployment capability must opt in to deployment sync',
        )

    def test_no_capability_options_declared(self) -> None:
        # The host now comes from the Integration's flavor/host options,
        # never from a per-capability ``host`` option.
        cap = GitHubPlugin.manifest.get_capability('deployment')
        assert cap is not None
        self.assertEqual(cap.options, [])

    def test_no_legacy_deploys_via_edge_declared(self) -> None:
        # Promote behaviour is inferred from the ref shape and per-env
        # payloads ride on the USES edge (``env_payloads``).  No plugin
        # should declare a leftover ``DEPLOYS_VIA`` edge.
        self.assertFalse(
            any(
                e.name == 'DEPLOYS_VIA'
                for e in GitHubPlugin.manifest.edge_labels
            ),
            'GitHubPlugin still declares DEPLOYS_VIA',
        )

    def test_owner_repo_required(self) -> None:
        plugin = GitHubDeployment()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            integration_options=_connection(),
        )
        with self.assertRaises(ValueError):
            plugin._owner_repo(ctx)

    def test_owner_repo_derived_from_project_link(self) -> None:
        plugin = GitHubDeployment()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            project_links={
                'github-repository': 'https://github.com/octo/demo'
            },
            integration_options=_connection(),
        )
        self.assertEqual(plugin._owner_repo(ctx), ('octo', 'demo'))

    def test_owner_repo_derived_strips_dot_git(self) -> None:
        plugin = GitHubDeployment()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            project_links={
                'github-repository': 'https://github.com/octo/demo.git'
            },
            integration_options=_connection(),
        )
        self.assertEqual(plugin._owner_repo(ctx), ('octo', 'demo'))

    def test_owner_repo_derived_for_ghec_tenant(self) -> None:
        plugin = GitHubDeployment()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            project_links={
                'github-repository': 'https://aweber.ghe.com/apis/account'
            },
            integration_options=_connection('ghec', 'aweber.ghe.com'),
        )
        self.assertEqual(plugin._owner_repo(ctx), ('apis', 'account'))

    def test_owner_repo_ignores_link_for_other_host(self) -> None:
        plugin = GitHubDeployment()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            project_links={
                'gitlab-repository': 'https://gitlab.com/octo/demo'
            },
            integration_options=_connection(),
        )
        with self.assertRaises(ValueError):
            plugin._owner_repo(ctx)

    def test_owner_repo_falls_back_to_project_type(self) -> None:
        plugin = GitHubDeployment()
        ctx = PluginContext(
            project_id='p',
            project_slug='account',
            org_slug='octo',
            project_type_slugs=['apis'],
            integration_options=_connection(),
        )
        self.assertEqual(plugin._owner_repo(ctx), ('apis', 'account'))

    def test_owner_repo_link_wins_over_project_type(self) -> None:
        plugin = GitHubDeployment()
        ctx = PluginContext(
            project_id='p',
            project_slug='account',
            org_slug='octo',
            project_links={
                'github-repository': 'https://github.com/from-link/repo'
            },
            project_type_slugs=['apis'],
            integration_options=_connection(),
        )
        self.assertEqual(plugin._owner_repo(ctx), ('from-link', 'repo'))

    def test_owner_repo_prefers_explicit_repo_link(self) -> None:
        """Explicit ``github-repository`` link key wins over other
        same-host links, even when it appears later in dict order."""
        plugin = GitHubDeployment()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            project_links={
                'docs': 'https://github.com/other-org/other-repo',
                'github-repository': 'https://github.com/correct/repo',
            },
            integration_options=_connection(),
        )
        self.assertEqual(plugin._owner_repo(ctx), ('correct', 'repo'))

    def test_owner_repo_rejects_orgs_path(self) -> None:
        """``github.com/orgs/<org>`` is not a repository URL — fall
        through to the project_type fallback rather than binding to
        ``orgs/<org>``."""
        plugin = GitHubDeployment()
        ctx = PluginContext(
            project_id='p',
            project_slug='account',
            org_slug='octo',
            project_links={'github-org': 'https://github.com/orgs/octo'},
            project_type_slugs=['apis'],
            integration_options=_connection(),
        )
        self.assertEqual(plugin._owner_repo(ctx), ('apis', 'account'))

    def test_owner_repo_rejects_marketplace_path(self) -> None:
        plugin = GitHubDeployment()
        ctx = PluginContext(
            project_id='p',
            project_slug='proj',
            org_slug='octo',
            project_links={
                'marketplace': 'https://github.com/marketplace/actions/checkout'
            },
            integration_options=_connection(),
        )
        with self.assertRaises(ValueError):
            plugin._owner_repo(ctx)

    def test_record_checks_disabled_evicts_expired(self) -> None:
        """``_record_checks_disabled`` must sweep stale entries before
        inserting; otherwise the cache grows unbounded."""
        from imbi.plugins.github import deployment as dep

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
        from imbi.plugins.github import deployment as dep

        original = dict(dep._CHECKS_DISABLED_TOKENS)
        dep._record_checks_disabled({}, 'github.com', 'octo', 'demo')
        self.assertEqual(dep._CHECKS_DISABLED_TOKENS, original)

    def test_bearer_requires_credentials(self) -> None:
        with self.assertRaises(ValueError):
            asyncio.run(GitHubDeployment()._bearer(_ctx(), {}))

    def test_bearer_accepts_token_alias(self) -> None:
        token = asyncio.run(
            GitHubDeployment()._bearer(_ctx(), {'token': 'abc'})
        )
        self.assertEqual(token, 'abc')

    def test_api_base_dot_com(self) -> None:
        plugin = GitHubDeployment()
        self.assertEqual(
            plugin._api_base(_ctx(connection=_connection('github'))),
            'https://api.github.com',
        )

    def test_api_base_ghec(self) -> None:
        plugin = GitHubDeployment()
        self.assertEqual(
            plugin._api_base(
                _ctx(connection=_connection('ghec', 'tenant.ghe.com'))
            ),
            'https://api.tenant.ghe.com',
        )

    def test_api_base_ghes(self) -> None:
        plugin = GitHubDeployment()
        self.assertEqual(
            plugin._api_base(
                _ctx(connection=_connection('ghes', 'github.example.com'))
            ),
            'https://github.example.com/api/v3',
        )

    def test_ghec_rejects_non_tenant_host(self) -> None:
        plugin = GitHubDeployment()
        with self.assertRaises(ValueError):
            plugin._api_base(
                _ctx(connection=_connection('ghec', 'github.example.com'))
            )

    def test_api_base_requires_integration_options(self) -> None:
        plugin = GitHubDeployment()
        with self.assertRaises(ValueError):
            plugin._api_base(_ctx(connection={}))


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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
        with self.assertRaises(ValueError):
            await plugin.trigger_deployment(_ctx(), _CREDS, 'main')

    @respx.mock
    async def test_trigger_uses_environment_config_payload(self) -> None:
        # ``ctx.environment_config`` carries the per-env payload dict
        # (``env_payloads[env_slug]`` from the USES_PLUGIN edge,
        # resolved by the host).  Caller-supplied ``inputs`` layer on
        # top, so a manual override wins on shared keys.
        deploy = respx.post(
            'https://api.github.com/repos/octo/demo/deployments'
        ).mock(return_value=httpx.Response(201, json={'id': 1, 'url': ''}))
        plugin = GitHubDeployment()
        ctx = _ctx(
            environment='production',
            environment_config={
                'cluster': 'prod-east',
                'feature_flag': 'on',
            },
        )
        await plugin.trigger_deployment(
            ctx,
            _CREDS,
            ref_or_sha='v1.2.3',
            inputs={'cluster': 'override', 'extra': 'kept'},
        )
        body = json.loads(deploy.calls.last.request.read())
        self.assertEqual(body['ref'], 'v1.2.3')
        self.assertEqual(body['environment'], 'production')
        self.assertEqual(
            body['payload'],
            {'cluster': 'override', 'feature_flag': 'on', 'extra': 'kept'},
        )


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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
        run = await plugin.get_deployment_status(_ctx(), _CREDS, '42')
        self.assertEqual(run.status, 'cancelled')


class ListRecentDeploymentsTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_app_credentials_mint_installation_token(self) -> None:
        # A service configured with only GitHub App credentials (no acting
        # user, e.g. the headless deployment-resync sweep) must mint an
        # installation token and still backfill deployments.
        from imbi.plugins.github import _app_auth
        from plugins.github.tests.test_commits import _APP_KEY_PEM, _FAR_FUTURE

        _app_auth.reset_cache()
        self.addCleanup(_app_auth.reset_cache)
        token_route = respx.post(
            'https://api.github.com/app/installations/42/access_tokens'
        ).mock(
            return_value=httpx.Response(
                201, json={'token': 'ghs_minted', 'expires_at': _FAR_FUTURE}
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '1'},
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 7,
                        'sha': 'appsha',
                        'ref': 'main',
                        'created_at': '2026-05-13T14:00:00Z',
                    }
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/7/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/main'
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(),
            {
                'app_id': '971',
                'private_key': _APP_KEY_PEM,
                'installation_id': '42',
            },
            ['production'],
        )
        self.assertTrue(token_route.called)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].sha, 'appsha')

    @respx.mock
    async def test_one_env_one_deployment_success(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={
                'environment': 'infrastructure-testing',
                'per_page': '1',
            },
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 123,
                        'sha': '2668cd0abc',
                        'ref': 'main',
                        'created_at': '2026-05-13T14:00:00Z',
                        'description': 'Deploy main',
                        'url': 'https://api.github.com/repos/octo/demo/deployments/123',
                        'creator': {'login': 'octocat', 'id': 583231},
                    }
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/123/statuses'
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'state': 'success',
                        'log_url': 'https://gh/runs/9001',
                        'created_at': '2026-05-13T14:01:00Z',
                    }
                ],
            )
        )
        # ``main`` is a branch, not a release tag -- the release lookup
        # 404s and ``release_notes`` stays ``None``.
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/main'
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['infrastructure-testing']
        )
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertIsNone(event.release_notes)
        self.assertEqual(event.environment, 'infrastructure-testing')
        self.assertEqual(event.sha, '2668cd0abc')
        self.assertEqual(event.ref, 'main')
        self.assertEqual(event.status, 'success')
        self.assertEqual(event.external_run_id, '123')
        self.assertEqual(event.run_url, 'https://gh/runs/9001')
        self.assertEqual(
            event.deployment_url,
            'https://api.github.com/repos/octo/demo/deployments/123',
        )
        # The creator login is kept for display and the numeric id is
        # surfaced as the identity subject so the host can attribute the
        # deploy to an Imbi user.
        self.assertEqual(event.creator, 'octocat')
        self.assertEqual(event.creator_subject, '583231')
        # ``created_at`` must come from the deployment row, not the
        # latest status row (which is one minute later above).
        self.assertEqual(
            event.created_at,
            datetime.datetime(2026, 5, 13, 14, 0, tzinfo=datetime.UTC),
        )

    @respx.mock
    async def test_multiple_envs_fan_out_in_parallel(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '1'},
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 1,
                        'sha': 'prodsha',
                        'ref': 'v1.0.0',
                        'created_at': '2026-05-13T12:00:00Z',
                    }
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'staging', 'per_page': '1'},
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 2,
                        'sha': 'stagesha',
                        'ref': 'main',
                        'created_at': '2026-05-13T13:00:00Z',
                    }
                ],
            )
        )
        # Both deployments resolve to ``pending`` because no statuses
        # have been posted yet.  The empty-statuses case must not be
        # treated as an error.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/1/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/2/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/v1.0.0'
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/main'
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production', 'staging']
        )
        by_env = {e.environment: e for e in events}
        self.assertEqual(by_env['production'].external_run_id, '1')
        self.assertEqual(by_env['staging'].external_run_id, '2')
        self.assertEqual(by_env['production'].status, 'pending')
        self.assertEqual(by_env['staging'].status, 'pending')

    @respx.mock
    async def test_unknown_env_skipped_not_raised(self) -> None:
        # GitHub returns 404 for an environment the repo doesn't know
        # about; resync must keep the partial result rather than fail.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '1'},
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 7,
                        'sha': 'abc',
                        'created_at': '2026-05-13T14:00:00Z',
                    }
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'never-deployed', 'per_page': '1'},
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/7/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production', 'never-deployed']
        )
        self.assertEqual([e.environment for e in events], ['production'])

    @respx.mock
    async def test_inactive_status_maps_to_rolled_back(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 99,
                        'sha': 'old',
                        'created_at': '2026-05-01T00:00:00Z',
                    }
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/99/statuses'
        ).mock(
            return_value=httpx.Response(
                200,
                json=[{'state': 'inactive'}],
            )
        )
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['staging']
        )
        self.assertEqual(events[0].status, 'rolled_back')

    @respx.mock
    async def test_status_history_failure_maps_to_failed(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 5,
                        'sha': 'abc',
                        'created_at': '2026-05-01T00:00:00Z',
                    }
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/5/statuses'
        ).mock(
            return_value=httpx.Response(
                200,
                json=[{'state': 'failure'}, {'state': 'in_progress'}],
            )
        )
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['staging']
        )
        self.assertEqual(events[0].status, 'failed')

    @respx.mock
    async def test_status_fetch_error_degrades_to_pending(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 8,
                        'sha': 'abc',
                        'created_at': '2026-05-01T00:00:00Z',
                    }
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/8/statuses'
        ).mock(return_value=httpx.Response(500, json={'message': 'oops'}))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['staging']
        )
        self.assertEqual(events[0].status, 'pending')
        self.assertIsNone(events[0].run_url)

    @respx.mock
    async def test_deployment_missing_id_skipped(self) -> None:
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {'sha': 'abc'},  # missing id
                    {
                        'id': 11,
                        'sha': 'def',
                        'created_at': '2026-05-13T00:00:00Z',
                    },
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/11/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['staging']
        )
        self.assertEqual([e.external_run_id for e in events], ['11'])

    @respx.mock
    async def test_release_notes_populated_for_tag_ref(self) -> None:
        # A deployment against a release tag carries the release body so
        # the host can persist it as the Release node's notes.
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 42,
                        'sha': 'relsha',
                        'ref': '5.9.0',
                        'created_at': '2026-05-13T14:00:00Z',
                    }
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/42/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/5.9.0'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'tag_name': '5.9.0',
                    'body': "## What's Changed\n- Migrated to servicelib",
                    'published_at': '2026-05-13T13:55:00Z',
                },
            )
        )
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production']
        )
        self.assertEqual(
            events[0].release_notes,
            "## What's Changed\n- Migrated to servicelib",
        )

    @respx.mock
    async def test_release_notes_none_when_body_empty(self) -> None:
        # A release with an empty body yields ``None`` rather than an
        # empty string, matching the "no notes" host semantics.
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 43,
                        'sha': 'relsha2',
                        'ref': '6.0.0',
                        'created_at': '2026-05-13T14:00:00Z',
                    }
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/43/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/6.0.0'
        ).mock(
            return_value=httpx.Response(
                200, json={'tag_name': '6.0.0', 'body': ''}
            )
        )
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production']
        )
        self.assertIsNone(events[0].release_notes)

    @respx.mock
    async def test_release_notes_403_suppresses_further_lookups(self) -> None:
        # A token that can't read releases 403s once; the process-wide
        # cache then short-circuits subsequent lookups (same repo+token)
        # so resync doesn't re-issue the failing request per deployment.
        from imbi.plugins.github.deployment import _RELEASES_FORBIDDEN_TOKENS

        _RELEASES_FORBIDDEN_TOKENS.clear()
        self.addCleanup(_RELEASES_FORBIDDEN_TOKENS.clear)
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 51,
                        'sha': 'sha1',
                        'ref': 'v1.0.0',
                        'created_at': '2026-05-13T14:00:00Z',
                    },
                    {
                        'id': 52,
                        'sha': 'sha2',
                        'ref': 'v2.0.0',
                        'created_at': '2026-05-13T14:05:00Z',
                    },
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/51/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/52/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        # Only the first release lookup is mocked (403).  The second
        # (v2.0.0) is deliberately left unmocked: if the 403 weren't
        # cached, resync would issue it and respx would raise.
        first = respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/v1.0.0'
        ).mock(return_value=httpx.Response(403, json={'message': 'Forbidden'}))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production'], limit=2
        )
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e.release_notes is None for e in events))
        self.assertEqual(first.call_count, 1)


class GetReleaseNotesTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_returns_release_body_for_tag(self) -> None:
        # The tag-keyed enrichment path: the host knows only the tag and
        # asks the plugin for the release body.
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/3.23.4'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'tag_name': '3.23.4',
                    'body': "## What's Changed\n- Fixed the thing",
                },
            )
        )
        plugin = GitHubDeployment()
        notes = await plugin.get_release_notes(_ctx(), _CREDS, '3.23.4')
        self.assertEqual(notes, "## What's Changed\n- Fixed the thing")

    @respx.mock
    async def test_returns_none_when_no_release(self) -> None:
        # A tag without a GitHub release 404s and yields ``None`` so the
        # host never fails a write on a missing release.
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/9.9.9'
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        plugin = GitHubDeployment()
        notes = await plugin.get_release_notes(_ctx(), _CREDS, '9.9.9')
        self.assertIsNone(notes)


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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
        status = await plugin.get_check_status(_ctx(), _CREDS, 'abc')
        self.assertEqual(status, 'fail')

    @respx.mock
    async def test_check_status_404_returns_unknown(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/commits/abc/check-runs'
        ).mock(return_value=httpx.Response(404, json={}))
        plugin = GitHubDeployment()
        status = await plugin.get_check_status(_ctx(), _CREDS, 'abc')
        self.assertEqual(status, 'unknown')

    @respx.mock
    async def test_check_status_network_error_returns_unknown(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/commits/abc/check-runs'
        ).mock(side_effect=httpx.ConnectError('boom'))
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
        with self.assertRaises(PluginAuthenticationFailed):
            await plugin.list_refs(_ctx(), _CREDS, kind='default')

    @respx.mock
    async def test_401_on_deployment_raises_authentication_failed(
        self,
    ) -> None:
        respx.post('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(401, json={'message': 'token expired'})
        )
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
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
        plugin = GitHubDeployment()
        self.assertEqual(await plugin.list_workflows(_ctx(), _CREDS), [])


class RepoRootFromRedirectTestCase(unittest.TestCase):
    def test_strips_subresource_to_repo_root(self) -> None:
        self.assertEqual(
            _repo_root_from_redirect(
                'https://api.github.com/repositories/687046/commits'
            ),
            'https://api.github.com/repositories/687046',
        )

    def test_bare_repo_id(self) -> None:
        self.assertEqual(
            _repo_root_from_redirect(
                'https://api.github.com/repositories/687046'
            ),
            'https://api.github.com/repositories/687046',
        )

    def test_returns_none_without_repositories_segment(self) -> None:
        self.assertIsNone(
            _repo_root_from_redirect('https://api.github.com/repos/o/r')
        )

    def test_returns_none_when_id_missing(self) -> None:
        self.assertIsNone(
            _repo_root_from_redirect('https://api.github.com/repositories')
        )


class RepoRenameRelocationTestCase(unittest.IsolatedAsyncioTestCase):
    """A repo renamed outside Imbi: GitHub 301s the stale path to the
    by-id form.  The client follows it (request succeeds) and reports the
    new name on ``ctx`` so the host can self-heal the stored link.
    """

    @staticmethod
    def _mock_rename() -> None:
        # Stale repo-path call 301s to the canonical /repositories/{id}.
        respx.get('https://api.github.com/repos/octo/demo/commits').mock(
            return_value=httpx.Response(
                301,
                headers={
                    'location': (
                        'https://api.github.com/repositories/123/commits'
                    )
                },
            )
        )
        respx.get('https://api.github.com/repositories/123/commits').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'sha': 'abc',
                        'commit': {
                            'message': 'msg',
                            'author': {'name': 'X', 'date': None},
                        },
                    }
                ],
            )
        )
        # Head-commit CI hydration follows the same redirect.
        respx.get(
            'https://api.github.com/repos/octo/demo/commits/abc/check-runs'
        ).mock(
            return_value=httpx.Response(
                301,
                headers={
                    'location': (
                        'https://api.github.com/repositories/123'
                        '/commits/abc/check-runs'
                    )
                },
            )
        )
        respx.get(
            'https://api.github.com/repositories/123/commits/abc/check-runs'
        ).mock(return_value=httpx.Response(200, json={'check_runs': []}))

    @respx.mock
    async def test_list_commits_follows_rename_and_reports_relocation(
        self,
    ) -> None:
        self._mock_rename()
        respx.get('https://api.github.com/repositories/123').mock(
            return_value=httpx.Response(
                200,
                json={
                    'full_name': 'octo/renamed',
                    'html_url': 'https://github.com/octo/renamed',
                },
            )
        )
        ctx = _ctx()
        plugin = GitHubDeployment()
        commits = await plugin.list_commits(ctx, _CREDS, ref='main')
        # The user-facing request still succeeds via the followed redirect.
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0].sha, 'abc')
        # ...and the rename is reported for the host to self-heal.
        reloc = ctx.link_writeback
        assert reloc is not None
        self.assertEqual(reloc.link_key, 'github-repository')
        self.assertEqual(reloc.new_url, 'https://github.com/octo/renamed')
        self.assertEqual(reloc.old_owner_repo, 'octo/demo')
        self.assertEqual(reloc.new_owner_repo, 'octo/renamed')

    @respx.mock
    async def test_no_relocation_when_repo_not_renamed(self) -> None:
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
                    }
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/commits/abc/check-runs'
        ).mock(return_value=httpx.Response(200, json={'check_runs': []}))
        ctx = _ctx()
        plugin = GitHubDeployment()
        await plugin.list_commits(ctx, _CREDS, ref='main')
        self.assertIsNone(ctx.link_writeback)

    @respx.mock
    async def test_no_relocation_when_repo_root_unresolvable(self) -> None:
        self._mock_rename()
        # Repo-root resolution fails -> best-effort, no relocation recorded.
        respx.get('https://api.github.com/repositories/123').mock(
            return_value=httpx.Response(404)
        )
        ctx = _ctx()
        plugin = GitHubDeployment()
        commits = await plugin.list_commits(ctx, _CREDS, ref='main')
        self.assertEqual(len(commits), 1)
        self.assertIsNone(ctx.link_writeback)

    @respx.mock
    async def test_no_relocation_when_name_unchanged(self) -> None:
        self._mock_rename()
        # Redirect happened but full_name matches the stored owner/repo
        # (e.g. a transient by-id redirect) -> nothing to heal.
        respx.get('https://api.github.com/repositories/123').mock(
            return_value=httpx.Response(
                200,
                json={
                    'full_name': 'octo/demo',
                    'html_url': 'https://github.com/octo/demo',
                },
            )
        )
        ctx = _ctx()
        plugin = GitHubDeployment()
        await plugin.list_commits(ctx, _CREDS, ref='main')
        self.assertIsNone(ctx.link_writeback)
