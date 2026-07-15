import unittest
from unittest import mock

from imbi_common import models
from imbi_common.scoring import history


def _project(score: float | None = None) -> models.Project:
    team = models.Team.model_construct(name='T', slug='t')
    return models.Project.model_construct(
        id='proj-id', name='P', slug='p', team=team, score=score
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
        self.assertEqual('proj-id', row[0])
        self.assertEqual(80.0, row[2])
        self.assertEqual(70.0, row[3])
        self.assertEqual('attribute_change', row[4])
        query = graph.execute.call_args.args[0]
        self.assertTrue(query.rstrip().endswith('RETURN p'))
        self.assertEqual(['p'], graph.execute.call_args.kwargs['columns'])

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


class ClearScoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_executes_set_null(self) -> None:
        graph = mock.AsyncMock()
        await history.clear_score(graph, _project(75.0))
        graph.execute.assert_awaited_once()
        query = graph.execute.call_args.args[0]
        self.assertIn('p.score = null', query)
        self.assertIn('p.previous_score = {previous_score}', query)
        self.assertTrue(query.rstrip().endswith('RETURN p'))
        self.assertEqual(['p'], graph.execute.call_args.kwargs['columns'])
        params = graph.execute.call_args.args[1]
        self.assertEqual('proj-id', params['id'])
        self.assertEqual(75.0, params['previous_score'])
