import unittest

from imbi.common.db.etl import ids


class DeriveIdTestCase(unittest.TestCase):
    def test_same_arguments_same_id(self) -> None:
        self.assertEqual(
            ids.derive_id('document_templates', 'org', 'readme'),
            ids.derive_id('document_templates', 'org', 'readme'),
        )

    def test_different_arguments_different_id(self) -> None:
        values = {
            ids.derive_id('tenants', 'default'),
            ids.derive_id('tenants', 'other'),
            ids.derive_id('other', 'default'),
            ids.derive_id('tenants', 'def', 'ault'),
        }
        self.assertEqual(len(values), 4)

    def test_nanoid_shape(self) -> None:
        value = ids.derive_id('tenants', 'default')
        self.assertEqual(len(value), 21)
        self.assertLessEqual(set(value), set(ids.ALPHABET))
