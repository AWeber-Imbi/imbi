import types
import unittest

from imbi_common.scoring import attribute, models


def _policy(
    *,
    slug: str,
    attribute_name: str,
    weight: int,
    value_score_map: dict[str, int] | None = None,
    range_score_map: dict[str, int] | None = None,
) -> models.AttributePolicy:
    return models.AttributePolicy(
        name=slug,
        slug=slug,
        attribute_name=attribute_name,
        weight=weight,
        value_score_map=value_score_map,
        range_score_map=range_score_map,
    )


class ComputeBaseScoreTests(unittest.TestCase):
    def test_no_policies_returns_100(self) -> None:
        score, contribs = attribute.compute_base_score(
            types.SimpleNamespace(programming_language='Python 3.12'),
            [],
        )
        self.assertEqual(100.0, score)
        self.assertEqual([], contribs)

    def test_weighted_average(self) -> None:
        policies = [
            _policy(
                slug='a',
                attribute_name='lang',
                weight=50,
                value_score_map={'py': 100},
            ),
            _policy(
                slug='b',
                attribute_name='cov',
                weight=10,
                range_score_map={'0..100': 50},
            ),
        ]
        proj = types.SimpleNamespace(lang='py', cov=42)
        score, contribs = attribute.compute_base_score(proj, policies)
        # (100*50 + 50*10) / 60 = 91.666...
        self.assertAlmostEqual(91.6666, score, places=3)
        self.assertEqual(2, len(contribs))

    def test_missing_value_contributes_zero(self) -> None:
        policy = _policy(
            slug='a',
            attribute_name='lang',
            weight=10,
            value_score_map={'py': 100},
        )
        proj = types.SimpleNamespace(lang=None)
        score, contribs = attribute.compute_base_score(proj, [policy])
        self.assertEqual(0.0, score)
        self.assertEqual(0.0, contribs[0].mapped_score)
        self.assertIsNone(contribs[0].value)

    def test_unmapped_value_contributes_zero(self) -> None:
        policy = _policy(
            slug='a',
            attribute_name='lang',
            weight=10,
            value_score_map={'py': 100},
        )
        proj = types.SimpleNamespace(lang='ruby')
        score, contribs = attribute.compute_base_score(proj, [policy])
        self.assertEqual(0.0, score)
        self.assertEqual('ruby', contribs[0].value)
        self.assertEqual(0.0, contribs[0].mapped_score)

    def test_multiple_policies_same_field(self) -> None:
        policies = [
            _policy(
                slug='global',
                attribute_name='lang',
                weight=10,
                value_score_map={'py': 100},
            ),
            _policy(
                slug='team',
                attribute_name='lang',
                weight=40,
                value_score_map={'py': 50},
            ),
        ]
        proj = types.SimpleNamespace(lang='py')
        score, contribs = attribute.compute_base_score(proj, policies)
        # (100*10 + 50*40) / 50 = 60
        self.assertEqual(60.0, score)
        self.assertEqual(2, len(contribs))

    def test_dict_project(self) -> None:
        policy = _policy(
            slug='a',
            attribute_name='lang',
            weight=10,
            value_score_map={'py': 100},
        )
        score, _ = attribute.compute_base_score({'lang': 'py'}, [policy])
        self.assertEqual(100.0, score)

    def test_zero_total_weight(self) -> None:
        policy = _policy(
            slug='a',
            attribute_name='lang',
            weight=0,
            value_score_map={'py': 100},
        )
        score, contribs = attribute.compute_base_score(
            types.SimpleNamespace(lang='py'),
            [policy],
        )
        self.assertEqual(0.0, score)
        self.assertEqual(0.0, contribs[0].weighted_contribution)
