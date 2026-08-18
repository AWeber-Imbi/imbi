"""Tests for the project deployment plugin endpoints."""

import asyncio
import datetime
import json
import typing
import unittest
from unittest import mock

import fastapi
import httpx
from fastapi import testclient

from apps.api.tests import support
from imbi.api import models
from imbi.api.auth import password, permissions
from imbi.api.endpoints import _helpers, project_deployments
from imbi.api.endpoints.project_deployments import (
    DraftReleaseNotes,
    _EnvFlags,
    persist_link_writeback,
)
from imbi.api.llm.dependencies import _get_anthropic_client
from imbi.api.plugins.resolution import ResolvedCapability
from imbi.common import graph
from imbi.common.llm import AnthropicClient, CompletionResult
from imbi.common.models import SEMVER_TAG_FORMAT, TagFormat
from imbi.common.plugins.base import (
    ArtifactRun,
    Capability,
    Commit,
    CompareResult,
    DeploymentCapability,
    DeploymentRun,
    LinkWriteback,
    Plugin,
    PluginManifest,
    Ref,
    RefInfo,
    ReleaseInfo,
    RemoteDeployment,
    RemoteRelease,
    WorkflowFile,
)
from imbi.common.plugins.registry import RegistryEntry


class _FakeDeploymentPlugin(DeploymentCapability):
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


class _DispatchingDeploymentPlugin(_FakeDeploymentPlugin):
    """Implements the artifact-dispatch half of the capability.

    Records every dispatch on the class so a test driving the endpoint
    through ``TestClient`` can assert what reached the remote.
    """

    dispatches: typing.ClassVar[list[dict[str, typing.Any]]] = []
    run_id: typing.ClassVar[str | None] = '4242'

    async def create_deployment_artifact(  # type: ignore[override]
        self, ctx, credentials, ref, version, inputs=None
    ):
        type(self).dispatches.append(
            {'ref': ref, 'version': version, 'inputs': dict(inputs or {})}
        )
        return ArtifactRun(
            run_id=type(self).run_id,
            run_url='https://ghe/run/4242' if type(self).run_id else None,
            status='queued',
        )

    async def get_artifact_run_status(  # type: ignore[override]
        self, ctx, credentials, run_id
    ):
        return ArtifactRun(run_id=run_id, status='in_progress')


def _listing_plugin(
    *paths: str,
    ids: tuple[str, ...] = (),
    raises: bool = False,
) -> type[DeploymentCapability]:
    """A dispatching plugin whose ``list_workflows`` answers *paths*.

    ``_DispatchingDeploymentPlugin`` deliberately leaves the method
    unimplemented -- that is the capability default, and the preflight
    fails open on it, which is what keeps every other dispatch test on
    this path.  *raises* models a listing call that reaches the remote and
    errors, which must fail open the same way.
    """

    class _ListingPlugin(_DispatchingDeploymentPlugin):
        async def list_workflows(  # type: ignore[override]
            self, ctx, credentials
        ):
            if raises:
                raise RuntimeError('workflows unavailable')
            return [
                WorkflowFile(
                    id=ids[index] if index < len(ids) else str(index),
                    path=path,
                    name=path.rsplit('/', 1)[-1],
                )
                for index, path in enumerate(paths)
            ]

    return _ListingPlugin


def _ci_plugin(
    status: str = 'fail',
    *,
    raises: bool = False,
    base: type[DeploymentCapability] = _FakeDeploymentPlugin,
) -> type[DeploymentCapability]:
    """A deployment plugin whose ``get_check_status`` answers *status*.

    ``_FakeDeploymentPlugin`` deliberately does *not* override
    ``get_check_status`` -- it inherits the capability's ``'unknown'``
    default, which is the status that never gates a promote, so every
    other test in this module stays unaffected by the CI gate.
    """

    class _CiPlugin(base):  # type: ignore[valid-type, misc]
        async def get_check_status(  # type: ignore[override]
            self, ctx, credentials, committish
        ):
            if raises:
                raise RuntimeError('check-runs unavailable')
            return status

    return _CiPlugin


class _FakeNoSyncDeploymentPlugin(_FakeDeploymentPlugin):
    """Deployment plugin that opts *out* of resync."""


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


class _FakePlugin(Plugin):
    pass


def _manifest(
    handler: type[DeploymentCapability],
    *,
    slug: str = 'github-deployment',
    name: str = 'GitHub Deployment',
    sync: bool = True,
) -> PluginManifest:
    hints = {'supports_deployment_sync': True} if sync else {}
    return PluginManifest(
        slug=slug,
        name=name,
        capabilities=[
            Capability(
                kind='deployment',
                label='Deployment',
                handler=handler,
                hints=hints,
            )
        ],
    )


def _entry(
    handler: type[DeploymentCapability] = _FakeDeploymentPlugin,
    *,
    slug: str = 'github-deployment',
    name: str = 'GitHub Deployment',
    sync: bool = True,
) -> RegistryEntry:
    return RegistryEntry(
        plugin_cls=_FakePlugin,
        manifest=_manifest(handler, slug=slug, name=name, sync=sync),
        package_name='imbi-plugin-github',
        package_version='0.1.0',
    )


def _make_resolved(
    handler: type[DeploymentCapability] = _FakeDeploymentPlugin,
    *,
    slug: str = 'github-deployment',
    name: str = 'GitHub Deployment',
    sync: bool = True,
    options: dict[str, typing.Any] | None = None,
    capability_options: dict[str, typing.Any] | None = None,
    env_payloads: dict[str, dict[str, typing.Any]] | None = None,
) -> ResolvedCapability:
    entry = _entry(handler, slug=slug, name=name, sync=sync)
    return ResolvedCapability(
        integration_id='p-1',
        integration_slug=f'{slug}-prod',
        plugin_slug=slug,
        kind='deployment',
        entry=entry,
        capability_cls=entry.manifest.get_capability('deployment').handler,
        integration={'id': 'p-1', 'slug': f'{slug}-prod', 'plugin': slug},
        integration_options=options or {},
        capability_options=capability_options or {},
        encrypted_credentials={},
        env_payloads=env_payloads,
    )


