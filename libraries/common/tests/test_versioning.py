"""Unit tests for the version format validators and release ranking."""

import datetime
import typing
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


class ShortCommittishTestCase(unittest.TestCase):
    """Tests for ``short_committish``."""

    def test_full_sha_is_shortened(self) -> None:
        self.assertEqual(
            'abc1234', versioning.short_committish('abc1234' + 'd' * 33)
        )

    def test_uppercase_sha_is_lowercased(self) -> None:
        self.assertEqual('abc1234', versioning.short_committish('ABC1234'))

    def test_short_sha_unchanged(self) -> None:
        self.assertEqual('abc1234', versioning.short_committish('abc1234'))

    def test_branch_name_unchanged(self) -> None:
        self.assertEqual('main', versioning.short_committish('main'))

    def test_tag_unchanged(self) -> None:
        self.assertEqual(
            'release-2.4.0', versioning.short_committish('release-2.4.0')
        )


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


class ReleaseVersionKeyTestCase(unittest.TestCase):
    """Tests for ``release_version_key``."""

    def test_three_components(self) -> None:
        self.assertEqual(versioning.release_version_key('1.2.3'), (1, 2, 3))

    def test_v_prefix(self) -> None:
        self.assertEqual(versioning.release_version_key('v1.2.3'), (1, 2, 3))

    def test_fourth_component_is_kept(self) -> None:
        self.assertEqual(
            versioning.release_version_key('0.17.0.1'), (0, 17, 0, 1)
        )

    def test_suffix_ignored(self) -> None:
        self.assertEqual(
            versioning.release_version_key('1.2.3-rc1'), (1, 2, 3)
        )
        self.assertEqual(
            versioning.release_version_key('1.2.3+build.4'), (1, 2, 3)
        )

    def test_leading_zeros_tolerated(self) -> None:
        self.assertEqual(versioning.release_version_key('1.02.3'), (1, 2, 3))

    def test_non_release_tags(self) -> None:
        for name in ('deploy-20240101', 'main', '1.2', 'v1', ''):
            with self.subTest(name=name):
                self.assertIsNone(versioning.release_version_key(name))

    def test_ordering_across_lengths(self) -> None:
        # A rebuild sorts above the version it rebuilds, and both sort
        # below the next major.
        keys = [
            versioning.release_version_key(n) or ()
            for n in ('0.17.0', '0.17.0.1', '1.0.0')
        ]
        self.assertEqual(keys, sorted(keys))


class ReleaseTagOrderKeyTestCase(unittest.TestCase):
    """Tests for ``release_tag_order_key``."""

    @staticmethod
    def _at(day: int) -> datetime.datetime:
        return datetime.datetime(2026, 8, day, tzinfo=datetime.UTC)

    def test_commit_history_outranks_version(self) -> None:
        # The #279 case: a stray 1.0.0 on an old commit must lose to the
        # lower-numbered tag on the newest commit.
        stray = versioning.release_tag_order_key(
            '1.0.0', self._at(1), self._at(1)
        )
        current = versioning.release_tag_order_key(
            '0.17.0-2', self._at(21), self._at(19)
        )
        self.assertGreater(current, stray)

    def test_unsynced_commit_ranks_below_synced(self) -> None:
        # A backport whose commit isn't synced can't win on version.
        backport = versioning.release_tag_order_key('9.9.9', self._at(22))
        synced = versioning.release_tag_order_key(
            '1.0.0', self._at(2), self._at(2)
        )
        self.assertGreater(synced, backport)

    def test_version_breaks_tie_on_one_commit(self) -> None:
        # Two tags on the same commit fall back to version order.
        lower = versioning.release_tag_order_key(
            '1.0.0', self._at(3), self._at(3)
        )
        higher = versioning.release_tag_order_key(
            '1.1.0', self._at(3), self._at(3)
        )
        self.assertGreater(higher, lower)

    def test_release_outranks_ad_hoc_on_one_commit(self) -> None:
        release = versioning.release_tag_order_key(
            '1.0.0', self._at(3), self._at(3)
        )
        ad_hoc = versioning.release_tag_order_key(
            'deploy-20260803', self._at(3), self._at(3)
        )
        self.assertGreater(release, ad_hoc)

    def test_timestamp_breaks_remaining_tie(self) -> None:
        # Same commit, same version tuple (suffix ignored) -> newer tag.
        older = versioning.release_tag_order_key(
            '0.17.0', self._at(3), self._at(3)
        )
        newer = versioning.release_tag_order_key(
            '0.17.0-2', self._at(4), self._at(3)
        )
        self.assertGreater(newer, older)

    def test_non_datetime_when_is_absent(self) -> None:
        self.assertEqual(
            versioning.release_tag_order_key('1.0.0', 'not-a-date'),
            ('', True, (1, 0, 0), ''),
        )

    def test_defaults_to_version_only_ordering(self) -> None:
        # No commit context at all -> plain highest-version behavior.
        self.assertGreater(
            versioning.release_tag_order_key('1.0.0'),
            versioning.release_tag_order_key('0.17.0'),
        )


