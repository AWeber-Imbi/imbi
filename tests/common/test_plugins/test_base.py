"""Tests for imbi_common.plugins.base (Plugin Architecture v3)."""

import datetime
import unittest

import pydantic

import imbi_common.plugins.base as plugin_base
from imbi_common.plugins.base import (
    CAPABILITY_CONTRACTS,
    CAPABILITY_SURFACES,
    HINT_ALLOWLIST,
    ActionDescriptor,
    AnalysisCapability,
    AnalysisResultItem,
    AuthorizationRequest,
    Capability,
    Commit,
    CommitSyncCapability,
    CompareResult,
    ConfigKey,
    ConfigKeyWithValue,
    ConfigurationCapability,
    ConfigValue,
    CredentialField,
    DeploymentCapability,
    DeploymentRun,
    IdentityCapability,
    IdentityCredentials,
    IdentityProfile,
    IncidentResult,
    IncidentsCapability,
    LifecycleCapability,
    LifecycleResult,
    LinkWriteback,
    LogFilter,
    LogQuery,
    LogsCapability,
    OpsLogTemplate,
    Plugin,
    PluginContext,
    PluginEdgeLabel,
    PluginManifest,
    PluginOption,
    PluginVertexLabel,
    PollingDescriptor,
    PullRequestSyncCapability,
    Ref,
    RefInfo,
    ReleaseInfo,
    RelocationTarget,
    RemoteDeployment,
    ServiceConnection,
    ServiceWriteback,
    ToolDescriptor,
    ToolsCapability,
    WebhookActionsCapability,
    WorkflowFile,
)
from imbi_common.plugins.errors import PluginRemediationNotSupported

# ---------------------------------------------------------------------------
# Minimal concrete handlers for building manifests
# ---------------------------------------------------------------------------


class StubConfiguration(ConfigurationCapability):
    async def list_keys(self, ctx, credentials):
        return []

    async def get_values(self, ctx, credentials, keys=None):
        return []

    async def set_value(self, ctx, credentials, key, value):
        return ConfigKey(key=key, data_type='string')

    async def delete_key(self, ctx, credentials, key):
        return None


class StubLogs(LogsCapability):
    async def search(self, ctx, credentials, query):
        return plugin_base.LogResult(entries=[])

    async def schema(self, ctx, credentials):
        return []


class StubDeployment(DeploymentCapability):
    async def list_refs(self, ctx, credentials, kind='all', query=None):
        return []

    async def list_commits(self, ctx, credentials, ref, limit=25):
        return []

    async def resolve_committish(self, ctx, credentials, committish):
        return Commit(sha='x', short_sha='x', message='')

    async def compare(self, ctx, credentials, base, head):
        return CompareResult(base_sha=base, head_sha=head, ahead=0, behind=0)

    async def trigger_deployment(
        self, ctx, credentials, ref_or_sha, inputs=None
    ):
        return DeploymentRun(run_id='1')

    async def get_deployment_status(self, ctx, credentials, run_id):
        return DeploymentRun(run_id=run_id)


class StubLifecycle(LifecycleCapability):
    async def on_project_archived(self, ctx, credentials):
        return LifecycleResult(status='ok')


class StubIdentity(IdentityCapability):
    async def authorization_request(
        self, ctx, credentials, redirect_uri, scopes=None
    ):
        return AuthorizationRequest(authorization_url='https://x', state='s')

    async def exchange_code(
        self, ctx, credentials, code, redirect_uri, code_verifier=None
    ):
        return (
            IdentityProfile(subject='s'),
            IdentityCredentials(access_token='t'),
        )

    async def refresh(self, ctx, credentials, refresh_token):
        return IdentityCredentials(access_token='t')


class StubAnalysis(AnalysisCapability):
    async def analyze(self, ctx, credentials):
        return []


class StubIncidents(IncidentsCapability):
    async def list_incidents(
        self,
        ctx,
        credentials,
        *,
        start_time,
        end_time,
        statuses=None,
        cursor=None,
        limit=100,
    ):
        return IncidentResult()