_MODULE = 'imbi.api.endpoints.project_deployments'
_UPDATE_LINK = 'imbi.api.endpoints._helpers.update_project_link'


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
        # Default every ad-hoc Cypher read to "no rows".  Without this the
        # AsyncMock hands back a truthy MagicMock, which reads as a match to
        # any caller that treats a non-empty result as a hit (e.g. the
        # release-block gate).  Tests needing rows set their own side_effect.
        self.mock_db.execute = mock.AsyncMock(return_value=[])
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
            'resolve_capability': self._start(
                mock.patch(
                    f'{_MODULE}.resolve_capability',
                    return_value=self._resolved(),
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
            'decrypt_integration_credentials': self._start(
                mock.patch(
                    f'{_MODULE}.decrypt_integration_credentials',
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

    def _resolved(self) -> ResolvedCapability:
        return _make_resolved(options={'owner': 'octo', 'repo': 'demo'})

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

        self.mocks['resolve_capability'].return_value = _make_resolved(
            _Capturing,
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

        self.mocks['resolve_capability'].return_value = _make_resolved(
            _Capturing,
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
        self.mocks['decrypt_integration_credentials'].return_value = {}
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

    def test_promote_sha_ref_cuts_tag_only(self) -> None:
        # Promote target is a git SHA -- the handler cuts a tag AND
        # dispatches trigger_deployment so the run is tracked in the
        # deployment event.  The GitHub Release is *not* created: it
        # ratifies a successful rollout, so it waits for the
        # deployment_status webhook to drive ``releases/{tag}/publish``.
        created: dict[str, bool] = {'release': False}

        class _WatchRelease(_FakeDeploymentPlugin):
            async def create_release(  # type: ignore[override]
                self,
                ctx,
                credentials,
                tag,
                name,
                body_markdown,
                prerelease=False,
            ):
                created['release'] = True
                return await super().create_release(
                    ctx, credentials, tag, name, body_markdown, prerelease
                )

        self.mocks['resolve_capability'].return_value = _make_resolved(
            _WatchRelease
        )
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
        self.assertIsNone(data['release_url'])
        self.assertFalse(created['release'])
        self.assertTrue(data['recorded'])
        self.assertIsNone(data['warning'])
        call = self.mocks['append_deployment_event'].call_args
        self.assertEqual(call.kwargs['env_slug'], 'staging')
        # Trigger was dispatched -- run id and url are present.
        self.assertEqual(call.kwargs['external_run_id'], '42')
        self.assertEqual(call.kwargs['external_run_url'], 'https://gh/runs/42')

    def test_promote_semver_tag_dispatches_without_publishing(self) -> None:
        # Promote target is a semver tag -- the handler attempts create_tag
        # (idempotently; a real GitHub 422 "already exists" is silently
        # ignored) AND dispatches trigger_deployment.  No release URL comes
        # back because no GitHub Release is created at promote time.
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
        self.assertIsNone(data['release_url'])
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

        self.mocks['resolve_capability'].return_value = _make_resolved(
            _Capturing,
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

        self.mocks['resolve_capability'].return_value = _make_resolved(
            _Boom, slug='boom', options={}
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

        self.mocks['resolve_capability'].return_value = _make_resolved(
            _NoTag, slug='no-tag', options={}
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

        self.mocks['resolve_capability'].return_value = _make_resolved(
            _NoStatus, slug='no-status', options={}
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
    """End-to-end coverage for the background resync flow.

    The endpoint enqueues onto the deployment-sync stream; the worker
    calls :func:`resync_for_project`, which these tests exercise
    directly (endpoint behavior is covered by
    :class:`ResyncEndpointTestCase`).
    """

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
        # No pre-existing tagged Release for the commit by default; a
        # reconcile test overrides this to exercise the SHA-ref path.
        self.mocks['existing_tag'] = self._start(
            mock.patch(
                f'{_MODULE}._existing_tag_for_committish',
                return_value=None,
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
        release_notes: str | None = None,
    ) -> RemoteDeployment:
        return RemoteDeployment(
            environment=environment,
            sha=sha,
            ref=ref,
            status=typing.cast('typing.Any', status),
            created_at=datetime.datetime(
                2026, 5, 13, 14, 0, tzinfo=datetime.UTC
            ),
            external_run_id=external_run_id,
            run_url='https://gh/runs/12345',
            deployment_url=(
                'https://api.github.com/repos/octo/demo/deployments/12345'
            ),
            description='Bump foo',
            release_notes=release_notes,
            creator=creator,
            creator_subject=creator_subject,
        )

    def _run_resync(self, limit: int = 1) -> project_deployments.ResyncSummary:
        return asyncio.run(
            project_deployments.resync_for_project(
                self.mock_db,
                org_slug='myorg',
                project_id='proj1',
                auth=self.auth_context,
                limit=limit,
            )
        )

    def test_resync_persists_release_and_event_for_sha(self) -> None:
        observed = self._observed()
        self._arm([observed], release_exists=False)
        summary = self._run_resync()
        self.assertEqual(summary.projects, 1)
        self.assertEqual(summary.observed, 1)
        self.assertEqual(summary.releases_created, 1)
        self.assertEqual(summary.releases_updated, 0)
        self.assertEqual(summary.events_recorded, 1)
        self.assertEqual(summary.errors, [])
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
        summary = self._run_resync()
        self.assertEqual(summary.releases_created, 0)
        self.assertEqual(summary.releases_updated, 1)
        upsert_call = self.mocks['upsert_release_node'].call_args
        self.assertEqual(upsert_call.kwargs['tag'], 'v1.2.3')
        self.assertEqual(upsert_call.kwargs['committish'], 'deadbee')

    def test_resync_prefers_release_notes_over_description(self) -> None:
        # A deployment against a release tag carries the release body; it
        # becomes the Release node's notes while the short deploy
        # description still supplies the title.
        self._arm(
            [
                self._observed(
                    ref='v2.0.0',
                    sha='deadbeefcafebabe',
                    release_notes="## What's Changed\n- servicelib",
                )
            ],
            release_exists=False,
        )
        self._run_resync()
        upsert_call = self.mocks['upsert_release_node'].call_args
        self.assertEqual(
            upsert_call.kwargs['notes_markdown'],
            "## What's Changed\n- servicelib",
        )
        self.assertEqual(upsert_call.kwargs['title'], 'Bump foo')

    def test_resync_falls_back_to_description_without_release_notes(
        self,
    ) -> None:
        # No release body (branch/SHA deploy) keeps the prior behavior:
        # the short deploy description supplies the notes.
        self._arm([self._observed(release_notes=None)], release_exists=False)
        self._run_resync()
        upsert_call = self.mocks['upsert_release_node'].call_args
        self.assertEqual(upsert_call.kwargs['notes_markdown'], 'Bump foo')

    def test_resync_reconciles_sha_ref_onto_existing_tag(self) -> None:
        # A deployment whose ref was a raw SHA carries no semver tag. When
        # a tagged Release already exists for the commit (created by the
        # webhook), resync reconciles onto that tag -- rather than spawning
        # a duplicate untagged node -- and enriches its notes by tag.
        self._arm([self._observed(ref='main')], release_exists=True)
        self.mocks['existing_tag'].return_value = '3.23.4'
        notes = "## What's Changed\n- Fixed the breadcrumb"
        self.mocks['get_release_notes'] = self._start(
            mock.patch(f'{_MODULE}._get_release_notes', return_value=notes)
        )
        self._run_resync()
        upsert_call = self.mocks['upsert_release_node'].call_args
        # Reconciled onto the existing tag, and notes fetched by that tag.
        self.assertEqual(upsert_call.kwargs['tag'], '3.23.4')
        self.assertEqual(upsert_call.kwargs['committish'], '2668cd0')
        self.assertEqual(upsert_call.kwargs['notes_markdown'], notes)

    def test_resync_400_when_plugin_opts_out(self) -> None:
        # Override the resolved plugin to advertise the no-sync flavor.
        self.mocks['resolve_capability'].return_value = _make_resolved(
            _FakeNoSyncDeploymentPlugin,
            slug='no-sync-deployment',
            name='No-Sync Deployment',
            sync=False,
            options={'owner': 'octo', 'repo': 'demo'},
        )
        with self.assertRaises(fastapi.HTTPException) as cm:
            self._run_resync()
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn('does not support', str(cm.exception.detail))

    def test_resync_no_environments_returns_zero(self) -> None:
        self._arm([], environments=[])
        summary = self._run_resync()
        self.assertEqual(summary.observed, 0)
        self.mocks['upsert_release_node'].assert_not_called()
        self.mocks['append_deployment_event'].assert_not_called()

    def test_resync_records_missing_edge_as_error(self) -> None:
        self._arm([self._observed()], edge_status='missing')
        summary = self._run_resync()
        self.assertEqual(len(summary.errors), 1)
        self.assertEqual(
            summary.errors[0].environment, 'infrastructure-testing'
        )
        self.assertEqual(summary.events_recorded, 0)

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
        self._run_resync()
        ch = self.mocks['clickhouse'].return_value
        ch.insert.assert_not_awaited()

    def test_resync_threads_creator_to_performed_by(self) -> None:
        """``observed.creator`` becomes ``DeploymentEvent.performed_by``."""
        self._arm([self._observed(creator='octocat')])
        self._run_resync()
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
                f'{_MODULE}.attribution.identity_integration_ids_for_project',
                new=mock.AsyncMock(return_value=['int-1']),
            )
        )
        self._start(
            mock.patch(
                f'{_MODULE}.attribution.make_user_resolver',
                return_value=_resolver,
            )
        )
        self._run_resync()
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
                f'{_MODULE}.attribution.identity_integration_ids_for_project',
                new=mock.AsyncMock(return_value=['int-1']),
            )
        )
        self._start(
            mock.patch(
                f'{_MODULE}.attribution.make_user_resolver',
                return_value=_resolver,
            )
        )
        self._run_resync()
        append_call = self.mocks['append_deployment_event'].call_args
        self.assertEqual(append_call.kwargs['performed_by'], 'kevinv')

    def test_resync_defaults_limit_to_one(self) -> None:
        """Absent ``limit`` keeps the cheap latest-per-env catch-up."""
        self._arm([self._observed()])
        self._run_resync()
        self.assertEqual(self.mocks['handler'].return_value._last_limit, 1)

    def test_resync_threads_limit_to_plugin(self) -> None:
        """``limit`` reaches ``list_recent_deployments`` for a deeper
        backfill that re-resolves historical attribution."""
        self._arm([self._observed()])
        self._run_resync(limit=50)
        self.assertEqual(self.mocks['handler'].return_value._last_limit, 50)

    def test_resync_falls_back_to_app_credentials_without_identity(
        self,
    ) -> None:
        """Identity-gated integration + no user connection must not 401.

        The backfill acts with the Integration's own GitHub App
        credentials (which the plugin turns into an installation token),
        so a headless sweep still records deployments.
        """
        self._arm([self._observed()], release_exists=False)

        def _identity_required(
            _db: object, _ctx: object, _resolved: object, _auth: object
        ) -> typing.NoReturn:
            raise fastapi.HTTPException(
                status_code=401,
                detail={
                    'error': 'identity_required',
                    'integration_id': 'int-1',
                    'start_url': '/me/identities/int-1/start',
                },
            )

        self.mocks['attach_identity'].side_effect = _identity_required
        self.mocks['decrypt_integration_credentials'].return_value = {
            'app_id': '971',
            'private_key': 'PEM',
        }
        summary = self._run_resync()
        self.assertEqual(summary.observed, 1)

    def test_resync_503_when_no_service_credentials(self) -> None:
        """No identity connection *and* no service secret is a genuine
        misconfiguration -- surface it rather than silently no-op."""
        self._arm([self._observed()])

        def _identity_required(
            _db: object, _ctx: object, _resolved: object, _auth: object
        ) -> typing.NoReturn:
            raise fastapi.HTTPException(
                status_code=401,
                detail={
                    'error': 'identity_required',
                    'integration_id': 'int-1',
                    'start_url': '/me/identities/int-1/start',
                },
            )

        self.mocks['attach_identity'].side_effect = _identity_required
        self.mocks['decrypt_integration_credentials'].return_value = {}
        with self.assertRaises(fastapi.HTTPException) as cm:
            self._run_resync()
        self.assertEqual(cm.exception.status_code, 503)


class ResyncEndpointTestCase(ProjectDeploymentsTestCase):
    """The resync endpoint validates, enqueues, and returns 202."""

    def setUp(self) -> None:
        super().setUp()
        from imbi.api import scoring

        self.test_app.dependency_overrides[scoring._inject_optional_client] = (
            lambda: mock.AsyncMock()
        )

    def _post(self, query: str = '') -> typing.Any:
        with testclient.TestClient(self.test_app) as client:
            return client.post(
                '/organizations/myorg/projects/proj1/deployments/resync'
                + query
            )

    def test_resync_enqueues(self) -> None:
        with (
            mock.patch.object(
                project_deployments.deployment_sync_queue,
                'enqueue_deployment_sync',
                mock.AsyncMock(return_value=True),
            ) as enqueue,
            mock.patch.object(
                project_deployments.deployment_sync_service,
                'set_status',
                mock.AsyncMock(),
            ) as set_status,
        ):
            response = self._post('?limit=50')
        self.assertEqual(response.status_code, 202, response.text)
        self.assertTrue(response.json()['enqueued'])
        self.assertEqual(enqueue.await_args.kwargs['limit'], 50)
        kwargs = set_status.await_args.kwargs
        self.assertEqual(kwargs['status'], 'queued')
        # The optimistic write is guarded by a pre-enqueue timestamp so
        # a worker that already finished the job cannot be clobbered.
        self.assertIsInstance(kwargs['only_if_before'], str)
        self.assertFalse(kwargs['retry'])

    def test_resync_debounced_skips_status(self) -> None:
        with (
            mock.patch.object(
                project_deployments.deployment_sync_queue,
                'enqueue_deployment_sync',
                mock.AsyncMock(return_value=False),
            ),
            mock.patch.object(
                project_deployments.deployment_sync_service,
                'set_status',
                mock.AsyncMock(),
            ) as set_status,
        ):
            response = self._post()
        self.assertEqual(response.status_code, 202, response.text)
        self.assertFalse(response.json()['enqueued'])
        set_status.assert_not_awaited()

    def test_resync_400_when_plugin_opts_out(self) -> None:
        self.mocks['resolve_capability'].return_value = _make_resolved(
            _FakeNoSyncDeploymentPlugin,
            slug='no-sync-deployment',
            name='No-Sync Deployment',
            sync=False,
            options={'owner': 'octo', 'repo': 'demo'},
        )
        response = self._post()
        self.assertEqual(response.status_code, 400)
        self.assertIn('does not support', response.json()['detail'])

    def test_resync_rejects_out_of_range_limit(self) -> None:
        """``limit`` is clamped to the 1..100 GitHub per-page window."""
        self.assertEqual(self._post('?limit=0').status_code, 422)
        self.assertEqual(self._post('?limit=101').status_code, 422)

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
        response = self._post()
        self.assertEqual(response.status_code, 403)

    def test_get_sync_status(self) -> None:
        from imbi.api.deployment_sync import service as sync_service

        status = sync_service.DeploymentSyncStatus(
            status='success', observed=3, events_recorded=2
        )
        with mock.patch.object(
            sync_service, 'read_status', mock.AsyncMock(return_value=status)
        ):
            with testclient.TestClient(self.test_app) as client:
                response = client.get(
                    '/organizations/myorg/projects/proj1/deployments'
                    '/sync-status'
                )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['observed'], 3)
        self.assertEqual(data['events_recorded'], 2)


class ReleaseNotesPromptTestCase(unittest.TestCase):
    """Direct tests for ``_build_release_notes_prompt``."""

    def test_prompt_includes_commit_bodies(self) -> None:
        from imbi.api.endpoints.project_deployments import (
            _build_release_notes_prompt,
        )

        commits = [
            Commit(
                sha='a',
                short_sha='aaa',
                message='Add widgets (#8)',
                body='## Summary\nAdds the widget endpoint.',
            ),
            Commit(sha='b', short_sha='bbb', message='Subject only'),
        ]
        prompt = _build_release_notes_prompt(
            'proj', 'v1.0.0', 'a', 'b', commits
        )
        self.assertIn('Adds the widget endpoint.', prompt)
        self.assertIn('    ## Summary', prompt)
        self.assertIn('bbb Subject only', prompt)

    def test_prompt_truncates_long_bodies(self) -> None:
        from imbi.api.endpoints.project_deployments import (
            _PROMPT_BODY_CAP,
            _build_release_notes_prompt,
        )

        commits = [
            Commit(
                sha='a',
                short_sha='aaa',
                message='Big one',
                body='x' * (_PROMPT_BODY_CAP + 500),
            )
        ]
        prompt = _build_release_notes_prompt('proj', None, 'a', 'b', commits)
        self.assertIn('(truncated)', prompt)
        self.assertNotIn('x' * (_PROMPT_BODY_CAP + 1), prompt)

    def test_truncated_body_stays_within_cap(self) -> None:
        """The marker counts against the cap, not on top of it."""
        from imbi.api.endpoints.project_deployments import (
            _PROMPT_BODY_CAP,
            _truncate_commit_body,
        )

        for extra in (1, 500, 10_000):
            with self.subTest(extra=extra):
                truncated = _truncate_commit_body(
                    'x' * (_PROMPT_BODY_CAP + extra)
                )
                self.assertLessEqual(len(truncated), _PROMPT_BODY_CAP)
                self.assertTrue(truncated.endswith('(truncated)'))

    def test_body_at_cap_is_untouched(self) -> None:
        from imbi.api.endpoints.project_deployments import (
            _PROMPT_BODY_CAP,
            _truncate_commit_body,
        )

        body = 'x' * _PROMPT_BODY_CAP
        self.assertEqual(_truncate_commit_body(body), body)


class FallbackNotesTestCase(unittest.TestCase):
    """Direct tests for ``_classify_bump`` and ``_fallback_notes``."""

    def test_classify_bump_breaking(self) -> None:
        from imbi.api.endpoints.project_deployments import _classify_bump

        commits = [Commit(sha='a', short_sha='a', message='feat!: drop')]
        self.assertEqual(_classify_bump(commits), 'major')

    def test_classify_bump_feature(self) -> None:
        from imbi.api.endpoints.project_deployments import _classify_bump

        commits = [Commit(sha='a', short_sha='a', message='feat: new thing')]
        self.assertEqual(_classify_bump(commits), 'minor')

    def test_classify_bump_patch_default(self) -> None:
        from imbi.api.endpoints.project_deployments import _classify_bump

        commits = [Commit(sha='a', short_sha='a', message='fix: thing')]
        self.assertEqual(_classify_bump(commits), 'patch')

    def test_fallback_notes_groups_by_prefix(self) -> None:
        from imbi.api.endpoints.project_deployments import _fallback_notes

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
        from imbi.api.endpoints.project_deployments import _fallback_notes

        self.assertIn('No commits', _fallback_notes([]))

    def test_fallback_notes_falls_back_to_other_for_long_prefix(self) -> None:
        from imbi.api.endpoints.project_deployments import _fallback_notes

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
        from imbi.api.endpoints.project_deployments import (
            _latest_deployment_timestamp,
        )

        self.assertIsNone(_latest_deployment_timestamp(None))
        self.assertIsNone(_latest_deployment_timestamp(''))
        self.assertIsNone(_latest_deployment_timestamp('[]'))

    def test_returns_none_for_non_list_payloads(self) -> None:
        from imbi.api.endpoints.project_deployments import (
            _latest_deployment_timestamp,
        )

        self.assertIsNone(_latest_deployment_timestamp('"oops"'))
        self.assertIsNone(_latest_deployment_timestamp('{"x": 1}'))

    def test_picks_max_timestamp(self) -> None:
        from imbi.api.endpoints.project_deployments import (
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
        from imbi.api.endpoints.project_deployments import (
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
        from imbi.api.endpoints.project_deployments import (
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
    """Direct tests for ``safe_audit_url`` (L22)."""

    def test_returns_none_for_none(self) -> None:
        from imbi.api.endpoints._helpers import safe_audit_url

        self.assertIsNone(safe_audit_url(None))

    def test_allows_http_and_https(self) -> None:
        from imbi.api.endpoints._helpers import safe_audit_url

        for url in (
            'http://example.com/run/42',
            'https://github.com/o/r/actions/runs/1',
        ):
            self.assertEqual(safe_audit_url(url), url)

    def test_strips_javascript_scheme(self) -> None:
        from imbi.api.endpoints._helpers import safe_audit_url

        self.assertIsNone(safe_audit_url('javascript:alert(1)'))
        self.assertIsNone(safe_audit_url('JavaScript:alert(1)'))

    def test_strips_data_scheme(self) -> None:
        from imbi.api.endpoints._helpers import safe_audit_url

        self.assertIsNone(safe_audit_url('data:text/html,<script>x</script>'))

    def test_strips_file_scheme(self) -> None:
        from imbi.api.endpoints._helpers import safe_audit_url

        self.assertIsNone(safe_audit_url('file:///etc/passwd'))


class DeployedOperationLogTestCase(unittest.TestCase):
    """The audit row records both release identities."""

    @staticmethod
    def _build(**kwargs: typing.Any) -> dict[str, typing.Any]:
        from imbi.api.endpoints._helpers import deployed_operation_log

        entry = deployed_operation_log(
            project_id='p1',
            project_slug='webform',
            environment_slug='production',
            recorded_by='dang@aweber.com',
            performed_by='dang@aweber.com',
            action='deploy',
            **kwargs,
        )
        return json.loads(entry.description)

    def test_commit_sha_recorded_alongside_a_tag(self) -> None:
        # The UI joins the rows of one release train by tag *or*
        # committish, so a tagged row must still carry the committish.
        description = self._build(version='1.29.0', commit_sha='c67213d')
        self.assertEqual('c67213d', description['commit_sha'])

    def test_commit_sha_defaults_to_none(self) -> None:
        description = self._build(version='1.29.0')
        self.assertIsNone(description['commit_sha'])


class DispatchDrivenPromoteTestCase(ProjectDeploymentsTestCase):
    """Promote dispatches the Release workflow when one is configured.

    The workflow owns the tag and the remote Release, so the endpoint
    creates neither -- it records the ``Release`` node, dispatches, and
    hands off to the watcher.
    """

    _BASE = '/organizations/myorg/projects/proj1/deployments'
    _PROMOTE: typing.ClassVar[dict[str, typing.Any]] = {
        'action': 'promote',
        'from_environment': 'testing',
        'to_environment': 'staging',
        'from_committish': 'e6a13a0d6cf93cd5af4eef2a0ca13035aea64192',
        'tag': '0.1.5',
        'release_name': 'Release 0.1.5',
        'release_notes_markdown': '## What changed',
    }

    def _enable_dispatch(
        self,
        *,
        workflow: str = 'release.yml',
        handler: type[DeploymentCapability] | None = None,
    ) -> None:
        """Opt this test into the dispatch path.

        Deliberately *not* in ``setUp``: this class inherits every test on
        ``ProjectDeploymentsTestCase``, and configuring a Release workflow
        for all of them would silently reroute the inherited promote tests
        onto the dispatch branch.
        """
        _DispatchingDeploymentPlugin.dispatches.clear()
        _DispatchingDeploymentPlugin.run_id = '4242'
        self.mocks['resolve_capability'].return_value = _make_resolved(
            handler or _DispatchingDeploymentPlugin,
            options={'owner': 'octo', 'repo': 'demo'},
            capability_options=(
                {'artifact_workflow': workflow} if workflow else {}
            ),
        )
        self.upsert = self._start(
            mock.patch(f'{_MODULE}._upsert_release_node', return_value='rel1')
        )
        self.deployable = self._start(
            mock.patch(f'{_MODULE}._project_is_deployable', return_value=True)
        )
        self.enqueue = self._start(
            mock.patch(
                f'{_MODULE}.release_promote_queue.enqueue_release_promote',
                return_value=True,
            )
        )
        self.set_status = self._start(
            mock.patch(
                f'{_MODULE}.release_promote_service.set_status',
                return_value=None,
            )
        )
        self.create_tag = self._start(
            mock.patch(f'{_MODULE}._promote_cut_tag', return_value=None)
        )

    def _promote(self, **overrides: typing.Any) -> httpx.Response:
        body = {**self._PROMOTE, **overrides}
        with testclient.TestClient(self.test_app) as client:
            return client.post(self._BASE, json=body)

    def test_dispatches_instead_of_cutting_the_tag(self) -> None:
        self._enable_dispatch()
        response = self._promote()
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertEqual('building', data['phase'])
        self.assertEqual('4242', data['artifact_run_id'])
        self.assertEqual('0.1.5', data['tag'])
        self.assertTrue(data['watched'])
        self.assertIsNone(data['warning'])
        self.assertEqual(1, len(_DispatchingDeploymentPlugin.dispatches))
        # The endpoint must not cut the tag itself any more.
        self.create_tag.assert_not_called()

    def test_always_sends_the_commit_input(self) -> None:
        """release-tag.yaml tags the tip of main when ``commit`` is empty.

        Omitting it would silently release a different tree than the one
        being promoted, and the run would still go green -- so this is a
        correctness guard, not a nicety.
        """
        self._enable_dispatch()
        self._promote()
        inputs = _DispatchingDeploymentPlugin.dispatches[0]['inputs']
        self.assertEqual('e6a13a0', inputs['commit'])
        self.assertTrue(inputs['commit'])

    def test_dispatch_input_mapping(self) -> None:
        self._enable_dispatch()
        self._promote()
        dispatch = _DispatchingDeploymentPlugin.dispatches[0]
        # Dispatched from the default branch: workflow_dispatch resolves
        # the workflow file on the ref, and the tag does not exist yet.
        self.assertEqual('main', dispatch['ref'])
        self.assertEqual('0.1.5', dispatch['version'])
        inputs = dispatch['inputs']
        self.assertEqual('Release 0.1.5', inputs['description'])
        self.assertEqual('## What changed', inputs['release_notes'])
        self.assertEqual('staging', inputs['environment'])
        # The D6 seam: Imbi owns Deployment creation now.
        self.assertEqual('false', inputs['create_deployment'])

    def test_deployment_inputs_omitted_for_a_releasable_project(self) -> None:
        """A releasable project's workflow declares neither input.

        Publishing *is* the release for a library, so its variant of
        release.yml drops ``environment`` and ``create_deployment``
        entirely -- and workflow_dispatch 422s the whole call when it is
        handed an input the workflow does not declare, so sending them
        anyway fails the release outright.
        """
        self._enable_dispatch()
        self.deployable.return_value = False
        self._promote()
        inputs = _DispatchingDeploymentPlugin.dispatches[0]['inputs']
        self.assertNotIn('create_deployment', inputs)
        self.assertNotIn('environment', inputs)
        # The universal inputs are unaffected.
        self.assertEqual('Release 0.1.5', inputs['description'])
        self.assertEqual('e6a13a0', inputs['commit'])

    def test_description_falls_back_to_the_tag(self) -> None:
        """``description`` is required by release.yml, so never send empty."""
        self._enable_dispatch()
        self._promote(release_name=None)
        inputs = _DispatchingDeploymentPlugin.dispatches[0]['inputs']
        self.assertEqual('0.1.5', inputs['description'])

    def test_records_the_release_node_before_dispatching(self) -> None:
        """A failed build needs a node to block."""
        self._enable_dispatch()
        self._promote()
        self.upsert.assert_awaited_once()
        kwargs = self.upsert.await_args.kwargs
        self.assertEqual('0.1.5', kwargs['tag'])
        self.assertEqual('e6a13a0', kwargs['committish'])
        # No release URL yet -- the build has not created one.
        self.assertIsNone(kwargs['release_url'])

    def test_enqueues_a_watch_job_carrying_the_promoter(self) -> None:
        self._enable_dispatch()
        self._promote()
        self.enqueue.assert_awaited_once()
        job = self.enqueue.await_args.args[1]
        self.assertEqual('0.1.5', job.tag)
        self.assertEqual('e6a13a0', job.committish)
        self.assertEqual('staging', job.to_environment)
        self.assertEqual('testing', job.from_environment)
        self.assertEqual('4242', job.run_id)
        self.assertEqual('rel1', job.release_id)
        self.assertTrue(job.deploy)
        self.assertEqual('admin@example.com', job.requested_by)

    def test_releasable_only_project_queues_a_build_only_job(self) -> None:
        self._enable_dispatch()
        self.deployable.return_value = False
        self._promote()
        self.assertFalse(self.enqueue.await_args.args[1].deploy)

    def test_unqueueable_watch_warns_and_is_not_watched(self) -> None:
        self._enable_dispatch()
        self.enqueue.return_value = False
        data = self._promote().json()
        self.assertFalse(data['watched'])
        self.assertIn('could not queue a watcher', data['warning'])

    def test_missing_run_id_warns_and_skips_the_watch(self) -> None:
        self._enable_dispatch()
        _DispatchingDeploymentPlugin.run_id = None
        data = self._promote().json()
        self.assertFalse(data['watched'])
        self.assertIn('did not report a run id', data['warning'])
        self.enqueue.assert_not_awaited()

    def test_blocked_release_is_refused_before_dispatching(self) -> None:
        self._enable_dispatch()
        self.mock_db.execute = mock.AsyncMock(
            return_value=[
                {
                    'release': json.dumps(
                        {
                            'tag': '0.1.5',
                            'committish': 'e6a13a0',
                            'blocked_reason': 'Bad build',
                        }
                    )
                }
            ]
        )
        response = self._promote()
        self.assertEqual(response.status_code, 409)
        self.assertEqual([], _DispatchingDeploymentPlugin.dispatches)

    def test_legacy_path_when_no_release_workflow_configured(self) -> None:
        """A blank Release workflow keeps cutting the tag inline."""
        self._enable_dispatch(workflow='')
        response = self._promote()
        self.assertEqual(response.status_code, 202)
        self.assertIsNone(response.json()['phase'])
        self.assertEqual([], _DispatchingDeploymentPlugin.dispatches)
        self.create_tag.assert_awaited_once()

    # -- Preflighting the configured workflow ------------------------------

    def _deletes(self) -> list[dict[str, typing.Any]]:
        """Params of every ``Release`` node deletion that ran."""
        return [
            call.args[1]
            for call in self.mock_db.execute.await_args_list
            if 'DETACH DELETE r' in call.args[0]
        ]

    def test_missing_workflow_is_refused_before_anything_is_written(
        self,
    ) -> None:
        """The whole point: a typo'd option costs nothing but a 400.

        Dispatching it would 404 from inside the plugin and arrive as a
        bare 500, with a ``Release`` node already written for a tag the
        remote will never carry.
        """
        self._enable_dispatch(
            handler=_listing_plugin(
                '.github/workflows/ci.yaml', '.github/workflows/docs.yaml'
            )
        )
        response = self._promote()
        self.assertEqual(response.status_code, 400)
        detail = response.json()['detail']
        self.assertIn("'release.yml'", detail)
        self.assertIn('does not exist', detail)
        # Names what *is* there, so the operator can spot the typo.
        self.assertIn('ci.yaml', detail)
        self.assertEqual([], _DispatchingDeploymentPlugin.dispatches)
        self.upsert.assert_not_awaited()
        self.assertEqual([], self._deletes())

    def test_workflow_matched_by_file_name(self) -> None:
        self._enable_dispatch(
            handler=_listing_plugin('.github/workflows/release.yml')
        )
        self.assertEqual(202, self._promote().status_code)
        self.assertEqual(1, len(_DispatchingDeploymentPlugin.dispatches))

    def test_workflow_matched_by_repo_relative_path(self) -> None:
        self._enable_dispatch(
            workflow='.github/workflows/release.yml',
            handler=_listing_plugin('.github/workflows/release.yml'),
        )
        self.assertEqual(202, self._promote().status_code)
        self.assertEqual(1, len(_DispatchingDeploymentPlugin.dispatches))

    def test_workflow_matched_by_remote_id(self) -> None:
        """A numeric id is what the workflow dropdown stores."""
        self._enable_dispatch(
            workflow='1234567',
            handler=_listing_plugin(
                '.github/workflows/release.yml', ids=('1234567',)
            ),
        )
        self.assertEqual(202, self._promote().status_code)
        self.assertEqual(1, len(_DispatchingDeploymentPlugin.dispatches))

    def test_unlistable_workflows_do_not_block_the_dispatch(self) -> None:
        """The preflight explains a misconfiguration; it does not gate.

        A listing call that errors says nothing about whether the workflow
        exists, so refusing on it would turn one flaky read into a release
        that cannot be cut.
        """
        self._enable_dispatch(handler=_listing_plugin(raises=True))
        self.assertEqual(202, self._promote().status_code)
        self.assertEqual(1, len(_DispatchingDeploymentPlugin.dispatches))

    def test_repo_with_no_workflows_at_all_is_refused(self) -> None:
        """An empty list is an answer, unlike a failed listing call."""
        self._enable_dispatch(handler=_listing_plugin())
        response = self._promote()
        self.assertEqual(response.status_code, 400)
        self.assertIn('Workflows found: none', response.json()['detail'])
        self.upsert.assert_not_awaited()

    # -- Abandoning the node a failed dispatch orphaned --------------------

    def _failing_dispatch(
        self, exc: BaseException | None = None
    ) -> type[DeploymentCapability]:
        failure = exc or RuntimeError('workflow_dispatch 422')

        class _FailingPlugin(_DispatchingDeploymentPlugin):
            async def create_deployment_artifact(  # type: ignore[override]
                self, ctx, credentials, ref, version, inputs=None
            ):
                raise failure

        return _FailingPlugin

    @staticmethod
    def _remote_error(status: int) -> httpx.HTTPStatusError:
        """The error a plugin's ``raise_for_status`` raises for *status*."""
        request = httpx.Request(
            'POST', 'https://api.gh/actions/workflows/release.yml/dispatches'
        )
        return httpx.HTTPStatusError(
            f'HTTP {status}',
            request=request,
            response=httpx.Response(
                status, request=request, json={'message': 'nope'}
            ),
        )

    def test_failed_dispatch_removes_the_release_it_created(self) -> None:
        """No tag was cut, so no release should be left claiming one."""
        self._enable_dispatch(handler=self._failing_dispatch())
        with self.assertRaises(RuntimeError):
            self._promote()
        deletes = self._deletes()
        self.assertEqual(1, len(deletes))
        self.assertEqual('rel1', deletes[0]['release_id'])

    def _untags(self) -> list[dict[str, typing.Any]]:
        """Params of every tag-removal that ran."""
        return [
            call.args[1]
            for call in self.mock_db.execute.await_args_list
            if 'SET r.tag = NULL' in call.args[0]
        ]

    def test_failed_dispatch_untags_an_adopted_release(self) -> None:
        """An adopted node is older than the promote, so it survives.

        ``_adopt_untagged_release`` tags the node the resync built from
        the commit's testing deployments; deleting that on a failed
        dispatch would take the testing history with it.  Only the tag
        this call put on comes back off.
        """
        self._enable_dispatch(handler=self._failing_dispatch())
        self._start(
            mock.patch(
                f'{_MODULE}._adopt_untagged_release',
                return_value='rel-testing',
            )
        )
        with self.assertRaises(RuntimeError):
            self._promote()
        self.assertEqual([], self._deletes())
        untags = self._untags()
        self.assertEqual(1, len(untags))
        self.assertEqual('rel-testing', untags[0]['release_id'])

    def test_failed_dispatch_keeps_a_release_it_did_not_create(self) -> None:
        """Re-promoting a tag must not delete the earlier promote's node.

        ``_upsert_release_node`` keys on ``(project, committish, tag)``, so
        a retry lands on the release the first attempt created -- which may
        have shipped, or be blocked, and is not this call's to discard.
        """
        self._enable_dispatch(handler=self._failing_dispatch())
        self._start(
            mock.patch(f'{_MODULE}._release_id_for', return_value='rel1')
        )
        with self.assertRaises(RuntimeError):
            self._promote()
        self.assertEqual([], self._deletes())

    # -- Explaining a refused dispatch -------------------------------------

    def test_remote_404_is_a_400_not_a_500(self) -> None:
        """Reachable when the preflight's own listing call failed open."""
        self._enable_dispatch(
            handler=self._failing_dispatch(self._remote_error(404))
        )
        response = self._promote()
        self.assertEqual(response.status_code, 400)
        detail = response.json()['detail']
        self.assertIn("no Release workflow named 'release.yml'", detail)
        self.assertEqual(1, len(self._deletes()))

    def test_remote_422_names_what_the_remote_rejects(self) -> None:
        """The three ways a real workflow still refuses to be dispatched."""
        self._enable_dispatch(
            handler=self._failing_dispatch(self._remote_error(422))
        )
        response = self._promote()
        self.assertEqual(response.status_code, 400)
        detail = response.json()['detail']
        self.assertIn('workflow_dispatch trigger', detail)
        self.assertIn("'main'", detail)
        self.assertIn('does not declare an input', detail)

    def test_remote_403_is_reported_as_a_refusal(self) -> None:
        self._enable_dispatch(
            handler=self._failing_dispatch(self._remote_error(403))
        )
        response = self._promote()
        self.assertEqual(response.status_code, 403)
        self.assertIn('disabled workflow', response.json()['detail'])

    def test_remote_5xx_is_a_502(self) -> None:
        self._enable_dispatch(
            handler=self._failing_dispatch(self._remote_error(500))
        )
        response = self._promote()
        self.assertEqual(response.status_code, 502)
        self.assertIn('HTTP 500', response.json()['detail'])
        self.assertIn('was not started', response.json()['detail'])

    def test_the_remotes_own_message_is_not_echoed_to_the_client(
        self,
    ) -> None:
        """Plugin text can carry internals; it belongs in the log."""
        self._enable_dispatch(
            handler=self._failing_dispatch(self._remote_error(422))
        )
        self.assertNotIn('nope', self._promote().json()['detail'])

    def test_a_plugin_timeout_keeps_its_own_status(self) -> None:
        """``call_with_timeout`` already answered 503; don't relabel it."""
        self._enable_dispatch(
            handler=self._failing_dispatch(
                fastapi.HTTPException(
                    status_code=503, detail='Plugin timed out'
                )
            )
        )
        response = self._promote()
        self.assertEqual(response.status_code, 503)
        self.assertEqual('Plugin timed out', response.json()['detail'])
        # Still abandoned: no build was accepted.
        self.assertEqual(1, len(self._deletes()))

    def test_an_unrecognized_failure_still_raises(self) -> None:
        """No guessing: an error we can't explain keeps its traceback."""
        self._enable_dispatch(handler=self._failing_dispatch())
        with self.assertRaises(RuntimeError):
            self._promote()

    def test_a_plugin_that_cannot_dispatch_abandons_the_node_too(self) -> None:
        """The 400 path leaves no more behind than the 500 path does."""

        class _NoDispatchPlugin(_DispatchingDeploymentPlugin):
            async def create_deployment_artifact(  # type: ignore[override]
                self, ctx, credentials, ref, version, inputs=None
            ):
                raise NotImplementedError

        self._enable_dispatch(handler=_NoDispatchPlugin)
        response = self._promote()
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'cannot dispatch a release workflow', response.json()['detail']
        )
        deletes = self._deletes()
        self.assertEqual(1, len(deletes))
        self.assertEqual('rel1', deletes[0]['release_id'])


class CiGateTestCase(ProjectDeploymentsTestCase):
    """ENG-102: promote / release off a red commit warns and confirms.

    The gate is deliberately narrow -- only ``'fail'`` stops anything.
    ``'unknown'`` is the status a project with no CI, a token without the
    check-runs scope, or a commit whose checks never ran all report, and
    treating that as a failure would refuse most promotes.
    """

    _BASE = '/organizations/myorg/projects/proj1/deployments'
    _PROMOTE: typing.ClassVar[dict[str, typing.Any]] = {
        'action': 'promote',
        'from_environment': 'testing',
        'to_environment': 'staging',
        'from_committish': '1a9c610',
        'tag': 'v6.4.0',
    }
    _CUT: typing.ClassVar[dict[str, typing.Any]] = {
        'committish': '1a9c610',
        'tag': 'v6.5.0',
    }
    _DEPLOY: typing.ClassVar[dict[str, typing.Any]] = {
        'action': 'deploy',
        'environment': 'testing',
        'committish': '1a9c610',
    }

    def _use(
        self, status: str = 'fail', *, raises: bool = False
    ) -> type[DeploymentCapability]:
        handler = _ci_plugin(status, raises=raises)
        self.mocks['resolve_capability'].return_value = _make_resolved(
            handler, options={'owner': 'octo', 'repo': 'demo'}
        )
        return handler

    def _promote(self, **overrides: typing.Any) -> httpx.Response:
        self.mocks['append_deployment_event'].return_value = mock.Mock()
        with testclient.TestClient(self.test_app) as client:
            return client.post(self._BASE, json={**self._PROMOTE, **overrides})

    def _deploy(self, **overrides: typing.Any) -> httpx.Response:
        self.mocks['append_deployment_event'].return_value = mock.Mock()
        with testclient.TestClient(self.test_app) as client:
            return client.post(self._BASE, json={**self._DEPLOY, **overrides})

    def _cut(self, **overrides: typing.Any) -> httpx.Response:
        with testclient.TestClient(self.test_app) as client:
            return client.post(
                f'{self._BASE}/releases/cut', json={**self._CUT, **overrides}
            )

    def _ci_stamps(self) -> list[dict[str, typing.Any]]:
        """Params of every ``ci_status_at_promote`` write that ran."""
        return [
            call.args[1]
            for call in self.mock_db.execute.await_args_list
            if 'ci_status_at_promote' in call.args[0]
        ]

    def _ci_override_writes(self) -> list[dict[str, typing.Any]]:
        """Params of every override-actor write that ran.

        A separate statement from the status write on purpose, so that a
        later green promote of the same tag cannot blank an override --
        which makes "did the actor get written at all?" the thing to
        assert, not what value the status write carried for it.
        """
        return [
            call.args[1]
            for call in self.mock_db.execute.await_args_list
            if 'ci_override_by' in call.args[0]
            and 'ci_status_at_promote' not in call.args[0]
        ]

    def _audit_description(self) -> dict[str, typing.Any]:
        ch = self.mocks['clickhouse'].return_value
        args, _ = ch.insert.call_args
        row = dict(zip(args[2], args[1][0], strict=False))
        return typing.cast(
            'dict[str, typing.Any]', json.loads(row['description'])
        )

    # -- The gate ---------------------------------------------------------

    def test_promote_409_when_ci_failed(self) -> None:
        self._use('fail')
        response = self._promote()
        self.assertEqual(response.status_code, 409)
        detail = response.json()['detail']
        self.assertIn('CI failed for commit 1a9c610', detail)
        self.assertIn('acknowledge_ci_failure=true', detail)

    def test_promote_gate_runs_before_any_side_effect(self) -> None:
        """A refused promote must leave nothing behind to clean up.

        This is what makes the 409 safe to retry with the acknowledgement
        set: no tag was cut, no Release node written, and no deployment
        event recorded, so the resubmit is a first attempt, not a repair.
        """
        self._use('fail')
        cut_tag = self._start(
            mock.patch(f'{_MODULE}._promote_cut_tag', return_value=None)
        )
        upsert = self._start(
            mock.patch(f'{_MODULE}._upsert_release_node', return_value='rel1')
        )
        self.assertEqual(409, self._promote().status_code)
        cut_tag.assert_not_called()
        upsert.assert_not_called()
        self.mocks['append_deployment_event'].assert_not_called()

    def test_promote_proceeds_when_ci_unknown(self) -> None:
        """The design note's load-bearing case: unknown is not failure."""
        self._use('unknown')
        self.assertEqual(202, self._promote().status_code)

    def test_promote_proceeds_when_ci_warns(self) -> None:
        # ``warn`` is a cancelled or stale run, not a failing one.
        self._use('warn')
        self.assertEqual(202, self._promote().status_code)

    def test_promote_proceeds_when_ci_passes(self) -> None:
        self._use('pass')
        self.assertEqual(202, self._promote().status_code)

    def test_promote_proceeds_when_the_ci_lookup_raises(self) -> None:
        """A plugin that cannot answer must not read as a failing build."""
        self._use('fail', raises=True)
        self.assertEqual(202, self._promote().status_code)

    def test_promote_allowed_when_acknowledged(self) -> None:
        self._use('fail')
        response = self._promote(acknowledge_ci_failure=True)
        self.assertEqual(response.status_code, 202)
        self.assertEqual('v6.4.0', response.json()['tag'])

    # -- The record -------------------------------------------------------

    def test_acknowledged_promote_stamps_the_release_node(self) -> None:
        self._use('fail')
        self.assertEqual(
            202, self._promote(acknowledge_ci_failure=True).status_code
        )
        stamps = self._ci_stamps()
        self.assertEqual(1, len(stamps))
        self.assertEqual('fail', stamps[0]['ci_status'])
        overrides = self._ci_override_writes()
        self.assertEqual(1, len(overrides))
        self.assertEqual('admin@example.com', overrides[0]['overridden_by'])
        self.assertTrue(overrides[0]['overridden_at'])

    def test_green_promote_records_the_status_without_an_actor(self) -> None:
        """A clean promote is still recorded, but is not an override.

        Keeping the status either way is what lets a reader tell "shipped
        green" from "shipped with CI never having run"; writing no actor
        at all is what keeps it from looking like a decision someone made
        -- and, on a re-promote of a tag that was acknowledged while red,
        what keeps the real decision from being blanked.
        """
        self._use('pass')
        self.assertEqual(202, self._promote().status_code)
        stamps = self._ci_stamps()
        self.assertEqual(1, len(stamps))
        self.assertEqual('pass', stamps[0]['ci_status'])
        self.assertNotIn('overridden_by', stamps[0])
        self.assertNotIn('overridden_at', stamps[0])
        self.assertEqual([], self._ci_override_writes())

    def test_green_repromote_keeps_an_earlier_override(self) -> None:
        """Re-promoting a tag after CI goes green preserves the record.

        ``_upsert_release_node`` keys on ``(project, committish, tag)``,
        so the second promote writes to the same ``Release`` node.  A CI
        re-run that turns the commit green makes this the expected
        sequence, and blanking the actor on it would erase an
        acknowledgement that really happened.
        """
        self._use('fail')
        self.assertEqual(
            202, self._promote(acknowledge_ci_failure=True).status_code
        )
        self._use('pass')
        self.assertEqual(202, self._promote().status_code)

        stamps = self._ci_stamps()
        self.assertEqual(['fail', 'pass'], [s['ci_status'] for s in stamps])
        # The green pass touched the status only -- the sole override
        # write is still the acknowledged one.
        overrides = self._ci_override_writes()
        self.assertEqual(1, len(overrides))
        self.assertEqual('admin@example.com', overrides[0]['overridden_by'])

    def test_acknowledged_promote_records_the_override_in_the_ops_log(
        self,
    ) -> None:
        self._use('fail')
        self.assertEqual(
            202, self._promote(acknowledge_ci_failure=True).status_code
        )
        description = self._audit_description()
        self.assertTrue(description['ci_override'])
        self.assertEqual('fail', description['ci_status'])

    def test_clean_promote_records_no_override_in_the_ops_log(self) -> None:
        self._use('pass')
        self.assertEqual(202, self._promote().status_code)
        description = self._audit_description()
        self.assertFalse(description['ci_override'])
        self.assertEqual('pass', description['ci_status'])

    # -- deploy / redeploy ------------------------------------------------

    def test_deploy_409_when_ci_failed(self) -> None:
        self._use('fail')
        response = self._deploy()
        self.assertEqual(response.status_code, 409)
        detail = response.json()['detail']
        self.assertIn('CI failed for commit 1a9c610', detail)
        self.assertIn('before you deploy it', detail)
        self.assertIn('acknowledge_ci_failure=true', detail)

    def test_deploy_gate_runs_before_the_plugin_is_called(self) -> None:
        """A refused deploy must never reach the remote."""
        handler = self._use('fail')
        triggered: list[str] = []

        async def _record(self, ctx, credentials, ref_or_sha, inputs=None):
            triggered.append(ref_or_sha)
            raise AssertionError('the gate let a red commit through')

        self._start(mock.patch.object(handler, 'trigger_deployment', _record))
        self.assertEqual(409, self._deploy().status_code)
        self.assertEqual([], triggered)

    def test_deploy_allowed_when_acknowledged(self) -> None:
        self._use('fail')
        self.assertEqual(
            202, self._deploy(acknowledge_ci_failure=True).status_code
        )

    def test_deploy_proceeds_when_ci_unknown(self) -> None:
        self._use('unknown')
        self.assertEqual(202, self._deploy().status_code)

    def test_deploy_proceeds_when_ci_warns(self) -> None:
        self._use('warn')
        self.assertEqual(202, self._deploy().status_code)

    def test_deploy_proceeds_when_ci_passes(self) -> None:
        self._use('pass')
        self.assertEqual(202, self._deploy().status_code)

    def test_deploy_proceeds_when_the_ci_lookup_raises(self) -> None:
        self._use('fail', raises=True)
        self.assertEqual(202, self._deploy().status_code)

    def test_acknowledged_deploy_records_the_override_in_the_ops_log(
        self,
    ) -> None:
        """The deploy audit row carries the CI decision, like promote's."""
        self._use('fail')
        self._start(
            mock.patch(f'{_MODULE}._release_id_for', return_value='rel1')
        )
        self.assertEqual(
            202, self._deploy(acknowledge_ci_failure=True).status_code
        )
        description = self._audit_description()
        self.assertTrue(description['ci_override'])
        self.assertEqual('fail', description['ci_status'])

    def test_clean_deploy_records_no_override_in_the_ops_log(self) -> None:
        self._use('pass')
        self._start(
            mock.patch(f'{_MODULE}._release_id_for', return_value='rel1')
        )
        self.assertEqual(202, self._deploy().status_code)
        description = self._audit_description()
        self.assertFalse(description['ci_override'])
        self.assertEqual('pass', description['ci_status'])

    def test_redeploy_is_gated_too(self) -> None:
        """A rollback is a redeploy, and is gated on the ref it ships.

        Deliberate: the gate asks about the ref, not about the operator's
        reason for shipping it, so rolling back onto a red ref during an
        incident costs one acknowledgement rather than being silent.
        """
        self._use('fail')
        response = self._deploy(action='redeploy')
        self.assertEqual(409, response.status_code)
        self.assertIn('before you redeploy it', response.json()['detail'])
        self.assertEqual(
            202,
            self._deploy(
                action='redeploy', acknowledge_ci_failure=True
            ).status_code,
        )

    # -- releases/cut -----------------------------------------------------

    def test_cut_release_409_when_ci_failed(self) -> None:
        self._use('fail')
        response = self._cut()
        self.assertEqual(response.status_code, 409)
        detail = response.json()['detail']
        self.assertIn('CI failed for commit 1a9c610', detail)
        # The action name comes from the caller, so the copy fits the flow.
        self.assertIn('before you release it', detail)

    def test_cut_release_allowed_when_acknowledged(self) -> None:
        self._use('fail')
        response = self._cut(acknowledge_ci_failure=True)
        self.assertEqual(response.status_code, 201)
        self.assertEqual('v6.5.0', response.json()['tag'])
        stamps = self._ci_stamps()
        self.assertEqual(1, len(stamps))
        self.assertEqual('fail', stamps[0]['ci_status'])
        overrides = self._ci_override_writes()
        self.assertEqual(1, len(overrides))
        self.assertEqual('admin@example.com', overrides[0]['overridden_by'])

    def test_cut_release_proceeds_when_ci_unknown(self) -> None:
        self._use('unknown')
        self.assertEqual(201, self._cut().status_code)

    # -- The pre-flight read ----------------------------------------------

    def test_check_status_endpoint_reports_the_plugin_status(self) -> None:
        self._use('fail')
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                f'{self._BASE}/check-status?committish=1a9c610'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {'committish': '1a9c610', 'ci_status': 'fail'}, response.json()
        )

    def test_check_status_endpoint_degrades_to_unknown(self) -> None:
        """The banner must render even when check-runs cannot be read."""
        self._use('fail', raises=True)
        with testclient.TestClient(self.test_app) as client:
            response = client.get(
                f'{self._BASE}/check-status?committish=1a9c610'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual('unknown', response.json()['ci_status'])


class DispatchCiGateTestCase(CiGateTestCase):
    """The CI gate also covers the dispatch-driven promote path.

    This is the path where a red commit matters most: the Release workflow
    itself cuts the tag, so without the gate Imbi would hand a failing
    commit to a build whose whole job is to make it a release.
    """

    def _use(
        self, status: str = 'fail', *, raises: bool = False
    ) -> type[DeploymentCapability]:
        """Resolve to a dispatching plugin with a Release workflow set."""
        _DispatchingDeploymentPlugin.dispatches.clear()
        _DispatchingDeploymentPlugin.run_id = '4242'
        handler = _ci_plugin(
            status, raises=raises, base=_DispatchingDeploymentPlugin
        )
        self.mocks['resolve_capability'].return_value = _make_resolved(
            handler,
            options={'owner': 'octo', 'repo': 'demo'},
            capability_options={'artifact_workflow': 'release.yml'},
        )
        self._start(
            mock.patch(f'{_MODULE}._project_is_deployable', return_value=True)
        )
        self._start(
            mock.patch(
                f'{_MODULE}.release_promote_queue.enqueue_release_promote',
                return_value=True,
            )
        )
        self._start(
            mock.patch(
                f'{_MODULE}.release_promote_service.set_status',
                return_value=None,
            )
        )
        return handler

    def test_dispatch_refused_when_ci_failed(self) -> None:
        self._use('fail')
        self.assertEqual(409, self._promote().status_code)
        # Nothing was dispatched, so no build can tag the red commit.
        self.assertEqual([], _DispatchingDeploymentPlugin.dispatches)

    def test_dispatch_allowed_when_acknowledged(self) -> None:
        self._use('fail')
        response = self._promote(acknowledge_ci_failure=True)
        self.assertEqual(response.status_code, 202)
        self.assertEqual('building', response.json()['phase'])
        self.assertEqual(1, len(_DispatchingDeploymentPlugin.dispatches))
        # Stamped before the dispatch, because on this path the ops-log row
        # is only written after a *green* build -- an override whose build
        # then failed would otherwise leave no trace of the decision.
        stamps = self._ci_stamps()
        self.assertEqual(1, len(stamps))
        self.assertEqual('fail', stamps[0]['ci_status'])
        overrides = self._ci_override_writes()
        self.assertEqual(1, len(overrides))
        self.assertEqual('admin@example.com', overrides[0]['overridden_by'])

    # The two inherited ops-log assertions do not hold on this path, and
    # why they don't is the whole reason the Release node is stamped: the
    # audit row is not written until the build lands, so it cannot be the
    # only record of a decision made now.  ``_release_ci_override`` is what
    # carries it across that gap (see ReleaseCiOverrideTestCase).

    def test_acknowledged_promote_records_the_override_in_the_ops_log(
        self,
    ) -> None:
        self._use('fail')
        self.assertEqual(
            202, self._promote(acknowledge_ci_failure=True).status_code
        )
        self.mocks['clickhouse'].return_value.insert.assert_not_called()

    def test_clean_promote_records_no_override_in_the_ops_log(self) -> None:
        self._use('pass')
        self.assertEqual(202, self._promote().status_code)
        self.mocks['clickhouse'].return_value.insert.assert_not_called()


class ReleaseCiOverrideTestCase(unittest.IsolatedAsyncioTestCase):
    """Reading the promote-time CI decision back off the Release node.

    The dispatch path's audit row is written minutes later by the watcher,
    which must report what was decided at promote time rather than
    re-asking the plugin -- a re-run could have turned the commit green in
    between, and the row would then claim nothing was overridden.
    """

    async def test_reads_the_stamped_status_and_override(self) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(
            return_value=[
                {'ci_status': 'fail', 'overridden_by': 'daves@aweber.com'}
            ]
        )
        status, overridden = await project_deployments._release_ci_override(
            db, project_id='p1', release_id='r1'
        )
        self.assertEqual('fail', status)
        self.assertTrue(overridden)

    async def test_blank_actor_is_not_an_override(self) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(
            return_value=[{'ci_status': 'pass', 'overridden_by': ''}]
        )
        status, overridden = await project_deployments._release_ci_override(
            db, project_id='p1', release_id='r1'
        )
        self.assertEqual('pass', status)
        self.assertFalse(overridden)

    async def test_release_written_before_this_feature_reads_unknown(
        self,
    ) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(
            return_value=[{'ci_status': None, 'overridden_by': None}]
        )
        self.assertEqual(
            ('unknown', False),
            await project_deployments._release_ci_override(
                db, project_id='p1', release_id='r1'
            ),
        )

    async def test_missing_release_reads_unknown(self) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[])
        self.assertEqual(
            ('unknown', False),
            await project_deployments._release_ci_override(
                db, project_id='p1', release_id='r1'
            ),
        )

    async def test_a_failed_read_does_not_sink_the_audit_row(self) -> None:
        """The audit row matters more than the CI annotation on it."""
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(side_effect=RuntimeError('AGE is down'))
        self.assertEqual(
            ('unknown', False),
            await project_deployments._release_ci_override(
                db, project_id='p1', release_id='r1'
            ),
        )


class BuildFailureBlockScopeTestCase(unittest.IsolatedAsyncioTestCase):
    """A failed build blocks the version, not the commit."""

    async def test_fail_promote_build_scopes_the_block_to_the_tag(
        self,
    ) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'rid': 'r1'}])
        await project_deployments.fail_promote_build(
            db,
            org_slug='octo',
            project_id='p1',
            tag='0.1.5',
            reason='Release build reported failure',
            requested_by='daves@aweber.com',
        )
        params = db.execute.await_args.args[1]
        self.assertEqual('tag', params['scope'])
        self.assertEqual('0.1.5', params['tag'])
        self.assertEqual('daves@aweber.com', params['blocked_by'])
        self.assertIn('failure', params['reason'])

    async def test_missing_release_node_is_survivable(self) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[])
        # Deleted mid-build: warn, don't raise into the watcher.
        await project_deployments.fail_promote_build(
            db, org_slug='octo', project_id='p1', tag='0.1.5', reason='boom'
        )


class ReleaseIdentityTestCase(unittest.IsolatedAsyncioTestCase):
    """A tagged release is looked up by tag, not by commit.

    The release workflow bumps the version and tags the bump commit, so
    the SHA every later correlation carries is not the one Imbi promoted.
    Keying the lookup on the commit is what made those correlations miss
    and create duplicate ``Release`` nodes.
    """

    async def test_release_id_for_matches_on_the_tag(self) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'rid': 'rel-1'}])
        found = await project_deployments._release_id_for(
            db, project_id='p1', committish='27f2f81', tag='2.45.3'
        )
        self.assertEqual('rel-1', found)
        query, params, _ = db.execute.await_args.args
        self.assertIn('r.tag = {tag}', query)
        self.assertEqual('2.45.3', params['tag'])

    async def test_upsert_merges_the_tagged_node(self) -> None:
        """One statement, keyed on the tag -- not check-then-create."""
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'rid': 'rel-1'}])
        with mock.patch(
            f'{_MODULE}.graph.parse_agtype', side_effect=lambda x: x
        ):
            rid = await project_deployments._upsert_release_node(
                db,
                project_id='p1',
                tag='2.45.3',
                committish='27F2F81ABCDEF',
                title='2.45.3',
                notes_markdown='notes',
                release_url=None,
                created_by='a@b.c',
            )
        self.assertEqual('rel-1', rid)
        db.execute.assert_awaited_once()
        query, params, _ = db.execute.await_args.args
        self.assertIn(
            'MERGE (p)-[:HAS_RELEASE]->(r:Release {{tag: {tag}}})', query
        )
        # The committish is an attribute now: written on create, never
        # rewritten over an existing node.
        self.assertIn('r.committish = COALESCE(r.committish', query)
        self.assertEqual('27f2f81', params['committish'])

    async def test_upsert_falls_back_to_the_committish_when_untagged(
        self,
    ) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'rid': 'rel-2'}])
        with mock.patch(
            f'{_MODULE}.graph.parse_agtype', side_effect=lambda x: x
        ):
            await project_deployments._upsert_release_node(
                db,
                project_id='p1',
                tag=None,
                committish='deadbee',
                title='deadbee',
                notes_markdown='',
                release_url=None,
                created_by='a@b.c',
            )
        query = db.execute.await_args.args[0]
        self.assertIn('r:Release {{committish: {committish}}}', query)
        self.assertNotIn('r.tag', query)


