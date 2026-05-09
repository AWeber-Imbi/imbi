import datetime
import unittest

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
