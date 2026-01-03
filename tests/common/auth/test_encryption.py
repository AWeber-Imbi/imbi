"""Unit tests for auth.encryption module."""

import unittest

from imbi_common.auth import encryption


class TestTokenEncryption(unittest.TestCase):
    """Test token encryption and decryption."""

    def test_encrypt_token_returns_string(self):
        """Test that encrypt_token returns a string."""
        encrypted = encryption.encrypt_token('test_token')
        self.assertIsInstance(encrypted, str)

    def test_encrypt_token_not_plaintext(self):
        """Test that encrypted token is not plaintext."""
        plaintext = 'test_token'
        encrypted = encryption.encrypt_token(plaintext)
        self.assertNotEqual(encrypted, plaintext)

    def test_decrypt_token_returns_original(self):
        """Test that decrypt_token returns original value."""
        plaintext = 'test_token_abc123'
        encrypted = encryption.encrypt_token(plaintext)
        decrypted = encryption.decrypt_token(encrypted)
        self.assertEqual(decrypted, plaintext)

    def test_encrypt_empty_string(self):
        """Test encrypting empty string."""
        encrypted = encryption.encrypt_token('')
        decrypted = encryption.decrypt_token(encrypted)
        self.assertEqual(decrypted, '')

    def test_encrypt_long_token(self):
        """Test encrypting long token."""
        plaintext = 'x' * 1000
        encrypted = encryption.encrypt_token(plaintext)
        decrypted = encryption.decrypt_token(encrypted)
        self.assertEqual(decrypted, plaintext)

    def test_encrypt_unicode(self):
        """Test encrypting unicode characters."""
        plaintext = 'test_token_🔒_secure'
        encrypted = encryption.encrypt_token(plaintext)
        decrypted = encryption.decrypt_token(encrypted)
        self.assertEqual(decrypted, plaintext)

    def test_different_ciphertexts_for_same_plaintext(self):
        """Test that same plaintext produces different ciphertexts."""
        plaintext = 'test_token'
        encrypted1 = encryption.encrypt_token(plaintext)
        encrypted2 = encryption.encrypt_token(plaintext)
        # Fernet includes timestamp, so they should be different
        self.assertNotEqual(encrypted1, encrypted2)

    def test_decrypt_invalid_token_raises_exception(self):
        """Test that decrypting invalid token raises exception."""
        from cryptography.fernet import InvalidToken

        with self.assertRaises(InvalidToken):
            encryption.decrypt_token('invalid_encrypted_token')

    def test_get_fernet_returns_fernet_instance(self):
        """Test that get_fernet returns Fernet instance."""
        from cryptography.fernet import Fernet

        fernet = encryption.get_fernet()
        self.assertIsInstance(fernet, Fernet)


if __name__ == '__main__':
    unittest.main()