class PromotedCommittishHealingTestCase(unittest.IsolatedAsyncioTestCase):
    """The Release adopts the commit its tag actually points at.

    ``release-tag.yaml`` bumps the version and tags the bump commit, so
    the tag routinely resolves to a different SHA than the one promoted.
    Imbi used to log that and keep the stale value, which guaranteed the
    deployment webhook -- which carries the post-bump SHA -- would miss.
    """

    def setUp(self) -> None:
        self.tagged = mock.Mock(sha='27f2f81abcdef')
        for target, replacement in (
            ('_resolve_and_context', mock.AsyncMock()),
            (
                '_handler',
                mock.Mock(
                    return_value=mock.Mock(
                        resolve_committish=mock.AsyncMock(
                            return_value=self.tagged
                        )
                    )
                ),
            ),
            ('_resolve_credentials', mock.Mock(return_value={})),
            ('_get_release', mock.AsyncMock(return_value=None)),
            ('persist_link_writeback', mock.AsyncMock()),
            ('_sync_promoted_tag', mock.AsyncMock()),
        ):
            patcher = mock.patch(f'{_MODULE}.{target}', replacement)
            self.addCleanup(patcher.stop)
            patcher.start()
        project_deployments._resolve_and_context.return_value = (
            mock.Mock(plugin_slug='github'),
            mock.Mock(environment_config=None),
            {},
        )

    async def _complete(self, db: mock.AsyncMock) -> None:
        await project_deployments.complete_promote_build(
            db,
            org_slug='octo',
            project_id='p1',
            release_id='rel1',
            tag='2.45.3',
            committish='3c1ea7b',
            to_environment='',
            deploy=False,
        )

    async def test_drift_rewrites_the_committish(self) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[])
        await self._complete(db)
        writes = [
            call.args[1]
            for call in db.execute.await_args_list
            if 'r.committish = {committish}' in call.args[0]
        ]
        self.assertEqual(1, len(writes))
        self.assertEqual('27f2f81', writes[0]['committish'])
        self.assertEqual('rel1', writes[0]['release_id'])

    async def test_an_agreeing_tag_writes_nothing(self) -> None:
        self.tagged.sha = '3c1ea7bfedcba'
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[])
        await self._complete(db)
        self.assertFalse(
            [
                call
                for call in db.execute.await_args_list
                if 'r.committish = {committish}' in call.args[0]
            ]
        )


