"""Smoke tests for the GitHub deployment capability handler."""

import asyncio
import base64
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
    _active_scan_limit,
    _artifact_status,
    _mainline_branches,
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


def _deployment(deployment_id: int, created_at: str) -> dict[str, object]:
    """A minimal ``GET /deployments`` row deploying a mainline branch."""
    return {
        'id': deployment_id,
        'sha': f'sha{deployment_id}',
        'ref': 'main',
        'created_at': created_at,
    }


def _statuses(*states: str) -> None:
    """Mock ``/deployments/{id}/statuses`` for ids 1..len(states)."""
    for offset, state in enumerate(states, start=1):
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/'
            f'{offset}/statuses'
        ).mock(return_value=httpx.Response(200, json=[{'state': state}]))


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

    def test_no_host_capability_option_declared(self) -> None:
        # The host now comes from the Integration's flavor/host options,
        # never from a per-capability ``host`` option.  Other capability
        # options (artifact creation) are fine.
        cap = GitHubPlugin.manifest.get_capability('deployment')
        assert cap is not None
        self.assertNotIn('host', {opt.name for opt in cap.options})

    def test_declares_artifact_workflow_options(self) -> None:
        cap = GitHubPlugin.manifest.get_capability('deployment')
        assert cap is not None
        options = {opt.name: opt for opt in cap.options}
        self.assertIn('artifact_workflow', options)
        # Optional: projects that build artifacts outside Imbi promote
        # against an artifact that already exists.
        self.assertFalse(options['artifact_workflow'].required)
        self.assertEqual(options['artifact_version_input'].default, 'version')

    def test_mainline_branches_declared_integration_level(self) -> None:
        # Mainline branch naming is a property of the org's repos, not of
        # one capability, and ``capability_options`` only ever reach their
        # own capability -- so it has to sit beside flavor/host where every
        # capability can read it off ``ctx.integration_options``.
        options = {opt.name: opt for opt in GitHubPlugin.manifest.options}
        self.assertIn('mainline_branches', options)
        self.assertEqual(options['mainline_branches'].default, 'main master')
        self.assertFalse(options['mainline_branches'].required)
        cap = GitHubPlugin.manifest.get_capability('deployment')
        assert cap is not None
        self.assertNotIn(
            'mainline_branches', {opt.name for opt in cap.options}
        )

    def test_active_scan_limit_declared_integration_level(self) -> None:
        # Scan depth follows the org's deploy habits, like mainline
        # branch naming, so it sits beside flavor/host on the Integration.
        options = {opt.name: opt for opt in GitHubPlugin.manifest.options}
        self.assertIn('active_scan_limit', options)
        self.assertEqual(options['active_scan_limit'].default, 10)
        self.assertFalse(options['active_scan_limit'].required)

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

    @respx.mock
    async def test_compare_splits_subject_from_body(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/compare/base...head'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'commits': [
                        {
                            'sha': 'c1',
                            'commit': {
                                'message': 'Add widgets (#8)\n\n## Summary\n'
                                'Adds the widget endpoint.\n',
                                'author': {'name': 'A', 'date': None},
                            },
                        },
                        {
                            'sha': 'c2',
                            'commit': {
                                'message': 'Subject only',
                                'author': {'name': 'A', 'date': None},
                            },
                        },
                    ],
                },
            )
        )
        plugin = GitHubDeployment()
        result = await plugin.compare(_ctx(), _CREDS, 'base', 'head')
        self.assertEqual(result.commits[0].message, 'Add widgets (#8)')
        self.assertEqual(
            result.commits[0].body,
            '## Summary\nAdds the widget endpoint.',
        )
        self.assertEqual(result.commits[1].message, 'Subject only')
        self.assertIsNone(result.commits[1].body)


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
    async def test_status_skips_inactive_to_the_real_outcome(self) -> None:
        """``inactive`` hides the success it was written on top of.

        GitHub stamps ``inactive`` on a deployment when a *later* one
        supersedes it, so it is newest-first but describes the wrong
        rollout.  Reading it as the answer relabelled a succeeded
        deployment as cancelled -> failed, and -- worse -- carried the
        successor's ``updated_at`` as this deployment's completion, so
        the close-out sorted after the release that replaced it.
        """
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/42/statuses'
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'state': 'inactive',
                        'created_at': '2026-08-14T19:51:26Z',
                        'updated_at': '2026-08-14T19:51:26Z',
                        'log_url': 'https://gh/runs/stale',
                    },
                    {
                        'state': 'success',
                        'created_at': '2026-08-03T19:03:32Z',
                        'updated_at': '2026-08-03T19:03:32Z',
                        'log_url': 'https://gh/runs/real',
                    },
                    {'state': 'in_progress'},
                ],
            )
        )
        plugin = GitHubDeployment()
        run = await plugin.get_deployment_status(_ctx(), _CREDS, '42')
        self.assertEqual(run.status, 'success')
        self.assertEqual(run.run_url, 'https://gh/runs/real')
        assert run.completed_at is not None
        self.assertEqual(
            datetime.datetime(2026, 8, 3, 19, 3, 32, tzinfo=datetime.UTC),
            run.completed_at,
        )

    @respx.mock
    async def test_status_only_inactive_reads_as_queued(self) -> None:
        # Superseded without ever reporting on itself: there is no
        # outcome to read, so it stays unresolved and the sweeper
        # expires it on age rather than inventing a terminal status.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/42/statuses'
        ).mock(return_value=httpx.Response(200, json=[{'state': 'inactive'}]))
        plugin = GitHubDeployment()
        run = await plugin.get_deployment_status(_ctx(), _CREDS, '42')
        self.assertEqual(run.status, 'queued')
        self.assertIsNone(run.completed_at)


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
    async def test_resync_skips_inactive_to_the_real_outcome(self) -> None:
        """Resync must not relabel deployment history as rolled_back.

        Every deployment except an environment's newest carries an
        ``inactive`` status, written when its successor went live.
        Reading the newest entry verbatim turned each of them into
        ``rolled_back``, overwriting the ``success`` directly beneath
        it -- ~14k nodes in the production graph, whose ``history``
        records the success-then-rolled_back flip.
        """
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '1'},
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 55,
                        'sha': 'deadbeef',
                        'ref': 'main',
                        'created_at': '2026-05-13T14:00:00Z',
                    }
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/55/statuses'
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'state': 'inactive',
                        'created_at': '2026-05-20T09:00:00Z',
                        'log_url': 'https://gh/runs/successor',
                    },
                    {
                        'state': 'success',
                        'created_at': '2026-05-13T14:01:00Z',
                        'log_url': 'https://gh/runs/real',
                    },
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/main'
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production']
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, 'success')
        self.assertEqual(events[0].run_url, 'https://gh/runs/real')

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

    @respx.mock
    async def test_branch_refs_never_reach_the_releases_api(self) -> None:
        # A repo that deploys off its default branch reports ``ref ==
        # 'main'``/``'master'``, which can never name a release.  Neither
        # release route is mocked: if the lookup were attempted at all,
        # respx would raise on the unmatched request.
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 61,
                        'sha': 'sha1',
                        'ref': 'main',
                        'created_at': '2026-05-13T14:00:00Z',
                    },
                    {
                        'id': 62,
                        'sha': 'sha2',
                        'ref': 'master',
                        'created_at': '2026-05-13T14:05:00Z',
                    },
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/61/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/62/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production'], limit=2
        )
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e.release_notes is None for e in events))

    @respx.mock
    async def test_configured_mainline_branches_retarget_the_guard(
        self,
    ) -> None:
        # An org that deploys off ``develop`` configures it, which both
        # suppresses the doomed ``develop`` lookup and re-enables the
        # ``main`` one: the option replaces the default set, it doesn't
        # extend it.  Only the ``main`` route is mocked, so respx raises
        # if ``develop`` is looked up after all.
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 91,
                        'sha': 'sha1',
                        'ref': 'develop',
                        'created_at': '2026-05-13T14:00:00Z',
                    },
                    {
                        'id': 92,
                        'sha': 'sha2',
                        'ref': 'main',
                        'created_at': '2026-05-13T14:05:00Z',
                    },
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/91/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/92/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        on_main = respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/main'
        ).mock(
            return_value=httpx.Response(
                200, json={'tag_name': 'main', 'body': 'notes from main'}
            )
        )
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(
                connection={
                    'flavor': 'github',
                    'mainline_branches': 'develop',
                }
            ),
            _CREDS,
            ['production'],
            limit=2,
        )
        by_ref = {e.ref: e for e in events}
        self.assertIsNone(by_ref['develop'].release_notes)
        self.assertEqual(by_ref['main'].release_notes, 'notes from main')
        self.assertEqual(on_main.call_count, 1)

    @respx.mock
    async def test_release_404_looked_up_once_per_sweep(self) -> None:
        # Deployments sharing a tagless ref must pay for the miss once,
        # not once per row -- and the memo is scoped to a single sweep,
        # so a second call re-checks (a release may have been cut since).
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 71,
                        'sha': 'sha1',
                        'ref': 'release-candidate',
                        'created_at': '2026-05-13T14:00:00Z',
                    },
                    {
                        'id': 72,
                        'sha': 'sha2',
                        'ref': 'release-candidate',
                        'created_at': '2026-05-13T14:05:00Z',
                    },
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/71/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/72/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        lookup = respx.get(
            'https://api.github.com/repos/octo/demo/releases/'
            'tags/release-candidate'
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production'], limit=2
        )
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e.release_notes is None for e in events))
        self.assertEqual(lookup.call_count, 1)
        await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production'], limit=2
        )
        self.assertEqual(lookup.call_count, 2)

    @respx.mock
    async def test_release_410_cached_like_404(self) -> None:
        # GitHub answers 410 Gone for a resource that's been disabled;
        # treat it as a miss and suppress the repeat like a 404.
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 81,
                        'sha': 'sha1',
                        'ref': 'v3.0.0',
                        'created_at': '2026-05-13T14:00:00Z',
                    },
                    {
                        'id': 82,
                        'sha': 'sha2',
                        'ref': 'v3.0.0',
                        'created_at': '2026-05-13T14:05:00Z',
                    },
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/81/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/82/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        lookup = respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/v3.0.0'
        ).mock(return_value=httpx.Response(410, json={'message': 'Gone'}))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production'], limit=2
        )
        self.assertTrue(all(e.release_notes is None for e in events))
        self.assertEqual(lookup.call_count, 1)

    @respx.mock
    async def test_release_404_coalesced_across_environments(self) -> None:
        # The per-env fan-out is concurrent, so a memo of *results* would
        # let every env past the check before the first response landed --
        # exactly the shape at the host's default limit=1, where no single
        # env repeats a ref and cross-env sharing is the only sharing
        # there is. Two envs on one tagless ref must cost one lookup.
        def _deployments(request: httpx.Request) -> httpx.Response:
            deployment_id = {'staging': 61, 'production': 62}[
                request.url.params['environment']
            ]
            return httpx.Response(
                200,
                json=[
                    {
                        'id': deployment_id,
                        'sha': f'sha{deployment_id}',
                        'ref': 'release-candidate',
                        'created_at': '2026-05-13T14:00:00Z',
                    }
                ],
            )

        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            side_effect=_deployments
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/61/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/62/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))

        async def _missing_release(request: httpx.Request) -> httpx.Response:
            # Yield the way a real request does, so the second env gets a
            # turn while the first one is still in flight.
            await asyncio.sleep(0)
            return httpx.Response(404, json={'message': 'Not Found'})

        lookup = respx.get(
            'https://api.github.com/repos/octo/demo/releases/'
            'tags/release-candidate'
        ).mock(side_effect=_missing_release)
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['staging', 'production'], limit=1
        )
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e.release_notes is None for e in events))
        self.assertEqual(lookup.call_count, 1)

    @respx.mock
    async def test_bot_creator_attributed_to_triggering_actor(self) -> None:
        # A workflow-created deployment lists the app bot as creator; the
        # status URL points at the Actions run, so attribution follows to
        # the run's triggering actor (the human who started it).
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 123,
                        'sha': 'botsha',
                        'ref': 'main',
                        'created_at': '2026-05-13T14:00:00Z',
                        'creator': {
                            'login': 'deployer[bot]',
                            'id': 111,
                            'type': 'Bot',
                        },
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
                        'log_url': (
                            'https://github.com/octo/demo'
                            '/actions/runs/9001/job/55'
                        ),
                        'created_at': '2026-05-13T14:01:00Z',
                    }
                ],
            )
        )
        run = respx.get(
            'https://api.github.com/repos/octo/demo/actions/runs/9001'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'triggering_actor': {'login': 'octocat', 'id': 583231},
                    'actor': {'login': 'someone-else', 'id': 42},
                },
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/main'
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production']
        )
        self.assertEqual(len(events), 1)
        self.assertTrue(run.called)
        self.assertEqual(events[0].creator, 'octocat')
        self.assertEqual(events[0].creator_subject, '583231')

    @respx.mock
    async def test_bot_detection_is_case_insensitive(self) -> None:
        # Bot detection must not depend on GitHub's casing: a creator
        # with type 'bot' and a mixed-case '[Bot]' login suffix is still
        # re-attributed to the run's triggering actor.
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 123,
                        'sha': 'botsha',
                        'ref': 'main',
                        'created_at': '2026-05-13T14:00:00Z',
                        'creator': {
                            'login': 'Deployer[Bot]',
                            'id': 111,
                            'type': 'bot',
                        },
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
                        'log_url': (
                            'https://github.com/octo/demo'
                            '/actions/runs/9001/job/55'
                        ),
                        'created_at': '2026-05-13T14:01:00Z',
                    }
                ],
            )
        )
        run = respx.get(
            'https://api.github.com/repos/octo/demo/actions/runs/9001'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'triggering_actor': {'login': 'octocat', 'id': 583231},
                },
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/main'
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production']
        )
        self.assertEqual(len(events), 1)
        self.assertTrue(run.called)
        self.assertEqual(events[0].creator, 'octocat')
        self.assertEqual(events[0].creator_subject, '583231')

    @respx.mock
    async def test_bot_creator_kept_when_run_fetch_fails(self) -> None:
        # The run lookup 500s; attribution degrades gracefully to the bot
        # creator rather than raising and failing the resync.
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 123,
                        'sha': 'botsha',
                        'ref': 'main',
                        'created_at': '2026-05-13T14:00:00Z',
                        'creator': {
                            'login': 'github-actions[bot]',
                            'id': 111,
                        },
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
                        'target_url': (
                            'https://github.com/octo/demo/actions/runs/9001'
                        ),
                        'created_at': '2026-05-13T14:01:00Z',
                    }
                ],
            )
        )
        run = respx.get(
            'https://api.github.com/repos/octo/demo/actions/runs/9001'
        ).mock(return_value=httpx.Response(500, json={'message': 'oops'}))
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/main'
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production']
        )
        self.assertEqual(len(events), 1)
        self.assertTrue(run.called)
        self.assertEqual(events[0].creator, 'github-actions[bot]')
        self.assertEqual(events[0].creator_subject, '111')

    @respx.mock
    async def test_human_creator_skips_run_lookup(self) -> None:
        # A human-created deployment must never issue the extra run
        # fetch; the creator is used as-is.
        respx.get('https://api.github.com/repos/octo/demo/deployments').mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        'id': 123,
                        'sha': 'humansha',
                        'ref': 'main',
                        'created_at': '2026-05-13T14:00:00Z',
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
                        'log_url': (
                            'https://github.com/octo/demo/actions/runs/9001'
                        ),
                        'created_at': '2026-05-13T14:01:00Z',
                    }
                ],
            )
        )
        run = respx.get(
            'https://api.github.com/repos/octo/demo/actions/runs/9001'
        ).mock(return_value=httpx.Response(200, json={}))
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/main'
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        plugin = GitHubDeployment()
        events = await plugin.list_recent_deployments(
            _ctx(), _CREDS, ['production']
        )
        self.assertEqual(len(events), 1)
        self.assertFalse(run.called)
        self.assertEqual(events[0].creator, 'octocat')
        self.assertEqual(events[0].creator_subject, '583231')


class GetEnvironmentStateTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_newest_success_is_active(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(
            return_value=httpx.Response(
                200, json=[_deployment(1, '2026-05-13T14:00:00Z')]
            )
        )
        _statuses('success')
        plugin = GitHubDeployment()
        states = await plugin.get_environment_state(
            _ctx(), _CREDS, ['production']
        )
        self.assertEqual(len(states), 1)
        state = states[0]
        self.assertEqual(state.active_resolution, 'found')
        assert state.active is not None
        assert state.latest is not None
        self.assertEqual(state.active.external_run_id, '1')
        # The newest attempt is also the active one here, and both carry
        # the same ``RemoteDeployment`` shape resync records.
        self.assertEqual(state.latest.external_run_id, '1')
        self.assertEqual(state.active.status, 'success')

    @respx.mock
    async def test_newest_failed_older_success_stays_active(self) -> None:
        # The original bug: the newest attempt failed, so the deployment
        # actually serving the environment is the older success.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    _deployment(1, '2026-05-13T15:00:00Z'),
                    _deployment(2, '2026-05-13T14:00:00Z'),
                ],
            )
        )
        _statuses('failure', 'success')
        plugin = GitHubDeployment()
        state = (
            await plugin.get_environment_state(_ctx(), _CREDS, ['production'])
        )[0]
        self.assertEqual(state.active_resolution, 'found')
        assert state.active is not None
        assert state.latest is not None
        self.assertEqual(state.active.external_run_id, '2')
        self.assertEqual(state.latest.external_run_id, '1')
        self.assertEqual(state.latest.status, 'failed')

    @respx.mock
    async def test_newest_pending_older_success_stays_active(self) -> None:
        # An in-flight deploy is activity, not currency: the older
        # success is still what serves traffic.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    _deployment(1, '2026-05-13T15:00:00Z'),
                    _deployment(2, '2026-05-13T14:00:00Z'),
                ],
            )
        )
        _statuses('in_progress', 'success')
        plugin = GitHubDeployment()
        state = (
            await plugin.get_environment_state(_ctx(), _CREDS, ['production'])
        )[0]
        self.assertEqual(state.active_resolution, 'found')
        assert state.active is not None
        assert state.latest is not None
        self.assertEqual(state.active.external_run_id, '2')
        self.assertEqual(state.latest.status, 'in_progress')

    @respx.mock
    async def test_retired_success_is_not_active(self) -> None:
        # GitHub wrote ``inactive`` on top of the success, so nothing is
        # serving this environment any more.  ``status`` still reads
        # ``success`` -- the rollout did succeed -- which is exactly why
        # the scan cannot answer from ``status`` alone.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(
            return_value=httpx.Response(
                200, json=[_deployment(1, '2026-05-13T14:00:00Z')]
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/1/statuses'
        ).mock(
            return_value=httpx.Response(
                200, json=[{'state': 'inactive'}, {'state': 'success'}]
            )
        )
        plugin = GitHubDeployment()
        state = (
            await plugin.get_environment_state(_ctx(), _CREDS, ['production'])
        )[0]
        self.assertEqual(state.active_resolution, 'none')
        self.assertIsNone(state.active)
        assert state.latest is not None
        self.assertEqual(state.latest.status, 'success')
        self.assertTrue(state.latest.superseded)

    @respx.mock
    async def test_scan_walks_past_a_retired_success(self) -> None:
        # The newest deployment was retired; the one below it is what
        # the environment is actually serving.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    _deployment(1, '2026-05-13T15:00:00Z'),
                    _deployment(2, '2026-05-13T14:00:00Z'),
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/1/statuses'
        ).mock(
            return_value=httpx.Response(
                200, json=[{'state': 'inactive'}, {'state': 'success'}]
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/2/statuses'
        ).mock(return_value=httpx.Response(200, json=[{'state': 'success'}]))
        plugin = GitHubDeployment()
        state = (
            await plugin.get_environment_state(_ctx(), _CREDS, ['production'])
        )[0]
        self.assertEqual(state.active_resolution, 'found')
        assert state.active is not None
        self.assertEqual(state.active.external_run_id, '2')
        self.assertFalse(state.active.superseded)
        assert state.latest is not None
        self.assertEqual(state.latest.external_run_id, '1')

    @respx.mock
    async def test_scan_cap_reached_is_unknown_never_none(self) -> None:
        # A full page with no success means an older active deployment
        # may sit just past the cap — reporting 'none' would have the
        # host clear a pointer that is right.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '2'},
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    _deployment(1, '2026-05-13T15:00:00Z'),
                    _deployment(2, '2026-05-13T14:00:00Z'),
                ],
            )
        )
        _statuses('failure', 'failure')
        plugin = GitHubDeployment()
        ctx = _ctx(connection=_connection() | {'active_scan_limit': 2})
        state = (
            await plugin.get_environment_state(ctx, _CREDS, ['production'])
        )[0]
        self.assertEqual(state.active_resolution, 'unknown')
        self.assertIsNone(state.active)
        assert state.latest is not None
        self.assertEqual(state.latest.external_run_id, '1')

    @respx.mock
    async def test_no_deployments_is_unknown_not_none(self) -> None:
        # GitHub answers 200 with ``[]`` both for an environment nothing
        # has deployed to and for an environment name it has never heard
        # of -- and local slugs reach it unmapped, so a project whose
        # slug is 'prod' against a remote 'production' looks identical to
        # an empty environment.  ``none`` clears the pointer, so an empty
        # listing must not earn it.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(return_value=httpx.Response(200, json=[]))
        plugin = GitHubDeployment()
        state = (
            await plugin.get_environment_state(_ctx(), _CREDS, ['production'])
        )[0]
        self.assertEqual(state.active_resolution, 'unknown')
        self.assertIsNone(state.active)
        self.assertIsNone(state.latest)

    @respx.mock
    async def test_short_page_without_success_is_none(self) -> None:
        # Fewer rows than the cap means the history is exhausted, so
        # "nothing is deployed" is a real answer.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(
            return_value=httpx.Response(
                200, json=[_deployment(1, '2026-05-13T15:00:00Z')]
            )
        )
        _statuses('failure')
        plugin = GitHubDeployment()
        state = (
            await plugin.get_environment_state(_ctx(), _CREDS, ['production'])
        )[0]
        self.assertEqual(state.active_resolution, 'none')
        self.assertIsNone(state.active)
        assert state.latest is not None
        self.assertEqual(state.latest.status, 'failed')

    @respx.mock
    async def test_provider_failure_is_error_not_none(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(
            return_value=httpx.Response(503, json={'message': 'unavailable'})
        )
        plugin = GitHubDeployment()
        state = (
            await plugin.get_environment_state(_ctx(), _CREDS, ['production'])
        )[0]
        self.assertEqual(state.active_resolution, 'error')
        self.assertIsNone(state.active)
        self.assertIsNone(state.latest)

    @respx.mock
    async def test_a_404_listing_is_error_not_none(self) -> None:
        # NOT ``none``, unlike ``list_recent_deployments``: here ``none``
        # authorizes clearing the pointer, and a 404 is what a renamed or
        # transferred repo -- or a token that lost access -- answers.  An
        # unknown *environment* is a 200 with an empty list.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(
            return_value=httpx.Response(
                200, json=[_deployment(1, '2026-05-13T15:00:00Z')]
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'never-deployed', 'per_page': '10'},
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        _statuses('success')
        plugin = GitHubDeployment()
        with self.assertLogs('imbi.plugins.github', level='WARNING'):
            states = await plugin.get_environment_state(
                _ctx(), _CREDS, ['production', 'never-deployed']
            )
        by_env = {s.environment: s for s in states}
        self.assertEqual(by_env['production'].active_resolution, 'found')
        missing = by_env['never-deployed']
        self.assertEqual(missing.active_resolution, 'error')
        self.assertIsNone(missing.active)
        self.assertIsNone(missing.latest)

    @respx.mock
    async def test_an_unread_status_is_error_not_none(self) -> None:
        # A throttled scan reads every status as the ``pending``
        # fallback.  Answering ``none`` there would clear a pointer that
        # is right, on every environment of the project at once.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(
            return_value=httpx.Response(
                200, json=[_deployment(1, '2026-05-13T15:00:00Z')]
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/1/statuses'
        ).mock(
            return_value=httpx.Response(
                403, json={'message': 'API rate limit exceeded'}
            )
        )
        plugin = GitHubDeployment()
        with self.assertLogs('imbi.plugins.github', level='WARNING'):
            state = (
                await plugin.get_environment_state(
                    _ctx(), _CREDS, ['production']
                )
            )[0]
        self.assertEqual(state.active_resolution, 'error')
        self.assertIsNone(state.active)
        assert state.latest is not None
        self.assertTrue(state.latest.status_unknown)

    @respx.mock
    async def test_a_success_above_an_unread_status_still_answers(
        self,
    ) -> None:
        # The walk stops at the first live success, so rows it never
        # reached cannot outrank it -- reading them is not required.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    _deployment(1, '2026-05-13T15:00:00Z'),
                    _deployment(2, '2026-05-13T14:00:00Z'),
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/1/statuses'
        ).mock(return_value=httpx.Response(200, json=[{'state': 'success'}]))
        unread = respx.get(
            'https://api.github.com/repos/octo/demo/deployments/2/statuses'
        ).mock(return_value=httpx.Response(500))
        plugin = GitHubDeployment()
        state = (
            await plugin.get_environment_state(_ctx(), _CREDS, ['production'])
        )[0]
        self.assertEqual(state.active_resolution, 'found')
        assert state.active is not None
        self.assertEqual(state.active.external_run_id, '1')
        self.assertFalse(unread.called)

    @respx.mock
    async def test_an_unread_row_above_a_success_is_error(self) -> None:
        # The mirror of the test above, and the case that matters: the
        # unread row is NEWER than the success.  The walk stops at the
        # first clean success, so anything it could not read sits above
        # that success and may be the deployment actually serving the
        # environment.  Answering ``found`` here would name the older
        # release as current and have the host write a stale pointer.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    _deployment(1, '2026-05-13T15:00:00Z'),
                    _deployment(2, '2026-05-13T14:00:00Z'),
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/1/statuses'
        ).mock(
            return_value=httpx.Response(
                403, json={'message': 'API rate limit exceeded'}
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/2/statuses'
        ).mock(return_value=httpx.Response(200, json=[{'state': 'success'}]))
        plugin = GitHubDeployment()
        with self.assertLogs('imbi.plugins.github', level='WARNING'):
            state = (
                await plugin.get_environment_state(
                    _ctx(), _CREDS, ['production']
                )
            )[0]
        self.assertEqual(state.active_resolution, 'error')
        self.assertIsNone(state.active)
        # ``latest`` still reports the newest attempt, unread status and
        # all -- it is activity, never currency.
        assert state.latest is not None
        self.assertEqual(state.latest.external_run_id, '1')
        self.assertTrue(state.latest.status_unknown)

    @respx.mock
    async def test_a_malformed_row_above_a_success_is_error(self) -> None:
        # A row too malformed to identify is just as unreadable as one
        # whose status would not load, and it is newer than the success
        # below it.  Skipping it silently would report that success as
        # active.
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {'id': None, 'sha': None, 'created_at': None},
                    _deployment(2, '2026-05-13T14:00:00Z'),
                ],
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/2/statuses'
        ).mock(return_value=httpx.Response(200, json=[{'state': 'success'}]))
        plugin = GitHubDeployment()
        with self.assertLogs('imbi.plugins.github', level='WARNING'):
            state = (
                await plugin.get_environment_state(
                    _ctx(), _CREDS, ['production']
                )
            )[0]
        self.assertEqual(state.active_resolution, 'error')
        self.assertIsNone(state.active)
        # The malformed row cannot be reported at all, so ``latest``
        # names the readable success below it even though nothing is
        # claimed active.  That pairing is the surprising part of the
        # contract, so pin it.
        assert state.latest is not None
        self.assertEqual(state.latest.external_run_id, '2')

    @respx.mock
    async def test_an_empty_status_list_is_not_unread(self) -> None:
        # Read fine, nothing posted yet: that is a real ``pending``, and
        # an exhausted page of them is a real "nothing deployed".
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments',
            params={'environment': 'production', 'per_page': '10'},
        ).mock(
            return_value=httpx.Response(
                200, json=[_deployment(1, '2026-05-13T15:00:00Z')]
            )
        )
        respx.get(
            'https://api.github.com/repos/octo/demo/deployments/1/statuses'
        ).mock(return_value=httpx.Response(200, json=[]))
        plugin = GitHubDeployment()
        state = (
            await plugin.get_environment_state(_ctx(), _CREDS, ['production'])
        )[0]
        self.assertEqual(state.active_resolution, 'none')
        assert state.latest is not None
        self.assertFalse(state.latest.status_unknown)


