import datetime
import unittest

import imbi_common.plugins.base as plugin_base
from imbi_common.plugins.base import (
    AuthorizationRequest,
    Commit,
    CompareResult,
    ConfigKey,
    ConfigKeyWithValue,
    DeploymentPlugin,
    DeploymentRun,
    IdentityCredentials,
    IdentityProfile,
    LifecyclePlugin,
    LifecycleResult,
    LogFilter,
    LogQuery,
    PluginContext,
    PluginEdgeLabel,
    PluginIndex,
    PluginManifest,
    PluginOption,
    PluginVertexLabel,
    PollingDescriptor,
    Ref,
    RefInfo,
    ReleaseInfo,
    RemoteDeployment,
    WorkflowFile,
)


class PluginManifestTestCase(unittest.TestCase):
    def test_plugin_manifest_valid(self) -> None:
        manifest = PluginManifest(
            slug='test',
            name='Test',
            plugin_type='configuration',
        )
        self.assertEqual(manifest.slug, 'test')
        self.assertEqual(manifest.name, 'Test')
        self.assertEqual(manifest.plugin_type, 'configuration')
        self.assertEqual(manifest.api_version, 1)
        self.assertTrue(manifest.cacheable)
        self.assertEqual(manifest.options, [])
        self.assertEqual(manifest.credentials, [])
        self.assertEqual(manifest.data_types, [])

    def test_plugin_manifest_with_options(self) -> None:
        option = PluginOption(name='key', label='Key', required=True)
        manifest = PluginManifest(
            slug='test',
            name='Test',
            plugin_type='configuration',
            options=[option],
        )
        self.assertEqual(len(manifest.options), 1)
        self.assertEqual(manifest.options[0].name, 'key')
        self.assertEqual(manifest.options[0].label, 'Key')
        self.assertTrue(manifest.options[0].required)


class ConfigKeyTestCase(unittest.TestCase):
    def test_config_key_no_value(self) -> None:
        key = ConfigKey(key='MY_KEY', data_type='string')
        self.assertEqual(key.key, 'MY_KEY')
        self.assertEqual(key.data_type, 'string')
        self.assertFalse(hasattr(key, 'value') and 'value' in key.model_fields)

    def test_config_key_with_value(self) -> None:
        key = ConfigKeyWithValue(
            key='MY_KEY', data_type='string', value='hello'
        )
        self.assertEqual(key.key, 'MY_KEY')
        self.assertEqual(key.value, 'hello')


