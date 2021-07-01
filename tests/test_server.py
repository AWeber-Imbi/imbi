import base64
import os
import tempfile
import unittest.mock
import uuid

import yaml

from imbi import server


class LoadConfigurationTests(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._patchers = []
        self.mock_stderr = self.add_patch(server.sys, 'stderr')

    def tearDown(self):
        for patcher in self._patchers:
            patcher.stop()
        super().tearDown()

    def add_patch(self, target, attribute, **kwargs):
        self._patchers.append(
            unittest.mock.patch.object(target, attribute, **kwargs))
        return self._patchers[-1].start()

    def test_missing_configuration_file(self):
        with self.assertRaises(SystemExit):
            server.load_configuration(str(uuid.uuid4()), False)
        self.mock_stderr.write.assert_called()

    def test_yaml_load_failure(self):
        with tempfile.NamedTemporaryFile() as config_file:
            config_file.write(b'\x00\x01\x02\x03')
            config_file.flush()
            with self.assertRaises(SystemExit):
                server.load_configuration(config_file.name, False)
            self.mock_stderr.write.assert_called()

    def test_bad_yaml_doc(self):
        with tempfile.NamedTemporaryFile() as config_file:
            config_file.write(b'<config/>')
            config_file.flush()
            with self.assertRaises(SystemExit):
                server.load_configuration(config_file.name, False)
            self.mock_stderr.write.assert_called()

    def test_encryption_key_encoding(self):
        secret = os.urandom(32)
        with tempfile.NamedTemporaryFile(
                mode='w+t', encoding='utf-8') as config_file:
            yaml.dump(
                {
                    'encryption_key': base64.b64encode(secret).decode(),
                    'http': {'canonical_server_name': 'server.example.com'},
                }, config_file)
            config, _ = server.load_configuration(config_file.name, False)
            self.assertEqual(secret, config['encryption_key'])

            config_file.seek(0)
            secret = b'not valid base64'
            yaml.dump(
                {
                    'encryption_key': secret.decode(),
                    'http': {'canonical_server_name': 'server.example.com'},
                }, config_file)
            config, _ = server.load_configuration(config_file.name, False)
            self.assertEqual(secret, config['encryption_key'])