class PromotedTagSyncTestCase(unittest.IsolatedAsyncioTestCase):
    """The tag a release build created is fed to ClickHouse.

    An API-created tag fires no ``push`` event, so nothing else records
    it.  The completion path syncs that one tag and only falls back to the
    queued full backfill when the bounded call cannot run.
    """

    def setUp(self) -> None:
        for target, replacement in (
            ('_resolve_and_context', mock.AsyncMock()),
            (
                '_handler',
                mock.Mock(
                    return_value=mock.Mock(
                        resolve_committish=mock.AsyncMock(return_value=None)
                    )
                ),
            ),
            ('_resolve_credentials', mock.Mock(return_value={})),
            ('_get_release', mock.AsyncMock(return_value=None)),
            ('persist_link_writeback', mock.AsyncMock()),
        ):
            patcher = mock.patch(f'{_MODULE}.{target}', replacement)
            self.addCleanup(patcher.stop)
            patcher.start()
        project_deployments._resolve_and_context.return_value = (
            mock.Mock(plugin_slug='github'),
            mock.Mock(environment_config=None),
            {},
        )
        self.sync_tag = self._patch(
            'commit_sync_service.run_tag_sync', return_value=1
        )
        self.enqueue = self._patch(
            'commit_sync_queue.enqueue_commit_sync', return_value=True
        )

    def _patch(self, target: str, **kwargs: typing.Any) -> mock.AsyncMock:
        patcher = mock.patch(f'{_MODULE}.{target}', mock.AsyncMock(**kwargs))
        self.addCleanup(patcher.stop)
        return patcher.start()

    async def _complete(self) -> None:
        await project_deployments.complete_promote_build(
            mock.AsyncMock(),
            org_slug='octo',
            project_id='p1',
            release_id='rel1',
            tag='0.1.5',
            committish='e6a13a0',
            to_environment='',
            deploy=False,
        )

    async def test_records_the_one_tag_without_a_backfill(self) -> None:
        await self._complete()
        self.sync_tag.assert_awaited_once_with(mock.ANY, 'octo', 'p1', '0.1.5')
        self.enqueue.assert_not_awaited()

    async def test_falls_back_when_the_plugin_lacks_the_bounded_sync(
        self,
    ) -> None:
        self.sync_tag.side_effect = NotImplementedError
        await self._complete()
        self.enqueue.assert_awaited_once()
        self.assertEqual('0.1.5', self.sync_tag.await_args.args[3])

    async def test_falls_back_when_the_bounded_sync_fails(self) -> None:
        self.sync_tag.side_effect = RuntimeError('clickhouse is down')
        await self._complete()
        self.enqueue.assert_awaited_once()

    async def test_a_tag_that_does_not_resolve_is_not_a_fallback(
        self,
    ) -> None:
        """Zero rows means the tag is absent remotely; a backfill can't
        find it either, so re-walking every tag buys nothing."""
        self.sync_tag.return_value = 0
        await self._complete()
        self.enqueue.assert_not_awaited()