class ActiveScanLimitTestCase(unittest.TestCase):
    def test_absent_option_uses_default(self) -> None:
        self.assertEqual(_active_scan_limit({}), 10)

    def test_string_option_parsed(self) -> None:
        # The admin form hands scalar options back as strings.
        self.assertEqual(_active_scan_limit({'active_scan_limit': '25'}), 25)

    def test_invalid_or_out_of_range_values_fall_back(self) -> None:
        self.assertEqual(_active_scan_limit({'active_scan_limit': 'ten'}), 10)
        self.assertEqual(_active_scan_limit({'active_scan_limit': 0}), 10)
        self.assertEqual(_active_scan_limit({'active_scan_limit': True}), 10)
        # One GitHub page is the ceiling.
        self.assertEqual(_active_scan_limit({'active_scan_limit': 500}), 100)


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

    @respx.mock
    async def test_get_release_carries_the_remote_author(self) -> None:
        # Attribution comes from GitHub: the login it credits with the
        # release, plus the numeric id the host resolves to an Imbi user.
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/3.23.4'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'tag_name': '3.23.4',
                    'name': 'Release 3.23.4',
                    'body': '## Fixed\n- the thing',
                    'html_url': 'https://github.com/octo/demo/releases/3.23.4',
                    'published_at': '2026-07-29T12:00:00Z',
                    'author': {'login': 'octocat', 'id': 583231},
                },
            )
        )
        plugin = GitHubDeployment()
        release = await plugin.get_release(_ctx(), _CREDS, '3.23.4')
        assert release is not None
        self.assertEqual('octocat', release.author)
        self.assertEqual('583231', release.author_subject)
        self.assertEqual('Release 3.23.4', release.name)
        self.assertEqual('## Fixed\n- the thing', release.body_markdown)
        self.assertEqual(
            'https://github.com/octo/demo/releases/3.23.4', release.html_url
        )
        self.assertEqual(
            datetime.datetime(2026, 7, 29, 12, 0, tzinfo=datetime.UTC),
            release.published_at,
        )

    @respx.mock
    async def test_get_release_returns_none_when_no_release(self) -> None:
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/9.9.9'
        ).mock(return_value=httpx.Response(404, json={'message': 'Not Found'}))
        plugin = GitHubDeployment()
        self.assertIsNone(await plugin.get_release(_ctx(), _CREDS, '9.9.9'))

    @respx.mock
    async def test_get_release_tolerates_a_missing_author(self) -> None:
        # A release with no author (a tag-only release, or a deleted
        # account) still yields its body rather than failing the lookup.
        respx.get(
            'https://api.github.com/repos/octo/demo/releases/tags/1.0.0'
        ).mock(
            return_value=httpx.Response(
                200, json={'tag_name': '1.0.0', 'body': 'notes'}
            )
        )
        plugin = GitHubDeployment()
        release = await plugin.get_release(_ctx(), _CREDS, '1.0.0')
        assert release is not None
        self.assertIsNone(release.author)
        self.assertIsNone(release.author_subject)
        self.assertEqual('notes', release.body_markdown)


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


