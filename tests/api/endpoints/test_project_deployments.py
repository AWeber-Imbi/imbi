"""Tests for the project deployment plugin endpoints."""

import datetime
import json
import typing
import unittest
from unittest import mock

from fastapi import testclient
from imbi_common import graph
from imbi_common.llm import AnthropicClient, CompletionResult
from imbi_common.models import SEMVER_TAG_FORMAT, TagFormat
from imbi_common.plugins.base import (
    Commit,
    CompareResult,
    DeploymentPlugin,
    DeploymentRun,
    LinkWriteback,
    PluginManifest,
    Ref,
    RefInfo,
    ReleaseInfo,
    RemoteDeployment,
)
from imbi_common.plugins.registry import RegistryEntry

from imbi_api import models
from imbi_api.auth import password, permissions
from imbi_api.endpoints import _helpers, project_deployments
from imbi_api.endpoints.project_deployments import (
    DraftReleaseNotes,
    _EnvFlags,
    persist_link_writeback,
)
from imbi_api.llm.dependencies import _get_anthropic_client
from imbi_api.plugins.resolution import ResolvedPlugin
from tests import support


class _FakeDeploymentPlugin(DeploymentPlugin):
    manifest = PluginManifest(
        slug='github-deployment',
        name='GitHub Deployment',
        plugin_type='deployment',
        supports_deployment_sync=True,
    )

    async def list_refs(  # type: ignore[override]
        self, ctx, credentials, kind='all', query=None
    ):
        return [
            Ref(name='main', kind='default', sha='m-sha', is_default=True),
            Ref(name='feature/x', kind='branch', sha='fx'),
        ]

    async def list_commits(  # type: ignore[override]
        self, ctx, credentials, ref, limit=25
    ):
        return [
            Commit(
                sha='abc1234567',
                short_sha='abc1234',
                message='Top',
                is_head=True,
            ),
            Commit(sha='def5678901', short_sha='def5678', message='prev'),
        ]

    async def resolve_committish(  # type: ignore[override]
        self, ctx, credentials, committish
    ):
        return Commit(sha=committish, short_sha=committish[:7], message='hi')

    async def compare(  # type: ignore[override]
        self, ctx, credentials, base, head
    ):
        return CompareResult(base_sha=base, head_sha=head, ahead=1, behind=0)

    async def trigger_deployment(  # type: ignore[override]
        self, ctx, credentials, ref_or_sha, inputs=None
    ):
        return DeploymentRun(
            run_id='42',
            run_url='https://gh/runs/42',
            status='queued',
        )

    async def get_deployment_status(  # type: ignore[override]
        self, ctx, credentials, run_id
    ):
        return DeploymentRun(run_id=run_id, status='in_progress')

    async def create_tag(  # type: ignore[override]
        self, ctx, credentials, sha, tag, message
    ):
        return RefInfo(name=f'refs/tags/{tag}', sha=sha)

    async def create_release(  # type: ignore[override]
        self, ctx, credentials, tag, name, body_markdown, prerelease=False
    ):
        return ReleaseInfo(
            id='rel-1',
            tag=tag,
            name=name,
            html_url=f'https://gh/releases/{tag}',
            url=f'https://api.gh/releases/{tag}',
            prerelease=prerelease,
        )

    async def list_recent_deployments(  # type: ignore[override]
        self, ctx, credentials, environments, limit=1
    ):
        # Override per-test by setting ``_recent`` on the instance.
        # Record the limit so tests can assert it was threaded through.
        self._last_limit = limit  # type: ignore[attr-defined]
        return getattr(self, '_recent', [])


class _FakeNoSyncDeploymentPlugin(_FakeDeploymentPlugin):
    """Deployment plugin that opts *out* of resync."""

    manifest = PluginManifest(
        slug='no-sync-deployment',
        name='No-Sync Deployment',
        plugin_type='deployment',
        supports_deployment_sync=False,
    )


class _RelocatingDeploymentPlugin(_FakeDeploymentPlugin):
    """Deployment plugin that reports a repo rename on every call.

    Mirrors how the real GitHub plugin stashes a
    ``LinkWriteback`` on ``ctx`` after following a 301.
    """

    @staticmethod
    def _report(ctx: typing.Any) -> None:
        ctx.link_writeback = LinkWriteback(
            link_key='github-repository',
            new_url='https://github.com/octo/renamed',
            old_owner_repo='octo/demo',
            new_owner_repo='octo/renamed',
        )

    async def list_commits(  # type: ignore[override]
        self, ctx, credentials, ref, limit=25
    ):
        self._report(ctx)
        return await super().list_commits(ctx, credentials, ref, limit)

    async def trigger_deployment(  # type: ignore[override]
        self, ctx, credentials, ref_or_sha, inputs=None
    ):
        self._report(ctx)
        return await super().trigger_deployment(
            ctx, credentials, ref_or_sha, inputs
        )


def _entry() -> RegistryEntry:
    return RegistryEntry(
        handler_cls=_FakeDeploymentPlugin,
        manifest=_FakeDeploymentPlugin.manifest,
        package_name='imbi-plugin-github',
        package_version='0.1.0',
    )


_MODULE = 'imbi_api.endpoints.project_deployments'
_UPDATE_LINK = 'imbi_api.endpoints._helpers.update_project_link'


