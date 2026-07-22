import unittest
from unittest import mock

from imbi.common import models
from imbi.common.scoring import engine
from imbi.common.scoring import models as scoring_models


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
            'imbi.common.scoring.engine.policies.applicable_policies',
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
            'imbi.common.scoring.engine.policies.applicable_policies',
            new=mock.AsyncMock(
                return_value=([_stub_policy()], models.Project)
            ),
        ):
            with mock.patch(
                'imbi.common.scoring.engine.attribute.compute_base_score',
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
            'imbi.common.scoring.engine.policies.applicable_policies',
            new=mock.AsyncMock(
                return_value=([_stub_policy()], models.Project)
            ),
        ):
            with mock.patch(
                'imbi.common.scoring.engine.attribute.compute_base_score',
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

    async def test_deployment_policy_triggers_status_load(self) -> None:
        project = _project()
        graph = mock.AsyncMock()
        graph.match.side_effect = [[project], [project]]
        policy = scoring_models.DeploymentStatusPolicy(
            name='prod',
            slug='prod',
            environment_slug='production',
            weight=50,
        )
        with mock.patch(
            'imbi.common.scoring.engine.policies.applicable_policies',
            new=mock.AsyncMock(return_value=([policy], models.Project)),
        ):
            with mock.patch(
                'imbi.common.scoring.engine._load_deployment_statuses',
                new=mock.AsyncMock(return_value={'production': 'failed'}),
            ) as load_mock:
                score, _ = await engine.compute_score(graph, 'proj-id')
        load_mock.assert_awaited_once()
        self.assertEqual(0.0, score)

    async def test_condition_policy_triggers_neighbour_load(self) -> None:
        project = _project()
        graph = mock.AsyncMock()
        graph.match.side_effect = [[project], [project]]
        policy = scoring_models.ConditionPolicy(
            name='no deprecated deps',
            slug='no-deprecated-deps',
            weight=50,
            condition={
                'relationship': {
                    'quantifier': 'none',
                    'where': {
                        'attribute': 'deprecated',
                        'op': 'eq',
                        'value': True,
                    },
                }
            },
        )
        with mock.patch(
            'imbi.common.scoring.engine.policies.applicable_policies',
            new=mock.AsyncMock(return_value=([policy], models.Project)),
        ):
            with mock.patch(
                'imbi.common.scoring.engine._load_dependency_neighbours',
                new=mock.AsyncMock(return_value=[{'deprecated': True}]),
            ) as load_mock:
                score, _ = await engine.compute_score(graph, 'proj-id')
        load_mock.assert_awaited_once()
        self.assertEqual(0.0, score)

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
            'imbi.common.scoring.engine.policies.applicable_policies',
            new=mock.AsyncMock(return_value=([_stub_policy()], _Extended)),
        ):
            captured: list[object] = []
            orig = engine.attribute.compute_base_score

            def _capture(
                proj, pols, results=None, deployments=None, neighbours=None
            ):
                captured.append(proj)
                return orig(proj, pols, results, deployments, neighbours)

            with mock.patch(
                'imbi.common.scoring.engine.attribute.compute_base_score',
                side_effect=_capture,
            ):
                await engine.compute_score(graph, 'proj-id')

        self.assertIsInstance(captured[0], _Extended)
        self.assertIs(_Extended, graph.match.call_args_list[1].args[0])


class ParseDeploymentEventsTests(unittest.TestCase):
    def test_parses_json_string_list(self) -> None:
        raw = (
            '[{"timestamp": "2026-06-01T00:00:00+00:00", "status": "success"}]'
        )
        events = engine._parse_deployment_events(raw)
        self.assertEqual(1, len(events))
        self.assertEqual('success', events[0].status)

    def test_malformed_json_returns_empty(self) -> None:
        self.assertEqual([], engine._parse_deployment_events('not json'))

    def test_non_list_returns_empty(self) -> None:
        self.assertEqual([], engine._parse_deployment_events('{"a": 1}'))

    def test_none_returns_empty(self) -> None:
        self.assertEqual([], engine._parse_deployment_events(None))

    def test_skips_invalid_event(self) -> None:
        raw = (
            '[{"status": "success", "timestamp": "2026-06-01T00:00:00+00:00"},'
            ' {"nope": true}]'
        )
        events = engine._parse_deployment_events(raw)
        self.assertEqual(1, len(events))


class LoadDeploymentStatusesTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_per_environment(self) -> None:
        graph = mock.AsyncMock()
        graph.execute.return_value = [
            {
                'slug': 'production',
                'deployments': (
                    '[{"timestamp": "2026-06-01T00:00:00+00:00",'
                    ' "status": "success"}]'
                ),
            },
            {
                'slug': 'production',
                'deployments': (
                    '[{"timestamp": "2026-06-03T00:00:00+00:00",'
                    ' "status": "failed"}]'
                ),
            },
            {
                'slug': 'staging',
                'deployments': (
                    '[{"timestamp": "2026-06-02T00:00:00+00:00",'
                    ' "status": "success"}]'
                ),
            },
        ]
        result = await engine._load_deployment_statuses(graph, 'proj-id')
        self.assertEqual(
            {'production': 'failed', 'staging': 'success'}, result
        )

    async def test_no_events_omits_environment(self) -> None:
        graph = mock.AsyncMock()
        graph.execute.return_value = [
            {'slug': 'production', 'deployments': None},
        ]
        result = await engine._load_deployment_statuses(graph, 'proj-id')
        self.assertEqual({}, result)


class LoadDependencyNeighboursTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_property_maps(self) -> None:
        graph = mock.AsyncMock()
        graph.execute.return_value = [
            {'n': '{"id": "a", "deprecated": true}::vertex'},
            {'n': '{"id": "b", "deprecated": false}::vertex'},
        ]
        result = await engine._load_dependency_neighbours(graph, 'proj-id')
        self.assertEqual(
            [
                {'id': 'a', 'deprecated': True},
                {'id': 'b', 'deprecated': False},
            ],
            result,
        )

    async def test_skips_non_dict_rows(self) -> None:
        graph = mock.AsyncMock()
        graph.execute.return_value = [{'n': None}]
        result = await engine._load_dependency_neighbours(graph, 'proj-id')
        self.assertEqual([], result)
