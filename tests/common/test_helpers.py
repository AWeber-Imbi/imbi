import unittest

from imbi_common import helpers


class UnwrapAsTestCase(unittest.TestCase):
    def test_fails_with_none(self) -> None:
        with self.assertRaises(ValueError):
            helpers.unwrap_as(int, None)

    def test_succeeds_with_correct_type(self) -> None:
        self.assertEqual(helpers.unwrap_as(int, 1), 1)

    def test_fails_with_incorrect_type(self) -> None:
        with self.assertRaises(ValueError):
            helpers.unwrap_as(str, 1)