class ProjectDeploymentsTestCase(support.SharedAppTestCase):
    def setUp(self) -> None:
        self.test_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.test_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={
                'project:deployment:read',
                'project:deployment:write',
            },
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )

        self.mock_anthropic = mock.MagicMock(spec=AnthropicClient)
        self.mock_anthropic.complete_json = mock.AsyncMock(
            return_value=CompletionResult(
                data=DraftReleaseNotes(
                    bump='minor',
                    version='v1.1.0',
                    reasoning='added feature foo',
                    notes_markdown='## Foo',
                ),
                degraded=False,
            )
        )
        self.test_app.dependency_overrides[_get_anthropic_client] = lambda: (
            self.mock_anthropic
        )

        self.mocks = {
            'resolve_plugin': self._start(
                mock.patch(
                    f'{_MODULE}.resolve_plugin', return_value=self._resolved()
                )
            ),
            'lookup_project_slugs': self._start(
                mock.patch(
                    f'{_MODULE}.lookup_project_slugs',
                    return_value=('proj', 'team'),
                )
            ),
            'attach_identity': self._start(
                mock.patch(
                    f'{_MODULE}.attach_identity',
                    side_effect=lambda db, ctx, resolved, auth: ctx,
                )
            ),
            'get_plugin_credentials': self._start(
                mock.patch(
                    f'{_MODULE}.get_plugin_credentials',
                    return_value={'access_token': 'gho_test'},
                )
            ),
            'append_deployment_event': self._start(
                mock.patch(
                    f'{_MODULE}.append_deployment_event',
                    return_value=None,
                )
            ),
            # Default env flags: deploy + promote both allowed.  Tests
            # exercising the 400 guardrails override this on the mock.
            '_load_env_flags': self._start(
                mock.patch(
                    f'{_MODULE}._load_env_flags',
                    return_value=_EnvFlags(
                        found=True,
                        can_deploy=True,
                        can_promote=True,
                    ),
                )
            ),
            # Default tag-format policy: none configured (any tag allowed).
            # Tests exercising the policy guardrails override the return.
            '_resolve_tag_formats': self._start(
                mock.patch(
                    f'{_MODULE}._resolve_tag_formats',
                    return_value=[],
                )
            ),
            'clickhouse': self._start(
                mock.patch(
                    f'{_MODULE}.clickhouse.client.Clickhouse.get_instance',
                    return_value=mock.MagicMock(
                        insert=mock.AsyncMock(return_value=None),
                        initialize=mock.AsyncMock(return_value=True),
                        setup_schema=mock.AsyncMock(return_value=None),
                        aclose=mock.AsyncMock(return_value=None),
                        close=mock.AsyncMock(return_value=None),
                    ),
                )
            ),
        }

    def _start(self, patcher: typing.Any) -> mock.MagicMock:
        m = patcher.start()
        self.addCleanup(patcher.stop)
        return m

    def _resolved(self) -> ResolvedPlugin:
        return ResolvedPlugin(
            plugin_id='p-1',
            plugin_slug='github-deployment',
            entry=_entry(),
            options={'owner': 'octo', 'repo': 'demo'},
        )

    def test_list_refs(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/deployments/refs'
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['name'], 'main')
        self.assertTrue(data[0]['is_default'])

    def test_list_commits(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/deployments/'
                'refs/main/commits'
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertTrue(data[0]['is_head'])

    def test_resolve_commit(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/deployments/'
                'commits/abc1234'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['sha'], 'abc1234')

    def test_compare(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/deployments/'
                'compare?base=v1&head=v2'
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['ahead'], 1)
        self.assertEqual(data['head_sha'], 'v2')

    def test_compare_missing_query_param_400(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/deployments/compare'
            )
        self.assertEqual(response.status_code, 422)

    def test_trigger_deploy(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'deploy',
                    'environment': 'testing',
                    'committish': 'main',
                    'ref_label': 'main',
                },
            )
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertEqual(data['plugin_slug'], 'github-deployment')
        self.assertEqual(data['run']['run_id'], '42')
        self.assertEqual(data['run']['status'], 'queued')
        self.assertFalse(data['recorded'])

    def test_trigger_deploy_records_event_when_release_matches(self) -> None:
        self.mocks['append_deployment_event'].return_value = mock.Mock()
        # Mock _release_id_for so the deploy flow finds a Release node
        # to attach the in-progress DeploymentEvent to.
        self._start(
            mock.patch(
                f'{_MODULE}._release_id_for',
                return_value='matched-release-id',
            )
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'deploy',
                    'environment': 'staging',
                    'committish': 'abc1234',
                    'ref_label': 'v6.4.0',
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()['recorded'])
        self.mocks['append_deployment_event'].assert_called_once()
        call = self.mocks['append_deployment_event'].call_args
        self.assertEqual(call.kwargs['release_id'], 'matched-release-id')
        self.assertEqual(call.kwargs['env_slug'], 'staging')
        self.assertEqual(call.kwargs['status'], 'in_progress')
        self.assertEqual(call.kwargs['external_run_id'], '42')
        self.assertEqual(call.kwargs['external_run_url'], 'https://gh/runs/42')
        # Note no longer encodes the run URL — that lives in the
        # external_run_url field now.
        self.assertNotIn('https://gh/runs/42', call.kwargs['note'] or '')

    def test_trigger_deploy_uses_ref_label_as_ref_when_set(self) -> None:
        # When the user selects a tag, the frontend sends committish=SHA
        # and ref_label=tag_name.  trigger_deployment must receive the tag
        # name as ref_or_sha so GitHub Actions dispatches against the tag,
        # not an anonymous SHA.
        captured: dict[str, typing.Any] = {}

        class _Capturing(_FakeDeploymentPlugin):
            async def trigger_deployment(  # type: ignore[override]
                self, ctx, credentials, ref_or_sha, inputs=None
            ):
                captured['ref_or_sha'] = ref_or_sha
                return await super().trigger_deployment(
                    ctx, credentials, ref_or_sha, inputs
                )

        self.mocks['resolve_plugin'].return_value = ResolvedPlugin(
            plugin_id='p-1',
            plugin_slug='github-deployment',
            entry=RegistryEntry(
                handler_cls=_Capturing,
                manifest=_Capturing.manifest,
                package_name='x',
                package_version='1',
            ),
            options={'owner': 'octo', 'repo': 'demo'},
            env_payloads={},
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'deploy',
                    'environment': 'staging',
                    'committish': 'abc1234def5678',
                    'ref_label': 'v2.3.1',
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(captured['ref_or_sha'], 'v2.3.1')

    def test_trigger_deploy_uses_committish_when_ref_label_absent(
        self,
    ) -> None:
        captured: dict[str, typing.Any] = {}

        class _Capturing(_FakeDeploymentPlugin):
            async def trigger_deployment(  # type: ignore[override]
                self, ctx, credentials, ref_or_sha, inputs=None
            ):
                captured['ref_or_sha'] = ref_or_sha
                return await super().trigger_deployment(
                    ctx, credentials, ref_or_sha, inputs
                )

        self.mocks['resolve_plugin'].return_value = ResolvedPlugin(
            plugin_id='p-1',
            plugin_slug='github-deployment',
            entry=RegistryEntry(
                handler_cls=_Capturing,
                manifest=_Capturing.manifest,
                package_name='x',
                package_version='1',
            ),
            options={'owner': 'octo', 'repo': 'demo'},
            env_payloads={},
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'deploy',
                    'environment': 'staging',
                    'committish': 'abc1234def5678',
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(captured['ref_or_sha'], 'abc1234def5678')

    def test_trigger_redeploy(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'redeploy',
                    'environment': 'staging',
                    'committish': 'v1.2.3',
                },
            )
        self.assertEqual(response.status_code, 202)

    def test_trigger_invalid_action(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'promote',
                    'environment': 'staging',
                    'committish': 'v1',
                },
            )
        self.assertEqual(response.status_code, 422)

    def test_no_credentials_returns_503(self) -> None:
        self.mocks['get_plugin_credentials'].return_value = {}
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/deployments/refs'
            )
        self.assertEqual(response.status_code, 503)

    def test_write_permission_required_for_post(self) -> None:
        non_admin = models.User(
            email='dev@example.com',
            display_name='Dev',
            is_active=True,
            is_admin=False,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=non_admin,
            session_id='test-session',
            auth_method='jwt',
            permissions={'project:deployment:read'},
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'deploy',
                    'environment': 'testing',
                    'committish': 'main',
                },
            )
        self.assertEqual(response.status_code, 403)

    def test_draft_release_notes_happy_path(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/'
                'draft-release-notes',
                json={
                    'base_sha': 'aaa',
                    'head_sha': 'bbb',
                    'last_tag': 'v1.0.0',
                },
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['bump'], 'minor')
        self.assertEqual(data['version'], 'v1.1.0')
        self.assertFalse(data['degraded'])
        # Compare came back empty in the fake plugin (no commits stubbed
        # for this path), so commits_considered is 0.
        self.assertEqual(data['commits_considered'], 0)
        # The Anthropic client was called with the system + prompt.
        self.mock_anthropic.complete_json.assert_called_once()
        call = self.mock_anthropic.complete_json.call_args
        prompt = call.args[0] if call.args else call.kwargs.get('prompt', '')
        self.assertIn('Project: proj', prompt)
        self.assertIn('aaa..bbb', prompt)
        self.assertTrue(call.kwargs['cache_system_prompt'])

    def test_draft_release_notes_degraded_falls_back(self) -> None:
        self.mock_anthropic.complete_json = mock.AsyncMock(
            side_effect=lambda *args, **kwargs: CompletionResult(
                data=kwargs['fallback'], degraded=True
            )
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/'
                'draft-release-notes',
                json={
                    'base_sha': 'aaa',
                    'head_sha': 'bbb',
                    'last_tag': 'v1.2.3',
                },
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['degraded'])
        # No commits in the stub → patch bump → v1.2.4
        self.assertEqual(data['bump'], 'patch')
        self.assertEqual(data['version'], 'v1.2.4')
        self.assertIn('AI unavailable', data['reasoning'])

    def test_draft_release_notes_rebumps_invalid_version(self) -> None:
        self.mock_anthropic.complete_json = mock.AsyncMock(
            return_value=CompletionResult(
                data=DraftReleaseNotes(
                    bump='major',
                    version='v9.0',  # not a valid semver
                    reasoning='breaking',
                    notes_markdown='## Breaking',
                ),
                degraded=False,
            )
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/'
                'draft-release-notes',
                json={
                    'base_sha': 'aaa',
                    'head_sha': 'bbb',
                    'last_tag': 'v6.3.0',
                },
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # last_tag bumped major: 6.3.0 → 7.0.0
        self.assertEqual(data['version'], 'v7.0.0')

    def test_promote_sha_ref_cuts_tag_and_release(self) -> None:
        # Promote target is a git SHA -- the handler cuts a tag, creates
        # a release, AND dispatches trigger_deployment so the run is
        # tracked in the deployment event.
        self.mocks['append_deployment_event'].return_value = mock.Mock()
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'promote',
                    'from_environment': 'testing',
                    'to_environment': 'staging',
                    'from_committish': '1a9c610',
                    'tag': '1a9c610abcdef',
                    'release_name': 'v6.4.0',
                    'release_notes_markdown': '## Highlights\n- foo',
                    'prerelease': False,
                },
            )
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertEqual(data['tag'], '1a9c610abcdef')
        self.assertEqual(
            data['release_url'], 'https://gh/releases/1a9c610abcdef'
        )
        self.assertTrue(data['recorded'])
        self.assertIsNone(data['warning'])
        call = self.mocks['append_deployment_event'].call_args
        self.assertEqual(call.kwargs['env_slug'], 'staging')
        # Trigger was dispatched -- run id and url are present.
        self.assertEqual(call.kwargs['external_run_id'], '42')
        self.assertEqual(call.kwargs['external_run_url'], 'https://gh/runs/42')

    def test_promote_semver_tag_dispatches_and_recreates_release(self) -> None:
        # Promote target is a semver tag -- the handler attempts create_tag
        # and create_release (idempotently) AND dispatches trigger_deployment.
        # A real GitHub 422 "already exists" for the tag/release is silently
        # ignored; the fake plugin succeeds so we get a release URL.
        self.mocks['append_deployment_event'].return_value = mock.Mock()
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'promote',
                    'from_environment': 'staging',
                    'to_environment': 'production',
                    'from_committish': '1a9c610',
                    'tag': 'v6.4.0',
                },
            )
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertEqual(data['tag'], 'v6.4.0')
        # The fake plugin returned a release URL.
        self.assertEqual(data['release_url'], 'https://gh/releases/v6.4.0')
        self.assertIsNone(data['warning'])
        # The dispatched run surfaced on the event.
        call = self.mocks['append_deployment_event'].call_args
        self.assertEqual(call.kwargs['external_run_id'], '42')
        self.assertEqual(call.kwargs['external_run_url'], 'https://gh/runs/42')

    def test_promote_400_on_ref_violating_configured_format(self) -> None:
        # With a semver policy configured, a branch-shaped ref like
        # ``main`` matches no format and is not a SHA; the handler must
        # refuse rather than silently cut a tag.
        self.mocks['_resolve_tag_formats'].return_value = [SEMVER_TAG_FORMAT]
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'promote',
                    'from_environment': 'testing',
                    'to_environment': 'staging',
                    'from_committish': '1a9c610',
                    'tag': 'main',
                },
            )
        self.assertEqual(response.status_code, 400)
        detail = response.json()['detail']
        self.assertIn('does not match any configured tag format', detail)
        self.assertIn('Semver', detail)

    def test_promote_allows_ref_matching_custom_format(self) -> None:
        # A non-semver ref is accepted when it matches a configured
        # custom format (here a CalVer-style tag).
        self.mocks['append_deployment_event'].return_value = mock.Mock()
        self.mocks['_resolve_tag_formats'].return_value = [
            TagFormat(label='CalVer', pattern=r'\d{4}\.\d{2}\.\d+')
        ]
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'promote',
                    'from_environment': 'staging',
                    'to_environment': 'production',
                    'from_committish': '1a9c610',
                    'tag': '2026.06.1',
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['tag'], '2026.06.1')

    def test_promote_400_when_can_promote_false(self) -> None:
        self.mocks['_load_env_flags'].return_value = _EnvFlags(
            found=True, can_deploy=True, can_promote=False
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'promote',
                    'from_environment': 'testing',
                    'to_environment': 'staging',
                    'from_committish': '1a9c610',
                    'tag': 'v6.4.0',
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('can_promote=false', response.json()['detail'])

    def test_deploy_400_when_can_deploy_false(self) -> None:
        self.mocks['_load_env_flags'].return_value = _EnvFlags(
            found=True, can_deploy=False, can_promote=True
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'deploy',
                    'environment': 'production',
                    'committish': 'v1.2.3',
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('can_deploy=false', response.json()['detail'])

    def test_promote_404_when_env_not_found(self) -> None:
        self.mocks['_load_env_flags'].return_value = _EnvFlags(
            found=False, can_deploy=True, can_promote=False
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'promote',
                    'from_environment': 'testing',
                    'to_environment': 'ghost',
                    'from_committish': '1a9c610',
                    'tag': 'v6.4.0',
                },
            )
        self.assertEqual(response.status_code, 404)

    def test_deploy_env_payloads_flow_into_trigger_inputs(self) -> None:
        # ``env_payloads`` on the resolved plugin is merged into the
        # ``inputs`` passed to ``trigger_deployment`` (caller-supplied
        # ``body.inputs`` still wins on key collisions).
        captured: dict[str, typing.Any] = {}

        class _Capturing(_FakeDeploymentPlugin):
            async def trigger_deployment(  # type: ignore[override]
                self, ctx, credentials, ref_or_sha, inputs=None
            ):
                captured['inputs'] = inputs
                return await super().trigger_deployment(
                    ctx, credentials, ref_or_sha, inputs
                )

        self.mocks['resolve_plugin'].return_value = ResolvedPlugin(
            plugin_id='p-1',
            plugin_slug='github-deployment',
            entry=RegistryEntry(
                handler_cls=_Capturing,
                manifest=_Capturing.manifest,
                package_name='x',
                package_version='1',
            ),
            options={'owner': 'octo', 'repo': 'demo'},
            env_payloads={
                'testing': {'environment': 'testing', 'tier': 'low'},
            },
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'deploy',
                    'environment': 'testing',
                    'committish': 'main',
                    'inputs': {'tier': 'override'},
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(captured['inputs']['environment'], 'testing')
        # Caller override beats env_payloads on shared keys.
        self.assertEqual(captured['inputs']['tier'], 'override')

    def test_promote_deployment_failure_becomes_warning(self) -> None:
        # If trigger_deployment raises, the promote returns early with
        # recorded=False and surfaces the failure as a warning rather
        # than 500ing.  No DeploymentEvent is recorded for a deployment
        # that never started.
        self.mocks['append_deployment_event'].return_value = mock.Mock()

        class _Boom(_FakeDeploymentPlugin):
            async def trigger_deployment(  # type: ignore[override]
                self, ctx, credentials, ref_or_sha, inputs=None
            ):
                raise RuntimeError('422 Unprocessable Entity')

        self.mocks['resolve_plugin'].return_value = ResolvedPlugin(
            plugin_id='p-1',
            plugin_slug='boom',
            entry=RegistryEntry(
                handler_cls=_Boom,
                manifest=_Boom.manifest,
                package_name='x',
                package_version='1',
            ),
            options={},
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'promote',
                    'from_environment': 'staging',
                    'to_environment': 'production',
                    'from_committish': '1a9c610',
                    'tag': 'v6.4.0',
                },
            )
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertIsNotNone(data['warning'])
        self.assertIn('trigger_deployment failed', data['warning'])
        # The raw exception text (here ``"422 Unprocessable Entity"``)
        # must NOT leak into client warnings; only the exception class
        # is included for actionability.
        self.assertIn('RuntimeError', data['warning'])
        self.assertNotIn('422', data['warning'])
        self.assertNotIn('Unprocessable', data['warning'])
        # No DeploymentEvent was recorded -- trigger never started.
        self.assertFalse(data['recorded'])

    def test_promote_falls_back_when_plugin_lacks_create_tag(self) -> None:
        class _NoTag(_FakeDeploymentPlugin):
            async def create_tag(  # type: ignore[override]
                self, ctx, credentials, sha, tag, message
            ):
                raise NotImplementedError

        self.mocks['resolve_plugin'].return_value = ResolvedPlugin(
            plugin_id='p-1',
            plugin_slug='no-tag',
            entry=RegistryEntry(
                handler_cls=_NoTag,
                manifest=_NoTag.manifest,
                package_name='x',
                package_version='1',
            ),
            options={},
        )
        # Use a SHA tag so the ref-shape inference picks the
        # ``create_tag`` branch (semver refs would skip create_tag).
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'promote',
                    'from_environment': 'testing',
                    'to_environment': 'staging',
                    'from_committish': '1a9c610',
                    'tag': '1a9c610',
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'does not support creating tags', response.json()['detail']
        )

    def test_promotion_options_returns_consecutive_pairs(self) -> None:
        # The endpoint runs a Cypher query, then for each gap calls
        # plugin.compare().  Stub the graph response with three envs;
        # the helper deduplicates by env-slug into the latest release
        # per env, so we feed one row per env to keep the test simple.
        def _mock_execute(query, params, columns):
            del query, params, columns
            return [
                {
                    'env': '{"slug": "testing", "name": "Testing", '
                    '"sort_order": 1}',
                    'release': '{"tag": "v6.4.0", "committish": "aaa6400"}',
                    'deployments': None,
                },
                {
                    'env': '{"slug": "staging", "name": "Staging", '
                    '"sort_order": 2}',
                    'release': '{"tag": "v6.3.0", "committish": "bbb6300"}',
                    'deployments': None,
                },
                {
                    'env': '{"slug": "production", "name": "Production", '
                    '"sort_order": 3}',
                    'release': '{"tag": "v6.2.0", "committish": "ccc6200"}',
                    'deployments': None,
                },
            ]

        self.mock_db.execute = mock.AsyncMock(side_effect=_mock_execute)
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/deployments/'
                'promotion-options'
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['from_environment'], 'testing')
        self.assertEqual(data[0]['to_environment'], 'staging')
        self.assertEqual(data[0]['from_version'], 'v6.4.0')
        self.assertEqual(data[0]['to_version'], 'v6.3.0')
        # Fake plugin's compare() returns ahead=1.
        self.assertEqual(data[0]['commits_pending'], 1)
        self.assertEqual(data[1]['from_environment'], 'staging')
        self.assertEqual(data[1]['to_environment'], 'production')

    def test_promotion_options_picks_latest_release_per_env(self) -> None:
        # Two rows for the same env: an older v6.3.0 with an earlier
        # event timestamp and a newer v6.4.0.  The reducer should pick
        # v6.4.0 as the testing env's current release.  We pair it
        # against staging (single-row) so the test asserts the
        # deterministic ordering rather than the staging row choice.
        def _mock_execute(query, params, columns):
            del query, params, columns
            return [
                {
                    'env': '{"slug": "testing", "name": "Testing", '
                    '"sort_order": 1}',
                    'release': '{"tag": "v6.3.0", "committish": "bbb6300"}',
                    'deployments': (
                        '[{"timestamp": "2024-01-01T00:00:00+00:00", '
                        '"status": "success"}]'
                    ),
                },
                {
                    'env': '{"slug": "testing", "name": "Testing", '
                    '"sort_order": 1}',
                    'release': '{"tag": "v6.4.0", "committish": "aaa6400"}',
                    'deployments': (
                        '[{"timestamp": "2024-06-01T00:00:00+00:00", '
                        '"status": "success"}]'
                    ),
                },
                {
                    'env': '{"slug": "staging", "name": "Staging", '
                    '"sort_order": 2}',
                    'release': '{"tag": "v6.2.0", "committish": "ccc6200"}',
                    'deployments': None,
                },
            ]

        self.mock_db.execute = mock.AsyncMock(side_effect=_mock_execute)
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/deployments/'
                'promotion-options'
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['from_environment'], 'testing')
        self.assertEqual(data[0]['from_version'], 'v6.4.0')
        self.assertEqual(data[0]['to_version'], 'v6.2.0')

    def test_promotion_options_falls_back_to_non_null_release(self) -> None:
        # When neither row for an env has any deployment events, the
        # reducer should still surface a non-null release if one row
        # has it.
        def _mock_execute(query, params, columns):
            del query, params, columns
            return [
                {
                    'env': '{"slug": "testing", "name": "Testing", '
                    '"sort_order": 1}',
                    'release': None,
                    'deployments': None,
                },
                {
                    'env': '{"slug": "testing", "name": "Testing", '
                    '"sort_order": 1}',
                    'release': '{"tag": "v1.0.0", "committish": "abc1000"}',
                    'deployments': None,
                },
                {
                    'env': '{"slug": "staging", "name": "Staging", '
                    '"sort_order": 2}',
                    'release': '{"tag": "v0.9.0", "committish": "def0900"}',
                    'deployments': None,
                },
            ]

        self.mock_db.execute = mock.AsyncMock(side_effect=_mock_execute)
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/deployments/'
                'promotion-options'
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['from_version'], 'v1.0.0')

    def test_get_run_status_returns_plugin_status(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/deployments/runs/42'
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['run_id'], '42')
        self.assertEqual(data['status'], 'in_progress')

    def test_get_run_status_400_when_plugin_unsupported(self) -> None:
        class _NoStatus(_FakeDeploymentPlugin):
            async def get_deployment_status(  # type: ignore[override]
                self, ctx, credentials, run_id
            ):
                raise NotImplementedError

        self.mocks['resolve_plugin'].return_value = ResolvedPlugin(
            plugin_id='p-1',
            plugin_slug='no-status',
            entry=RegistryEntry(
                handler_cls=_NoStatus,
                manifest=_NoStatus.manifest,
                package_name='x',
                package_version='1',
            ),
            options={},
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/deployments/runs/abc'
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'does not report deployment status', response.json()['detail']
        )

    def test_deploy_writes_operations_log_audit(self) -> None:
        self.mocks['append_deployment_event'].return_value = mock.Mock()
        # Mock _release_id_for so the deploy flow finds a Release node —
        # the audit row is only written when a deploy ties back to a
        # known Release (see L24).
        self._start(
            mock.patch(
                f'{_MODULE}._release_id_for',
                return_value='matched-release-id',
            )
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'deploy',
                    'environment': 'testing',
                    'committish': 'abc1234',
                    'ref_label': 'main',
                },
            )
        self.assertEqual(response.status_code, 202)
        ch = self.mocks['clickhouse'].return_value
        ch.insert.assert_awaited_once()
        args, _kwargs = ch.insert.call_args
        self.assertEqual(args[0], 'operations_log')
        rows = args[1]
        cols = args[2]
        self.assertEqual(len(rows), 1)
        row = dict(zip(cols, rows[0], strict=False))
        self.assertEqual(row['entry_type'], 'Deployed')
        self.assertEqual(row['environment_slug'], 'testing')
        self.assertEqual(row['link'], 'https://gh/runs/42')
        # ``ref_label='main'`` is not semver-shaped, so it's treated as
        # a non-tag and the audit row's ``version`` falls back to the
        # committish short SHA.
        self.assertEqual(row['version'], 'abc1234')
        self.assertEqual(row['plugin_slug'], 'github-deployment')

    def test_promote_writes_operations_log_audit(self) -> None:
        self.mocks['append_deployment_event'].return_value = mock.Mock()
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'promote',
                    'from_environment': 'testing',
                    'to_environment': 'staging',
                    'from_committish': '1a9c610',
                    'tag': 'v6.4.0',
                },
            )
        self.assertEqual(response.status_code, 202)
        ch = self.mocks['clickhouse'].return_value
        ch.insert.assert_awaited_once()
        args, _kwargs = ch.insert.call_args
        rows = args[1]
        cols = args[2]
        row = dict(zip(cols, rows[0], strict=False))
        self.assertEqual(row['entry_type'], 'Deployed')
        self.assertEqual(row['environment_slug'], 'staging')
        self.assertEqual(row['version'], 'v6.4.0')
        self.assertEqual(row['plugin_slug'], 'github-deployment')

    def test_deploy_suppresses_audit_when_no_release_matches(self) -> None:
        # L24: when ``_release_id_for`` returns no match, the workflow
        # was still dispatched but we cannot tie it to a Release node,
        # so the audit row is suppressed to keep operations_log clean.
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'deploy',
                    'environment': 'testing',
                    'committish': 'abc1234',
                    'ref_label': 'main',
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.json()['recorded'])
        ch = self.mocks['clickhouse'].return_value
        ch.insert.assert_not_called()


