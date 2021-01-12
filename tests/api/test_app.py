import uuid

from tests import base


class EncryptionTestCase(base.TestCase):

    def test_is_encrypted_false(self):
        self.assertFalse(self._app.is_encrypted_value(str(uuid.uuid4())))

    def test_is_encrypted_none(self):
        self.assertFalse(self._app.is_encrypted_value(None))

    def test_lifecycle(self):
        key = str(uuid.uuid4()).encode('utf-8')
        value = str(uuid.uuid4()).encode('utf-8')
        encrypted = self._app.encrypt_value(key, value)
        self.assertTrue(self._app.is_encrypted_value(encrypted))
        self.assertEqual(self._app.decrypt_value(key, encrypted), value)
