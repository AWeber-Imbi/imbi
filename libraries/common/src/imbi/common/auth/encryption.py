"""Token encryption utilities using Fernet symmetric encryption.

This module provides encryption/decryption for sensitive tokens (e.g., OAuth
provider access/refresh tokens) using the Fernet symmetric encryption scheme
from the cryptography library.

The encryption key is sourced from settings (IMBI_AUTH_ENCRYPTION_KEY
environment variable) and auto-generated if not provided.
"""

import base64
import binascii
import logging
import typing

from cryptography import fernet

from imbi_common import settings

LOGGER = logging.getLogger(__name__)


class TokenEncryption:
    """Handles encryption/decryption of sensitive tokens using Fernet.

    This class follows the singleton pattern to ensure a single encryption
    instance is used throughout the application lifecycle.

    Example:
        >>> encryptor = TokenEncryption.get_instance()
        >>> encrypted = encryptor.encrypt('my-secret-token')
        >>> decrypted = encryptor.decrypt(encrypted)
        >>> assert decrypted == 'my-secret-token'
    """

    _instance: typing.ClassVar['TokenEncryption | None'] = None
    _fernet: fernet.Fernet

    def __init__(self, encryption_key: str) -> None:
        """Initialize with base64-encoded Fernet key.

        Args:
            encryption_key: Base64-encoded Fernet encryption key

        Raises:
            ValueError: If encryption key format is invalid
        """
        try:
            key_bytes = encryption_key.encode('ascii')
            self._fernet = fernet.Fernet(key_bytes)
        except Exception as err:
            LOGGER.error('Invalid encryption key format: %s', err)
            raise ValueError('Invalid encryption key') from err

    @classmethod
    def get_instance(cls) -> 'TokenEncryption':
        """Get singleton instance of TokenEncryption.

        Returns:
            TokenEncryption: The singleton instance

        Raises:
            RuntimeError: If encryption key not configured in settings
        """
        if cls._instance is None:
            auth_settings = settings.get_auth_settings()
            if not auth_settings.encryption_key:
                raise RuntimeError('Encryption key not configured')
            cls._instance = cls(auth_settings.encryption_key)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing).

        This method is primarily used in test suites to reset the singleton
        state between tests.
        """
        cls._instance = None

    def encrypt(self, plaintext: str | None) -> str | None:
        """Encrypt a token string.

        Args:
            plaintext: Token string to encrypt, or None

        Returns:
            Base64-encoded encrypted token, or None if input is None

        Raises:
            Exception: If encryption fails
        """
        if plaintext is None:
            return None

        try:
            encrypted_bytes: bytes = self._fernet.encrypt(
                plaintext.encode('utf-8')
            )
            # Fernet already returns base64-encoded bytes, just decode to str
            return encrypted_bytes.decode('ascii')
        except Exception as err:
            LOGGER.exception('Encryption failed: %s', err)
            raise

    def decrypt(self, ciphertext: str | None) -> str | None:
        """Decrypt a token string.

        Args:
            ciphertext: Base64-encoded encrypted token, or None

        Returns:
            Decrypted plaintext token, or None if input is None
                or decryption fails

        Note:
            Returns None instead of raising exception on decryption failure
            to handle corrupted/invalid ciphertext gracefully.
            Handles both new format (Fernet base64) and legacy format
            (double base64 encoding) for backward compatibility.
        """
        if ciphertext is None:
            return None

        try:
            # Try new format first (Fernet base64 only)
            encrypted_bytes = ciphertext.encode('ascii')
            plaintext_bytes: bytes = self._fernet.decrypt(encrypted_bytes)
            return plaintext_bytes.decode('utf-8')
        except fernet.InvalidToken:
            # Try legacy format (double base64 encoding)
            try:
                encrypted_bytes = base64.urlsafe_b64decode(
                    ciphertext.encode('ascii')
                )
                plaintext_bytes = self._fernet.decrypt(encrypted_bytes)
                return plaintext_bytes.decode('utf-8')
            except (
                fernet.InvalidToken,
                binascii.Error,
                ValueError,
                UnicodeDecodeError,
            ):
                # All decryption attempts failed - invalid or corrupted
                LOGGER.warning(
                    'Failed to decrypt token - invalid or corrupted ciphertext'
                )
                return None
        except (binascii.Error, ValueError, UnicodeDecodeError):
            # Handle decryption errors (base64 decode, unicode errors)
            LOGGER.warning(
                'Failed to decrypt token - invalid or corrupted ciphertext'
            )
            return None


# Module-level convenience functions
def get_fernet(auth_settings: settings.Auth | None = None) -> fernet.Fernet:
    """Get Fernet instance for encryption/decryption.

    Args:
        auth_settings: Optional auth settings (uses singleton if not provided)

    Returns:
        Fernet instance configured with encryption key

    """
    if auth_settings is None:
        auth_settings = settings.get_auth_settings()

    if not auth_settings.encryption_key:
        # This should not happen since Auth now auto-generates encryption_key
        auth_settings.encryption_key = fernet.Fernet.generate_key().decode(
            'ascii'
        )

    return fernet.Fernet(auth_settings.encryption_key.encode('ascii'))


def encrypt_token(
    plaintext: str, auth_settings: settings.Auth | None = None
) -> str:
    """Encrypt a token string.

    Args:
        plaintext: Token string to encrypt
        auth_settings: Optional auth settings (creates default if not provided)

    Returns:
        Base64-encoded encrypted token

    """
    f = get_fernet(auth_settings)
    encrypted_bytes: bytes = f.encrypt(plaintext.encode('utf-8'))
    return encrypted_bytes.decode('ascii')


def decrypt_token(
    ciphertext: str, auth_settings: settings.Auth | None = None
) -> str:
    """Decrypt a token string.

    Args:
        ciphertext: Base64-encoded encrypted token
        auth_settings: Optional auth settings (creates default if not provided)

    Returns:
        Decrypted plaintext token

    Raises:
        Exception: If decryption fails

    """
    f = get_fernet(auth_settings)
    plaintext_bytes: bytes = f.decrypt(ciphertext.encode('ascii'))
    return plaintext_bytes.decode('utf-8')