class ResyncProjectDeploymentsTestCase(ProjectDeploymentsTestCase):
    """End-to-end coverage for the per-project resync endpoint."""

    def _arm(
        self,
        recent: list[RemoteDeployment],
        *,
        environments: list[str] | None = None,
        release_exists: bool = False,
        edge_status: typing.Literal['append', 'dedupe', 'missing'] = 'append',
    ) -> None:
        self._FakeDeploymentPlugin_recent = recent  # for visibility
        # The endpoint instantiates a new plugin per call so we patch the
        # handler factory directly to inject the prepared rows.
        plugin = _FakeDeploymentPlugin()
        plugin._recent = recent  # type: ignore[attr-defined]
        self.mocks['handler'] = self._start(
            mock.patch(
                f'{_MODULE}._handler',
                return_value=plugin,
            )
        )
        self.mocks['load_envs'] = self._start(
            mock.patch(
                f'{_MODULE}._load_resync_environments',
                return_value=environments
                if environments is not None
                else [o.environment for o in recent],
            )
        )
        self.mocks['release_exists'] = self._start(
            mock.patch(
                f'{_MODULE}._release_id_for',
                # Existing returns a release_id; missing returns None
                return_value='existing-release-id' if release_exists else None,
            )
        )
        self.mocks['upsert_release_node'] = self._start(
            mock.patch(
                f'{_MODULE}._upsert_release_node',
                return_value='upserted-release-id',
            )
        )
        if edge_status == 'missing':
            self.mocks['append_deployment_event'].return_value = None
        else:
            outcome = 'noop' if edge_status == 'dedupe' else 'appended'
            edge = mock.Mock(
                deployments=[
                    mock.Mock(external_run_id=o.external_run_id)
                    for o in recent
                ]
            )
            self.mocks['append_deployment_event'].return_value = (
                edge,
                outcome,
            )

    def _observed(
        self,
        *,
        environment: str = 'infrastructure-testing',
        ref: str | None = 'main',
        sha: str = '2668cd0abcdef',
        status: str = 'success',
        external_run_id: str = '12345',
        creator: str | None = 'octocat',
        creator_subject: str | None = None,
    ) -> RemoteDeployment:
        return RemoteDeployment(
            environment=environment,
            sha=sha,
            ref=ref,
            status=typing.cast(typing.Any, status),
            created_at=datetime.datetime(
                2026, 5, 13, 14, 0, tzinfo=datetime.UTC
            ),
            external_run_id=external_run_id,
            run_url='https://gh/runs/12345',
            deployment_url=(
                'https://api.github.com/repos/octo/demo/deployments/12345'
            ),
            description='Bump foo',
            creator=creator,
            creator_subject=creator_subject,
        )

    def test_resync_persists_release_and_event_for_sha(self) -> None:
        observed = self._observed()
        self._arm([observed], release_exists=False)
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/resync'
            )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['projects'], 1)
        self.assertEqual(data['observed'], 1)
        self.assertEqual(data['releases_created'], 1)
        self.assertEqual(data['releases_updated'], 0)
        self.assertEqual(data['events_recorded'], 1)
        self.assertEqual(data['errors'], [])
        # Sha-style ref produces (tag=None, committish=sha[:7]).
        upsert_call = self.mocks['upsert_release_node'].call_args
        self.assertIsNone(upsert_call.kwargs['tag'])
        self.assertEqual(upsert_call.kwargs['committish'], '2668cd0')
        append_call = self.mocks['append_deployment_event'].call_args
        self.assertEqual(
            append_call.kwargs['release_id'], 'upserted-release-id'
        )
        self.assertEqual(
            append_call.kwargs['env_slug'], 'infrastructure-testing'
        )
        self.assertEqual(append_call.kwargs['external_run_id'], '12345')
        self.assertEqual(append_call.kwargs['timestamp'], observed.created_at)

    def test_resync_uses_semver_ref_as_tag(self) -> None:
        self._arm(
            [self._observed(ref='v1.2.3', sha='deadbeefcafebabe')],
            release_exists=True,
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/resync'
            )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['releases_created'], 0)
        self.assertEqual(data['releases_updated'], 1)
        upsert_call = self.mocks['upsert_release_node'].call_args
        self.assertEqual(upsert_call.kwargs['tag'], 'v1.2.3')
        self.assertEqual(upsert_call.kwargs['committish'], 'deadbee')

    def test_resync_400_when_plugin_opts_out(self) -> None:
        # Override the resolved plugin to advertise the no-sync flavor.
        self.mocks['resolve_plugin'].return_value = ResolvedPlugin(
            plugin_id='p-1',
            plugin_slug='no-sync-deployment',
            entry=RegistryEntry(
                handler_cls=_FakeNoSyncDeploymentPlugin,
                manifest=_FakeNoSyncDeploymentPlugin.manifest,
                package_name='imbi-plugin-test',
                package_version='0.1.0',
            ),
            options={'owner': 'octo', 'repo': 'demo'},
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/resync'
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('does not support', response.json()['detail'])

    def test_resync_no_environments_returns_zero(self) -> None:
        self._arm([], environments=[])
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/resync'
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['observed'], 0)
        self.mocks['upsert_release_node'].assert_not_called()
        self.mocks['append_deployment_event'].assert_not_called()

    def test_resync_records_missing_edge_as_error(self) -> None:
        self._arm([self._observed()], edge_status='missing')
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/resync'
            )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(len(data['errors']), 1)
        self.assertEqual(
            data['errors'][0]['environment'], 'infrastructure-testing'
        )
        self.assertEqual(data['events_recorded'], 0)

    def test_resync_does_not_write_operations_log_audit(self) -> None:
        """Resync must not poison ``argMax(performed_by, occurred_at)``.

        Backfilling historical remote deployments through the
        ``operations_log`` would attribute every event to whoever
        clicked "Resync", overriding the v1-migrated rows that already
        carry the real deployer.  The ``DEPLOYED_TO`` edge alone
        carries the event during resync; in-product deploy / promote
        flows still write their own audit rows.
        """
        self._arm([self._observed()])
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/resync'
            )
        self.assertEqual(response.status_code, 200, response.text)
        ch = self.mocks['clickhouse'].return_value
        ch.insert.assert_not_awaited()

    def test_resync_threads_creator_to_performed_by(self) -> None:
        """``observed.creator`` becomes ``DeploymentEvent.performed_by``."""
        self._arm([self._observed(creator='octocat')])
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/resync'
            )
        self.assertEqual(response.status_code, 200, response.text)
        append_call = self.mocks['append_deployment_event'].call_args
        self.assertEqual(append_call.kwargs['performed_by'], 'octocat')

    def test_resync_resolves_creator_subject_to_imbi_user(self) -> None:
        """A resolvable ``creator_subject`` attributes the deploy to the
        matching Imbi user's email rather than the raw remote login."""
        self._arm([self._observed(creator='kevinv', creator_subject='42')])

        async def _resolver(subject: str) -> str | None:
            return 'kevin@example.com' if subject == '42' else None

        self._start(
            mock.patch(
                f'{_MODULE}.attribution.load_service_plugins',
                new=mock.AsyncMock(return_value=[mock.Mock()]),
            )
        )
        self._start(
            mock.patch(
                f'{_MODULE}.attribution.make_user_resolver',
                return_value=_resolver,
            )
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/resync'
            )
        self.assertEqual(response.status_code, 200, response.text)
        append_call = self.mocks['append_deployment_event'].call_args
        self.assertEqual(
            append_call.kwargs['performed_by'], 'kevin@example.com'
        )

    def test_resync_unresolved_subject_keeps_login(self) -> None:
        """An unresolved subject falls back to the raw remote login."""
        self._arm([self._observed(creator='kevinv', creator_subject='99')])

        async def _resolver(_subject: str) -> str | None:
            return None

        self._start(
            mock.patch(
                f'{_MODULE}.attribution.load_service_plugins',
                new=mock.AsyncMock(return_value=[mock.Mock()]),
            )
        )
        self._start(
            mock.patch(
                f'{_MODULE}.attribution.make_user_resolver',
                return_value=_resolver,
            )
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/resync'
            )
        self.assertEqual(response.status_code, 200, response.text)
        append_call = self.mocks['append_deployment_event'].call_args
        self.assertEqual(append_call.kwargs['performed_by'], 'kevinv')

    def test_resync_defaults_limit_to_one(self) -> None:
        """Absent ``limit`` keeps the cheap latest-per-env catch-up."""
        self._arm([self._observed()])
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/resync'
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.mocks['handler'].return_value._last_limit, 1)

    def test_resync_threads_limit_to_plugin(self) -> None:
        """``?limit=N`` reaches ``list_recent_deployments`` for a deeper
        backfill that re-resolves historical attribution."""
        self._arm([self._observed()])
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/resync'
                '?limit=50'
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.mocks['handler'].return_value._last_limit, 50)

    def test_resync_rejects_out_of_range_limit(self) -> None:
        """``limit`` is clamped to the 1..100 GitHub per-page window."""
        self._arm([self._observed()])
        with testclient.TestClient(self.test_app) as client:
            self.assertEqual(
                client.post(
                    '/organizations/myorg/projects/proj1/deployments/'
                    'resync?limit=0'
                ).status_code,
                422,
            )
            self.assertEqual(
                client.post(
                    '/organizations/myorg/projects/proj1/deployments/'
                    'resync?limit=101'
                ).status_code,
                422,
            )

    def test_resync_requires_write_permission(self) -> None:
        non_admin = models.User(
            email='dev@example.com',
            display_name='Dev',
            is_active=True,
            is_admin=False,
            password_hash=password.hash_password('testpassword123'),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=non_admin,
            session_id='test-session',
            auth_method='jwt',
            permissions={'project:deployment:read'},
        )

        async def _ctx() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = _ctx
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments/resync'
            )
        self.assertEqual(response.status_code, 403)


