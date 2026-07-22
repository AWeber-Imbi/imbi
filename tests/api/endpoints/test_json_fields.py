"""Tests for the shared JSON-field serialize/deserialize helpers."""

import unittest

from imbi_api.endpoints import _json_fields

FIELDS: _json_fields.JSONFields = {'links': {}, 'tags': []}


class SerializeTests(unittest.TestCase):
    def test_dict_and_list_become_strings(self) -> None:
        out = _json_fields.serialize_json_fields(
            {'links': {'a': 1}, 'tags': ['x'], 'name': 'keep'}, FIELDS
        )
        self.assertEqual(out['links'], '{"a": 1}')
        self.assertEqual(out['tags'], '["x"]')
        self.assertEqual(out['name'], 'keep')

    def test_already_string_left_untouched(self) -> None:
        out = _json_fields.serialize_json_fields({'links': '{"a": 1}'}, FIELDS)
        self.assertEqual(out['links'], '{"a": 1}')

    def test_missing_field_ignored(self) -> None:
        out = _json_fields.serialize_json_fields({'name': 'x'}, FIELDS)
        self.assertNotIn('links', out)

    def test_does_not_mutate_input(self) -> None:
        source = {'links': {'a': 1}}
        _json_fields.serialize_json_fields(source, FIELDS)
        self.assertEqual(source['links'], {'a': 1})


class DeserializeTests(unittest.TestCase):
    def test_string_parsed_back(self) -> None:
        out = _json_fields.deserialize_json_fields(
            {'links': '{"a": 1}', 'tags': '["x"]'}, FIELDS
        )
        self.assertEqual(out['links'], {'a': 1})
        self.assertEqual(out['tags'], ['x'])

    def test_none_uses_default(self) -> None:
        out = _json_fields.deserialize_json_fields(
            {'links': None, 'tags': None}, FIELDS
        )
        self.assertEqual(out['links'], {})
        self.assertEqual(out['tags'], [])

    def test_missing_field_filled_with_default(self) -> None:
        # A missing key reads as None, so it is populated with its default
        # -- this guarantees response models always see the field.
        out = _json_fields.deserialize_json_fields({'name': 'x'}, FIELDS)
        self.assertEqual(out['links'], {})
        self.assertEqual(out['tags'], [])

    def test_malformed_json_falls_back_to_default(self) -> None:
        out = _json_fields.deserialize_json_fields({'links': '{bad'}, FIELDS)
        self.assertEqual(out['links'], {})

    def test_non_string_non_none_passes_through(self) -> None:
        out = _json_fields.deserialize_json_fields(
            {'links': {'already': 'dict'}}, FIELDS
        )
        self.assertEqual(out['links'], {'already': 'dict'})

    def test_does_not_mutate_input(self) -> None:
        source = {'links': '{"a": 1}'}
        _json_fields.deserialize_json_fields(source, FIELDS)
        self.assertEqual(source['links'], '{"a": 1}')


if __name__ == '__main__':
    unittest.main()
