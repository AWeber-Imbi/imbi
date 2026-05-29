import datetime
import unittest

import pydantic

from imbi_common.scoring import models


def _policy(**overrides: object) -> models.AttributePolicy:
    defaults: dict[str, object] = {
        'name': 'Lang',
        'slug': 'lang',
        'attribute_name': 'programming_language',
        'weight': 50,
        'value_score_map': {'Python 3.12': 100, 'Python 2.7': 0},
    }
    defaults.update(overrides)
    return models.AttributePolicy(**defaults)  # type: ignore[arg-type]


class ValidatorTests(unittest.TestCase):
    def test_both_maps_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            _policy(
                value_score_map={'a': 1},
                range_score_map={'0..1': 1},
            )

    def test_overlapping_ranges_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            _policy(
                value_score_map=None,
                range_score_map={'0..50': 0, '40..100': 100},
            )

    def test_gaps_allowed(self) -> None:
        policy = _policy(
            value_score_map=None,
            range_score_map={'0..50': 0, '60..100': 100},
        )
        self.assertEqual(0.0, policy.evaluate(25))
        self.assertEqual(100.0, policy.evaluate(75))
        self.assertIsNone(policy.evaluate(55))

    def test_invalid_range_lo_ge_hi(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            _policy(
                value_score_map=None,
                range_score_map={'10..10': 0},
            )


class EvaluationTests(unittest.TestCase):
    def test_value_map_match(self) -> None:
        policy = _policy()
        self.assertEqual(100.0, policy.evaluate('Python 3.12'))

    def test_value_map_unmapped(self) -> None:
        self.assertIsNone(_policy().evaluate('Ruby 3.3'))

    def test_value_map_missing(self) -> None:
        self.assertIsNone(_policy().evaluate(None))

    def test_value_map_boolean_true(self) -> None:
        # AGE stores some boolean attributes as real booleans; ``str(True)``
        # is ``'True'`` which must still match the lowercase ``'true'`` key.
        policy = _policy(value_score_map={'true': 100, 'false': 0})
        self.assertEqual(100.0, policy.evaluate(True))

    def test_value_map_boolean_false(self) -> None:
        policy = _policy(value_score_map={'true': 100, 'false': 0})
        self.assertEqual(0.0, policy.evaluate(False))

    def test_value_map_string_true_still_matches(self) -> None:
        # Attributes stored as the string ``'true'`` keep working.
        policy = _policy(value_score_map={'true': 100, 'false': 0})
        self.assertEqual(100.0, policy.evaluate('true'))

    def test_value_map_case_sensitive_string_preserved(self) -> None:
        # Non-boolean keys must not be lowercased.
        policy = _policy(value_score_map={'GitHub Actions': 100})
        self.assertEqual(100.0, policy.evaluate('GitHub Actions'))
        self.assertIsNone(policy.evaluate('github actions'))

    def test_range_closed(self) -> None:
        policy = _policy(
            value_score_map=None,
            range_score_map={'90..100': 100, '0..89': 0},
        )
        # Both bounds are inclusive — exact upper bound must match.
        self.assertEqual(100.0, policy.evaluate(90))
        self.assertEqual(100.0, policy.evaluate(100))
        self.assertEqual(0.0, policy.evaluate(0))
        self.assertEqual(0.0, policy.evaluate(89))
        self.assertIsNone(policy.evaluate(89.5))  # gap between 89 and 90

    def test_range_non_numeric(self) -> None:
        policy = _policy(
            value_score_map=None,
            range_score_map={'0..100': 50},
        )
        self.assertIsNone(policy.evaluate('not-a-number'))

    def test_no_maps_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.AttributePolicy(
                name='x',
                slug='x',
                attribute_name='x',
                weight=10,
            )

    def test_value_score_map_accepts_json_string(self) -> None:
        # AGE serializes nested objects as JSON strings; validator parses them.
        policy = models.AttributePolicy.model_validate(
            {
                'name': 'Lang',
                'slug': 'lang',
                'attribute_name': 'programming_language',
                'weight': 50,
                'value_score_map': '{"Python 3.12": 100, "Python 2.7": 0}',
            }
        )
        self.assertEqual(
            {'Python 3.12': 100, 'Python 2.7': 0}, policy.value_score_map
        )
        self.assertEqual(100.0, policy.evaluate('Python 3.12'))

    def test_range_score_map_accepts_json_string(self) -> None:
        policy = models.AttributePolicy.model_validate(
            {
                'name': 'Cov',
                'slug': 'cov',
                'attribute_name': 'test_coverage',
                'weight': 50,
                'range_score_map': '{"90.01..100": 100, "0..90": 0}',
            }
        )
        self.assertEqual(100.0, policy.evaluate(95))
        self.assertEqual(100.0, policy.evaluate(100))


class IsMissingTests(unittest.TestCase):
    def test_none_is_missing(self) -> None:
        self.assertTrue(models.is_missing(None))

    def test_empty_string_is_missing(self) -> None:
        self.assertTrue(models.is_missing(''))
        self.assertTrue(models.is_missing('   '))

    def test_empty_collection_is_missing(self) -> None:
        self.assertTrue(models.is_missing([]))
        self.assertTrue(models.is_missing({}))
        self.assertTrue(models.is_missing(()))
        self.assertTrue(models.is_missing(set()))

    def test_non_empty_is_present(self) -> None:
        self.assertFalse(models.is_missing('x'))
        self.assertFalse(models.is_missing([1]))
        self.assertFalse(models.is_missing(0))
        self.assertFalse(models.is_missing(False))


class PresencePolicyTests(unittest.TestCase):
    def _policy(self, **overrides: object) -> models.PresencePolicy:
        defaults: dict[str, object] = {
            'name': 'Has description',
            'slug': 'has-description',
            'attribute_name': 'description',
            'weight': 10,
        }
        defaults.update(overrides)
        return models.PresencePolicy(**defaults)  # type: ignore[arg-type]

    def test_present_default(self) -> None:
        self.assertEqual(100.0, self._policy().evaluate('a description'))

    def test_missing_default(self) -> None:
        self.assertEqual(0.0, self._policy().evaluate(None))
        self.assertEqual(0.0, self._policy().evaluate(''))

    def test_custom_scores(self) -> None:
        policy = self._policy(present_score=75, missing_score=25)
        self.assertEqual(75.0, policy.evaluate('x'))
        self.assertEqual(25.0, policy.evaluate(None))


class LinkPresencePolicyTests(unittest.TestCase):
    def _policy(self, **overrides: object) -> models.LinkPresencePolicy:
        defaults: dict[str, object] = {
            'name': 'Has source link',
            'slug': 'has-source-link',
            'link_slug': 'source-code',
            'weight': 10,
        }
        defaults.update(overrides)
        return models.LinkPresencePolicy(**defaults)  # type: ignore[arg-type]

    def test_present(self) -> None:
        policy = self._policy()
        self.assertEqual(
            100.0,
            policy.evaluate({'source-code': 'https://example.com/repo'}),
        )

    def test_missing(self) -> None:
        policy = self._policy()
        self.assertEqual(0.0, policy.evaluate({}))
        self.assertEqual(0.0, policy.evaluate({'other': 'https://x'}))
        self.assertEqual(0.0, policy.evaluate(None))

    def test_empty_url_treated_as_missing(self) -> None:
        policy = self._policy()
        self.assertEqual(0.0, policy.evaluate({'source-code': ''}))


class AgePolicyTests(unittest.TestCase):
    def _policy(self, **overrides: object) -> models.AgePolicy:
        defaults: dict[str, object] = {
            'name': 'Oldest PR Age',
            'slug': 'oldest-open-pr-age',
            'attribute_name': 'oldest_open_pr',
            'weight': 10,
            'age_score_map': {
                '>90d': 0,
                '>30d': 25,
                '>7d': 75,
                '<=7d': 100,
            },
        }
        defaults.update(overrides)
        return models.AgePolicy(**defaults)  # type: ignore[arg-type]

    def test_fresh_value_scores_high(self) -> None:
        now = datetime.datetime(2026, 5, 12, tzinfo=datetime.UTC)
        value = (now - datetime.timedelta(days=1)).isoformat()
        self.assertEqual(100.0, self._policy().evaluate(value, now=now))

    def test_old_value_scores_low(self) -> None:
        now = datetime.datetime(2026, 5, 12, tzinfo=datetime.UTC)
        value = (now - datetime.timedelta(days=120)).isoformat()
        self.assertEqual(0.0, self._policy().evaluate(value, now=now))

    def test_order_first_match_wins(self) -> None:
        now = datetime.datetime(2026, 5, 12, tzinfo=datetime.UTC)
        value = (now - datetime.timedelta(days=45)).isoformat()
        # 45d matches >30d before >7d
        self.assertEqual(25.0, self._policy().evaluate(value, now=now))

    def test_missing_value_returns_none(self) -> None:
        self.assertIsNone(self._policy().evaluate(None))
        self.assertIsNone(self._policy().evaluate(''))
        self.assertIsNone(self._policy().evaluate('not-a-date'))

    def test_accepts_z_suffix(self) -> None:
        now = datetime.datetime(2026, 5, 12, tzinfo=datetime.UTC)
        value = (now - datetime.timedelta(days=2)).strftime(
            '%Y-%m-%dT%H:%M:%SZ'
        )
        self.assertEqual(100.0, self._policy().evaluate(value, now=now))

    def test_accepts_json_map_string(self) -> None:
        # AGE serializes nested objects as JSON strings.
        policy = models.AgePolicy.model_validate(
            {
                'name': 'PR Age',
                'slug': 'pr-age',
                'attribute_name': 'oldest_open_pr',
                'weight': 10,
                'age_score_map': '{">7d": 0, "<=7d": 100}',
            }
        )
        self.assertEqual({'>7d': 0, '<=7d': 100}, policy.age_score_map)

    def test_empty_map_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.AgePolicy(
                name='x',
                slug='x',
                attribute_name='x',
                weight=10,
                age_score_map={},
            )

    def test_invalid_threshold_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.AgePolicy(
                name='x',
                slug='x',
                attribute_name='x',
                weight=10,
                age_score_map={'30d': 0},  # missing operator
            )

    def test_supports_hours_and_weeks(self) -> None:
        now = datetime.datetime(2026, 5, 12, tzinfo=datetime.UTC)
        policy = models.AgePolicy(
            name='Last sync',
            slug='last-sync',
            attribute_name='last_sync_at',
            weight=10,
            age_score_map={'>2w': 0, '>1h': 50, '<=1h': 100},
        )
        recent = (now - datetime.timedelta(minutes=30)).isoformat()
        self.assertEqual(100.0, policy.evaluate(recent, now=now))
        mid = (now - datetime.timedelta(days=3)).isoformat()
        self.assertEqual(50.0, policy.evaluate(mid, now=now))
        old = (now - datetime.timedelta(weeks=4)).isoformat()
        self.assertEqual(0.0, policy.evaluate(old, now=now))


class DiscriminatedUnionTests(unittest.TestCase):
    def test_attribute_validates(self) -> None:
        adapter = pydantic.TypeAdapter(models.ScoringPolicy)
        policy = adapter.validate_python(
            {
                'name': 'Lang',
                'slug': 'lang',
                'category': 'attribute',
                'attribute_name': 'programming_language',
                'weight': 50,
                'value_score_map': {'py': 100},
            }
        )
        self.assertIsInstance(policy, models.AttributePolicy)

    def test_presence_validates(self) -> None:
        adapter = pydantic.TypeAdapter(models.ScoringPolicy)
        policy = adapter.validate_python(
            {
                'name': 'Has desc',
                'slug': 'has-desc',
                'category': 'presence',
                'attribute_name': 'description',
                'weight': 10,
            }
        )
        self.assertIsInstance(policy, models.PresencePolicy)

    def test_link_presence_validates(self) -> None:
        adapter = pydantic.TypeAdapter(models.ScoringPolicy)
        policy = adapter.validate_python(
            {
                'name': 'Has source link',
                'slug': 'has-source-link',
                'category': 'link_presence',
                'link_slug': 'source-code',
                'weight': 10,
            }
        )
        self.assertIsInstance(policy, models.LinkPresencePolicy)

    def test_age_validates(self) -> None:
        adapter = pydantic.TypeAdapter(models.ScoringPolicy)
        policy = adapter.validate_python(
            {
                'name': 'Last commit age',
                'slug': 'last-commit-age',
                'category': 'age',
                'attribute_name': 'last_commit_at',
                'weight': 10,
                'age_score_map': {'>30d': 0, '<=30d': 100},
            }
        )
        self.assertIsInstance(policy, models.AgePolicy)

    def test_analysis_result_validates(self) -> None:
        adapter = pydantic.TypeAdapter(models.ScoringPolicy)
        policy = adapter.validate_python(
            {
                'name': 'Logzio errors',
                'slug': 'logzio-errors',
                'category': 'analysis_result',
                'result_slug': 'logzio:error-rate',
                'weight': 25,
                'status_score_map': {'pass': 100, 'warn': 50, 'fail': 0},
            }
        )
        self.assertIsInstance(policy, models.AnalysisResultPolicy)


class AnalysisResultPolicyTests(unittest.TestCase):
    def _policy(self, **overrides: object) -> models.AnalysisResultPolicy:
        defaults: dict[str, object] = {
            'name': 'Logzio errors',
            'slug': 'logzio-errors',
            'result_slug': 'logzio:error-rate',
            'weight': 25,
        }
        defaults.update(overrides)
        return models.AnalysisResultPolicy(**defaults)  # type: ignore[arg-type]

    def test_default_status_map(self) -> None:
        policy = self._policy()
        self.assertEqual(100.0, policy.evaluate('pass'))
        self.assertEqual(50.0, policy.evaluate('warn'))
        self.assertEqual(0.0, policy.evaluate('fail'))

    def test_missing_value_is_none(self) -> None:
        self.assertIsNone(self._policy().evaluate(None))

    def test_unknown_status_is_none(self) -> None:
        self.assertIsNone(self._policy().evaluate('unknown'))

    def test_status_map_accepts_json_string(self) -> None:
        policy = models.AnalysisResultPolicy.model_validate(
            {
                'name': 'Logzio errors',
                'slug': 'logzio-errors',
                'result_slug': 'logzio:error-rate',
                'weight': 25,
                'status_score_map': '{"pass": 80, "warn": 40, "fail": 0}',
            }
        )
        self.assertEqual(80.0, policy.evaluate('pass'))

    def test_invalid_score_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            self._policy(status_score_map={'pass': 200, 'warn': 50, 'fail': 0})