class FallbackNotesTestCase(unittest.TestCase):
    """Direct tests for ``_classify_bump`` and ``_fallback_notes``."""

    def test_classify_bump_breaking(self) -> None:
        from imbi_api.endpoints.project_deployments import _classify_bump

        commits = [Commit(sha='a', short_sha='a', message='feat!: drop')]
        self.assertEqual(_classify_bump(commits), 'major')

    def test_classify_bump_feature(self) -> None:
        from imbi_api.endpoints.project_deployments import _classify_bump

        commits = [Commit(sha='a', short_sha='a', message='feat: new thing')]
        self.assertEqual(_classify_bump(commits), 'minor')

    def test_classify_bump_patch_default(self) -> None:
        from imbi_api.endpoints.project_deployments import _classify_bump

        commits = [Commit(sha='a', short_sha='a', message='fix: thing')]
        self.assertEqual(_classify_bump(commits), 'patch')

    def test_fallback_notes_groups_by_prefix(self) -> None:
        from imbi_api.endpoints.project_deployments import _fallback_notes

        commits = [
            Commit(sha='a', short_sha='aaa', message='feat: one'),
            Commit(sha='b', short_sha='bbb', message='fix: two'),
            Commit(sha='c', short_sha='ccc', message='feat: three'),
        ]
        body = _fallback_notes(commits)
        self.assertIn('### feat', body)
        self.assertIn('### fix', body)
        self.assertIn('feat: one (aaa)', body)
        self.assertIn('fix: two (bbb)', body)

    def test_fallback_notes_empty(self) -> None:
        from imbi_api.endpoints.project_deployments import _fallback_notes

        self.assertIn('No commits', _fallback_notes([]))

    def test_fallback_notes_falls_back_to_other_for_long_prefix(self) -> None:
        from imbi_api.endpoints.project_deployments import _fallback_notes

        commits = [
            Commit(
                sha='a',
                short_sha='aaa',
                message='thisprefixiswaytoolong: hi',
            ),
        ]
        body = _fallback_notes(commits)
        self.assertIn('### other', body)