class ProjectIsDeployableTestCase(unittest.IsolatedAsyncioTestCase):
    """``deployable`` is per project *type*, and a project can have several."""

    async def _ask(self, flags: typing.Any) -> bool:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(
            return_value=[{'flags': json.dumps(flags)}]
        )
        return await project_deployments._project_is_deployable(db, 'p1')

    async def test_true_when_any_type_is_deployable(self) -> None:
        self.assertTrue(await self._ask([False, True]))

    async def test_false_when_no_type_is_deployable(self) -> None:
        self.assertFalse(await self._ask([False, False]))

    async def test_false_when_the_project_has_no_type(self) -> None:
        self.assertFalse(await self._ask([]))

    async def test_false_when_the_project_is_missing(self) -> None:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[])
        self.assertFalse(
            await project_deployments._project_is_deployable(db, 'nope')
        )


def _relocating_resolved() -> ResolvedCapability:
    return _make_resolved(
        _RelocatingDeploymentPlugin, options={'owner': 'octo', 'repo': 'demo'}
    )


class LinkWritebackPersistTestCase(ProjectDeploymentsTestCase):
    """The endpoint persists the stored link when a plugin reports a
    canonical-URL change on ``ctx.link_writeback``.
    """

    def setUp(self) -> None:
        super().setUp()
        self.mocks['resolve_capability'].return_value = _relocating_resolved()
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


