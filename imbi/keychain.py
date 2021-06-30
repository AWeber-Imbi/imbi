import base64

from cryptography import fernet
from cryptography.hazmat.primitives import hashes, hmac


class DecryptionFailure(RuntimeError):
    """Raised when a value cannot be decrypted."""
    ...


class Keychain:
    """Simple keychain abstraction.

    This class takes a random 32-byte key and uses it for symmetric
    encryption and one-way hashing.  The interfaces are ALWAYS in
    terms of byte strings.

    .. rubric:: Import Note

    Though this keychain can decrypt any message that was encrypted
    using the same key, it is not true that encrypting the same plain
    text twice will result in the same cipher text value.  In fact,
    the current implementation will guarantee that this is not the
    case so you should never store an encrypted value somewhere and
    then compare it to a newly encrypted value for raw byte equality.

    """
    algorithm = hashes.SHA512()

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError('Keychain requires a 32-byte key')
        self._key = key
        self._fernet = fernet.Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt `ciphertext` using the configured key."""
        return base64.urlsafe_b64decode(self._fernet.encrypt(plaintext))

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt `ciphertext` using the configured key.

        :raises: :exc:`DecryptionFailure` when the value cannot be
            decrypted.
        """
        try:
            return self._fernet.decrypt(base64.urlsafe_b64encode(ciphertext))
        except fernet.InvalidToken as error:
            raise DecryptionFailure() from error

    def hash(self, data: str) -> bytes:
        """Generate a HMAC-SHA512 of the supplied data."""
        hasher = hmac.HMAC(self._key, self.algorithm)
        hasher.update(data.encode('utf-8'))
        return hasher.finalize()
