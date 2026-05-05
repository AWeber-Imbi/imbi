import datetime
import unittest

from imbi_common.plugins.base import (
    AuthorizationRequest,
    ConfigKey,
    ConfigKeyWithValue,
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