async def _sample_action(
    *, ctx, credentials, external_identifier, action_config, event
):
    del ctx, credentials, external_identifier, action_config, event


class _SampleConfig(pydantic.BaseModel):
    pass


class StubWebhookActions(WebhookActionsCapability):
    @classmethod
    def actions(cls):
        return [
            ActionDescriptor(
                name='do_thing',
                label='Do Thing',
                callable=_sample_action,  # type: ignore[arg-type]
                config_model=_SampleConfig,  # type: ignore[arg-type]
            )
        ]


class StubCommitSync(CommitSyncCapability):
    async def sync_all_history(self, *, ctx, credentials):
        return (0, 0)


class StubPRSync(PullRequestSyncCapability):
    async def sync_all_history(self, *, ctx, credentials):
        return 0


class StubTools(ToolsCapability):
    @classmethod
    def tools(cls):
        return []


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------


class CapabilityTestCase(unittest.TestCase):
    def test_valid_capability(self) -> None:
        cap = Capability(
            kind='configuration',
            label='Config',
            handler=StubConfiguration,
        )
        self.assertEqual(cap.kind, 'configuration')
        self.assertTrue(cap.default_enabled)
        self.assertTrue(cap.project_scoped)
        self.assertFalse(cap.requires_identity)
        self.assertIsNone(cap.ui_module)

    def test_surfaces_property(self) -> None:
        cap = Capability(kind='deployment', label='D', handler=StubDeployment)
        self.assertEqual(cap.surfaces, frozenset({'ui', 'api'}))

    def test_handler_excluded_from_serialization(self) -> None:
        cap = Capability(
            kind='configuration', label='C', handler=StubConfiguration
        )
        dumped = cap.model_dump()
        self.assertNotIn('handler', dumped)
        self.assertNotIn('handler', cap.model_dump_json())

    def test_handler_kind_mismatch_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            Capability(kind='logs', label='L', handler=StubConfiguration)

    def test_handler_not_a_class_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            Capability(
                kind='configuration',
                label='C',
                handler=object(),  # type: ignore[arg-type]
            )

    def test_unknown_hint_key_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            Capability(
                kind='configuration',
                label='C',
                handler=StubConfiguration,
                hints={'bogus': 1},
            )

    def test_kind_specific_hint_allowed(self) -> None:
        cap = Capability(
            kind='logs',
            label='L',
            handler=StubLogs,
            hints={'supports_histogram': True, 'cacheable': False},
        )
        self.assertTrue(cap.hints['supports_histogram'])

    def test_kind_specific_hint_rejected_for_wrong_kind(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            Capability(
                kind='configuration',
                label='C',
                handler=StubConfiguration,
                hints={'supports_histogram': True},
            )

    def test_cacheable_allowed_everywhere(self) -> None:
        cap = Capability(
            kind='incidents',
            label='I',
            handler=StubIncidents,
            hints={'cacheable': False},
        )
        self.assertFalse(cap.hints['cacheable'])


class CapabilityEnumTestCase(unittest.TestCase):
    def test_surfaces_map_covers_every_contract(self) -> None:
        self.assertEqual(set(CAPABILITY_SURFACES), set(CAPABILITY_CONTRACTS))

    def test_hint_allowlist_covers_every_kind(self) -> None:
        self.assertEqual(set(HINT_ALLOWLIST), set(CAPABILITY_CONTRACTS))

    def test_every_contract_subclasses_handler(self) -> None:
        for contract in CAPABILITY_CONTRACTS.values():
            self.assertTrue(
                issubclass(contract, plugin_base.CapabilityHandler)
            )


# ---------------------------------------------------------------------------
# PluginManifest + Plugin
# ---------------------------------------------------------------------------


class PluginManifestTestCase(unittest.TestCase):
    def _cap(self, kind='configuration', handler=StubConfiguration):
        return Capability(kind=kind, label=kind, handler=handler)

    def test_valid_manifest(self) -> None:
        manifest = PluginManifest(
            slug='github',
            name='GitHub',
            capabilities=[self._cap()],
        )
        self.assertEqual(manifest.api_version, 2)
        self.assertEqual(manifest.auth_type, 'api_token')

    def test_empty_capabilities_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            PluginManifest(slug='x', name='X', capabilities=[])

    def test_duplicate_capability_kinds_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            PluginManifest(
                slug='x',
                name='X',
                capabilities=[self._cap(), self._cap()],
            )

    def test_get_capability(self) -> None:
        manifest = PluginManifest(
            slug='x',
            name='X',
            capabilities=[
                self._cap(),
                self._cap('logs', StubLogs),
            ],
        )
        self.assertEqual(manifest.get_capability('logs').kind, 'logs')
        self.assertIsNone(manifest.get_capability('deployment'))

    def test_handler_excluded_from_manifest_dump(self) -> None:
        manifest = PluginManifest(
            slug='x', name='X', capabilities=[self._cap()]
        )
        dumped = manifest.model_dump()
        self.assertNotIn('handler', dumped['capabilities'][0])

    def test_manifest_carries_credentials_once(self) -> None:
        manifest = PluginManifest(
            slug='x',
            name='X',
            credentials=[CredentialField(name='token', label='Token')],
            capabilities=[self._cap()],
        )
        self.assertEqual(manifest.credentials[0].name, 'token')


class PluginTestCase(unittest.TestCase):
    def test_plugin_manifest_classvar(self) -> None:
        manifest = PluginManifest(
            slug='x',
            name='X',
            capabilities=[
                Capability(
                    kind='configuration',
                    label='C',
                    handler=StubConfiguration,
                )
            ],
        )

        class MyPlugin(Plugin):
            pass

        MyPlugin.manifest = manifest
        self.assertIs(MyPlugin.manifest, manifest)


# ---------------------------------------------------------------------------
# PluginContext + writeback / connection models
# ---------------------------------------------------------------------------


class PluginContextTestCase(unittest.TestCase):
    def _ctx(self, **kw) -> PluginContext:
        base = {'project_id': 'p', 'project_slug': 's', 'org_slug': 'o'}
        base.update(kw)
        return PluginContext(**base)

    def test_defaults(self) -> None:
        ctx = self._ctx()
        self.assertEqual(ctx.integration_options, {})
        self.assertEqual(ctx.capability_options, {})
        self.assertEqual(ctx.assignment_options, {})
        self.assertIsNone(ctx.integration_slug)
        self.assertEqual(ctx.service_connections, [])
        self.assertIsNone(ctx.service_writeback)

    def test_integration_fields_round_trip(self) -> None:
        ctx = self._ctx(
            integration_slug='github-dot-com',
            integration_options={'host': 'github.com'},
            capability_options={'branch': 'main'},
        )
        restored = PluginContext.model_validate_json(ctx.model_dump_json())
        self.assertEqual(restored.integration_slug, 'github-dot-com')
        self.assertEqual(restored.integration_options['host'], 'github.com')
        self.assertEqual(restored.capability_options['branch'], 'main')

    def test_no_service_plugins_field(self) -> None:
        self.assertNotIn('service_plugins', PluginContext.model_fields)
        self.assertNotIn(
            'third_party_service_slug', PluginContext.model_fields
        )

    def test_resolver_excluded_from_dump(self) -> None:
        async def _resolver(subject):
            return None

        ctx = self._ctx(resolve_user_by_identity=_resolver)
        self.assertNotIn('resolve_user_by_identity', ctx.model_dump())


class ServiceConnectionTestCase(unittest.TestCase):
    def test_integration_slug_field(self) -> None:
        conn = ServiceConnection(integration_slug='gh', identifier='42')
        self.assertEqual(conn.integration_slug, 'gh')
        self.assertIsNone(conn.canonical_url)

    def test_no_service_slug_field(self) -> None:
        self.assertNotIn('service_slug', ServiceConnection.model_fields)


class ServiceWritebackTestCase(unittest.TestCase):
    def test_round_trip(self) -> None:
        wb = ServiceWriteback(
            identifier='42',
            canonical_url='https://api/repositories/42',
            dashboard_links={'github': 'https://x'},
            webhook_secret_enc='enc',
        )
        restored = ServiceWriteback.model_validate_json(wb.model_dump_json())
        self.assertEqual(restored.identifier, '42')
        self.assertFalse(restored.remove)

    def test_defaults(self) -> None:
        wb = ServiceWriteback(identifier='1', canonical_url='https://x')
        self.assertEqual(wb.dashboard_links, {})
        self.assertIsNone(wb.webhook_secret_enc)


class LinkWritebackTestCase(unittest.TestCase):
    def test_round_trip(self) -> None:
        wb = LinkWriteback(link_key='github-repository', new_url='https://x')
        self.assertEqual(wb.link_key, 'github-repository')
        self.assertIsNone(wb.old_owner_repo)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PluginOptionMappingTestCase(unittest.TestCase):
    def test_mapping_default_dict(self) -> None:
        opt = PluginOption(
            name='m', label='M', type='mapping', default={'a': 'b'}
        )
        self.assertEqual(opt.default, {'a': 'b'})

    def test_mapping_rejects_choices(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            PluginOption(name='m', label='M', type='mapping', choices=['a'])

    def test_mapping_rejects_scalar_default(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            PluginOption(name='m', label='M', type='mapping', default='x')

    def test_scalar_rejects_dict_default(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            PluginOption(name='s', label='S', default={'a': 'b'})


class ConfigModelsTestCase(unittest.TestCase):
    def test_config_key_no_value(self) -> None:
        key = ConfigKey(key='k', data_type='string')
        self.assertFalse(key.secret)

    def test_config_key_with_value(self) -> None:
        key = ConfigKeyWithValue(key='k', data_type='string', value='v')
        self.assertEqual(key.value, 'v')

    def test_config_value(self) -> None:
        val = ConfigValue(data_type='string', value='v')
        self.assertFalse(val.secret)


class LogModelsTestCase(unittest.TestCase):
    def test_log_query_filters(self) -> None:
        q = LogQuery(
            start_time=datetime.datetime.now(datetime.UTC),
            end_time=datetime.datetime.now(datetime.UTC),
            filters=[LogFilter(field='f', op='eq', value='v')],
        )
        self.assertEqual(q.limit, 100)
        self.assertEqual(q.filters[0].op, 'eq')


class IdentityModelsTestCase(unittest.TestCase):
    def test_identity_profile(self) -> None:
        p = IdentityProfile(subject='s', email='e@x')
        self.assertEqual(p.subject, 's')

    def test_identity_credentials_redacted(self) -> None:
        c = IdentityCredentials(access_token='secret')
        self.assertNotIn('secret', repr(c))
        self.assertNotIn('secret', str(c))

    def test_authorization_request_polling(self) -> None:
        req = AuthorizationRequest(
            authorization_url='https://x',
            state='s',
            polling=PollingDescriptor(
                user_code='ABCD',
                verification_uri='https://v',
                expires_in=600,
            ),
        )
        self.assertEqual(req.polling.interval, 5)


class DeploymentModelsTestCase(unittest.TestCase):
    def test_ref(self) -> None:
        r = Ref(name='main', kind='branch', sha='abc')
        self.assertFalse(r.is_default)

    def test_commit_defaults(self) -> None:
        c = Commit(sha='a', short_sha='a', message='m')
        self.assertEqual(c.ci_status, 'unknown')

    def test_release_info(self) -> None:
        info = ReleaseInfo(id='1', tag='v1')
        self.assertFalse(info.prerelease)

    def test_ref_info(self) -> None:
        info = RefInfo(name='v1', sha='abc')
        self.assertIsNone(info.url)

    def test_workflow_file(self) -> None:
        wf = WorkflowFile(id='1', path='.github/x.yml', name='CI')
        self.assertEqual(wf.state, 'active')

    def test_deployment_run_default_status(self) -> None:
        self.assertEqual(DeploymentRun(run_id='1').status, 'queued')

    def test_remote_deployment(self) -> None:
        rd = RemoteDeployment(
            environment='prod',
            sha='abc',
            status='success',
            created_at=datetime.datetime.now(datetime.UTC),
            external_run_id='42',
        )
        self.assertIsNone(rd.creator)


class LifecycleModelsTestCase(unittest.TestCase):
    def test_result(self) -> None:
        self.assertEqual(LifecycleResult(status='ok').artifacts, {})

    def test_relocation_target(self) -> None:
        t = RelocationTarget(link_key='k', identifier='a/b')
        self.assertIsNone(t.display)


class AnalysisModelsTestCase(unittest.TestCase):
    def test_result_item(self) -> None:
        item = AnalysisResultItem(
            slug='s', title='t', description='d', status='pass'
        )
        self.assertIsNone(item.remediation)

    def test_invalid_status_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            AnalysisResultItem(
                slug='s', title='t', description='d', status='nope'
            )


class ActionDescriptorTestCase(unittest.TestCase):
    def test_resolves_import_strings(self) -> None:
        d = ActionDescriptor(
            name='do_thing',
            label='Do Thing',
            callable=_sample_action,  # type: ignore[arg-type]
            config_model=_SampleConfig,  # type: ignore[arg-type]
        )
        self.assertIs(d.callable, _sample_action)
        self.assertIs(d.config_model, _SampleConfig)

    def test_rejects_bad_name(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            ActionDescriptor(
                name='Bad Name',
                label='x',
                callable=_sample_action,  # type: ignore[arg-type]
                config_model=_SampleConfig,  # type: ignore[arg-type]
            )


class ToolDescriptorTestCase(unittest.TestCase):
    def test_valid(self) -> None:
        d = ToolDescriptor(
            name='do_thing',
            description='does a thing',
            callable=_sample_action,  # type: ignore[arg-type]
        )
        self.assertEqual(d.input_schema, {})

    def test_rejects_bad_name(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            ToolDescriptor(
                name='Bad',
                description='x',
                callable=_sample_action,  # type: ignore[arg-type]
            )


class OpsLogTemplateTestCase(unittest.TestCase):
    def test_round_trip(self) -> None:
        t = OpsLogTemplate(label='Deployed {{version}}')
        self.assertIsNone(t.summary)


class PluginVertexLabelTestCase(unittest.TestCase):
    def test_round_trip(self) -> None:
        v = PluginVertexLabel(name='AwsAccount', model_ref='aws:AwsAccount')
        self.assertEqual(v.indexes, [])

    def test_edge_label_round_trip(self) -> None:
        e = PluginEdgeLabel(
            name='MAPS_TO', from_labels=['Project'], to_labels=['AwsAccount']
        )
        self.assertEqual(e.properties, {})


# ---------------------------------------------------------------------------
# Contract default methods
# ---------------------------------------------------------------------------


class DeploymentDefaultsTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.plugin = StubDeployment()
        self.ctx = PluginContext(
            project_id='p', project_slug='s', org_slug='o'
        )

    async def test_get_check_status_default(self) -> None:
        result = await self.plugin.get_check_status(self.ctx, {}, 'main')
        self.assertEqual(result, 'unknown')

    async def test_create_tag_default_raises(self) -> None:
        with self.assertRaises(NotImplementedError):
            await self.plugin.create_tag(self.ctx, {}, 'sha', 't', 'm')

    async def test_create_release_default_raises(self) -> None:
        with self.assertRaises(NotImplementedError):
            await self.plugin.create_release(self.ctx, {}, 't', 'n', 'b')

    async def test_list_workflows_default_raises(self) -> None:
        with self.assertRaises(NotImplementedError):
            await self.plugin.list_workflows(self.ctx, {})

    async def test_list_recent_deployments_default_raises(self) -> None:
        with self.assertRaises(NotImplementedError):
            await self.plugin.list_recent_deployments(self.ctx, {}, ['prod'])

    async def test_get_release_notes_default(self) -> None:
        result = await self.plugin.get_release_notes(self.ctx, {}, '1.0.0')
        self.assertIsNone(result)


class LifecycleDefaultsTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.plugin = StubLifecycle()
        self.ctx = PluginContext(
            project_id='p', project_slug='s', org_slug='o'
        )

    async def test_archived_returns_result(self) -> None:
        result = await self.plugin.on_project_archived(self.ctx, {})
        self.assertEqual(result.status, 'ok')

    async def test_optional_hooks_raise(self) -> None:
        for hook in (
            self.plugin.on_project_unarchived,
            self.plugin.on_project_created,
            self.plugin.on_project_updated,
            self.plugin.on_project_deleted,
            self.plugin.on_project_relocated,
        ):
            with self.assertRaises(NotImplementedError):
                await hook(self.ctx, {})

    async def test_resolve_relocation_target_default_none(self) -> None:
        result = await self.plugin.resolve_relocation_target(self.ctx, {})
        self.assertIsNone(result)


class LogsDefaultsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_histogram_default_empty(self) -> None:
        q = LogQuery(
            start_time=datetime.datetime.now(datetime.UTC),
            end_time=datetime.datetime.now(datetime.UTC),
        )
        result = await StubLogs().histogram(
            PluginContext(project_id='p', project_slug='s', org_slug='o'),
            {},
            q,
        )
        self.assertEqual(result, [])


class IdentityDefaultsTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.plugin = StubIdentity()
        self.ctx = PluginContext(
            project_id='p', project_slug='s', org_slug='o'
        )

    async def test_revoke_default_none(self) -> None:
        self.assertIsNone(await self.plugin.revoke(self.ctx, {}, 'tok'))

    async def test_materialize_default_passthrough(self) -> None:
        creds = IdentityCredentials(access_token='t')
        result = await self.plugin.materialize(self.ctx, {}, creds)
        self.assertIs(result, creds)


class AnalysisRemediateTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_default_remediate_raises(self) -> None:
        ctx = PluginContext(project_id='p', project_slug='s', org_slug='o')
        with self.assertRaises(PluginRemediationNotSupported):
            await StubAnalysis().remediate(ctx, {}, 'rid')


class SyncDefaultsTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.ctx = PluginContext(
            project_id='p', project_slug='s', org_slug='o'
        )

    async def test_commit_sync_check_available_default(self) -> None:
        self.assertTrue(
            await StubCommitSync().check_available(
                ctx=self.ctx, credentials={}
            )
        )

    async def test_commit_sync_all_history(self) -> None:
        self.assertEqual(
            await StubCommitSync().sync_all_history(
                ctx=self.ctx, credentials={}
            ),
            (0, 0),
        )

    async def test_pr_sync_check_available_default(self) -> None:
        self.assertTrue(
            await StubPRSync().check_available(ctx=self.ctx, credentials={})
        )

    async def test_pr_sync_all_history(self) -> None:
        self.assertEqual(
            await StubPRSync().sync_all_history(ctx=self.ctx, credentials={}),
            0,
        )


class AbstractContractsTestCase(unittest.TestCase):
    def test_webhook_actions_abstract(self) -> None:
        with self.assertRaises(TypeError):
            WebhookActionsCapability()  # type: ignore[abstract]

    def test_tools_abstract(self) -> None:
        with self.assertRaises(TypeError):
            ToolsCapability()  # type: ignore[abstract]

    def test_incidents_abstract(self) -> None:
        with self.assertRaises(TypeError):
            IncidentsCapability()  # type: ignore[abstract]

    def test_configuration_abstract(self) -> None:
        with self.assertRaises(TypeError):
            ConfigurationCapability()  # type: ignore[abstract]

    def test_stub_webhook_actions_catalog(self) -> None:
        self.assertEqual(StubWebhookActions.actions()[0].name, 'do_thing')

    def test_stub_tools_catalog(self) -> None:
        self.assertEqual(StubTools.tools(), [])
