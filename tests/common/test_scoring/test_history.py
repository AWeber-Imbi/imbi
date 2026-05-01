import unittest
from unittest import mock

from imbi_common import models
from imbi_common.scoring import history


def _project(score: float | None = None) -> models.Project:
    org = models.Organization(name='Org', slug='org')
    team = models.Team(name='Team', slug='team', organization=org)
    pt = models.ProjectType(name='API', slug='api', organization=org)
    return models.Project(
        id='proj-id',
        name='P',
        slug='p',
        team=team,
        project_types=[pt],
        score=score,
    )


class RecordScoreChangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_skip_when_equal(self) -> None:
        clickhouse = mock.AsyncMock()
        graph = mock.AsyncMock()
        await history.record_score_change(
            clickhouse, graph, _project(50.0), 50.0, 50.0, 'attribute_change'
        )
        clickhouse.insert.assert_not_called()
        graph.execute.assert_not_called()

    async def test_ch_then_age_ordering(self) -> None:
        calls: list[str] = []
        clickhouse = mock.AsyncMock()
        clickhouse.insert.side_effect = lambda *a, **k: calls.append('ch')
        graph = mock.AsyncMock()
        graph.execute.side_effect = lambda *a, **k: calls.append('age')
        await history.record_score_change(
            clickhouse, graph, _project(), 80.0, 70.0, 'attribute_change'
        )
        self.assertEqual(['ch', 'age'], calls)
        clickhouse.insert.assert_awaited_once()
        args, _ = clickhouse.insert.call_args
        self.assertEqual('score_history', args[0])
        row = args[1][0]
        self.assertEqual('org', row[0])
        self.assertEqual('team', row[1])
        self.assertEqual('api', row[2])
        self.assertEqual('proj-id', row[3])
        self.assertEqual('p', row[4])
        self.assertEqual(80.0, row[6])
        self.assertEqual(70.0, row[7])
        self.assertEqual('attribute_change', row[8])

    async def test_age_failure_leaves_history_durable(self) -> None:
        clickhouse = mock.AsyncMock()
        graph = mock.AsyncMock()
        graph.execute.side_effect = RuntimeError('age down')
        with self.assertRaises(RuntimeError):
            await history.record_score_change(
                clickhouse,
                graph,
                _project(),
                80.0,
                70.0,
                'attribute_change',
            )
        clickhouse.insert.assert_awaited_once()
