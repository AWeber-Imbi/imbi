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
