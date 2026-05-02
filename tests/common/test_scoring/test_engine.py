import unittest
from unittest import mock

from imbi_common import models
from imbi_common.scoring import engine
from imbi_common.scoring import models as scoring_models


def _project() -> models.Project:
    org = models.Organization(name='Org', slug='org')
    team = models.Team(name='Team', slug='team', organization=org)
    return models.Project(
        id='proj-id',
        name='P',
        slug='p',
        team=team,
    )


def _stub_policy() -> scoring_models.AttributePolicy:
    return scoring_models.AttributePolicy(
        name='p',
        slug='p',
        attribute_name='lang',
        weight=10,
        value_score_map={'py': 100},
    )


class ComputeScoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_policies_returns_none(self) -> None:
        project = _project()
        graph = mock.AsyncMock()
        graph.match.return_value = [project]
        with mock.patch(
            'imbi_common.scoring.engine.policies.applicable_policies',
            new=mock.AsyncMock(return_value=([], models.Project)),
        ):
            score, breakdown = await engine.compute_score(graph, 'proj-id')
        self.assertIsNone(score)
        self.assertEqual([], breakdown.attribute_contributions)

    async def test_floor_at_zero(self) -> None:
        project = _project()
        graph = mock.AsyncMock()
        graph.match.return_value = [project]
        with mock.patch(
            'imbi_common.scoring.engine.policies.applicable_policies',
            new=mock.AsyncMock(
                return_value=([_stub_policy()], models.Project)
            ),
        ):
            with mock.patch(
                'imbi_common.scoring.engine.attribute.compute_base_score',
                return_value=(-25.0, []),
            ):
                score, breakdown = await engine.compute_score(graph, 'proj-id')
        self.assertEqual(0.0, score)
        self.assertEqual(-25.0, breakdown.unfloored_total)
        self.assertEqual(-25.0, breakdown.base_score)

    async def test_breakdown_shape(self) -> None:
        project = _project()
        graph = mock.AsyncMock()
        graph.match.return_value = [project]
        contribs = [
            scoring_models.AttributeContribution(
                policy_slug='a',
                attribute_name='lang',
                value='py',
                mapped_score=100.0,
                weight=50,
                weighted_contribution=100.0,
            ),
            scoring_models.AttributeContribution(
                policy_slug='b',
                attribute_name='cov',
                value=None,
                mapped_score=0.0,
                weight=10,
                weighted_contribution=0.0,
            ),
        ]
        with mock.patch(
            'imbi_common.scoring.engine.policies.applicable_policies',
            new=mock.AsyncMock(
                return_value=([_stub_policy()], models.Project)
            ),
        ):
            with mock.patch(
                'imbi_common.scoring.engine.attribute.compute_base_score',
                return_value=(83.3, contribs),
            ):
                score, breakdown = await engine.compute_score(graph, 'proj-id')
        self.assertEqual(83.3, score)
        self.assertEqual(2, len(breakdown.attribute_contributions))
        self.assertIsNone(breakdown.attribute_contributions[1].value)

    async def test_missing_project_raises(self) -> None:
        graph = mock.AsyncMock()
        graph.match.return_value = []
        with self.assertRaises(ValueError):
            await engine.compute_score(graph, 'nope')

    async def test_extended_model_used_for_attribute_lookup(self) -> None:
        """Reload project with extended model so blueprint attrs are set."""

        class _Extended(models.Project):
            lang: str | None = None

        project = _project()
        extended = _Extended.model_construct(
            id='proj-id', name='P', slug='p', team=project.team, lang='py'
        )
        graph = mock.AsyncMock()
        graph.match.side_effect = [[project], [extended]]
        with mock.patch(
            'imbi_common.scoring.engine.policies.applicable_policies',
            new=mock.AsyncMock(return_value=([_stub_policy()], _Extended)),
        ):
            captured: list[object] = []
            orig = engine.attribute.compute_base_score

            def _capture(proj, pols):
                captured.append(proj)
                return orig(proj, pols)

            with mock.patch(
                'imbi_common.scoring.engine.attribute.compute_base_score',
                side_effect=_capture,
            ):
                await engine.compute_score(graph, 'proj-id')

        self.assertIsInstance(captured[0], _Extended)
        self.assertIs(_Extended, graph.match.call_args_list[1].args[0])
