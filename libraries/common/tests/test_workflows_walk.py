import unittest

from imbi.common.workflows import graph, validation, walk


def _graph(
    edges: list[tuple[str, int, str]], joins: dict[str, str] | None = None
) -> graph.Graph:
    ids = sorted({e[0] for e in edges} | {e[2] for e in edges})
    return graph.Graph.model_validate(
        {
            'nodes': [
                {
                    'id': i,
                    'key': i,
                    'type': 'wait',
                    'title': i,
                    'position': {'x': 0, 'y': 0},
                    'join': (joins or {}).get(i, 'any'),
                }
                for i in ids
            ],
            'edges': [
                {'source': s, 'port': p, 'target': t} for s, p, t in edges
            ],
        }
    )


class AdvanceTestCase(unittest.TestCase):
    def test_all_join_waits_for_every_edge(self) -> None:
        g = _graph(
            [('t', 0, 'a'), ('t', 0, 'b'), ('a', 0, 'j'), ('b', 0, 'j')],
            {'j': 'all'},
        )
        status = {'t': 'succeeded', 'a': 'succeeded', 'b': 'running'}
        status['j'] = 'pending'
        ports: dict[str, int | None] = {'t': 0, 'a': 0}
        self.assertEqual(walk.advance(g, status, ports), ([], []))
        status['b'], ports['b'] = 'succeeded', 0
        self.assertEqual(walk.advance(g, status, ports), (['j'], []))

    def test_any_join_runs_at_first_edge(self) -> None:
        g = _graph(
            [('t', 0, 'a'), ('t', 0, 'b'), ('a', 0, 'j'), ('b', 0, 'j')]
        )
        status = {
            't': 'succeeded',
            'a': 'succeeded',
            'b': 'running',
            'j': 'pending',
        }
        ready, _ = walk.advance(g, status, {'t': 0, 'a': 0})
        self.assertEqual(ready, ['j'])

    def test_branch_not_taken_is_skipped_downstream(self) -> None:
        g = _graph(
            [
                ('t', 0, 'd'),
                ('d', 0, 'yes'),
                ('d', 1, 'no'),
                ('no', 0, 'after'),
                ('yes', 0, 'j'),
                ('after', 0, 'j'),
            ],
            {'j': 'all'},
        )
        status = dict.fromkeys(['yes', 'no', 'after', 'j'], 'pending')
        status |= {'t': 'succeeded', 'd': 'succeeded'}
        ports: dict[str, int | None] = {'t': 0, 'd': 0}
        self.assertEqual(
            walk.advance(g, status, ports), (['yes'], ['no', 'after'])
        )
        status['yes'], ports['yes'] = 'succeeded', 0
        self.assertEqual(walk.advance(g, status, ports), (['j'], []))

    def test_failure_without_port_makes_edges_inactive(self) -> None:
        g = _graph([('t', 0, 'a'), ('a', 0, 'b')])
        status = {'t': 'succeeded', 'a': 'failed', 'b': 'pending'}
        self.assertEqual(walk.advance(g, status, {'t': 0}), ([], ['b']))


class ConcurrencyKeyTestCase(unittest.TestCase):
    def test_modes(self) -> None:
        settings = graph.Settings()
        self.assertIsNone(validation.concurrency_key(settings, 'w', {}))
        settings = graph.Settings(concurrency_mode='one_at_a_time')
        self.assertEqual(validation.concurrency_key(settings, 'w', {}), 'w')
        settings = graph.Settings(
            concurrency_mode='one_per_key',
            concurrency_key='{{ trigger.service }}',
        )
        self.assertEqual(
            validation.concurrency_key(settings, 'w', {'service': 'api'}),
            'api',
        )
        with self.assertRaisesRegex(ValueError, 'concurrency_key_missing'):
            validation.concurrency_key(settings, 'w', {})

    def test_nested_field(self) -> None:
        settings = graph.Settings(
            concurrency_mode='one_per_key',
            concurrency_key='{{ trigger.payload.repository.name }}',
        )
        payload = {'payload': {'repository': {'name': 'imbi'}}}
        self.assertEqual(
            validation.concurrency_key(settings, 'w', payload), 'imbi'
        )
        for missing in (
            {},
            {'payload': []},
            {'payload': {'repository': 'imbi'}},
            {'payload': {'repository': {'name': ''}}},
            {'payload': {'repository': {'name': {'x': 1}}}},
        ):
            with (
                self.subTest(payload=missing),
                self.assertRaisesRegex(ValueError, 'concurrency_key_missing'),
            ):
                validation.concurrency_key(settings, 'w', missing)