class LatestReleaseTagTestCase(unittest.TestCase):
    """Tests for ``latest_release_tag``."""

    #: The production tag set from #279, trimmed to the rows that decide
    #: the outcome.  ``1.0.0`` is a leftover from an abandoned scheme.
    ROWS: list[dict[str, typing.Any]] = [  # noqa: RUF012
        {
            'name': '1.0.0',
            'sha': '022303B',
            'tagged_at': datetime.datetime(2025, 6, 4, tzinfo=datetime.UTC),
        },
        {
            'name': '0.17.0',
            'sha': '489ae31',
            'tagged_at': datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
        },
        {
            'name': '0.17.0-2',
            'sha': 'e9b3899',
            'tagged_at': datetime.datetime(2026, 8, 21, tzinfo=datetime.UTC),
        },
    ]

    AUTHORED: dict[str, datetime.datetime] = {  # noqa: RUF012
        '022303b': datetime.datetime(2025, 6, 4, tzinfo=datetime.UTC),
        '489ae31': datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
        'e9b3899': datetime.datetime(2026, 8, 19, tzinfo=datetime.UTC),
    }

    def test_empty_rows(self) -> None:
        self.assertIsNone(versioning.latest_release_tag([]))

    def test_picks_tag_on_newest_commit(self) -> None:
        latest = versioning.latest_release_tag(self.ROWS, self.AUTHORED)
        assert latest is not None
        self.assertEqual(latest['name'], '0.17.0-2')

    def test_sha_lookup_is_case_insensitive(self) -> None:
        # The row carries an upper-case sha; the map is keyed lowercase.
        rows = [self.ROWS[0]]
        latest = versioning.latest_release_tag(rows, self.AUTHORED)
        assert latest is not None
        self.assertEqual(latest['name'], '1.0.0')

    def test_without_commit_dates_highest_version_wins(self) -> None:
        # Degraded mode (e.g. the commit query failed): the stray tag
        # wins, which is the pre-#279 behavior.
        latest = versioning.latest_release_tag(self.ROWS)
        assert latest is not None
        self.assertEqual(latest['name'], '1.0.0')

    def test_falls_back_to_recorded_at(self) -> None:
        rows: list[dict[str, typing.Any]] = [
            {'name': '1.0.0', 'sha': 'aaaaaaa', 'recorded_at': None},
            {
                'name': '1.1.0',
                'sha': 'bbbbbbb',
                'recorded_at': datetime.datetime(
                    2026, 1, 1, tzinfo=datetime.UTC
                ),
            },
        ]
        latest = versioning.latest_release_tag(rows)
        assert latest is not None
        self.assertEqual(latest['name'], '1.1.0')

    def test_ad_hoc_tag_on_newest_commit_wins(self) -> None:
        # Consistent with release-history, which lists it first.
        rows: list[dict[str, typing.Any]] = [
            {'name': '1.0.0', 'sha': 'aaaaaaa'},
            {'name': 'deploy-20260901', 'sha': 'bbbbbbb'},
        ]
        authored = {
            'aaaaaaa': datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            'bbbbbbb': datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC),
        }
        latest = versioning.latest_release_tag(rows, authored)
        assert latest is not None
        self.assertEqual(latest['name'], 'deploy-20260901')

    def test_four_component_tag_is_selectable(self) -> None:
        rows: list[dict[str, typing.Any]] = [
            {'name': '0.17.0.1', 'sha': 'aaaaaaa'},
            {'name': '0.17.0.2', 'sha': 'bbbbbbb'},
        ]
        latest = versioning.latest_release_tag(rows)
        assert latest is not None
        self.assertEqual(latest['name'], '0.17.0.2')


if __name__ == '__main__':
    unittest.main()
