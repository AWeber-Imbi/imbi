import uuid

from tests import base


class EncryptionTestCase(base.TestCase):

    def test_lifecycle(self):
        value = str(uuid.uuid4())
        encrypted = self._app.encrypt_value('REMOVEME', value)
        self.assertEqual(self._app.decrypt_value('REMOVEME', encrypted), value)