class LogQueryTestCase(unittest.TestCase):
    def test_log_query_filters(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        later = now + datetime.timedelta(hours=1)
        filt = LogFilter(field='level', op='eq', value='ERROR')
        query = LogQuery(start_time=now, end_time=later, filters=[filt])
        self.assertEqual(len(query.filters), 1)
        self.assertEqual(query.filters[0].field, 'level')
        self.assertEqual(query.filters[0].op, 'eq')
        self.assertEqual(query.filters[0].value, 'ERROR')

    def test_log_filter_ops(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        later = now + datetime.timedelta(hours=1)
        for op in ('eq', 'ne', 'contains', 'starts_with', 'regex'):
            filt = LogFilter(field='msg', op=op, value='test')  # type: ignore[arg-type]
            query = LogQuery(start_time=now, end_time=later, filters=[filt])
            self.assertEqual(query.filters[0].op, op)


class IdentityModelsTestCase(unittest.TestCase):
    def test_identity_profile_round_trip(self) -> None:
        profile = IdentityProfile(
            subject='user-123',
            email='alice@example.com',
            email_verified=True,
            name='Alice',
            groups=['admins'],
            raw_claims={'sub': 'user-123'},
        )
        restored = IdentityProfile.model_validate(profile.model_dump())
        self.assertEqual(restored.subject, 'user-123')
        self.assertEqual(restored.email, 'alice@example.com')
        self.assertTrue(restored.email_verified)
        self.assertEqual(restored.groups, ['admins'])

    def test_identity_credentials_redacted_repr(self) -> None:
        credentials = IdentityCredentials(
            access_token='very-secret',
            refresh_token='refresh-secret',
            extra={'aws_secret_access_key': 'keep-me-out'},
        )
        self.assertEqual(repr(credentials), '<IdentityCredentials redacted>')
        self.assertEqual(str(credentials), '<IdentityCredentials redacted>')
        self.assertNotIn('very-secret', repr(credentials))
        self.assertNotIn('refresh-secret', str(credentials))

    def test_authorization_request_polling(self) -> None:
        polling = PollingDescriptor(
            user_code='ABCD-1234',
            verification_uri='https://device.sso.example.com',
            interval=5,
            expires_in=600,
        )
        request = AuthorizationRequest(
            authorization_url='https://device.sso.example.com',
            state='state-token',
            polling=polling,
        )
        self.assertEqual(request.polling, polling)

    def test_plugin_context_identity_optional(self) -> None:
        ctx = PluginContext(
            project_id='p-1',
            project_slug='proj',
            org_slug='org',
        )
        self.assertIsNone(ctx.identity)
        self.assertIsNone(ctx.actor_user_id)


class IdentityPluginManifestTestCase(unittest.TestCase):
    def test_identity_plugin_manifest(self) -> None:
        manifest = PluginManifest(
            slug='oidc',
            name='OIDC',
            plugin_type='identity',
            auth_type='oidc',
            login_capable=True,
            requires_identity=False,
            default_scopes=['openid', 'profile'],
        )
        self.assertEqual(manifest.plugin_type, 'identity')
        self.assertEqual(manifest.auth_type, 'oidc')
        self.assertTrue(manifest.login_capable)
        self.assertEqual(manifest.default_scopes, ['openid', 'profile'])

    def test_plugin_vertex_label_round_trip(self) -> None:
        vlabel = PluginVertexLabel(
            name='AwsAccount',
            indexes=[
                PluginIndex(fields=['account_id'], unique=True),
                PluginIndex(fields=['name']),
            ],
            model_ref='imbi_plugin_aws.models:AwsAccount',
        )
        restored = PluginVertexLabel.model_validate(vlabel.model_dump())
        self.assertEqual(restored.name, 'AwsAccount')
        self.assertEqual(len(restored.indexes), 2)
        self.assertTrue(restored.indexes[0].unique)
        self.assertFalse(restored.indexes[1].unique)
        self.assertEqual(
            restored.model_ref, 'imbi_plugin_aws.models:AwsAccount'
        )

    def test_plugin_edge_label_round_trip(self) -> None:
        edge = PluginEdgeLabel(
            name='MAPS_TO',
            from_labels=['Environment', 'Project'],
            to_labels=['AwsAccount'],
        )
        self.assertEqual(edge.name, 'MAPS_TO')
        self.assertEqual(edge.to_labels, ['AwsAccount'])


class DeploymentModelsTestCase(unittest.TestCase):
    def test_ref_round_trip(self) -> None:
        ref = Ref(
            name='main',
            kind='default',
            sha='1a2b3c4',
            is_default=True,
            ahead=0,
            behind=0,
        )
        restored = Ref.model_validate(ref.model_dump())
        self.assertEqual(restored.name, 'main')
        self.assertEqual(restored.kind, 'default')
        self.assertTrue(restored.is_default)

    def test_commit_defaults(self) -> None:
        commit = Commit(
            sha='abcdef0123456789',
            short_sha='abcdef0',
            message='Fix bug',
        )
        self.assertEqual(commit.ci_status, 'unknown')
        self.assertFalse(commit.is_head)
        self.assertIsNone(commit.author)

    def test_compare_result_aggregates(self) -> None:
        commit = Commit(sha='abc', short_sha='abc', message='one')
        result = CompareResult(
            base_sha='base',
            head_sha='head',
            ahead=1,
            behind=0,
            commits=[commit],
            files_changed=2,
            additions=10,
            deletions=3,
        )
        restored = CompareResult.model_validate(result.model_dump())
        self.assertEqual(len(restored.commits), 1)
        self.assertEqual(restored.commits[0].sha, 'abc')
        self.assertEqual(restored.additions, 10)

    def test_release_info_round_trip(self) -> None:
        release = ReleaseInfo(
            id='123',
            tag='v6.4.0',
            name='v6.4.0',
            url='https://api.github.com/repos/o/r/releases/123',
            html_url='https://github.com/o/r/releases/tag/v6.4.0',
            prerelease=False,
        )
        restored = ReleaseInfo.model_validate(release.model_dump())
        self.assertEqual(restored.tag, 'v6.4.0')
        self.assertFalse(restored.prerelease)

    def test_ref_info_round_trip(self) -> None:
        info = RefInfo(name='refs/tags/v6.4.0', sha='abc')
        self.assertEqual(info.name, 'refs/tags/v6.4.0')
        self.assertEqual(info.sha, 'abc')

    def test_deployment_run_default_status(self) -> None:
        run = DeploymentRun(run_id='42')
        self.assertEqual(run.status, 'queued')
        self.assertIsNone(run.completed_at)

    def test_workflow_file_round_trip(self) -> None:
        wf = WorkflowFile(
            id='12345',
            path='.github/workflows/python-api-deploy.yml',
            name='python-api deploy',
        )
        restored = WorkflowFile.model_validate(wf.model_dump())
        self.assertEqual(
            restored.path, '.github/workflows/python-api-deploy.yml'
        )
        self.assertEqual(restored.state, 'active')


class DeploymentManifestTestCase(unittest.TestCase):
    def test_deployment_plugin_type_accepted(self) -> None:
        manifest = PluginManifest(
            slug='gh-deploy',
            name='GitHub Deployment',
            plugin_type='deployment',
            options=[
                PluginOption(name='workflow', label='Workflow file'),
            ],
        )
        self.assertEqual(manifest.plugin_type, 'deployment')
        self.assertEqual(manifest.options[0].name, 'workflow')


class _StubDeploymentPlugin(DeploymentPlugin):
    """Minimal subclass used to exercise default optional methods."""

    manifest = PluginManifest(
        slug='stub-deploy',
        name='Stub Deployment',
        plugin_type='deployment',
    )

    async def list_refs(  # type: ignore[override]
        self, ctx, credentials, kind='all', query=None
    ):
        return []

    async def list_commits(  # type: ignore[override]
        self, ctx, credentials, ref, limit=25
    ):
        return []

    async def resolve_committish(  # type: ignore[override]
        self, ctx, credentials, committish
    ):
        return Commit(sha='x', short_sha='x', message='')

    async def compare(  # type: ignore[override]
        self, ctx, credentials, base, head
    ):
        return CompareResult(base_sha=base, head_sha=head, ahead=0, behind=0)

    async def trigger_deployment(  # type: ignore[override]
        self, ctx, credentials, ref_or_sha, inputs=None
    ):
        return DeploymentRun(run_id='1')

    async def get_deployment_status(  # type: ignore[override]
        self, ctx, credentials, run_id
    ):
        return DeploymentRun(run_id=run_id, status='in_progress')


class DeploymentPluginDefaultsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_create_tag_default_raises(self) -> None:
        ctx = PluginContext(project_id='p', project_slug='p', org_slug='o')
        plugin = _StubDeploymentPlugin()
        with self.assertRaises(NotImplementedError):
            await plugin.create_tag(ctx, {}, 'sha', 'v1.0.0', 'msg')

    async def test_create_release_default_raises(self) -> None:
        ctx = PluginContext(project_id='p', project_slug='p', org_slug='o')
        plugin = _StubDeploymentPlugin()
        with self.assertRaises(NotImplementedError):
            await plugin.create_release(ctx, {}, 'v1.0.0', 'v1.0.0', '')

    async def test_get_check_status_default_returns_unknown(self) -> None:
        ctx = PluginContext(project_id='p', project_slug='p', org_slug='o')
        plugin = _StubDeploymentPlugin()
        status = await plugin.get_check_status(ctx, {}, 'v1.0.0')
        self.assertEqual(status, 'unknown')

    async def test_list_workflows_default_raises(self) -> None:
        ctx = PluginContext(project_id='p', project_slug='p', org_slug='o')
        plugin = _StubDeploymentPlugin()
        with self.assertRaises(NotImplementedError):
            await plugin.list_workflows(ctx, {})

    async def test_list_recent_deployments_default_raises(self) -> None:
        ctx = PluginContext(project_id='p', project_slug='p', org_slug='o')
        plugin = _StubDeploymentPlugin()
        with self.assertRaises(NotImplementedError):
            await plugin.list_recent_deployments(ctx, {}, ['production'])


class ManifestDeploymentSyncFlagTestCase(unittest.TestCase):
    def test_supports_deployment_sync_defaults_false(self) -> None:
        manifest = PluginManifest(
            slug='gh-deploy',
            name='GitHub Deployment',
            plugin_type='deployment',
        )
        self.assertFalse(manifest.supports_deployment_sync)

    def test_supports_deployment_sync_round_trip(self) -> None:
        manifest = PluginManifest(
            slug='gh-deploy',
            name='GitHub Deployment',
            plugin_type='deployment',
            supports_deployment_sync=True,
        )
        restored = PluginManifest.model_validate(manifest.model_dump())
        self.assertTrue(restored.supports_deployment_sync)


class RemoteDeploymentTestCase(unittest.TestCase):
    def test_round_trip(self) -> None:
        observed = RemoteDeployment(
            environment='production',
            sha='abc1234deadbeef',
            ref='v1.0.0',
            status='success',
            created_at=datetime.datetime(
                2026, 5, 13, 14, 0, tzinfo=datetime.UTC
            ),
            external_run_id='123456789',
            run_url='https://github.com/o/r/actions/runs/42',
            deployment_url='https://github.com/o/r/deployments/123456789',
            description='Bump foo to 1.2.3',
        )
        restored = RemoteDeployment.model_validate(observed.model_dump())
        self.assertEqual(restored.external_run_id, '123456789')
        self.assertEqual(restored.status, 'success')
        self.assertEqual(restored.environment, 'production')

    def test_minimal_fields(self) -> None:
        observed = RemoteDeployment(
            environment='staging',
            sha='abc1234',
            status='in_progress',
            created_at=datetime.datetime(
                2026, 5, 13, 14, 0, tzinfo=datetime.UTC
            ),
            external_run_id='99',
        )
        self.assertIsNone(observed.ref)
        self.assertIsNone(observed.run_url)


class LifecycleManifestTestCase(unittest.TestCase):
    def test_lifecycle_plugin_type_accepted(self) -> None:
        manifest = PluginManifest(
            slug='gh-lifecycle',
            name='GitHub Lifecycle',
            plugin_type='lifecycle',
            options=[
                PluginOption(name='archive_target_org', label='Target org'),
            ],
        )
        self.assertEqual(manifest.plugin_type, 'lifecycle')
        self.assertEqual(manifest.options[0].name, 'archive_target_org')


class LifecycleResultTestCase(unittest.TestCase):
    def test_lifecycle_result_round_trip(self) -> None:
        result = LifecycleResult(
            status='ok',
            message='archived',
            artifacts={'repo_url': 'https://github.com/o/r'},
        )
        restored = LifecycleResult.model_validate(result.model_dump())
        self.assertEqual(restored.status, 'ok')
        self.assertEqual(restored.message, 'archived')
        self.assertEqual(
            restored.artifacts['repo_url'], 'https://github.com/o/r'
        )

    def test_lifecycle_result_defaults(self) -> None:
        result = LifecycleResult(status='skipped')
        self.assertIsNone(result.message)
        self.assertEqual(result.artifacts, {})


class _StubLifecyclePlugin(LifecyclePlugin):
    manifest = PluginManifest(
        slug='stub-lifecycle',
        name='Stub Lifecycle',
        plugin_type='lifecycle',
    )

    async def on_project_archived(  # type: ignore[override]
        self, ctx, credentials
    ):
        return LifecycleResult(status='ok')


class LifecyclePluginDefaultsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_on_project_unarchived_default_raises(self) -> None:
        ctx = PluginContext(project_id='p', project_slug='p', org_slug='o')
        plugin = _StubLifecyclePlugin()
        with self.assertRaises(NotImplementedError):
            await plugin.on_project_unarchived(ctx, {})

    async def test_on_project_archived_returns_result(self) -> None:
        ctx = PluginContext(project_id='p', project_slug='p', org_slug='o')
        plugin = _StubLifecyclePlugin()
        result = await plugin.on_project_archived(ctx, {})
        self.assertEqual(result.status, 'ok')


class PluginContextEnvironmentConfigTestCase(unittest.TestCase):
    def test_environment_config_defaults_empty(self) -> None:
        ctx = PluginContext(project_id='p', project_slug='p', org_slug='o')
        self.assertEqual(ctx.environment_config, {})

    def test_environment_config_round_trip(self) -> None:
        ctx = PluginContext(
            project_id='p',
            project_slug='p',
            org_slug='o',
            environment='production',
            environment_config={
                'action': 'dispatch',
                'workflow': 'python-api-deploy.yml',
                'inputs': {'foo': 'bar'},
            },
        )
        restored = PluginContext.model_validate(ctx.model_dump())
        self.assertEqual(restored.environment_config['action'], 'dispatch')
        self.assertEqual(restored.environment_config['inputs'], {'foo': 'bar'})


class PluginManifestWebhookTypeTestCase(unittest.TestCase):
    def test_webhook_plugin_type_accepted(self) -> None:
        manifest = plugin_base.PluginManifest(
            slug='wh',
            name='Webhook plugin',
            plugin_type='webhook',
        )
        self.assertEqual(manifest.plugin_type, 'webhook')

    def test_webhook_plugin_type_with_credentials(self) -> None:
        manifest = plugin_base.PluginManifest(
            slug='wh',
            name='Webhook plugin',
            plugin_type='webhook',
            credentials=[
                plugin_base.CredentialField(
                    name='api_token', label='API Token'
                ),
            ],
        )
        self.assertEqual(len(manifest.credentials), 1)
        self.assertEqual(manifest.credentials[0].name, 'api_token')


class WebhookActionPluginTestCase(unittest.TestCase):
    def test_subclass_must_implement_run_action(self) -> None:
        class _IncompleteWebhook(plugin_base.WebhookActionPlugin):
            pass

        with self.assertRaises(TypeError):
            _IncompleteWebhook()  # type: ignore[abstract]

    def test_concrete_subclass_instantiates(self) -> None:
        class _FakeWebhook(plugin_base.WebhookActionPlugin):
            async def run_action(  # type: ignore[override]
                self,
                ctx,
                credentials,
                external_identifier,
                action,
                action_config,
                payload,
            ):
                _ = (
                    ctx,
                    credentials,
                    external_identifier,
                    action,
                    action_config,
                    payload,
                )

        _FakeWebhook.manifest = plugin_base.PluginManifest(
            slug='wh', name='Webhook plugin', plugin_type='webhook'
        )
        instance = _FakeWebhook()
        self.assertEqual(instance.manifest.slug, 'wh')
