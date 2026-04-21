"""Unit tests for the version format validators."""

import unittest

from imbi_common import versioning


class ValidateSemverTestCase(unittest.TestCase):
    """Tests for ``validate_version`` with ``fmt='semver'``."""

    def test_basic_version(self) -> None:
        self.assertEqual(
            versioning.validate_version('1.2.3', 'semver'),
            '1.2.3',
        )

    def test_zero_version(self) -> None:
        self.assertEqual(
            versioning.validate_version('0.0.0', 'semver'),
            '0.0.0',
        )

    def test_prerelease(self) -> None:
        self.assertEqual(
            versioning.validate_version('1.0.0-rc.1', 'semver'),
            '1.0.0-rc.1',
        )

    def test_prerelease_alpha(self) -> None:
        self.assertEqual(
            versioning.validate_version('1.0.0-alpha', 'semver'),
            '1.0.0-alpha',
        )

    def test_build_metadata(self) -> None:
        self.assertEqual(
            versioning.validate_version('1.0.0+build.42', 'semver'),
            '1.0.0+build.42',
        )

    def test_prerelease_and_build(self) -> None:
        self.assertEqual(
            versioning.validate_version(
                '1.0.0-rc.1+build.42',
                'semver',
            ),
            '1.0.0-rc.1+build.42',
        )

    def test_leading_zero_rejected(self) -> None:
        with self.assertRaises(ValueError):
            versioning.validate_version('01.2.3', 'semver')

    def test_leading_zero_minor_rejected(self) -> None:
        with self.assertRaises(ValueError):
            versioning.validate_version('1.02.3', 'semver')

    def test_leading_zero_patch_rejected(self) -> None:
        with self.assertRaises(ValueError):
            versioning.validate_version('1.2.03', 'semver')

    def test_v_prefix_rejected(self) -> None:
        with self.assertRaises(ValueError):
            versioning.validate_version('v1.2.3', 'semver')

    def test_missing_patch_rejected(self) -> None:
        with self.assertRaises(ValueError):
            versioning.validate_version('1.2', 'semver')

    def test_empty_rejected(self) -> None:
        with self.assertRaises(ValueError):
            versioning.validate_version('', 'semver')

    def test_non_numeric_rejected(self) -> None:
        with self.assertRaises(ValueError):
            versioning.validate_version('a.b.c', 'semver')


class ValidateCommitishTestCase(unittest.TestCase):
    """Tests for ``validate_version`` with ``fmt='commitish'``."""

    def test_seven_char(self) -> None:
        self.assertEqual(
            versioning.validate_version('abc1234', 'commitish'),
            'abc1234',
        )

    def test_forty_char(self) -> None:
        sha = 'a' * 40
        self.assertEqual(
            versioning.validate_version(sha, 'commitish'),
            sha,
        )

    def test_uppercase_rejected(self) -> None:
        with self.assertRaises(ValueError):
            versioning.validate_version('ABC1234', 'commitish')

    def test_too_short_rejected(self) -> None:
        with self.assertRaises(ValueError):
            versioning.validate_version('abc123', 'commitish')

    def test_too_long_rejected(self) -> None:
        with self.assertRaises(ValueError):
            versioning.validate_version('a' * 41, 'commitish')

    def test_non_hex_rejected(self) -> None:
        with self.assertRaises(ValueError):
            versioning.validate_version('ghij123', 'commitish')

    def test_empty_rejected(self) -> None:
        with self.assertRaises(ValueError):
            versioning.validate_version('', 'commitish')


class GetVersionValidatorTestCase(unittest.TestCase):
    """Tests for the ``get_version_validator`` helper."""

    def test_returns_callable_that_validates_semver(self) -> None:
        validator = versioning.get_version_validator('semver')
        self.assertEqual(validator('1.2.3'), '1.2.3')
        with self.assertRaises(ValueError):
            validator('not-a-version')

    def test_returns_callable_that_validates_commitish(self) -> None:
        validator = versioning.get_version_validator('commitish')
        self.assertEqual(validator('abc1234'), 'abc1234')
        with self.assertRaises(ValueError):
            validator('ABC1234')


if __name__ == '__main__':
    unittest.main()