_DISPATCH_URL = (
    'https://api.github.com/repos/octo/demo/actions/workflows/'
    'release.yml/dispatches'
)


def _artifact_ctx(
    options: dict[str, object] | None = None,
) -> PluginContext:
    return _ctx(
        options={'artifact_workflow': 'release.yml', **(options or {})}
    )


class CreateDeploymentArtifactTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_dispatch_returns_run_id_on_200(self) -> None:
        dispatch = respx.post(_DISPATCH_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    'workflow_run_id': 4242,
                    'run_url': (
                        'https://api.github.com/repos/octo/demo/'
                        'actions/runs/4242'
                    ),
                    'html_url': (
                        'https://github.com/octo/demo/actions/runs/4242'
                    ),
                },
            )
        )
        plugin = GitHubDeployment()
        run = await plugin.create_deployment_artifact(
            _artifact_ctx(), _CREDS, ref='main', version='2.23.0'
        )
        self.assertEqual(run.run_id, '4242')
        # ``html_url`` is the human-facing page; the response's sibling
        # ``run_url`` is the API URL and must not leak into the UI.
        self.assertEqual(
            run.run_url, 'https://github.com/octo/demo/actions/runs/4242'
        )
        self.assertEqual(run.status, 'queued')
        body = json.loads(dispatch.calls.last.request.read())
        self.assertEqual(body['ref'], 'main')
        self.assertEqual(body['inputs'], {'version': '2.23.0'})

    @respx.mock
    async def test_dispatch_pins_api_version_per_call(self) -> None:
        dispatch = respx.post(_DISPATCH_URL).mock(
            return_value=httpx.Response(204)
        )
        plugin = GitHubDeployment()
        await plugin.create_deployment_artifact(
            _artifact_ctx(), _CREDS, ref='main', version='2.23.0'
        )
        self.assertEqual(
            dispatch.calls.last.request.headers['x-github-api-version'],
            '2026-03-10',
        )

    @respx.mock
    async def test_other_calls_do_not_pin_api_version(self) -> None:
        # Pinning belongs on the dispatch alone -- putting it on the
        # shared client would change every deployment call's behaviour.
        deploy = respx.post(
            'https://api.github.com/repos/octo/demo/deployments'
        ).mock(return_value=httpx.Response(201, json={'id': 1, 'url': ''}))
        plugin = GitHubDeployment()
        await plugin.trigger_deployment(
            _ctx(environment='testing'), _CREDS, ref_or_sha='main'
        )
        self.assertNotIn(
            'x-github-api-version', deploy.calls.last.request.headers
        )

    @respx.mock
    async def test_204_is_dispatched_with_unknown_run_id(self) -> None:
        # The tenant default API version answers bodiless; the build IS
        # running, so this must not read as a failure.
        respx.post(_DISPATCH_URL).mock(return_value=httpx.Response(204))
        plugin = GitHubDeployment()
        run = await plugin.create_deployment_artifact(
            _artifact_ctx(), _CREDS, ref='main', version='2.23.0'
        )
        self.assertIsNone(run.run_id)
        self.assertIsNone(run.run_url)
        self.assertEqual(run.status, 'queued')

    @respx.mock
    async def test_200_with_unparseable_body_degrades(self) -> None:
        respx.post(_DISPATCH_URL).mock(
            return_value=httpx.Response(
                200,
                content=b'not json',
                headers={'content-type': 'text/plain'},
            )
        )
        plugin = GitHubDeployment()
        run = await plugin.create_deployment_artifact(
            _artifact_ctx(), _CREDS, ref='main', version='2.23.0'
        )
        self.assertIsNone(run.run_id)
        self.assertEqual(run.status, 'queued')

    @respx.mock
    async def test_version_input_name_is_configurable(self) -> None:
        dispatch = respx.post(_DISPATCH_URL).mock(
            return_value=httpx.Response(204)
        )
        plugin = GitHubDeployment()
        await plugin.create_deployment_artifact(
            _artifact_ctx({'artifact_version_input': 'tag'}),
            _CREDS,
            ref='main',
            version='2.23.0',
        )
        body = json.loads(dispatch.calls.last.request.read())
        self.assertEqual(body['inputs'], {'tag': '2.23.0'})

    @respx.mock
    async def test_caller_inputs_layer_over_version(self) -> None:
        dispatch = respx.post(_DISPATCH_URL).mock(
            return_value=httpx.Response(204)
        )
        plugin = GitHubDeployment()
        await plugin.create_deployment_artifact(
            _artifact_ctx(),
            _CREDS,
            ref='main',
            version='2.23.0',
            inputs={'version': 'override', 'dry_run': 'false'},
        )
        body = json.loads(dispatch.calls.last.request.read())
        self.assertEqual(
            body['inputs'], {'version': 'override', 'dry_run': 'false'}
        )

    @respx.mock
    async def test_numeric_workflow_id_accepted(self) -> None:
        dispatch = respx.post(
            'https://api.github.com/repos/octo/demo/actions/workflows/'
            '161335/dispatches'
        ).mock(return_value=httpx.Response(204))
        plugin = GitHubDeployment()
        await plugin.create_deployment_artifact(
            _ctx(options={'artifact_workflow': 161335}),
            _CREDS,
            ref='main',
            version='2.23.0',
        )
        self.assertTrue(dispatch.called)

    @respx.mock
    async def test_missing_workflow_option_raises(self) -> None:
        plugin = GitHubDeployment()
        with self.assertRaises(ValueError) as ctx:
            await plugin.create_deployment_artifact(
                _ctx(), _CREDS, ref='main', version='2.23.0'
            )
        self.assertIn('artifact_workflow', str(ctx.exception))

    @respx.mock
    async def test_too_many_inputs_raises_before_dispatch(self) -> None:
        dispatch = respx.post(_DISPATCH_URL).mock(
            return_value=httpx.Response(204)
        )
        plugin = GitHubDeployment()
        with self.assertRaises(ValueError) as ctx:
            await plugin.create_deployment_artifact(
                _artifact_ctx(),
                _CREDS,
                ref='main',
                version='2.23.0',
                # 25 here plus the injected version key is 26.
                inputs={f'k{i}': str(i) for i in range(25)},
            )
        self.assertIn('at most 25', str(ctx.exception))
        self.assertFalse(dispatch.called)

    @respx.mock
    async def test_twenty_five_inputs_are_accepted(self) -> None:
        # GitHub raised the cap from 10 to 25 in December 2025; rejecting
        # at the old limit would refuse valid dispatches.
        dispatch = respx.post(_DISPATCH_URL).mock(
            return_value=httpx.Response(204)
        )
        plugin = GitHubDeployment()
        await plugin.create_deployment_artifact(
            _artifact_ctx(),
            _CREDS,
            ref='main',
            version='2.23.0',
            inputs={f'k{i}': str(i) for i in range(24)},
        )
        body = json.loads(dispatch.calls.last.request.read())
        self.assertEqual(25, len(body['inputs']))

    @respx.mock
    async def test_http_error_propagates(self) -> None:
        # A 422 (no workflow_dispatch trigger, or unknown ref) must reach
        # the host so the promote records a warning rather than silently
        # reporting a build that never started.
        respx.post(_DISPATCH_URL).mock(
            return_value=httpx.Response(
                422,
                json={
                    'message': 'Workflow does not have '
                    'workflow_dispatch trigger'
                },
            )
        )
        plugin = GitHubDeployment()
        with self.assertRaises(httpx.HTTPStatusError):
            await plugin.create_deployment_artifact(
                _artifact_ctx(), _CREDS, ref='main', version='2.23.0'
            )


