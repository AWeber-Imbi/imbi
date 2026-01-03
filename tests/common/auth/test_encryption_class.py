"""Tests for TokenEncryption class."""

import base64
import unittest
from unittest import mock

from cryptography import fernet

from imbi_common.auth import encryption


class TokenEncryptionTestCase(unittest.TestCase):
    """Test TokenEncryption class."""

    def setUp(self) -> None:
        """Reset singleton before each test."""
        encryption.TokenEncryption.reset_instance()
        self.test_key = fernet.Fernet.generate_key().decode('ascii')

    def tearDown(self) -> None:
        """Clean up singleton after each test."""
        encryption.TokenEncryption.reset_instance()

    def test_init_valid_key(self) -> None:
        """Test initialization with valid key."""
        encryptor = encryption.TokenEncryption(self.test_key)
        self.assertIsInstance(encryptor._fernet, fernet.Fernet)

    def test_init_invalid_key(self) -> None:
        """Test initialization with invalid key."""
        with self.assertRaises(ValueError) as ctx:
            encryption.TokenEncryption('invalid-key')
        self.assertIn('Invalid encryption key', str(ctx.exception))

    def test_get_instance_creates_singleton(self) -> None:
        """Test get_instance creates singleton."""
        with mock.patch(
            'imbi_common.settings.get_auth_settings'
        ) as mock_settings:
            mock_settings.return_value.encryption_key = self.test_key

            instance1 = encryption.TokenEncryption.get_instance()
            instance2 = encryption.TokenEncryption.get_instance()

            self.assertIs(instance1, instance2)

    def test_get_instance_missing_key(self) -> None:
        """Test get_instance raises error when key not configured."""
        with mock.patch(
            'imbi_common.settings.get_auth_settings'
        ) as mock_settings:
            mock_settings.return_value.encryption_key = None

            with self.assertRaises(RuntimeError) as ctx:
                encryption.TokenEncryption.get_instance()
            self.assertIn('Encryption key not configured', str(ctx.exception))

    def test_reset_instance(self) -> None:
        """Test reset_instance clears singleton."""
        with mock.patch(
            'imbi_common.settings.get_auth_settings'
        ) as mock_settings:
            mock_settings.return_value.encryption_key = self.test_key

            instance1 = encryption.TokenEncryption.get_instance()
            encryption.TokenEncryption.reset_instance()
            instance2 = encryption.TokenEncryption.get_instance()

            self.assertIsNot(instance1, instance2)

    def test_encrypt_none(self) -> None:
        """Test encrypt with None input."""
        encryptor = encryption.TokenEncryption(self.test_key)
        result = encryptor.encrypt(None)
        self.assertIsNone(result)

    def test_encrypt_valid_string(self) -> None:
        """Test encrypt with valid string."""
        encryptor = encryption.TokenEncryption(self.test_key)
        plaintext = 'my-secret-token-12345'
        ciphertext = encryptor.encrypt(plaintext)

        self.assertIsNotNone(ciphertext)
        self.assertIsInstance(ciphertext, str)
        self.assertNotEqual(plaintext, ciphertext)
        # Fernet output is base64
        self.assertTrue(len(ciphertext) > len(plaintext))

    def test_encrypt_decrypt_round_trip(self) -> None:
        """Test encrypt/decrypt round trip."""
        encryptor = encryption.TokenEncryption(self.test_key)
        plaintext = 'test-token-xyz-789'
        ciphertext = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(ciphertext)

        self.assertEqual(plaintext, decrypted)

    def test_decrypt_none(self) -> None:
        """Test decrypt with None input."""
        encryptor = encryption.TokenEncryption(self.test_key)
        result = encryptor.decrypt(None)
        self.assertIsNone(result)

    def test_decrypt_invalid_ciphertext(self) -> None:
        """Test decrypt with invalid ciphertext."""
        encryptor = encryption.TokenEncryption(self.test_key)
        result = encryptor.decrypt('invalid-ciphertext')
        self.assertIsNone(result)

    def test_decrypt_wrong_key(self) -> None:
        """Test decrypt with wrong encryption key."""
        encryptor1 = encryption.TokenEncryption(self.test_key)
        plaintext = 'secret-data'
        ciphertext = encryptor1.encrypt(plaintext)

        # Try to decrypt with different key
        other_key = fernet.Fernet.generate_key().decode('ascii')
        encryptor2 = encryption.TokenEncryption(other_key)
        result = encryptor2.decrypt(ciphertext)

        self.assertIsNone(result)

    def test_decrypt_legacy_double_encoded_format(self) -> None:
        """Test decrypt handles legacy double-encoded format."""
        encryptor = encryption.TokenEncryption(self.test_key)
        plaintext = 'legacy-token'

        # Create legacy double-encoded format
        encrypted_bytes = encryptor._fernet.encrypt(plaintext.encode('utf-8'))
        double_encoded = base64.urlsafe_b64encode(encrypted_bytes).decode(
            'ascii'
        )

        # Should decrypt successfully
        decrypted = encryptor.decrypt(double_encoded)
        self.assertEqual(plaintext, decrypted)

    def test_encrypt_unicode(self) -> None:
        """Test encrypt with unicode characters."""
        encryptor = encryption.TokenEncryption(self.test_key)
        plaintext = 'token-with-émojis-🔐-and-ñ'
        ciphertext = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(ciphertext)

        self.assertEqual(plaintext, decrypted)

    def test_encrypt_long_string(self) -> None:
        """Test encrypt with long string."""
        encryptor = encryption.TokenEncryption(self.test_key)
        plaintext = 'x' * 10000  # 10KB string
        ciphertext = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(ciphertext)

        self.assertEqual(plaintext, decrypted)

    def test_encrypt_empty_string(self) -> None:
        """Test encrypt with empty string."""
        encryptor = encryption.TokenEncryption(self.test_key)
        plaintext = ''
        ciphertext = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(ciphertext)

        self.assertEqual(plaintext, decrypted)

    def test_encrypt_failure(self) -> None:
        """Test encrypt raises exception on encryption failure."""
        encryptor = encryption.TokenEncryption(self.test_key)

        # Mock Fernet.encrypt to raise an exception
        with (
            mock.patch.object(
                encryptor._fernet,
                'encrypt',
                side_effect=Exception('Mock error'),
            ),
            self.assertRaises(Exception) as cm,
        ):
            encryptor.encrypt('test')

        self.assertEqual(str(cm.exception), 'Mock error')

    def test_decrypt_corrupted_base64(self) -> None:
        """Test decrypt with corrupted base64 (not valid Fernet token)."""
        encryptor = encryption.TokenEncryption(self.test_key)

        # Create invalid base64 that's not a valid Fernet token
        # This will fail both new format and legacy format attempts
        corrupted = base64.urlsafe_b64encode(
            b'not-a-valid-fernet-token'
        ).decode('ascii')

        result = encryptor.decrypt(corrupted)
        self.assertIsNone(result)

    def test_decrypt_invalid_base64_padding(self) -> None:
        """Test decrypt with invalid base64 (triggers binascii.Error)."""
        encryptor = encryption.TokenEncryption(self.test_key)

        # Invalid base64 - triggers binascii.Error during urlsafe_b64decode
        # This will fail the first Fernet decrypt, then fail base64 decode
        invalid_b64 = 'not!valid@base64#string$'

        result = encryptor.decrypt(invalid_b64)
        self.assertIsNone(result)

    def test_decrypt_non_ascii_ciphertext(self) -> None:
        """Test decrypt with non-ASCII (triggers UnicodeEncodeError)."""
        encryptor = encryption.TokenEncryption(self.test_key)

        # Non-ASCII characters will fail ciphertext.encode('ascii')
        # This triggers the outer exception handler
        non_ascii = 'invalid-token-with-unicode-\u2603-snowman'

        result = encryptor.decrypt(non_ascii)
        self.assertIsNone(result)