class ReleaseHistoryCiFallbackTestCase(ProjectDeploymentsTestCase):
    """#211: CI status for a project with nothing to deploy into.

    The history's ``ci_status`` is hydrated from the synced ``commits``
    table, which the deployment sync fills by walking ``DEPLOYED_TO``
    edges.  A releasable-only project (a CLI, a library) has no
    environments and therefore no edges, so every release read
    ``'unknown'`` while a green build sat in GitHub.
    """

    _BASE = '/organizations/myorg/projects/proj1/deployments'
    _WHEN = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

    def setUp(self) -> None:
        super().setUp()
        self._deployable = False
        self._props: dict[str, typing.Any] = {}
        self.mock_db.execute = mock.AsyncMock(side_effect=self._execute)

    def _execute(
        self, query: str, params: typing.Any, columns: typing.Any
    ) -> list[dict[str, typing.Any]]:
        del params, columns
        if 'pt.deployable' in query:
            return [{'flags': json.dumps([self._deployable])}]
        if 'properties(p)' in query:
            return [{'props': json.dumps(self._props)}]
        return []

    def _tags(self, *shas: str) -> None:
        """One ClickHouse tag row per sha, and no commit facts for any."""
        m = mock.AsyncMock(
            side_effect=[
                [
                    {
                        'name': f'v1.{i}.0',
                        'sha': sha,
                        'tagged_at': self._WHEN,
                        'tagger_name': 'Rel Bot',
                        'url': '',
                        'recorded_at': self._WHEN,
                    }
                    for i, sha in enumerate(shas)
                ],
                [],
            ]
        )
        patcher = mock.patch(f'{_MODULE}.clickhouse.query', new=m)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _use_plugin(self, status: str) -> None:
        self.mocks['resolve_capability'].return_value = _make_resolved(
            _ci_plugin(status), options={'owner': 'octo', 'repo': 'demo'}
        )

    def _history(self) -> list[dict[str, typing.Any]]:
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/release-history')
        self.assertEqual(200, response.status_code, response.text)
        return typing.cast('list[dict[str, typing.Any]]', response.json())

    def test_reads_the_projects_ci_attributes_first(self) -> None:
        """Attributes win over check-runs, deliberately.

        The check-runs path answers ``'unknown'`` for a repo on the legacy
        combined-status API and after the 403 memoization -- both of which
        would reintroduce the exact symptom this fixes.
        """
        self._props = {
            'ci_build_result': 'success',
            'ci_build_sha': 'aaa1111',
        }
        self._use_plugin('fail')
        self._tags('aaa1111aaa1111')
        self.assertEqual('pass', self._history()[0]['ci_status'])

    def test_attributes_naming_another_commit_are_ignored(self) -> None:
        """A green latest build says nothing about an older tag."""
        self._props = {
            'ci_build_result': 'success',
            'ci_build_sha': 'bbb2222',
        }
        self._use_plugin('unknown')
        self._tags('aaa1111aaa1111')
        self.assertEqual('not_applicable', self._history()[0]['ci_status'])

    def test_attributes_without_a_commit_are_ignored(self) -> None:
        """Nothing ties an unattributed result to a particular release."""
        self._props = {'ci_build_result': 'success'}
        self._use_plugin('unknown')
        self._tags('aaa1111aaa1111')
        self.assertEqual('not_applicable', self._history()[0]['ci_status'])

    def test_an_unrecognized_result_word_is_not_guessed_at(self) -> None:
        self._props = {'ci_build_result': 'purple', 'ci_build_sha': 'aaa1111'}
        self._use_plugin('unknown')
        self._tags('aaa1111aaa1111')
        self.assertEqual('not_applicable', self._history()[0]['ci_status'])

    def test_a_short_commit_attribute_is_too_ambiguous_to_match(self) -> None:
        """``'a'`` would prefix-match most shas; skip it instead."""
        self._props = {'ci_build_result': 'success', 'ci_build_sha': 'a'}
        self._use_plugin('unknown')
        self._tags('aaa1111aaa1111')
        self.assertEqual('not_applicable', self._history()[0]['ci_status'])

    def test_a_non_hex_commit_attribute_is_ignored(self) -> None:
        """A value that is not a sha at all cannot name a commit."""
        self._props = {
            'ci_build_result': 'success',
            'ci_build_sha': 'not-a-sha-at-all',
        }
        self._use_plugin('unknown')
        self._tags('aaa1111aaa1111')
        self.assertEqual('not_applicable', self._history()[0]['ci_status'])

    def test_falls_through_to_live_check_runs(self) -> None:
        self._use_plugin('pass')
        self._tags('aaa1111aaa1111')
        self.assertEqual('pass', self._history()[0]['ci_status'])

    def test_a_failing_build_is_reported_as_failing(self) -> None:
        self._use_plugin('fail')
        self._tags('aaa1111aaa1111')
        self.assertEqual('fail', self._history()[0]['ci_status'])

    def test_says_not_applicable_rather_than_unknown(self) -> None:
        """The whole point of #211.

        ``'unknown'`` claims a question was asked and came back empty.
        For this project nothing had been asked at all, and the column
        read the same as a genuinely red-flagged build.
        """
        self._use_plugin('unknown')
        self._tags('aaa1111aaa1111')
        self.assertEqual('not_applicable', self._history()[0]['ci_status'])

    def test_a_plugin_that_cannot_answer_does_not_fail_the_page(self) -> None:
        self.mocks['resolve_capability'].side_effect = fastapi.HTTPException(
            status_code=404, detail='no deployment plugin'
        )
        self._tags('aaa1111aaa1111')
        self.assertEqual('not_applicable', self._history()[0]['ci_status'])

    def test_a_deployable_project_keeps_its_unknown(self) -> None:
        """A deployable project's ``unknown`` really is unknown.

        The sync asked and got nothing, so a live check-runs call per
        release on every page load would buy nothing but latency.
        """
        self._deployable = True
        self._use_plugin('pass')
        self._tags('aaa1111aaa1111')
        self.assertEqual('unknown', self._history()[0]['ci_status'])

    def test_the_live_fallback_is_bounded(self) -> None:
        """One request per release, on a page load -- so it is capped.

        Releases past the cap keep the honest label rather than making
        the page wait on a request per row.
        """
        seen: list[str] = []

        class _RecordingCiPlugin(_FakeDeploymentPlugin):
            async def get_check_status(  # type: ignore[override]
                self, ctx, credentials, committish
            ):
                seen.append(committish)
                return 'pass'

        self.mocks['resolve_capability'].return_value = _make_resolved(
            _RecordingCiPlugin, options={'owner': 'octo', 'repo': 'demo'}
        )
        shas = [f'{i:02d}aaaaaaaaaaa' for i in range(15)]
        self._tags(*shas)
        statuses = [e['ci_status'] for e in self._history()]
        self.assertEqual(['pass'] * 10 + ['not_applicable'] * 5, statuses)
        # The cap keeps the ten highest-semver releases (v1.14.0 down to
        # v1.5.0), not just any ten.
        self.assertCountEqual(shas[5:], seen)


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

    # --- ClickHouse naive-timestamp serialization ---------------------
    #
    # DateTime64 columns come back naive even though they hold UTC. Passed
    # straight into a Pydantic model the JSON carries no offset, and the
    # browser then reads the value in its own zone — commit and release
    # dates drifted by that zone's offset.

    # Naive on purpose: ClickHouse returns naive DateTime64 values.
    _NAIVE = datetime.datetime(2026, 1, 1, 12, 0, 0)  # noqa: DTZ001

    def _assert_utc(self, value: str) -> None:
        parsed = datetime.datetime.fromisoformat(value)
        self.assertIsNotNone(parsed.tzinfo, f'{value!r} carries no offset')
        self.assertEqual(parsed.utcoffset(), datetime.timedelta(0))
        self.assertEqual(parsed, self._NAIVE.replace(tzinfo=datetime.UTC))

    def test_recent_commits_authored_at_carries_utc_offset(self) -> None:
        row = self._commit_row('abc1234def')
        row['authored_at'] = self._NAIVE
        self._patch_query([[row]])
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/recent-commits')
        self.assertEqual(response.status_code, 200, response.text)
        self._assert_utc(response.json()[0]['authored_at'])

    def test_release_history_published_at_carries_utc_offset(self) -> None:
        self._patch_query(
            [
                [
                    {
                        'name': 'v1.0.0',
                        'sha': 'sha10',
                        'tagged_at': self._NAIVE,
                        'tagger_name': 'Rel Bot',
                        'url': '',
                        'recorded_at': None,
                    }
                ],
                [{'sha': 'sha10', 'ci_status': 'pass'}],
            ]
        )
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/release-history')
        self.assertEqual(response.status_code, 200, response.text)
        self._assert_utc(response.json()[0]['published_at'])

    def test_release_history_falls_back_to_recorded_at(self) -> None:
        """No tag date recorded -> recorded_at, still offset-bearing."""
        self._patch_query(
            [
                [
                    {
                        'name': 'v1.0.0',
                        'sha': 'sha10',
                        'tagged_at': None,
                        'tagger_name': '',
                        'url': '',
                        'recorded_at': self._NAIVE,
                    }
                ],
                [],
            ]
        )
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/release-history')
        self.assertEqual(response.status_code, 200, response.text)
        self._assert_utc(response.json()[0]['published_at'])

    def test_release_history_published_at_null_when_undated(self) -> None:
        self._patch_query(
            [
                [
                    {
                        'name': 'v1.0.0',
                        'sha': 'sha10',
                        'tagged_at': None,
                        'tagger_name': '',
                        'url': '',
                        'recorded_at': None,
                    }
                ],
                [],
            ]
        )
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        with testclient.TestClient(self.test_app) as client:
            response = client.get(f'{self._BASE}/release-history')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()[0]['published_at'])

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
        # Tag with no matching Release node -> null metadata, and no CI
        # status anywhere: the mocked project is not deployable, so the
        # #211 fallback runs and answers ``not_applicable`` rather than
        # claiming a question was asked and came back empty.
        self.assertIsNone(data[1]['notes_markdown'])
        self.assertEqual(data[1]['ci_status'], 'not_applicable')

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

        self.mocks['resolve_capability'].return_value = _make_resolved(
            _NoDeploy, options={'owner': 'octo', 'repo': 'demo'}
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

        self.mocks['resolve_capability'].return_value = _make_resolved(
            _BoomRelease, options={}
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


class ReleasePublishTestCase(ProjectDeploymentsTestCase):
    """Ratifying a Release: ``POST /deployments/releases/{tag}/publish``."""

    _BASE = '/organizations/myorg/projects/proj1/deployments'
    _PUBLISH = f'{_BASE}/releases/v6.4.0/publish'

    def _patch_execute(
        self,
        *,
        found: bool = True,
        blocked: bool = False,
    ) -> dict[str, list[dict[str, typing.Any]]]:
        """Route the endpoint's graph reads by query text.

        Returns a dict the test can inspect for the parameters of the
        ``Release``-node link upsert (empty when it never ran).
        """
        node = self._release_node() if found else None
        seen: dict[str, list[dict[str, typing.Any]]] = {'upsert': []}

        def _execute(
            query: str, params: dict[str, typing.Any], columns: typing.Any
        ) -> list[dict[str, typing.Any]]:
            del columns
            if 'r.blocked_at IS NOT NULL' in query:
                return (
                    [
                        {
                            'release': json.dumps(
                                {
                                    'tag': 'v6.4.0',
                                    'blocked_reason': 'Regression',
                                }
                            )
                        }
                    ]
                    if blocked
                    else []
                )
            if 'RETURN r{{.id, .tag' in query:
                return [] if node is None else [{'release': json.dumps(node)}]
            if 'MERGE (p)-[:HAS_RELEASE]->' in query:
                seen['upsert'].append(params)
                return [{'rid': 'rel-1'}]
            return []

        self.mock_db.execute = mock.AsyncMock(side_effect=_execute)
        return seen

    @staticmethod
    def _release_node(**overrides: typing.Any) -> dict[str, typing.Any]:
        return {
            'id': 'rel-1',
            'tag': 'v6.4.0',
            'committish': '1a9c610',
            'title': 'Release 6.4.0',
            'description': '## Highlights\n- foo',
            'created_at': '2026-01-01T00:00:00+00:00',
            **overrides,
        }

    def test_publish_creates_the_remote_release(self) -> None:
        seen = self._patch_execute()
        with testclient.TestClient(self.test_app) as client:
            response = client.post(self._PUBLISH)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['tag'], 'v6.4.0')
        self.assertTrue(data['published'])
        self.assertEqual(data['release_url'], 'https://gh/releases/v6.4.0')
        self.assertIsNone(data['warning'])
        # The github_release link was written back onto the node.
        self.assertEqual(len(seen['upsert']), 1)
        self.assertIn('https://gh/releases/v6.4.0', seen['upsert'][0]['links'])
        # ...without clobbering the notes already recorded there.
        self.assertEqual(seen['upsert'][0]['description'], '')

    def test_publish_uses_the_nodes_title_and_notes(self) -> None:
        # The ratification must not drift from what Imbi recorded at
        # promote time, so title/body come from the Release node rather
        # than from the caller.
        captured: dict[str, typing.Any] = {}

        class _Capturing(_FakeDeploymentPlugin):
            async def create_release(  # type: ignore[override]
                self,
                ctx,
                credentials,
                tag,
                name,
                body_markdown,
                prerelease=False,
            ):
                captured.update(
                    tag=tag,
                    name=name,
                    body_markdown=body_markdown,
                    prerelease=prerelease,
                )
                return await super().create_release(
                    ctx, credentials, tag, name, body_markdown, prerelease
                )

        self.mocks['resolve_capability'].return_value = _make_resolved(
            _Capturing
        )
        self._patch_execute()
        with testclient.TestClient(self.test_app) as client:
            response = client.post(self._PUBLISH, json={'prerelease': True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured['tag'], 'v6.4.0')
        self.assertEqual(captured['name'], 'Release 6.4.0')
        self.assertEqual(captured['body_markdown'], '## Highlights\n- foo')
        self.assertTrue(captured['prerelease'])

    def test_publish_unknown_tag_is_404(self) -> None:
        self._patch_execute(found=False)
        with testclient.TestClient(self.test_app) as client:
            response = client.post(self._PUBLISH)
        self.assertEqual(response.status_code, 404)
        self.assertIn('No release found', response.json()['detail'])

    def test_publish_of_a_blocked_release_is_409(self) -> None:
        self._patch_execute(blocked=True)
        with testclient.TestClient(self.test_app) as client:
            response = client.post(self._PUBLISH)
        self.assertEqual(response.status_code, 409)
        self.assertIn('is blocked', response.json()['detail'])

    def test_publish_degrades_a_plugin_failure_to_a_warning(self) -> None:
        class _Boom(_FakeDeploymentPlugin):
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

        self.mocks['resolve_capability'].return_value = _make_resolved(_Boom)
        seen = self._patch_execute()
        with testclient.TestClient(self.test_app) as client:
            response = client.post(self._PUBLISH)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['published'])
        self.assertIsNone(data['release_url'])
        self.assertIn('create_release', data['warning'])
        # Nothing was written back -- there is no URL to record.
        self.assertEqual(seen['upsert'], [])

    def test_publish_is_idempotent_for_an_existing_remote_release(
        self,
    ) -> None:
        # A 422 "already exists" is the second delivery of the same
        # deployment_status webhook, not a failure: the endpoint reports
        # published and recovers the URL via ``get_release``.
        class _AlreadyThere(_FakeDeploymentPlugin):
            async def create_release(  # type: ignore[override]
                self,
                ctx,
                credentials,
                tag,
                name,
                body_markdown,
                prerelease=False,
            ):
                raise httpx.HTTPStatusError(
                    'already exists',
                    request=httpx.Request('POST', 'https://api.gh/releases'),
                    response=httpx.Response(
                        422, json={'message': 'Reference already exists'}
                    ),
                )

            async def get_release(  # type: ignore[override]
                self, ctx, credentials, tag
            ):
                return RemoteRelease(
                    tag=tag, html_url=f'https://gh/releases/{tag}'
                )

        self.mocks['resolve_capability'].return_value = _make_resolved(
            _AlreadyThere
        )
        seen = self._patch_execute()
        with testclient.TestClient(self.test_app) as client:
            response = client.post(self._PUBLISH)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['published'])
        self.assertEqual(data['release_url'], 'https://gh/releases/v6.4.0')
        self.assertIsNone(data['warning'])
        self.assertEqual(len(seen['upsert']), 1)

    def test_publish_is_idempotent_for_a_validation_failed_conflict(
        self,
    ) -> None:
        # ``POST /releases`` does not report a duplicate tag the way
        # ``POST /git/refs`` does: the top-level message is the generic
        # "Validation Failed" and ``already_exists`` shows up only as an
        # error code.  Both shapes are the same idempotent no-op.
        class _AlreadyThere(_FakeDeploymentPlugin):
            async def create_release(  # type: ignore[override]
                self,
                ctx,
                credentials,
                tag,
                name,
                body_markdown,
                prerelease=False,
            ):
                raise httpx.HTTPStatusError(
                    "Client error '422 Unprocessable Entity'",
                    request=httpx.Request('POST', 'https://api.gh/releases'),
                    response=httpx.Response(
                        422,
                        json={
                            'message': 'Validation Failed',
                            'errors': [
                                {
                                    'resource': 'Release',
                                    'code': 'already_exists',
                                    'field': 'tag_name',
                                }
                            ],
                        },
                    ),
                )

            async def get_release(  # type: ignore[override]
                self, ctx, credentials, tag
            ):
                return RemoteRelease(
                    tag=tag, html_url=f'https://gh/releases/{tag}'
                )

        self.mocks['resolve_capability'].return_value = _make_resolved(
            _AlreadyThere
        )
        seen = self._patch_execute()
        with testclient.TestClient(self.test_app) as client:
            response = client.post(self._PUBLISH)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['published'])
        self.assertEqual(data['release_url'], 'https://gh/releases/v6.4.0')
        self.assertIsNone(data['warning'])
        self.assertEqual(len(seen['upsert']), 1)

    def test_publish_writes_an_operations_log_audit(self) -> None:
        self._patch_execute()
        with testclient.TestClient(self.test_app) as client:
            response = client.post(self._PUBLISH)
        self.assertEqual(response.status_code, 200)
        insert = self.mocks['clickhouse'].return_value.insert
        insert.assert_awaited()
        columns = insert.await_args.args[2]
        row = dict(zip(columns, insert.await_args.args[1][0], strict=True))
        self.assertEqual(row['version'], 'v6.4.0')
        self.assertEqual(json.loads(row['description'])['action'], 'publish')