class GetArtifactRunStatusTestCase(unittest.IsolatedAsyncioTestCase):
    def _mock_run(self, **fields: object) -> None:
        payload: dict[str, object] = {
            'id': 4242,
            'status': 'completed',
            'conclusion': 'success',
            'html_url': 'https://github.com/octo/demo/actions/runs/4242',
            'run_started_at': '2026-08-04T12:00:00Z',
            'created_at': '2026-08-04T11:59:00Z',
            'updated_at': '2026-08-04T12:05:00Z',
        }
        payload.update(fields)
        respx.get(
            'https://api.github.com/repos/octo/demo/actions/runs/4242'
        ).mock(return_value=httpx.Response(200, json=payload))

    @respx.mock
    async def test_completed_success(self) -> None:
        self._mock_run()
        plugin = GitHubDeployment()
        run = await plugin.get_artifact_run_status(_ctx(), _CREDS, '4242')
        self.assertEqual(run.run_id, '4242')
        self.assertEqual(run.status, 'success')
        self.assertEqual(
            run.run_url, 'https://github.com/octo/demo/actions/runs/4242'
        )
        self.assertEqual(
            run.started_at,
            datetime.datetime(2026, 8, 4, 12, 0, tzinfo=datetime.UTC),
        )
        self.assertEqual(
            run.completed_at,
            datetime.datetime(2026, 8, 4, 12, 5, tzinfo=datetime.UTC),
        )

    @respx.mock
    async def test_in_progress_has_no_completed_at(self) -> None:
        self._mock_run(status='in_progress', conclusion=None)
        plugin = GitHubDeployment()
        run = await plugin.get_artifact_run_status(_ctx(), _CREDS, '4242')
        self.assertEqual(run.status, 'in_progress')
        self.assertIsNone(run.completed_at)

    @respx.mock
    async def test_falls_back_to_created_at_when_unstarted(self) -> None:
        self._mock_run(status='queued', conclusion=None, run_started_at=None)
        plugin = GitHubDeployment()
        run = await plugin.get_artifact_run_status(_ctx(), _CREDS, '4242')
        self.assertEqual(
            run.started_at,
            datetime.datetime(2026, 8, 4, 11, 59, tzinfo=datetime.UTC),
        )


