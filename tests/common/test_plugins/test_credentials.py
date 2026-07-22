"""Tests for imbi_common.plugins.credentials."""

import unittest
from unittest import mock

from cryptography import fernet

from imbi_common.auth import encryption
from imbi_common.plugins import credentials


class _EncryptionFixture(unittest.TestCase):
    """Wires a real Fernet key into TokenEncryption."""

    def setUp(self) -> None:
        encryption.TokenEncryption.reset_instance()
        self.test_key = fernet.Fernet.generate_key().decode('ascii')
        self._patcher = mock.patch('imbi_common.settings.get_auth_settings')
        mock_settings = self._patcher.start()
        mock_settings.return_value.encryption_key = self.test_key

    def tearDown(self) -> None:
        self._patcher.stop()
        encryption.TokenEncryption.reset_instance()

    def encrypt(self, plaintext: str) -> str:
        result = encryption.TokenEncryption.get_instance().encrypt(plaintext)
        assert result is not None
        return result


class _Integration:
    """Minimal stand-in exposing ``encrypted_credentials``."""

    def __init__(self, encrypted_credentials: dict[str, str]) -> None:
        self.encrypted_credentials = encrypted_credentials


class DecryptIntegrationCredentialsTestCase(_EncryptionFixture):
    def test_decrypts_mapping(self) -> None:
        blob = {
            'token': self.encrypt('secret'),
            'app_id': self.encrypt('123'),
        }
        result = credentials.decrypt_integration_credentials(blob)
        self.assertEqual(result, {'token': 'secret', 'app_id': '123'})

    def test_accepts_integration_node(self) -> None:
        node = _Integration({'token': self.encrypt('secret')})
        result = credentials.decrypt_integration_credentials(node)
        self.assertEqual(result, {'token': 'secret'})

    def test_empty_blob_returns_empty(self) -> None:
        self.assertEqual(credentials.decrypt_integration_credentials({}), {})

    def test_empty_ciphertext_skipped(self) -> None:
        blob = {'token': self.encrypt('secret'), 'blank': ''}
        result = credentials.decrypt_integration_credentials(blob)
        self.assertEqual(result, {'token': 'secret'})

    def test_undecryptable_value_skipped(self) -> None:
        # ``TokenEncryption.decrypt`` swallows fernet errors and returns
        # ``None``, so a value ciphered under another key is dropped.
        other_key = fernet.Fernet.generate_key().decode('ascii')
        bad = encryption.TokenEncryption(other_key).encrypt('x')
        assert bad is not None
        blob = {'token': self.encrypt('secret'), 'bad': bad}
        result = credentials.decrypt_integration_credentials(blob)
        self.assertEqual(result, {'token': 'secret'})

    def test_decrypt_raises_logged_and_skipped(self) -> None:
        blob = {'token': 'some-ciphertext'}
        with mock.patch.object(
            encryption.TokenEncryption,
            'decrypt',
            side_effect=RuntimeError('boom'),
        ):
            with self.assertLogs(
                'imbi_common.plugins.credentials', level='WARNING'
            ) as logs:
                result = credentials.decrypt_integration_credentials(blob)
        self.assertEqual(result, {})
        self.assertTrue(any('failed to decrypt' in m for m in logs.output))