class LatestDeploymentTimestampTestCase(unittest.TestCase):
    """Direct tests for ``_latest_deployment_timestamp``."""

    def test_returns_none_for_empty_or_missing(self) -> None:
        from imbi_api.endpoints.project_deployments import (
            _latest_deployment_timestamp,
        )

        self.assertIsNone(_latest_deployment_timestamp(None))
        self.assertIsNone(_latest_deployment_timestamp(''))
        self.assertIsNone(_latest_deployment_timestamp('[]'))

    def test_returns_none_for_non_list_payloads(self) -> None:
        from imbi_api.endpoints.project_deployments import (
            _latest_deployment_timestamp,
        )

        self.assertIsNone(_latest_deployment_timestamp('"oops"'))
        self.assertIsNone(_latest_deployment_timestamp('{"x": 1}'))

    def test_picks_max_timestamp(self) -> None:
        from imbi_api.endpoints.project_deployments import (
            _latest_deployment_timestamp,
        )

        raw = (
            '[{"timestamp": "2024-01-01T00:00:00+00:00", "status": "success"},'
            ' {"timestamp": "2024-06-01T00:00:00+00:00", "status": "success"},'
            ' {"timestamp": "2024-03-01T00:00:00+00:00", "status": "success"}]'
        )
        result = _latest_deployment_timestamp(raw)
        self.assertEqual(
            result,
            datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC),
        )

    def test_skips_invalid_entries(self) -> None:
        from imbi_api.endpoints.project_deployments import (
            _latest_deployment_timestamp,
        )

        raw = (
            '[{"timestamp": "not-a-date", "status": "success"},'
            ' "scalar",'
            ' {"timestamp": 42, "status": "success"},'
            ' {"timestamp": "2024-06-01T00:00:00+00:00", '
            '"status": "success"}]'
        )
        result = _latest_deployment_timestamp(raw)
        self.assertEqual(
            result,
            datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC),
        )

    def test_accepts_already_decoded_list(self) -> None:
        from imbi_api.endpoints.project_deployments import (
            _latest_deployment_timestamp,
        )

        result = _latest_deployment_timestamp(
            [{'timestamp': '2024-06-01T00:00:00+00:00', 'status': 'success'}]
        )
        self.assertEqual(
            result,
            datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC),
        )


