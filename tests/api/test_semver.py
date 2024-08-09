import json
import unittest.mock
from collections import abc

import pydantic
import semantic_version

from imbi import semver


class VersionCheckingTests(unittest.TestCase):
    def verify_range(self, spec: str, in_range: abc.Iterable[str],
                     out_of_range: abc.Iterable[str]) -> None:
        ver_range = semver.parse_semver_range(spec)
        for value in in_range:
            self.assertIn(value, ver_range, value)
        for value in out_of_range:
            self.assertNotIn(value, ver_range, value)

    def test_tilde_ranges_from_documentation(self) -> None:
        # https://www.npmjs.com/package/semver#user-content-tilde-ranges-123-12-1

        # ~1.2.3 := >=1.2.3 <1.(2+1).0 := >=1.2.3 <1.3.0-0
        self.verify_range('~1.2.3', ('1.2.3', '1.2.4', '1.2.99'),
                          ('1.1', '1.2.2', '1.2.2.99', '1.2', '1.3'))

        # ~1.2 := >=1.2.0 <1.(2+1).0 := >=1.2.0 <1.3.0-0
        self.verify_range('~1.2', ('1.2', '1.2.2', '1.2.3', '1.2.99'),
                          ('1.1', '1.3.0', '1.3'))

        # ~1 := >=1.0.0 <(1+1).0.0 := >=1.0.0 <2.0.0-0
        self.verify_range('~1', ('1.2', '1.2.2', '1.2.3', '1.2.99', '1.99'),
                          ('2.0', '0.1.2', '3'))

        # ~0.2.3 := >=0.2.3 <0.(2+1).0 := >=0.2.3 <0.3.0-0
        self.verify_range('~0.2.3', ('0.2.3', '0.2.99'),
                          ('0.2.2', '0.3', '1.0'))

        # ~0.2 := >=0.2.0 <0.(2+1).0 := >=0.2.0 <0.3.0-0
        self.verify_range('~0.2', ('0.2.0', '0.2.99'), ('0.1', '0.3', '1.0'))

        # ~0 := >=0.0.0 <(0+1).0.0 := >=0.0.0 <1.0.0-0
        self.verify_range('~0', ('0.9.9', '0.1', '0'), ('1.0', '2.0'))

    def test_caret_ranges_from_documentation(self) -> None:
        # https://www.npmjs.com/package/semver#caret-ranges-123-025-004

        # ^1.2.3 := >=1.2.3 <2.0.0-0
        self.verify_range('^1.2.3', ('1.2.3', '1.2.4', '1.9.9'),
                          ('1.2.2', '2'))

        # ^0.2.3 := >=0.2.3 <0.3.0-0
        self.verify_range('^0.2.3', ('0.2.3', '0.2.4', '0.2.9'),
                          ('0.2.2', '0.3', '0', '1'))

        # ^0.0.3 := >=0.0.3 <0.0.4-0
        self.verify_range('^0.0.3', ('0.0.3', '0.0.3.1'),
                          ('0.0.2', '0.0.4', '0', '1'))

    def test_exact_ranges(self) -> None:
        self.verify_range('1.2.3', ['1.2.3'],
                          ['1.2', '1.2.2', '1.2.3.1', '1.2.4'])

    def test_caret_range_of_all_zeros(self) -> None:  # this is an edge case
        self.verify_range('^0', ('0', '0.1', '0.99.99'), ('1', '1.0'))
        self.verify_range('^0.0', ('0', '0.0.1', '0.0.99'), ('0.1', '1.0'))
        self.verify_range('^0.0.0', ('0', '0.0.0'), ('0.0.1', '0.1', '1.0'))


class VersionRangeErrorHandlingTests(unittest.TestCase):
    def test_that_empty_spec_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            semver.ExactRange('')

        with self.assertRaises(ValueError):
            semver.parse_semver_range('')

    def test_contains_works_with_str(self) -> None:
        self.assertIn('1.2.3', semver.parse_semver_range('1.2.3'))

    def test_contains_works_with_version(self) -> None:
        self.assertIn(semantic_version.Version('1.2.3'),
                      semver.parse_semver_range('1.2.3'))

    def test_contains_with_other_instance_types(self) -> None:
        ver_range = semver.parse_semver_range('1')
        self.assertNotIn(1, ver_range)
        self.assertNotIn(True, ver_range)
        self.assertNotIn(object(), ver_range)


class PydanticModelTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.adapter = pydantic.TypeAdapter(semver.VersionRange)
        self.value = semver.VersionRange('~1.2.3')

    def test_core_schema_validation(self) -> None:
        self.assertEqual(self.value, self.adapter.validate_json('"~1.2.3"'))
        self.assertEqual(self.value, self.adapter.validate_python(self.value))

    def test_core_schema_serialization(self) -> None:
        result = json.loads(self.adapter.serializer.to_json(self.value))
        self.assertEqual(self.value.spec, result)
        self.assertEqual(self.value.spec,
                         self.adapter.serializer.to_python(self.value))


class UtilityFunctionTests(unittest.TestCase):
    def test_equality(self) -> None:
        self.assertEqual(semver.VersionRange('1'), semver.VersionRange('1'))
        self.assertNotEqual(semver.VersionRange('1'), '1')

    def test_hashing(self) -> None:
        v1 = semver.VersionRange('1.2.3')
        v2 = semver.VersionRange('~1.2.3')
        self.assertEqual(hash(v1), hash(semver.VersionRange(v1.spec)))
        self.assertEqual(hash(v1), hash(v1))
        self.assertNotEqual(hash(v1), hash(v2))

    def test_repr(self) -> None:
        v1 = semver.VersionRange('1.2.3')
        v2 = eval(repr(v1), {'VersionRange': semver.VersionRange})
        self.assertEqual(v1, v2)

    def test_str(self) -> None:
        v = semver.VersionRange('~1.2.3')
        self.assertEqual('VersionRange(~1.2.3)', str(v))

    def test_validation(self) -> None:
        v = semver.VersionRange('~1.2.3')
        self.assertEqual(v, semver.VersionRange._validate(v))
        self.assertEqual(v, semver.VersionRange._validate('~1.2.3'))
        with self.assertRaises(TypeError):
            semver.VersionRange._validate(1.2)

    def test_json_schema(self) -> None:
        schema = pydantic.TypeAdapter(semver.VersionRange).json_schema()
        self.assertEqual('string', schema['type'])
        self.assertEqual(1, schema['minLength'])