class ReleaseBlockTestCase(ProjectDeploymentsTestCase):
    """Blocking a release, unblocking it, and the deploy / promote gate."""

    _BASE = '/organizations/myorg/projects/proj1/deployments'
    _BLOCK = f'{_BASE}/releases/v3.32.2/block'

    @staticmethod
    def _blocked_row(
        *,
        tag: str = 'v3.32.2',
        committish: str = '1a9c610',
        reason: str | None = 'Regression in checkout',
    ) -> list[dict[str, typing.Any]]:
        """One row shaped like the ``_blocked_release`` projection."""
        return [
            {
                'release': json.dumps(
                    {
                        'tag': tag,
                        'committish': committish,
                        'blocked_reason': reason,
                    }
                )
            }
        ]

    def test_block_sets_state_and_echoes_reason(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[{'rid': 'r1'}])
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                self._BLOCK, json={'reason': 'Regression in checkout'}
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['tag'], 'v3.32.2')
        self.assertTrue(data['blocked'])
        self.assertEqual(data['blocked_reason'], 'Regression in checkout')
        self.assertEqual(data['blocked_by'], 'admin@example.com')
        self.assertIsNotNone(data['blocked_at'])

    def test_block_requires_a_reason(self) -> None:
        with testclient.TestClient(self.test_app) as client:
            blank = client.post(self._BLOCK, json={'reason': '   '})
            missing = client.post(self._BLOCK, json={})
        self.assertEqual(blank.status_code, 422)
        self.assertEqual(missing.status_code, 422)

    def test_block_creates_release_node_for_a_synced_tag(self) -> None:
        """A tag synced but never cut in Imbi still blocks."""
        # Dispatch on the query rather than call order: the block only
        # lands once the upsert has created the node, and keying off the
        # text survives a change in how many round-trips the upsert makes.
        created: dict[str, bool] = {'node': False}

        def _execute(
            query: str, params: typing.Any, columns: typing.Any
        ) -> list[dict[str, typing.Any]]:
            del params, columns
            if 'MERGE (p)-[:HAS_RELEASE]' in query:
                created['node'] = True
                return []
            if 'SET r.blocked_at' in query:
                return [{'rid': 'r9'}] if created['node'] else []
            return [{'rid': 'r9'}]

        self.mock_db.execute = mock.AsyncMock(side_effect=_execute)
        query = mock.AsyncMock(return_value=[{'sha': '1a9c610abcdef'}])
        with (
            mock.patch(f'{_MODULE}.clickhouse.query', new=query),
            testclient.TestClient(self.test_app) as client,
        ):
            response = client.post(self._BLOCK, json={'reason': 'Rolled back'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['blocked'])
        self.assertEqual(query.await_args.args[1]['tag'], 'v3.32.2')

    def test_block_unknown_tag_is_404(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        with (
            mock.patch(
                f'{_MODULE}.clickhouse.query',
                new=mock.AsyncMock(return_value=[]),
            ),
            testclient.TestClient(self.test_app) as client,
        ):
            response = client.post(self._BLOCK, json={'reason': 'Rolled back'})
        self.assertEqual(response.status_code, 404)
        self.assertIn('No release found', response.json()['detail'])

    def test_unblock_clears_the_state(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[{'rid': 'r1'}])
        with testclient.TestClient(self.test_app) as client:
            response = client.delete(self._BLOCK)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['blocked'])
        self.assertIsNone(data['blocked_reason'])
        # All three properties are nulled in the SET.
        params = self.mock_db.execute.await_args.args[1]
        self.assertIsNone(params['blocked_at'])
        self.assertIsNone(params['blocked_by'])
        self.assertIsNone(params['reason'])

    def test_unblock_unknown_tag_is_404(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=[])
        with testclient.TestClient(self.test_app) as client:
            response = client.delete(self._BLOCK)
        self.assertEqual(response.status_code, 404)

    def test_deploy_of_a_blocked_release_is_409_with_the_reason(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=self._blocked_row())
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                self._BASE,
                json={
                    'action': 'deploy',
                    'environment': 'production',
                    'committish': '1a9c610',
                    'ref_label': 'v3.32.2',
                },
            )
        self.assertEqual(response.status_code, 409)
        detail = response.json()['detail']
        self.assertIn("Release 'v3.32.2' is blocked", detail)
        self.assertIn('Regression in checkout', detail)

    def test_promote_of_a_blocked_release_is_409(self) -> None:
        self.mock_db.execute = mock.AsyncMock(return_value=self._blocked_row())
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                self._BASE,
                json={
                    'action': 'promote',
                    'from_environment': 'staging',
                    'to_environment': 'production',
                    'from_committish': '1a9c610',
                    'tag': 'v3.32.2',
                },
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn('is blocked', response.json()['detail'])

    def test_block_gate_omits_the_reason_when_none_recorded(self) -> None:
        self.mock_db.execute = mock.AsyncMock(
            return_value=self._blocked_row(reason=None)
        )
        with testclient.TestClient(self.test_app) as client:
            response = client.post(
                self._BASE,
                json={
                    'action': 'deploy',
                    'environment': 'production',
                    'committish': '1a9c610',
                    'ref_label': 'v3.32.2',
                },
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['detail'],
            "Release 'v3.32.2' is blocked and cannot be deployed",
        )

    def test_release_history_reports_block_state(self) -> None:
        when = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        blocked_at = datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC)
        query = mock.AsyncMock(
            side_effect=[
                [
                    {
                        'name': 'v3.32.2',
                        'sha': 'sha3322',
                        'tagged_at': when,
                        'tagger_name': 'Rel Bot',
                        'url': '',
                        'recorded_at': when,
                    },
                    {
                        'name': 'v3.32.1',
                        'sha': 'sha3321',
                        'tagged_at': when,
                        'tagger_name': 'Rel Bot',
                        'url': '',
                        'recorded_at': when,
                    },
                ],
                [],  # ci_status lookup
            ]
        )
        self.mock_db.execute = mock.AsyncMock(
            return_value=[
                {
                    'release': json.dumps(
                        {
                            'tag': 'v3.32.2',
                            'title': 'Release 3.32.2',
                            'created_by': 'gr',
                            'blocked_at': blocked_at.isoformat(),
                            'blocked_by': 'admin@example.com',
                            'blocked_reason': 'Regression in checkout',
                        }
                    )
                }
            ]
        )
        with (
            mock.patch(f'{_MODULE}.clickhouse.query', new=query),
            testclient.TestClient(self.test_app) as client,
        ):
            response = client.get(f'{self._BASE}/release-history')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data[0]['tag'], 'v3.32.2')
        self.assertTrue(data[0]['blocked'])
        self.assertEqual(data[0]['blocked_reason'], 'Regression in checkout')
        self.assertEqual(data[0]['blocked_by'], 'admin@example.com')
        self.assertIsNotNone(data[0]['blocked_at'])
        # A tag with no Release node is not blocked.
        self.assertFalse(data[1]['blocked'])
        self.assertIsNone(data[1]['blocked_reason'])


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