class SafeAuditUrlTestCase(unittest.TestCase):
    """Direct tests for ``_safe_audit_url`` (L22)."""

    def test_returns_none_for_none(self) -> None:
        from imbi_api.endpoints.project_deployments import _safe_audit_url

        self.assertIsNone(_safe_audit_url(None))

    def test_allows_http_and_https(self) -> None:
        from imbi_api.endpoints.project_deployments import _safe_audit_url

        for url in (
            'http://example.com/run/42',
            'https://github.com/o/r/actions/runs/1',
        ):
            self.assertEqual(_safe_audit_url(url), url)

    def test_strips_javascript_scheme(self) -> None:
        from imbi_api.endpoints.project_deployments import _safe_audit_url

        self.assertIsNone(_safe_audit_url('javascript:alert(1)'))
        self.assertIsNone(_safe_audit_url('JavaScript:alert(1)'))

    def test_strips_data_scheme(self) -> None:
        from imbi_api.endpoints.project_deployments import _safe_audit_url

        self.assertIsNone(_safe_audit_url('data:text/html,<script>x</script>'))

    def test_strips_file_scheme(self) -> None:
        from imbi_api.endpoints.project_deployments import _safe_audit_url

        self.assertIsNone(_safe_audit_url('file:///etc/passwd'))


def _relocating_resolved() -> ResolvedPlugin:
    return ResolvedPlugin(
        plugin_id='p-1',
        plugin_slug='github-deployment',
        entry=RegistryEntry(
            handler_cls=_RelocatingDeploymentPlugin,
            manifest=_RelocatingDeploymentPlugin.manifest,
            package_name='imbi-plugin-github',
            package_version='0.1.0',
        ),
        options={'owner': 'octo', 'repo': 'demo'},
    )


class LinkWritebackPersistTestCase(ProjectDeploymentsTestCase):
    """The endpoint persists the stored link when a plugin reports a
    canonical-URL change on ``ctx.link_writeback``.
    """

    def setUp(self) -> None:
        super().setUp()
        self.mocks['resolve_plugin'].return_value = _relocating_resolved()
        # update_project_link is async; patch auto-uses AsyncMock.
        self.update_link = self._start(
            mock.patch(_UPDATE_LINK, return_value=True)
        )

    def test_list_commits_persists_link_writeback(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                '/organizations/myorg/projects/proj1/deployments/'
                'refs/main/commits'
            )
        self.assertEqual(response.status_code, 200)
        self.update_link.assert_awaited_once()
        args = self.update_link.await_args.args
        # (db, project_id, link_key, new_url)
        self.assertEqual(args[2], 'github-repository')
        self.assertEqual(args[3], 'https://github.com/octo/renamed')

    def test_trigger_deploy_persists_link_writeback(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                '/organizations/myorg/projects/proj1/deployments',
                json={
                    'action': 'deploy',
                    'environment': 'testing',
                    'committish': 'main',
                    'ref_label': 'main',
                },
            )
        self.assertEqual(response.status_code, 202)
        self.update_link.assert_awaited_once()
        self.assertEqual(
            self.update_link.await_args.args[3],
            'https://github.com/octo/renamed',
        )


class PersistLinkWritebackTestCase(unittest.IsolatedAsyncioTestCase):
    """Unit coverage for ``persist_link_writeback``."""

    def _ctx(self, wb: LinkWriteback | None) -> mock.MagicMock:
        ctx = mock.MagicMock()
        ctx.project_id = 'proj1'
        ctx.link_writeback = wb
        return ctx

    async def test_noop_when_no_writeback(self) -> None:
        db = mock.AsyncMock()
        with mock.patch(_UPDATE_LINK) as update_link:
            await persist_link_writeback(db, self._ctx(None))
        update_link.assert_not_called()

    async def test_writes_when_writeback_present(self) -> None:
        db = mock.AsyncMock()
        wb = LinkWriteback(
            link_key='github-repository',
            new_url='https://github.com/octo/renamed',
            old_owner_repo='octo/demo',
            new_owner_repo='octo/renamed',
        )
        with mock.patch(_UPDATE_LINK, return_value=True) as update_link:
            await persist_link_writeback(db, self._ctx(wb))
        update_link.assert_awaited_once_with(
            db, 'proj1', 'github-repository', 'https://github.com/octo/renamed'
        )

    async def test_swallows_write_failure(self) -> None:
        db = mock.AsyncMock()
        wb = LinkWriteback(
            link_key='github-repository',
            new_url='https://github.com/octo/renamed',
        )
        with mock.patch(
            _UPDATE_LINK,
            side_effect=RuntimeError('graph down'),
        ):
            # Must not raise — persistence is best-effort.
            await persist_link_writeback(db, self._ctx(wb))


