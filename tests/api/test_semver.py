import unittest
from collections import abc

import packaging.version

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

        # ~0.2.3 := >=0.2.3 <0.(2+1).0 := >=0.2.3 <0.3.0-0
        self.verify_range('~0.2.3', ('0.2.3', '0.2.99'),
                          ('0.2.2', '0.3', '1.0'))

        # ~0.2 := >=0.2.0 <0.(2+1).0 := >=0.2.0 <0.3.0-0
        self.verify_range('~0.2.3', ('0.2.3', '0.2.99'),
                          ('0.2.2', '0.3', '1.0'))

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
        self.assertIn(packaging.version.Version('1.2.3'),
                      semver.parse_semver_range('1.2.3'))

    def test_contains_with_other_instance_types(self) -> None:
        ver_range = semver.parse_semver_range('1')
        self.assertNotIn(1, ver_range)
        self.assertNotIn(True, ver_range)
        self.assertNotIn(object(), ver_range)
