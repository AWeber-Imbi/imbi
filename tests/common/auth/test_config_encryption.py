"""Unit tests for config-secret encryption helpers."""

import os
import unittest
import unittest.mock

from cryptography import fernet

from imbi.common import settings
from imbi.common.auth import encryption


class ConfigEncryptionTestCase(unittest.TestCase):
    """Test config value encryption and decryption."""

    def setUp(self) -> None:
        super().setUp()
        settings._config_settings = None
        encryption.ConfigEncryption.reset_instance()

    def tearDown(self) -> None:
        settings._config_settings = None
        encryption.ConfigEncryption.reset_instance()
        super().tearDown()

    def test_round_trip(self) -> None:
        """A value survives an encrypt/decrypt round trip."""
        plaintext = 'super-secret-value'
        encrypted = encryption.encrypt_config_value(plaintext)
        self.assertIsNotNone(encrypted)
        self.assertNotEqual(encrypted, plaintext)
        self.assertEqual(encryption.decrypt_config_value(encrypted), plaintext)

    def test_encrypt_none_returns_none(self) -> None:
        """Encrypting None returns None."""
        self.assertIsNone(encryption.encrypt_config_value(None))

    def test_decrypt_none_returns_none(self) -> None:
        """Decrypting None returns None."""
        self.assertIsNone(encryption.decrypt_config_value(None))

    def test_decrypt_invalid_returns_none(self) -> None:
        """Decrypting corrupt ciphertext returns None gracefully."""
        self.assertIsNone(
            encryption.decrypt_config_value('not-valid-ciphertext')
        )

    def test_get_config_fernet_raises_when_key_missing(self) -> None:
        """RuntimeError is raised when the config key is unset."""
        config_settings = settings.ConfigSecrets()
        config_settings.encryption_key = None
        with self.assertRaises(RuntimeError) as ctx:
            encryption.get_config_fernet(config_settings)
        self.assertEqual(str(ctx.exception), 'Encryption key not configured')

    def test_isolated_from_auth_key(self) -> None:
        """Config and auth keys are independent and not interchangeable.

        A value encrypted with the config key must not decrypt with the
        auth-token helpers, and vice versa.
        """
        auth_key = fernet.Fernet.generate_key().decode('ascii')
        config_key = fernet.Fernet.generate_key().decode('ascii')
        with unittest.mock.patch.dict(
            os.environ,
            {
                'IMBI_AUTH_ENCRYPTION_KEY': auth_key,
                'IMBI_CONFIG_ENCRYPTION_KEY': config_key,
            },
            clear=True,
        ):
            from imbi.common.auth import encryption as enc

            settings._auth_settings = None
            settings._config_settings = None

            config_ciphertext = enc.encrypt_config_value('value')
            auth_ciphertext = enc.encrypt_token('value')

            # Config ciphertext is undecryptable by the auth helper.
            with self.assertRaises(fernet.InvalidToken):
                enc.decrypt_token(config_ciphertext)

            # Auth ciphertext is undecryptable by the config helper
            # (returns None on failure).
            self.assertIsNone(enc.decrypt_config_value(auth_ciphertext))

            settings._auth_settings = None
            settings._config_settings = None


class ConfigEncryptionClassTestCase(unittest.TestCase):
    """Test the ConfigEncryption singleton class."""

    def setUp(self) -> None:
        super().setUp()
        settings._config_settings = None
        encryption.ConfigEncryption.reset_instance()

    def tearDown(self) -> None:
        settings._config_settings = None
        encryption.ConfigEncryption.reset_instance()
        super().tearDown()

    def test_get_instance_is_singleton(self) -> None:
        """get_instance returns the same instance on repeat calls."""
        first = encryption.ConfigEncryption.get_instance()
        second = encryption.ConfigEncryption.get_instance()
        self.assertIs(first, second)

    def test_get_instance_raises_when_key_missing(self) -> None:
        """RuntimeError is raised when the config key is unset."""
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            instance = encryption.ConfigEncryption(
                fernet.Fernet.generate_key().decode('ascii')
            )
            self.assertIsNotNone(instance)
            cfg = settings.ConfigSecrets()
            cfg.encryption_key = None
            settings._config_settings = cfg
            with self.assertRaises(RuntimeError) as ctx:
                encryption.ConfigEncryption.get_instance()
            self.assertEqual(
                str(ctx.exception), 'Encryption key not configured'
            )

    def test_invalid_key_raises_value_error(self) -> None:
        """An invalid Fernet key raises ValueError."""
        with self.assertRaises(ValueError):
            encryption.ConfigEncryption('not-a-valid-fernet-key')

    def test_round_trip(self) -> None:
        """The class encrypts and decrypts a value."""
        instance = encryption.ConfigEncryption.get_instance()
        encrypted = instance.encrypt('value')
        self.assertEqual(instance.decrypt(encrypted), 'value')

    def test_encrypt_and_decrypt_none(self) -> None:
        """None passes through encrypt and decrypt unchanged."""
        instance = encryption.ConfigEncryption.get_instance()
        self.assertIsNone(instance.encrypt(None))
        self.assertIsNone(instance.decrypt(None))

    def test_decrypt_invalid_returns_none(self) -> None:
        """Corrupt ciphertext decrypts to None."""
        instance = encryption.ConfigEncryption.get_instance()
        self.assertIsNone(instance.decrypt('corrupt'))


if __name__ == '__main__':
    unittest.main()
