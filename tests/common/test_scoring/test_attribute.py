import datetime
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

    def test_presence_policy_present(self) -> None:
        policy = models.PresencePolicy(
            name='desc',
            slug='desc',
            attribute_name='description',
            weight=20,
        )
        score, contribs = attribute.compute_base_score(
            types.SimpleNamespace(description='a project'),
            [policy],
        )
        self.assertEqual(100.0, score)
        self.assertEqual('presence', contribs[0].category)
        self.assertEqual('description', contribs[0].attribute_name)

    def test_presence_policy_missing(self) -> None:
        policy = models.PresencePolicy(
            name='desc',
            slug='desc',
            attribute_name='description',
            weight=20,
        )
        score, contribs = attribute.compute_base_score(
            types.SimpleNamespace(description=''),
            [policy],
        )
        self.assertEqual(0.0, score)
        self.assertEqual('', contribs[0].value)

    def test_link_presence_present(self) -> None:
        policy = models.LinkPresencePolicy(
            name='source link',
            slug='source-link',
            link_slug='source-code',
            weight=20,
        )
        score, contribs = attribute.compute_base_score(
            types.SimpleNamespace(
                links={'source-code': 'https://example.com/repo'}
            ),
            [policy],
        )
        self.assertEqual(100.0, score)
        self.assertEqual('link_presence', contribs[0].category)
        self.assertEqual('source-code', contribs[0].link_slug)
        self.assertEqual('https://example.com/repo', contribs[0].value)

    def test_link_presence_missing(self) -> None:
        policy = models.LinkPresencePolicy(
            name='source link',
            slug='source-link',
            link_slug='source-code',
            weight=20,
        )
        score, _ = attribute.compute_base_score(
            types.SimpleNamespace(links={}),
            [policy],
        )
        self.assertEqual(0.0, score)

    def test_link_presence_links_as_json_string(self) -> None:
        """model_construct fallback leaves links as a JSON string; scoring
        must still detect the link rather than treating it as absent."""
        policy = models.LinkPresencePolicy(
            name='grafana',
            slug='grafana-dashboard',
            link_slug='grafana-dashboard',
            weight=10,
        )
        score, contribs = attribute.compute_base_score(
            types.SimpleNamespace(
                links='{"grafana-dashboard": "https://grafana.example/d/abc"}'
            ),
            [policy],
        )
        self.assertEqual(100.0, score)
        self.assertEqual('grafana-dashboard', contribs[0].link_slug)

    def test_age_policy_fresh(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        recent = (now - datetime.timedelta(days=1)).isoformat()
        policy = models.AgePolicy(
            name='last commit',
            slug='last-commit',
            attribute_name='last_commit_at',
            weight=10,
            age_score_map={'>30d': 0, '<=30d': 100},
        )
        score, contribs = attribute.compute_base_score(
            types.SimpleNamespace(last_commit_at=recent),
            [policy],
        )
        self.assertEqual(100.0, score)
        self.assertEqual('age', contribs[0].category)

    def test_age_policy_missing_contributes_zero(self) -> None:
        policy = models.AgePolicy(
            name='last commit',
            slug='last-commit',
            attribute_name='last_commit_at',
            weight=10,
            age_score_map={'>30d': 0, '<=30d': 100},
        )
        score, _ = attribute.compute_base_score(
            types.SimpleNamespace(last_commit_at=None),
            [policy],
        )
        self.assertEqual(0.0, score)

    def test_mixed_categories_weighted_average(self) -> None:
        policies: list[attribute.Policy] = [
            models.AttributePolicy(
                name='lang',
                slug='lang',
                attribute_name='lang',
                weight=50,
                value_score_map={'py': 100},
            ),
            models.PresencePolicy(
                name='desc',
                slug='desc',
                attribute_name='description',
                weight=10,
            ),
            models.LinkPresencePolicy(
                name='source',
                slug='source',
                link_slug='source-code',
                weight=20,
            ),
        ]
        proj = types.SimpleNamespace(
            lang='py',
            description='',  # missing → 0
            links={'source-code': 'https://example.com'},
        )
        score, contribs = attribute.compute_base_score(proj, policies)
        # (100*50 + 0*10 + 100*20) / 80 = 87.5
        self.assertAlmostEqual(87.5, score, places=3)
        self.assertEqual(3, len(contribs))

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
