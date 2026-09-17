import unittest
from unittest import mock

from imbi.common import iggy, models
from imbi.common.scoring import history


def _project(score: float | None = None) -> models.Project:
    team = models.Team.model_construct(name='T', slug='t')
    return models.Project.model_construct(
        id='proj-id', name='P', slug='p', team=team, score=score
    )


class RecordScoreChangeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.publish = self.enterContext(
            mock.patch.object(iggy, 'publish_rows', new=mock.AsyncMock())
        )

    async def test_skip_when_equal(self) -> None:
        graph = mock.AsyncMock()
        await history.record_score_change(
            graph, _project(50.0), 50.0, 50.0, 'attribute_change'
        )
        self.publish.assert_not_called()
        graph.execute.assert_not_called()

    async def test_publish_then_age_ordering(self) -> None:
        calls: list[str] = []
        self.publish.side_effect = lambda *a, **k: calls.append('iggy')
        graph = mock.AsyncMock()
        graph.execute.side_effect = lambda *a, **k: calls.append('age')
        await history.record_score_change(
            graph, _project(), 80.0, 70.0, 'attribute_change'
        )
        self.assertEqual(['iggy', 'age'], calls)
        self.publish.assert_awaited_once()
        args, _ = self.publish.call_args
        self.assertEqual(('score_history', 'scoring'), args[:2])
        row = args[2][0]
        self.assertEqual('proj-id', row['project_id'])
        self.assertEqual(80.0, row['score'])
        self.assertEqual(70.0, row['previous_score'])
        self.assertEqual('attribute_change', row['change_reason'])
        query = graph.execute.call_args.args[0]
        self.assertTrue(query.rstrip().endswith('RETURN p'))
        self.assertEqual(['p'], graph.execute.call_args.kwargs['columns'])

    async def test_age_failure_leaves_history_durable(self) -> None:
        graph = mock.AsyncMock()
        graph.execute.side_effect = RuntimeError('age down')
        with self.assertRaises(RuntimeError):
            await history.record_score_change(
                graph, _project(), 80.0, 70.0, 'attribute_change'
            )
        self.publish.assert_awaited_once()


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
