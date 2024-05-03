from __future__ import annotations

import base64
import contextlib
import io
import os
import tempfile
import unittest.mock
import uuid

import yaml

from imbi import server


class ConfigurationTestCase(unittest.TestCase):
    temp_file: io.FileIO

    def setUp(self) -> None:
        super().setUp()
        self._exit_stack = contextlib.ExitStack()
        self.addCleanup(self._exit_stack.close)
        self.mock_stderr = self.patch_object(server.sys, 'stderr')
        self.temp_file = self._exit_stack.enter_context(
            tempfile.NamedTemporaryFile(mode='w+t', encoding='utf-8'))
        self.config = {'http': {'canonical_server_name': 'server.example.com'}}

    def patch_object(
            self, target: object, attribute: str,
            **kwargs) -> unittest.mock.MagicMock | unittest.mock.AsyncMock:
        return self._exit_stack.enter_context(
            unittest.mock.patch.object(target, attribute, **kwargs))


class LoadConfigurationTests(ConfigurationTestCase):
    def test_missing_configuration_file(self):
        with self.assertRaises(SystemExit):
            server.load_configuration(str(uuid.uuid4()), False)
        self.mock_stderr.write.assert_called()

    def test_yaml_load_failure(self):
        self.temp_file.write('\x00\x01\x02\x03')
        self.temp_file.flush()
        with self.assertRaises(SystemExit):
            server.load_configuration(self.temp_file.name, False)
        self.mock_stderr.write.assert_called()

    def test_bad_yaml_doc(self):
        self.temp_file.write('<config/>')
        self.temp_file.flush()
        with self.assertRaises(SystemExit):
            server.load_configuration(self.temp_file.name, False)
        self.mock_stderr.write.assert_called()

    def test_encryption_key_encoding(self):
        secret = os.urandom(32)
        self.config['encryption_key'] = base64.b64encode(secret).decode()
        yaml.dump(self.config, self.temp_file)
        config, _ = server.load_configuration(self.temp_file.name, False)
        self.assertEqual(secret, config['encryption_key'])

        self.temp_file.seek(0)
        self.config['encryption_key'] = 'not valid base64'
        yaml.dump(self.config, self.temp_file)
        config, _ = server.load_configuration(self.temp_file.name, False)
        self.assertEqual('not valid base64'.encode(), config['encryption_key'])


class SentryConfigurationTests(ConfigurationTestCase):
    def test_that_default_is_enabled(self):
        yaml.dump(self.config, self.temp_file)
        config, _ = server.load_configuration(self.temp_file.name, False)
        self.assertTrue(config['automations']['sentry']['enabled'])

    def test_that_sentry_can_be_disabled(self):
        self.config['automations'] = {'sentry': {'enabled': False}}
        yaml.dump(self.config, self.temp_file)
        loaded, _ = server.load_configuration(self.temp_file.name, False)
        self.assertFalse(loaded['automations']['sentry']['enabled'])

    def test_that_sentry_url_has_sensible_default(self):
        yaml.dump(self.config, self.temp_file)
        config, _ = server.load_configuration(self.temp_file.name, False)
        self.assertEqual('https://sentry.io/',
                         config['automations']['sentry']['url'])


class GitLabConfiguratTests(ConfigurationTestCase):
    def test_that_default_is_disabled(self):
        yaml.dump(self.config, self.temp_file)
        config, _ = server.load_configuration(self.temp_file.name, False)
        self.assertFalse(config['automations']['gitlab']['enabled'])

    def test_that_gitlab_is_enabled_when_fully_configured(self):
        self.config['automations'] = {'gitlab': {}}
        yaml.dump(self.config, self.temp_file)
        loaded, _ = server.load_configuration(self.temp_file.name, False)
        self.assertFalse(loaded['automations']['gitlab']['enabled'])
        self.temp_file.seek(0)

        self.config['automations']['gitlab']['project_link_type_id'] = 1
        yaml.dump(self.config, self.temp_file)
        loaded, _ = server.load_configuration(self.temp_file.name, False)
        self.assertTrue(loaded['automations']['gitlab']['enabled'])