class ExistingTagForCommittishTestCase(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the ``_existing_tag_for_committish`` reconcile helper."""

    @staticmethod
    def _db(rows: list[dict[str, typing.Any]]) -> mock.AsyncMock:
        db = mock.AsyncMock(spec=graph.Graph)
        db.execute = mock.AsyncMock(return_value=rows)
        return db

    async def test_returns_none_when_no_tagged_release(self) -> None:
        db = self._db([])
        result = await project_deployments._existing_tag_for_committish(
            db, project_id='pid', committish='deadbeef'
        )
        self.assertIsNone(result)

    async def test_returns_single_tag(self) -> None:
        db = self._db([{'tag': 'v1.0.0'}])
        result = await project_deployments._existing_tag_for_committish(
            db, project_id='pid', committish='deadbeef'
        )
        self.assertEqual(result, 'v1.0.0')

    async def test_deduplicates_repeated_tag(self) -> None:
        db = self._db([{'tag': 'v1.0.0'}, {'tag': 'v1.0.0'}])
        result = await project_deployments._existing_tag_for_committish(
            db, project_id='pid', committish='deadbeef'
        )
        self.assertEqual(result, 'v1.0.0')

    async def test_raises_when_commit_has_multiple_tags(self) -> None:
        db = self._db([{'tag': 'v1.0.0'}, {'tag': 'v2.0.0'}])
        with self.assertRaises(ValueError):
            await project_deployments._existing_tag_for_committish(
                db, project_id='pid', committish='deadbeef'
            )

    async def test_matches_the_promoted_committish(self) -> None:
        """A promote heals the node onto the version-bump commit.

        The testing deployments that preceded it still resync carrying
        the promoted commit, so the lookup has to consider both.
        """
        db = self._db([{'tag': 'v1.0.0'}])
        await project_deployments._existing_tag_for_committish(
            db, project_id='pid', committish='deadbeef'
        )
        self.assertIn(
            'r.promoted_committish = {committish}',
            db.execute.await_args.args[0],
        )


class AdoptUntaggedReleaseTestCase(unittest.IsolatedAsyncioTestCase):
    """The promote tags the node already holding the commit's history."""

    @staticmethod
    def _db(*results: list[dict[str, typing.Any]]) -> mock.AsyncMock:
        db = mock.AsyncMock(spec=graph.Graph)
        db.execute = mock.AsyncMock(side_effect=list(results))
        return db

    async def test_tags_the_untagged_release_for_the_commit(self) -> None:
        db = self._db([], [{'rid': 'rel-1'}], [{'rid': 'rel-1'}])
        result = await project_deployments._adopt_untagged_release(
            db, project_id='pid', committish='1A9C610FFFF', tag='v1.0.0'
        )
        self.assertEqual(result, 'rel-1')
        # Normalized, because the untagged node was keyed on the short
        # form when the resync created it.
        self.assertEqual(
            db.execute.await_args_list[1].args[1]['committish'], '1a9c610'
        )
        query, params, _ = db.execute.await_args_list[2].args
        self.assertIn('SET r.tag', query)
        self.assertIn('WHERE r.tag IS NULL', query)
        self.assertEqual(params['release_id'], 'rel-1')
        self.assertEqual(params['tag'], 'v1.0.0')

    async def test_skips_when_the_node_is_tagged_before_the_write(
        self,
    ) -> None:
        """Two tags promoting the same commit at once.

        Both probes see the node untagged, so both reach the write.  The
        write's own ``r.tag IS NULL`` is what makes the loser match
        nothing rather than overwrite the winner's tag.
        """
        db = self._db([], [{'rid': 'rel-1'}], [])
        with self.assertLogs('imbi.api.endpoints', level='WARNING') as logs:
            result = await project_deployments._adopt_untagged_release(
                db, project_id='pid', committish='1a9c610', tag='v2.0.0'
            )
        self.assertIsNone(result)
        self.assertTrue(
            any('tagged between the probe' in line for line in logs.output),
        )

    async def test_skips_when_a_release_already_carries_the_tag(self) -> None:
        db = self._db([{'rid': 'rel-existing'}])
        result = await project_deployments._adopt_untagged_release(
            db, project_id='pid', committish='1a9c610', tag='v1.0.0'
        )
        self.assertIsNone(result)
        self.assertEqual(db.execute.await_count, 1)

    async def test_returns_none_when_nothing_to_adopt(self) -> None:
        db = self._db([], [])
        result = await project_deployments._adopt_untagged_release(
            db, project_id='pid', committish='1a9c610', tag='v1.0.0'
        )
        self.assertIsNone(result)

    async def test_skips_when_several_untagged_nodes_share_the_commit(
        self,
    ) -> None:
        """Tagging every match would create the duplicate we avoid."""
        db = self._db([], [{'rid': 'rel-1'}, {'rid': 'rel-2'}])
        with self.assertLogs('imbi.api.endpoints', level='WARNING') as logs:
            result = await project_deployments._adopt_untagged_release(
                db, project_id='pid', committish='1a9c610', tag='v1.0.0'
            )
        self.assertIsNone(result)
        self.assertEqual(db.execute.await_count, 2)
        self.assertTrue(
            any('Not adopting' in line for line in logs.output),
        )


class ReleaseCommittishHealTestCase(unittest.IsolatedAsyncioTestCase):
    """The heal keeps the commit it moves away from."""

    async def test_preserves_the_promoted_committish(self) -> None:
        db = mock.AsyncMock(spec=graph.Graph)
        db.execute = mock.AsyncMock(return_value=[])
        await project_deployments._set_release_committish(
            db, release_id='rel-1', committish='bump123'
        )
        query = db.execute.await_args.args[0]
        self.assertIn(
            'r.promoted_committish = COALESCE(\n            '
            'r.promoted_committish, r.committish)',
            query,
        )
        self.assertIn('r.committish = {committish}', query)


class ReleaseAuthorTestCase(unittest.TestCase):
    """Who a release-history entry is attributed to."""

    @staticmethod
    def _author(
        tagger: str | None,
        created_by: str | None,
        commit: tuple[str | None, str | None] = (None, None),
    ) -> tuple[str | None, str | None]:
        from imbi.api.endpoints.project_deployments import (
            _CommitFacts,
            _release_author,
        )

        facts = _CommitFacts(
            ci_status='unknown', author=commit[0], author_email=commit[1]
        )
        return _release_author(tagger, created_by, facts)

    def test_annotated_tagger_wins(self) -> None:
        self.assertEqual(
            ('Gavin M. Roy', None), self._author('Gavin M. Roy', None)
        )

    def test_recorded_person_is_used_with_their_email(self) -> None:
        self.assertEqual(
            ('gavinr@aweber.com', 'gavinr@aweber.com'),
            self._author(None, 'gavinr@aweber.com'),
        )

    def test_worker_principal_is_never_the_author(self) -> None:
        # The reported break: a release the resync observed read as
        # "released by deployment-sync" -- a process, not a person.
        self.assertEqual(
            ('Gavin M. Roy', 'gavinr@aweber.com'),
            self._author(
                None, 'deployment-sync', ('Gavin M. Roy', 'gavinr@aweber.com')
            ),
        )
        for principal in ('commit-sync', 'maintenance', 'pr-sync', 'system'):
            self.assertEqual((None, None), self._author(None, principal))

    def test_falls_back_to_the_tagged_commits_author(self) -> None:
        self.assertEqual(
            ('Gavin M. Roy', 'gavinr@aweber.com'),
            self._author(None, None, ('Gavin M. Roy', 'gavinr@aweber.com')),
        )

    def test_nothing_known_is_none(self) -> None:
        self.assertEqual((None, None), self._author(None, None))


class ReleaseAuthorPrincipalTestCase(unittest.IsolatedAsyncioTestCase):
    """What ``created_by`` a remote release is stored under."""

    @staticmethod
    async def _principal(
        release: typing.Any, resolver: object = None
    ) -> str | None:
        from imbi.api.endpoints.project_deployments import _remote_principal

        if release is None:
            return None
        return await _remote_principal(
            release.author,
            release.author_subject,
            resolver,  # type: ignore[arg-type]
        )

    async def test_resolves_the_remote_subject_to_an_imbi_user(self) -> None:
        from imbi.common.plugins.base import RemoteRelease

        release = RemoteRelease(
            tag='2.21.0', author='gavinr', author_subject='175531'
        )
        resolver = mock.AsyncMock(return_value='gavinr@aweber.com')
        self.assertEqual(
            'gavinr@aweber.com', await self._principal(release, resolver)
        )
        resolver.assert_awaited_once_with('175531')

    async def test_falls_back_to_the_remote_login(self) -> None:
        from imbi.common.plugins.base import RemoteRelease

        release = RemoteRelease(
            tag='2.21.0', author='gavinr', author_subject='175531'
        )
        resolver = mock.AsyncMock(return_value=None)
        self.assertEqual('gavinr', await self._principal(release, resolver))

    async def test_resolver_failure_still_yields_the_login(self) -> None:
        from imbi.common.plugins.base import RemoteRelease

        release = RemoteRelease(
            tag='2.21.0', author='gavinr', author_subject='175531'
        )
        resolver = mock.AsyncMock(side_effect=RuntimeError('boom'))
        self.assertEqual('gavinr', await self._principal(release, resolver))

    async def test_no_release_is_none(self) -> None:
        self.assertIsNone(await self._principal(None))
