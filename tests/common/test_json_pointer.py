import unittest

import jsonpointer
import pydantic

from imbi_common import json_pointer

JsonPointerAdapter = pydantic.TypeAdapter[json_pointer.JsonPointer](
    json_pointer.JsonPointer
)


class JsonPointerTests(unittest.TestCase):
    def test_json_pointer_parsing(self) -> None:
        ptr = jsonpointer.JsonPointer('/target')
        self.assertIs(ptr, JsonPointerAdapter.validate_python(ptr))
        self.assertEqual(ptr, JsonPointerAdapter.validate_python('/target'))
        with self.assertRaises(ValueError):
            JsonPointerAdapter.validate_python('../relative-is-unsupported')
        with self.assertRaises(ValueError):
            JsonPointerAdapter.validate_python(42)

    def test_serialization(self) -> None:
        ptr = JsonPointerAdapter.validate_python('/target')
        self.assertEqual(b'"/target"', JsonPointerAdapter.dump_json(ptr))
        self.assertEqual(
            jsonpointer.JsonPointer('/target'),
            JsonPointerAdapter.dump_python(ptr),
        )
        self.assertEqual(
            {'type': 'string', 'format': 'json-pointer'},
            JsonPointerAdapter.json_schema(),
        )