class ArtifactStatusMappingTestCase(unittest.TestCase):
    def test_in_flight_states(self) -> None:
        self.assertEqual(_artifact_status('in_progress', ''), 'in_progress')
        for state in ('queued', 'requested', 'waiting', 'pending'):
            with self.subTest(state=state):
                self.assertEqual(_artifact_status(state, ''), 'queued')

    def test_unrecognised_in_flight_state_stays_queued(self) -> None:
        # Not terminal, so the host keeps polling rather than treating an
        # unfamiliar state as a dead run.
        self.assertEqual(_artifact_status('something_new', ''), 'queued')

    def test_terminal_conclusions(self) -> None:
        cases = {
            'success': 'success',
            'failure': 'failure',
            'timed_out': 'failure',
            # Completed but produced no artifact -- a failure to the host
            # whatever GitHub calls it.
            'action_required': 'failure',
            'startup_failure': 'failure',
            'cancelled': 'cancelled',
            'skipped': 'cancelled',
            'stale': 'cancelled',
            # Terminal, but says nothing about whether the artifact exists.
            'neutral': 'unknown',
            'something_new': 'unknown',
        }
        for conclusion, expected in cases.items():
            with self.subTest(conclusion=conclusion):
                self.assertEqual(
                    _artifact_status('completed', conclusion), expected
                )

    def test_completed_without_conclusion_stays_in_flight(self) -> None:
        # GitHub briefly reports ``completed`` before the conclusion is
        # populated. Classifying that as terminal would let a host settle
        # on a run whose real outcome lands moments later.
        self.assertEqual(_artifact_status('completed', ''), 'in_progress')


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


