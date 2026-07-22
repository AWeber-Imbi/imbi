"""Unit tests for the version format validators."""

import unittest

from imbi.common import versioning


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


class IsSemverTagTestCase(unittest.TestCase):
    """Tests for ``is_semver_tag``."""

    def test_bare_semver(self) -> None:
        self.assertTrue(versioning.is_semver_tag('1.2.3'))

    def test_v_prefixed_semver(self) -> None:
        self.assertTrue(versioning.is_semver_tag('v1.2.3'))

    def test_prerelease(self) -> None:
        self.assertTrue(versioning.is_semver_tag('v1.0.0-rc.1'))

    def test_sha_rejected(self) -> None:
        self.assertFalse(versioning.is_semver_tag('abc1234'))

    def test_branch_name_rejected(self) -> None:
        self.assertFalse(versioning.is_semver_tag('main'))

    def test_empty_rejected(self) -> None:
        self.assertFalse(versioning.is_semver_tag(''))


class IsCommitishTestCase(unittest.TestCase):
    """Tests for ``is_commitish``."""

    def test_short_sha(self) -> None:
        self.assertTrue(versioning.is_commitish('abc1234'))

    def test_long_sha(self) -> None:
        self.assertTrue(versioning.is_commitish('a' * 40))

    def test_uppercase_rejected(self) -> None:
        self.assertFalse(versioning.is_commitish('ABC1234'))

    def test_tag_rejected(self) -> None:
        self.assertFalse(versioning.is_commitish('v1.2.3'))

    def test_branch_name_rejected(self) -> None:
        self.assertFalse(versioning.is_commitish('main'))


class MatchesTagFormatsTestCase(unittest.TestCase):
    """Tests for ``matches_tag_formats``."""

    def test_empty_patterns_matches_anything(self) -> None:
        self.assertTrue(versioning.matches_tag_formats('anything', []))
        self.assertTrue(versioning.matches_tag_formats('main', ()))

    def test_matches_single_pattern(self) -> None:
        self.assertTrue(
            versioning.matches_tag_formats(
                'v1.2.3',
                [versioning.SEMVER_TAG_PATTERN],
            )
        )

    def test_matches_any_of_several(self) -> None:
        patterns = [r'rc-\d+', versioning.SEMVER_TAG_PATTERN]
        self.assertTrue(versioning.matches_tag_formats('rc-42', patterns))
        self.assertTrue(versioning.matches_tag_formats('1.0.0', patterns))

    def test_no_match(self) -> None:
        self.assertFalse(
            versioning.matches_tag_formats(
                'main',
                [versioning.SEMVER_TAG_PATTERN],
            )
        )

    def test_fullmatch_semantics(self) -> None:
        # An unanchored pattern still must span the whole tag.
        self.assertFalse(versioning.matches_tag_formats('v1.2.3-x', [r'\d+']))
        self.assertTrue(versioning.matches_tag_formats('123', [r'\d+']))

    def test_invalid_pattern_treated_as_non_match(self) -> None:
        self.assertFalse(versioning.matches_tag_formats('1.2.3', ['(']))


if __name__ == '__main__':
    unittest.main()
