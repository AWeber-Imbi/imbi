import unittest
import uuid

from imbi import common


class JSONSchemaValidateTestCase(unittest.TestCase):

    def test_invalid_raises_value_error(self):
        with self.assertRaises(ValueError):
            common.jsonschema_validate('patch.yaml', {'foo': 'bar'}, False)

    def test_valid_does_not_raise(self):
        self.validate = common.jsonschema_validate(
            'patch.yaml',
            [{'op': 'add', 'path': '/key', 'value': 'foo'}], False)


class EncryptionTestCase(unittest.TestCase):

    def test_is_encrypted_false(self):
        self.assertFalse(common.is_encrypted_value(str(uuid.uuid4())))

    def test_is_encrypted_none(self):
        self.assertFalse(common.is_encrypted_value(None))

    def test_lifecycle(self):
        key = str(uuid.uuid4()).encode('utf-8')
        value = str(uuid.uuid4()).encode('utf-8')
        encrypted = common.encrypt_value(key, value)
        self.assertTrue(common.is_encrypted_value(encrypted))
        self.assertEqual(common.decrypt_value(key, encrypted), value)