class MainlineBranchesTestCase(unittest.TestCase):
    def test_unset_falls_back_to_default(self) -> None:
        self.assertEqual(
            _mainline_branches({'flavor': 'github'}),
            frozenset({'main', 'master'}),
        )

    def test_space_separated(self) -> None:
        self.assertEqual(
            _mainline_branches({'mainline_branches': 'develop trunk'}),
            frozenset({'develop', 'trunk'}),
        )

    def test_commas_tolerated(self) -> None:
        # The label advertises spaces; operators type commas anyway.
        self.assertEqual(
            _mainline_branches({'mainline_branches': 'main, develop,trunk'}),
            frozenset({'main', 'develop', 'trunk'}),
        )

    def test_stray_separators_do_not_yield_empty_branch(self) -> None:
        # An empty-string member would match a deployment with ``ref: ''``
        # and, worse, read as a configured value.
        self.assertEqual(
            _mainline_branches({'mainline_branches': '  main,, master,  '}),
            frozenset({'main', 'master'}),
        )

    def test_blank_falls_back_to_default(self) -> None:
        # The manifest default is a form pre-fill the host does not
        # substitute, so blank means "unconfigured", not "no exclusions".
        self.assertEqual(
            _mainline_branches({'mainline_branches': '   '}),
            frozenset({'main', 'master'}),
        )

    def test_non_string_falls_back_to_default(self) -> None:
        self.assertEqual(
            _mainline_branches({'mainline_branches': None}),
            frozenset({'main', 'master'}),
        )
        self.assertEqual(
            _mainline_branches({'mainline_branches': 7}),
            frozenset({'main', 'master'}),
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


class GitNotesTestCase(unittest.IsolatedAsyncioTestCase):
    """Reading and diffing ``refs/notes/imbi-drift`` via the Git Data API."""

    REPO = 'https://api.github.com/repos/octo/demo'
    FULL_SHA = 'abc1234' + 'f' * 33

    def setUp(self) -> None:
        self.handler = GitHubDeployment()

    def _mock_tree(self, entries: list[dict[str, object]]) -> None:
        respx.get(f'{self.REPO}/git/ref/notes/imbi-drift').mock(
            return_value=httpx.Response(
                200, json={'object': {'sha': 'notes-tip'}}
            )
        )
        respx.get(f'{self.REPO}/git/commits/notes-tip').mock(
            return_value=httpx.Response(200, json={'tree': {'sha': 't1'}})
        )
        respx.get(f'{self.REPO}/git/trees/t1').mock(
            return_value=httpx.Response(200, json={'tree': entries})
        )

    @staticmethod
    def _blob(sha: str, text: str) -> None:
        respx.get(
            f'https://api.github.com/repos/octo/demo/git/blobs/{sha}'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'encoding': 'base64',
                    'content': base64.b64encode(text.encode()).decode(),
                },
            )
        )

    @respx.mock
    async def test_get_commit_note_resolves_short_sha_and_fanout(
        self,
    ) -> None:
        respx.get(f'{self.REPO}/commits/abc1234').mock(
            return_value=httpx.Response(200, json={'sha': self.FULL_SHA})
        )
        fanout = f'{self.FULL_SHA[:2]}/{self.FULL_SHA[2:]}'
        self._mock_tree([{'type': 'blob', 'path': fanout, 'sha': 'b1'}])
        self._blob('b1', '{"drift_detected":false}')
        note = await self.handler.get_commit_note(
            _ctx(), _CREDS, 'imbi-drift', 'abc1234'
        )
        self.assertEqual('{"drift_detected":false}', note)

    @respx.mock
    async def test_get_commit_note_missing_ref_is_none(self) -> None:
        respx.get(f'{self.REPO}/git/ref/notes/imbi-drift').mock(
            return_value=httpx.Response(404, json={'message': 'Not Found'})
        )
        note = await self.handler.get_commit_note(
            _ctx(), _CREDS, 'imbi-drift', self.FULL_SHA
        )
        self.assertIsNone(note)

    @respx.mock
    async def test_get_commit_note_no_entry_is_none(self) -> None:
        self._mock_tree([{'type': 'blob', 'path': 'e' * 40, 'sha': 'b1'}])
        note = await self.handler.get_commit_note(
            _ctx(), _CREDS, 'imbi-drift', self.FULL_SHA
        )
        self.assertIsNone(note)

    @respx.mock
    async def test_diff_commit_notes_reads_the_tree_diff(self) -> None:
        removed_sha = 'e' * 40
        respx.get(f'{self.REPO}/compare/{"a" * 40}...{"b" * 40}').mock(
            return_value=httpx.Response(
                200,
                json={
                    'files': [
                        {
                            'filename': (
                                f'{self.FULL_SHA[:2]}/{self.FULL_SHA[2:]}'
                            ),
                            'status': 'modified',
                            'sha': 'b2',
                        },
                        {'filename': removed_sha, 'status': 'removed'},
                        {'filename': 'README', 'status': 'added'},
                    ]
                },
            )
        )
        self._blob('b2', '{"drift_detected":true}')
        changed = await self.handler.diff_commit_notes(
            _ctx(), _CREDS, 'imbi-drift', 'a' * 40, 'b' * 40
        )
        self.assertEqual(
            {
                self.FULL_SHA: '{"drift_detected":true}',
                removed_sha: None,
            },
            changed,
        )

    def _mock_after_tree(
        self, entries: list[dict[str, object]] | None = None
    ) -> None:
        """The full tree at ``after`` the fallback paths read."""
        respx.get(f'{self.REPO}/git/commits/{"b" * 40}').mock(
            return_value=httpx.Response(200, json={'tree': {'sha': 't1'}})
        )
        respx.get(f'{self.REPO}/git/trees/t1').mock(
            return_value=httpx.Response(
                200,
                json={
                    'tree': entries
                    or [{'type': 'blob', 'path': self.FULL_SHA, 'sha': 'b1'}]
                },
            )
        )

    @respx.mock
    async def test_diff_commit_notes_tracks_a_renamed_note(self) -> None:
        old_sha = 'e' * 40
        respx.get(f'{self.REPO}/compare/{"a" * 40}...{"b" * 40}').mock(
            return_value=httpx.Response(
                200,
                json={
                    'files': [
                        {
                            'filename': (
                                f'{self.FULL_SHA[:2]}/{self.FULL_SHA[2:]}'
                            ),
                            'previous_filename': old_sha,
                            'status': 'renamed',
                            'sha': 'b2',
                        }
                    ]
                },
            )
        )
        self._blob('b2', '{"drift_detected":true}')
        changed = await self.handler.diff_commit_notes(
            _ctx(), _CREDS, 'imbi-drift', 'a' * 40, 'b' * 40
        )
        self.assertEqual(
            {
                self.FULL_SHA: '{"drift_detected":true}',
                old_sha: None,
            },
            changed,
        )

    @respx.mock
    async def test_diff_commit_notes_404_falls_back_to_the_tree(
        self,
    ) -> None:
        respx.get(f'{self.REPO}/compare/{"a" * 40}...{"b" * 40}').mock(
            return_value=httpx.Response(404, json={'message': 'Not Found'})
        )
        self._mock_after_tree()
        self._blob('b1', '{"drift_detected":false}')
        changed = await self.handler.diff_commit_notes(
            _ctx(), _CREDS, 'imbi-drift', 'a' * 40, 'b' * 40
        )
        self.assertEqual({self.FULL_SHA: '{"drift_detected":false}'}, changed)

    @respx.mock
    async def test_diff_commit_notes_file_cap_falls_back_to_the_tree(
        self,
    ) -> None:
        # 300 files means the unpaginated list may be incomplete.
        files = [
            {'filename': f'{i:040x}', 'status': 'added', 'sha': f's{i}'}
            for i in range(300)
        ]
        respx.get(f'{self.REPO}/compare/{"a" * 40}...{"b" * 40}').mock(
            return_value=httpx.Response(200, json={'files': files})
        )
        self._mock_after_tree()
        self._blob('b1', '{"drift_detected":false}')
        with self.assertLogs('imbi.plugins.github', level='WARNING'):
            changed = await self.handler.diff_commit_notes(
                _ctx(), _CREDS, 'imbi-drift', 'a' * 40, 'b' * 40
            )
        self.assertEqual({self.FULL_SHA: '{"drift_detected":false}'}, changed)

    @respx.mock
    async def test_diff_commit_notes_skips_an_unreadable_blob(self) -> None:
        # A failed read is skipped, not recorded as ``None`` -- in the
        # diff a ``None`` means "note removed" and resolves blockers.
        other_sha = 'e' * 40
        respx.get(f'{self.REPO}/compare/{"a" * 40}...{"b" * 40}').mock(
            return_value=httpx.Response(
                200,
                json={
                    'files': [
                        {
                            'filename': self.FULL_SHA,
                            'status': 'modified',
                            'sha': 'bad',
                        },
                        {
                            'filename': other_sha,
                            'status': 'modified',
                            'sha': 'b2',
                        },
                    ]
                },
            )
        )
        respx.get(f'{self.REPO}/git/blobs/bad').mock(
            return_value=httpx.Response(500)
        )
        self._blob('b2', '{"drift_detected":true}')
        with self.assertLogs('imbi.plugins.github', level='WARNING'):
            changed = await self.handler.diff_commit_notes(
                _ctx(), _CREDS, 'imbi-drift', 'a' * 40, 'b' * 40
            )
        self.assertEqual({other_sha: '{"drift_detected":true}'}, changed)

    @respx.mock
    async def test_undecodable_blob_is_skipped(self) -> None:
        # Not recorded as ``None``: in the diff a ``None`` means "note
        # removed" and would resolve a drift blocker over a note that
        # merely could not be decoded.
        respx.get(f'{self.REPO}/compare/{"a" * 40}...{"b" * 40}').mock(
            return_value=httpx.Response(
                200,
                json={
                    'files': [
                        {
                            'filename': self.FULL_SHA,
                            'status': 'modified',
                            'sha': 'b2',
                        }
                    ]
                },
            )
        )
        respx.get(f'{self.REPO}/git/blobs/b2').mock(
            return_value=httpx.Response(
                200,
                json={'encoding': 'base64', 'content': '%%%not-base64%%%'},
            )
        )
        with self.assertLogs('imbi.plugins.github', level='WARNING'):
            changed = await self.handler.diff_commit_notes(
                _ctx(), _CREDS, 'imbi-drift', 'a' * 40, 'b' * 40
            )
        self.assertEqual({}, changed)

    @respx.mock
    async def test_garbage_base64_is_skipped_not_read_as_empty(self) -> None:
        # The default decoder discards invalid characters, so '%%%%'
        # would decode to an empty body and stamp a null verdict
        # instead of landing on the "cannot read" skip path.
        respx.get(f'{self.REPO}/compare/{"a" * 40}...{"b" * 40}').mock(
            return_value=httpx.Response(
                200,
                json={
                    'files': [
                        {
                            'filename': self.FULL_SHA,
                            'status': 'modified',
                            'sha': 'b2',
                        }
                    ]
                },
            )
        )
        respx.get(f'{self.REPO}/git/blobs/b2').mock(
            return_value=httpx.Response(
                200, json={'encoding': 'base64', 'content': '%%%%'}
            )
        )
        with self.assertLogs('imbi.plugins.github', level='WARNING'):
            changed = await self.handler.diff_commit_notes(
                _ctx(), _CREDS, 'imbi-drift', 'a' * 40, 'b' * 40
            )
        self.assertEqual({}, changed)

    @respx.mock
    async def test_line_wrapped_base64_still_decodes(self) -> None:
        # GitHub wraps blob content in newlines; strict validation must
        # not reject its own wrapping.
        fanout = f'{self.FULL_SHA[:2]}/{self.FULL_SHA[2:]}'
        self._mock_tree([{'type': 'blob', 'path': fanout, 'sha': 'b1'}])
        encoded = base64.b64encode(b'{"drift_detected":true}').decode()
        wrapped = f'{encoded[:16]}\n{encoded[16:]}\n'
        respx.get(f'{self.REPO}/git/blobs/b1').mock(
            return_value=httpx.Response(
                200, json={'encoding': 'base64', 'content': wrapped}
            )
        )
        note = await self.handler.get_commit_note(
            _ctx(), _CREDS, 'imbi-drift', self.FULL_SHA
        )
        self.assertEqual('{"drift_detected":true}', note)

    @respx.mock
    async def test_undecodable_blob_is_skipped_in_the_full_tree(
        self,
    ) -> None:
        other_sha = 'e' * 40
        self._mock_after_tree(
            [
                {'type': 'blob', 'path': self.FULL_SHA, 'sha': 'b2'},
                {'type': 'blob', 'path': other_sha, 'sha': 'b3'},
            ]
        )
        respx.get(f'{self.REPO}/git/blobs/b2').mock(
            return_value=httpx.Response(
                200,
                json={'encoding': 'base64', 'content': '%%%not-base64%%%'},
            )
        )
        self._blob('b3', '{"drift_detected":false}')
        with self.assertLogs('imbi.plugins.github', level='WARNING'):
            changed = await self.handler.diff_commit_notes(
                _ctx(), _CREDS, 'imbi-drift', '0' * 40, 'b' * 40
            )
        self.assertEqual({other_sha: '{"drift_detected":false}'}, changed)

    @respx.mock
    async def test_oversized_blob_is_none(self) -> None:
        # ``encoding: none`` with empty content is GitHub's answer for
        # blobs above the inline size limit -- "cannot read", not an
        # empty note.
        self._mock_tree(
            [{'type': 'blob', 'path': self.FULL_SHA, 'sha': 'big'}]
        )
        respx.get(f'{self.REPO}/git/blobs/big').mock(
            return_value=httpx.Response(
                200, json={'encoding': 'none', 'content': ''}
            )
        )
        with self.assertLogs('imbi.plugins.github', level='WARNING'):
            note = await self.handler.get_commit_note(
                _ctx(), _CREDS, 'imbi-drift', self.FULL_SHA
            )
        self.assertIsNone(note)

    @respx.mock
    async def test_all_notes_skips_an_unreadable_blob(self) -> None:
        other_sha = 'e' * 40
        self._mock_after_tree(
            [
                {'type': 'blob', 'path': self.FULL_SHA, 'sha': 'bad'},
                {'type': 'blob', 'path': other_sha, 'sha': 'b2'},
            ]
        )
        respx.get(f'{self.REPO}/git/blobs/bad').mock(
            return_value=httpx.Response(500)
        )
        self._blob('b2', '{"drift_detected":false}')
        with self.assertLogs('imbi.plugins.github', level='WARNING'):
            changed = await self.handler.diff_commit_notes(
                _ctx(), _CREDS, 'imbi-drift', '0' * 40, 'b' * 40
            )
        self.assertEqual({other_sha: '{"drift_detected":false}'}, changed)

    @respx.mock
    async def test_list_commit_notes_reads_the_whole_ref(self) -> None:
        fanout = f'{self.FULL_SHA[:2]}/{self.FULL_SHA[2:]}'
        self._mock_tree(
            [
                {'type': 'blob', 'path': fanout, 'sha': 'b1'},
                {'type': 'tree', 'path': 'ab', 'sha': 'sub'},
            ]
        )
        self._blob('b1', '{"drift_detected":true}')
        listing = await self.handler.list_commit_notes(
            _ctx(), _CREDS, 'imbi-drift'
        )
        # Fan-out subtree flattened back to the annotated full SHA.
        self.assertEqual(
            {self.FULL_SHA: '{"drift_detected":true}'}, listing.notes
        )
        self.assertTrue(listing.complete)

    @respx.mock
    async def test_list_commit_notes_skips_answered_commits(self) -> None:
        # Enumerating the ref is a call or two; every body is a request
        # of its own, so a caller repairing a gap must be able to pay
        # only for what it is missing.
        other_sha = 'e' * 40
        self._mock_tree(
            [
                {'type': 'blob', 'path': self.FULL_SHA, 'sha': 'b1'},
                {'type': 'blob', 'path': other_sha, 'sha': 'b2'},
            ]
        )
        skipped = respx.get(f'{self.REPO}/git/blobs/b1').mock(
            return_value=httpx.Response(500)
        )
        self._blob('b2', '{"drift_detected":false}')
        listing = await self.handler.list_commit_notes(
            _ctx(), _CREDS, 'imbi-drift', skip_shas=[self.FULL_SHA.upper()]
        )
        self.assertFalse(skipped.called)
        self.assertEqual(
            {other_sha: '{"drift_detected":false}'}, listing.notes
        )
        # A note skipped on request is not a note that could not be
        # read: the caller already holds that answer.
        self.assertTrue(listing.complete)

    @respx.mock
    async def test_list_commit_notes_reports_an_unreadable_blob(self) -> None:
        # The readable note still comes back, but the listing says it is
        # not the whole ref, so a caller cannot record a finished
        # backfill over a note it never saw.
        other_sha = 'e' * 40
        self._mock_tree(
            [
                {'type': 'blob', 'path': self.FULL_SHA, 'sha': 'bad'},
                {'type': 'blob', 'path': other_sha, 'sha': 'b2'},
            ]
        )
        respx.get(f'{self.REPO}/git/blobs/bad').mock(
            return_value=httpx.Response(500)
        )
        self._blob('b2', '{"drift_detected":false}')
        with self.assertLogs('imbi.plugins.github', level='WARNING'):
            listing = await self.handler.list_commit_notes(
                _ctx(), _CREDS, 'imbi-drift'
            )
        self.assertEqual(
            {other_sha: '{"drift_detected":false}'}, listing.notes
        )
        self.assertFalse(listing.complete)

    @respx.mock
    async def test_list_commit_notes_reports_a_truncated_tree(self) -> None:
        # Every note in the (partial) tree read fine, so blob-read
        # completeness alone would call this whole. The tree itself says
        # otherwise.
        respx.get(f'{self.REPO}/git/ref/notes/imbi-drift').mock(
            return_value=httpx.Response(
                200, json={'object': {'sha': 'notes-tip'}}
            )
        )
        respx.get(f'{self.REPO}/git/commits/notes-tip').mock(
            return_value=httpx.Response(200, json={'tree': {'sha': 't1'}})
        )
        respx.get(f'{self.REPO}/git/trees/t1').mock(
            return_value=httpx.Response(
                200,
                json={
                    'tree': [
                        {'type': 'blob', 'path': self.FULL_SHA, 'sha': 'b1'}
                    ],
                    'truncated': True,
                },
            )
        )
        self._blob('b1', '{"drift_detected":true}')
        with self.assertLogs('imbi.plugins.github', level='WARNING'):
            listing = await self.handler.list_commit_notes(
                _ctx(), _CREDS, 'imbi-drift'
            )
        self.assertEqual(
            {self.FULL_SHA: '{"drift_detected":true}'}, listing.notes
        )
        self.assertFalse(listing.complete)

    @respx.mock
    async def test_list_commit_notes_without_the_ref_is_empty(self) -> None:
        respx.get(f'{self.REPO}/git/ref/notes/imbi-drift').mock(
            return_value=httpx.Response(404)
        )
        listing = await self.handler.list_commit_notes(
            _ctx(), _CREDS, 'imbi-drift'
        )
        # Empty but complete: "no notes" is the whole truth here.
        self.assertEqual({}, listing.notes)
        self.assertTrue(listing.complete)

    @respx.mock
    async def test_diff_commit_notes_zero_before_lists_everything(
        self,
    ) -> None:
        respx.get(f'{self.REPO}/git/commits/{"b" * 40}').mock(
            return_value=httpx.Response(200, json={'tree': {'sha': 't1'}})
        )
        respx.get(f'{self.REPO}/git/trees/t1').mock(
            return_value=httpx.Response(
                200,
                json={
                    'tree': [
                        {'type': 'blob', 'path': self.FULL_SHA, 'sha': 'b1'},
                        {'type': 'tree', 'path': 'ab', 'sha': 'sub'},
                    ]
                },
            )
        )
        self._blob('b1', '{"drift_detected":false}')
        changed = await self.handler.diff_commit_notes(
            _ctx(), _CREDS, 'imbi-drift', '0' * 40, 'b' * 40
        )
        self.assertEqual({self.FULL_SHA: '{"drift_detected":false}'}, changed)
