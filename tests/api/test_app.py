import uuid

from tests import base


class EncryptionTestCase(base.TestCase):
    def test_lifecycle(self):
        value = str(uuid.uuid4())
        encrypted = self._app.encrypt_value(value)
        self.assertEqual(self._app.decrypt_value(encrypted), value)


class PasswordHashingTestCase(base.TestCase):
    def test_that_password_hashes_include_algorithm(self):
        hashed = self._app.hash_password('my password')
        self.assertTrue(
            hashed.startswith(self._app.keychain.algorithm.name + ':'),
            'Hashed password is not prefixed by algorithm')
