import datetime
import unittest

from imbi_common.plugins.base import (
    ConfigKey,
    ConfigKeyWithValue,
    LogFilter,
    LogQuery,
    PluginManifest,
    PluginOption,
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