class UpdateProjectLinkTestCase(unittest.IsolatedAsyncioTestCase):
    """Unit coverage for ``_helpers.update_project_link``."""

    async def test_writes_new_value(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            _helpers,
            'lookup_project_links',
            mock.AsyncMock(return_value={'other': 'https://x'}),
        ):
            changed = await _helpers.update_project_link(
                db, 'proj1', 'github-repository', 'https://github.com/o/new'
            )
        self.assertTrue(changed)
        db.execute.assert_awaited_once()
        params = db.execute.await_args.args[1]
        self.assertEqual(params['project_id'], 'proj1')
        self.assertEqual(
            json.loads(params['links']),
            {
                'other': 'https://x',
                'github-repository': 'https://github.com/o/new',
            },
        )

    async def test_noop_when_unchanged(self) -> None:
        db = mock.AsyncMock()
        with mock.patch.object(
            _helpers,
            'lookup_project_links',
            mock.AsyncMock(
                return_value={'github-repository': 'https://github.com/o/new'}
            ),
        ):
            changed = await _helpers.update_project_link(
                db, 'proj1', 'github-repository', 'https://github.com/o/new'
            )
        self.assertFalse(changed)
        db.execute.assert_not_called()


class ReleasesTabEndpointsTestCase(ProjectDeploymentsTestCase):
    """recent-commits / release-drift / release-history / releases/cut."""

    _BASE = '/organizations/myorg/projects/proj1/deployments'

    def _patch_query(self, results: list[typing.Any]) -> mock.AsyncMock:
        """Patch ``clickhouse.query``; ``results`` is one entry per call."""
        m = mock.AsyncMock(side_effect=results)
        patcher = mock.patch(f'{_MODULE}.clickhouse.query', new=m)
        patcher.start()
        self.addCleanup(patcher.stop)
        return m

    @staticmethod
    def _commit_row(
        sha: str,
        *,
        message: str = 'fix: a thing',
        author: str = 'Alice',
        ci_status: str = 'pass',
    ) -> dict[str, typing.Any]:
        return {
            'sha': sha,
            'short_sha': sha[:7],
            'message': message,
            'author': author,
            'authored_at': datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            'ci_status': ci_status,
            'url': f'https://gh/commit/{sha}',
        }

    def test_recent_commits_maps_rows(self) -> None:
        query = self._patch_query(
            [
                [
                    self._commit_row('abc1234def'),
                    self._commit_row('999', author=''),
                ]
            ]
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/recent-commits')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data[0]['short_sha'], 'abc1234')
        self.assertEqual(data[0]['ci_status'], 'pass')
        # Empty author coerces to null.
        self.assertIsNone(data[1]['author'])
        # Default limit clamps to 25.
        self.assertEqual(query.await_args.args[1]['limit'], 25)

    def test_recent_commits_clamps_limit_and_passes_ref(self) -> None:
        query = self._patch_query([[]])
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                f'{self._BASE}/recent-commits?limit=9000&ref=main'
            )
        self.assertEqual(response.status_code, 200)
        params = query.await_args.args[1]
        self.assertEqual(params['limit'], 200)
        self.assertEqual(params['ref'], 'main')

    def test_release_drift_with_tag(self) -> None:
        when = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        self._patch_query(
            [
                [{'name': 'v1.0.0', 'sha': 'tagsha', 'tagged_at': when}],
                [{'sha': 'headsha'}],
                [{'authored_at': when}],
                [self._commit_row('feat1', message='feat: new thing')],
                [{'c': 1}],
            ]
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/release-drift')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['latest_tag'], 'v1.0.0')
        self.assertEqual(data['head_sha'], 'headsha')
        self.assertEqual(data['commits_since_tag'], 1)
        self.assertEqual(data['suggested_bump'], 'minor')
        self.assertEqual(data['suggested_tag'], 'v1.1.0')

    def test_release_drift_no_tag(self) -> None:
        self._patch_query(
            [
                [],  # no tags
                [{'sha': 'headsha'}],
                [self._commit_row('c1', message='feat: first feature')],
                [{'c': 1}],
            ]
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/release-drift')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data['latest_tag'])
        # No prior tag + a feat commit -> minor bump off v0.0.0 -> v0.1.0.
        self.assertEqual(data['suggested_tag'], 'v0.1.0')
        self.assertEqual(data['commits_since_tag'], 1)

    def test_release_drift_tag_commit_not_synced(self) -> None:
        self._patch_query(
            [
                [{'name': 'v2.0.0', 'sha': 'missing', 'tagged_at': None}],
                [{'sha': 'headsha'}],
                [],  # base commit not in ClickHouse
            ]
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/release-drift')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['commits_since_tag'], 0)
        self.assertEqual(data['commits'], [])
        self.assertEqual(data['suggested_tag'], 'v2.0.1')

    def test_release_drift_picks_highest_semver_not_newest(self) -> None:
        """A late-synced lower version must not out-rank the latest release."""
        older = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        newer = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)
        self._patch_query(
            [
                [
                    # v4.1.3 (a backport) was tagged most recently, but
                    # v7.1.0 is the highest version -> the real base.
                    {
                        'name': 'v4.1.3',
                        'sha': 'sha413',
                        'tagged_at': newer,
                        'recorded_at': newer,
                    },
                    {
                        'name': 'v7.1.0',
                        'sha': 'sha710',
                        'tagged_at': older,
                        'recorded_at': older,
                    },
                ],
                [{'sha': 'headsha'}],
                [{'authored_at': older}],
                [self._commit_row('feat1', message='feat: new thing')],
                [{'c': 2}],
            ]
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/release-drift')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['latest_tag'], 'v7.1.0')
        self.assertEqual(data['latest_tag_sha'], 'sha710')
        # A feat commit bumps the minor off v7.1.0, not off v4.1.3.
        self.assertEqual(data['suggested_tag'], 'v7.2.0')

    def test_release_drift_latest_tag_at_falls_back_to_recorded_at(
        self,
    ) -> None:
        """``latest_tag_at`` uses ``recorded_at`` when ``tagged_at`` null."""
        recorded = datetime.datetime(2026, 3, 2, tzinfo=datetime.UTC)
        self._patch_query(
            [
                [
                    {
                        'name': 'v1.0.0',
                        'sha': 'tagsha',
                        'tagged_at': None,
                        'recorded_at': recorded,
                    }
                ],
                [{'sha': 'headsha'}],
                [{'authored_at': recorded}],
                [self._commit_row('feat1', message='feat: new thing')],
                [{'c': 1}],
            ]
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/release-drift')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNotNone(data['latest_tag_at'])
        self.assertEqual(
            datetime.datetime.fromisoformat(data['latest_tag_at']),
            recorded,
        )

    def test_release_history_joins_tags_and_nodes(self) -> None:
        when = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        self._patch_query(
            [
                [
                    {
                        'name': 'v1.0.0',
                        'sha': 'sha10',
                        'tagged_at': when,
                        'tagger_name': 'Rel Bot',
                        'url': 'https://gh/releases/tag/v1.0.0',
                        'recorded_at': when,
                    },
                    {
                        'name': 'v0.9.0',
                        'sha': 'sha09',
                        'tagged_at': None,
                        'tagger_name': '',
                        'url': '',
                        'recorded_at': when,
                    },
                ],
                # ci_status lookup
                [{'sha': 'sha10', 'ci_status': 'pass'}],
            ]
        )

        def _mock_execute(query, params, columns):
            del query, params, columns
            return [
                {
                    'release': json.dumps(
                        {
                            'tag': 'v1.0.0',
                            'title': 'Release 1.0.0',
                            'description': '## Notes',
                            'created_by': 'gr',
                            'links': json.dumps(
                                [
                                    {
                                        'type': 'github_release',
                                        'url': 'https://gh/releases/v1.0.0',
                                    }
                                ]
                            ),
                        }
                    )
                }
            ]

        self.mock_db.execute = mock.AsyncMock(side_effect=_mock_execute)
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/release-history')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        first = data[0]
        self.assertEqual(first['tag'], 'v1.0.0')
        self.assertEqual(first['notes_markdown'], '## Notes')
        self.assertEqual(first['release_url'], 'https://gh/releases/v1.0.0')
        self.assertEqual(first['ci_status'], 'pass')
        # Tag with no matching Release node -> null metadata, unknown CI.
        self.assertIsNone(data[1]['notes_markdown'])
        self.assertEqual(data[1]['ci_status'], 'unknown')

    def test_release_history_head_is_highest_semver_not_newest(self) -> None:
        """The head of history is the highest semver, ignoring timestamps.

        A late-synced lower version (newer timestamp) must not out-rank the
        highest semver tag, mirroring the drift base selection.  This guards
        against re-introducing a timestamp-limited candidate window that could
        drop the highest version before the semver sort runs.
        """
        older = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        newer = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)
        self._patch_query(
            [
                [
                    {
                        'name': 'v4.1.3',
                        'sha': 'sha413',
                        'tagged_at': newer,
                        'tagger_name': 'Rel Bot',
                        'url': '',
                        'recorded_at': newer,
                    },
                    {
                        'name': 'v7.1.0',
                        'sha': 'sha710',
                        'tagged_at': older,
                        'tagger_name': 'Rel Bot',
                        'url': '',
                        'recorded_at': older,
                    },
                ],
                # ci_status lookup
                [],
            ]
        )
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/release-history')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([e['tag'] for e in data], ['v7.1.0', 'v4.1.3'])

    def test_release_history_limit_applies_after_semver_sort(self) -> None:
        """``limit`` slices the semver-sorted list, keeping top versions."""
        when = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        self._patch_query(
            [
                [
                    {
                        'name': f'v{major}.0.0',
                        'sha': f'sha{major}',
                        'tagged_at': when,
                        'tagger_name': 'Rel Bot',
                        'url': '',
                        'recorded_at': when,
                    }
                    for major in (1, 5, 3, 2, 4)
                ],
                [],
            ]
        )
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/release-history?limit=2')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([e['tag'] for e in data], ['v5.0.0', 'v4.0.0'])

    def test_cut_release_creates_tag_and_release_no_deploy(self) -> None:
        triggered: dict[str, bool] = {'called': False}

        class _NoDeploy(_FakeDeploymentPlugin):
            async def trigger_deployment(  # type: ignore[override]
                self, ctx, credentials, ref_or_sha, inputs=None
            ):
                triggered['called'] = True
                return await super().trigger_deployment(
                    ctx, credentials, ref_or_sha, inputs
                )

        self.mocks['resolve_plugin'].return_value = ResolvedPlugin(
            plugin_id='p-1',
            plugin_slug='github-deployment',
            entry=RegistryEntry(
                handler_cls=_NoDeploy,
                manifest=_NoDeploy.manifest,
                package_name='x',
                package_version='1',
            ),
            options={'owner': 'octo', 'repo': 'demo'},
        )
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                f'{self._BASE}/releases/cut',
                json={
                    'committish': '1a9c610',
                    'tag': 'v6.5.0',
                    'release_notes_markdown': '## Notes',
                },
            )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['tag'], 'v6.5.0')
        self.assertEqual(data['committish'], '1a9c610')
        self.assertTrue(data['recorded'])
        self.assertEqual(data['release_url'], 'https://gh/releases/v6.5.0')
        self.assertIsNone(data['warning'])
        # No deployment is dispatched for a library release.
        self.assertFalse(triggered['called'])

    def test_cut_release_rejects_tag_violating_configured_format(
        self,
    ) -> None:
        self.mocks['_resolve_tag_formats'].return_value = [SEMVER_TAG_FORMAT]
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                f'{self._BASE}/releases/cut',
                json={'committish': '1a9c610', 'tag': 'main'},
            )
        self.assertEqual(response.status_code, 400)
        detail = response.json()['detail']
        self.assertIn('does not match any configured tag format', detail)
        self.assertIn('Semver', detail)

    def test_cut_release_accepts_tag_matching_custom_format(self) -> None:
        self.mocks['_resolve_tag_formats'].return_value = [
            TagFormat(label='CalVer', pattern=r'\d{4}\.\d{2}\.\d+')
        ]
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                f'{self._BASE}/releases/cut',
                json={'committish': '1a9c610', 'tag': '2026.06.1'},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['tag'], '2026.06.1')

    def test_cut_release_allows_any_tag_when_no_format_configured(
        self,
    ) -> None:
        # Default policy is empty -> any tag is accepted.
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                f'{self._BASE}/releases/cut',
                json={'committish': '1a9c610', 'tag': 'nightly-build'},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['tag'], 'nightly-build')

    def test_cut_release_rejects_non_sha_committish(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                f'{self._BASE}/releases/cut',
                json={'committish': 'main', 'tag': 'v1.2.3'},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('git SHA', response.json()['detail'])

    def test_cut_release_degrades_create_release_failure_to_warning(
        self,
    ) -> None:
        class _BoomRelease(_FakeDeploymentPlugin):
            async def create_release(  # type: ignore[override]
                self,
                ctx,
                credentials,
                tag,
                name,
                body_markdown,
                prerelease=False,
            ):
                raise RuntimeError('boom')

        self.mocks['resolve_plugin'].return_value = ResolvedPlugin(
            plugin_id='p-1',
            plugin_slug='github-deployment',
            entry=RegistryEntry(
                handler_cls=_BoomRelease,
                manifest=_BoomRelease.manifest,
                package_name='x',
                package_version='1',
            ),
            options={},
        )
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                f'{self._BASE}/releases/cut',
                json={'committish': '1a9c610', 'tag': 'v6.5.0'},
            )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIsNotNone(data['warning'])
        self.assertIn('create_release', data['warning'])


class ResolveTagFormatsTestCase(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the ``_resolve_tag_formats`` cascade helper."""

    @staticmethod
    def _db(org_formats: typing.Any, pt_formats: typing.Any) -> mock.AsyncMock:
        db = mock.AsyncMock(spec=graph.Graph)
        db.execute = mock.AsyncMock(
            return_value=[
                {'org_formats': org_formats, 'pt_formats': pt_formats}
            ]
        )
        return db

    async def test_project_type_overrides_org(self) -> None:
        db = self._db(
            org_formats=[{'label': 'Org', 'pattern': 'a'}],
            pt_formats=[[{'label': 'PT', 'pattern': 'b'}]],
        )
        result = await project_deployments._resolve_tag_formats(
            db, 'org', 'pid'
        )
        self.assertEqual([f.label for f in result], ['PT'])

    async def test_falls_back_to_org_when_no_project_type_formats(
        self,
    ) -> None:
        db = self._db(
            org_formats=[{'label': 'Org', 'pattern': 'a'}],
            pt_formats=[[]],
        )
        result = await project_deployments._resolve_tag_formats(
            db, 'org', 'pid'
        )
        self.assertEqual([f.label for f in result], ['Org'])

    async def test_empty_when_neither_configured(self) -> None:
        db = self._db(org_formats=None, pt_formats=[])
        result = await project_deployments._resolve_tag_formats(
            db, 'org', 'pid'
        )
        self.assertEqual(result, [])

    async def test_unions_multiple_project_types(self) -> None:
        db = self._db(
            org_formats=[{'label': 'Org', 'pattern': 'a'}],
            pt_formats=[
                [{'label': 'A', 'pattern': 'a'}],
                [{'label': 'B', 'pattern': 'b'}],
            ],
        )
        result = await project_deployments._resolve_tag_formats(
            db, 'org', 'pid'
        )
        self.assertEqual({f.label for f in result}, {'A', 'B'})

    async def test_lookup_failure_returns_empty(self) -> None:
        db = mock.AsyncMock(spec=graph.Graph)
        db.execute = mock.AsyncMock(side_effect=RuntimeError('boom'))
        result = await project_deployments._resolve_tag_formats(
            db, 'org', 'pid'
        )
        self.assertEqual(result, [])

    async def test_skips_malformed_stored_format(self) -> None:
        db = self._db(
            org_formats=None,
            pt_formats=[[{'label': 'Good', 'pattern': 'a'}, {'oops': 1}]],
        )
        result = await project_deployments._resolve_tag_formats(
            db, 'org', 'pid'
        )
        self.assertEqual([f.label for f in result], ['Good'])

    async def test_falls_back_to_org_when_project_type_all_malformed(
        self,
    ) -> None:
        db = self._db(
            org_formats=[{'label': 'Org', 'pattern': 'a'}],
            pt_formats=[[{'oops': 1}]],
        )
        result = await project_deployments._resolve_tag_formats(
            db, 'org', 'pid'
        )
        self.assertEqual([f.label for f in result], ['Org'])
