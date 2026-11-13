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
            {'payload': {'repository': {'name': '  \t'}}},
            {'payload': {'repository': {'name': {'x': 1}}}},
        ):
            with (
                self.subTest(payload=missing),
                self.assertRaisesRegex(ValueError, 'concurrency_key_missing'),
            ):
                validation.concurrency_key(settings, 'w', missing)

    def test_two_references(self) -> None:
        settings = graph.Settings(
            concurrency_mode='one_per_key',
            concurrency_key='{{ trigger.repo }}/{{ trigger.env }}',
        )
        self.assertEqual(
            validation.concurrency_key(
                settings, 'w', {'repo': 'imbi', 'env': 'testing'}
            ),
            'imbi/testing',
        )
        with self.assertRaisesRegex(ValueError, 'concurrency_key_missing'):
            validation.concurrency_key(settings, 'w', {'repo': 'imbi'})


#: A GitHub ``workflow_run`` delivery, as the gateway sends it.
WORKFLOW_RUN = {
    'payload': {
        'repository': {'full_name': 'octo/imbi'},
        'workflow_run': {'head_sha': 'abc123'},
    },
    'project': 'p-1',
}


class KeyTemplateTestCase(unittest.TestCase):
    def test_key_paths(self) -> None:
        self.assertEqual(
            validation.key_paths('{{ trigger.service }}'), [['service']]
        )
        self.assertEqual(
            validation.key_paths(
                '{{trigger.payload.repository.full_name}}:'
                '{{ trigger.payload.workflow_run.head_sha }}'
            ),
            [
                ['payload', 'repository', 'full_name'],
                ['payload', 'workflow_run', 'head_sha'],
            ],
        )
        for key in (
            None,
            '',
            'static',
            '{{ service }}',
            '{{ trigger.service | upper }}',
            '{{ trigger.a }}{% if x %}{% endif %}',
            '{{ trigger.a }} }}',
            '{{ trigger.a }}{# note #}',
        ):
            with self.subTest(key=key):
                self.assertIsNone(validation.key_paths(key))

    def test_dedupe_key(self) -> None:
        self.assertIsNone(
            validation.dedupe_key(graph.Settings(), WORKFLOW_RUN)
        )
        settings = graph.Settings(
            dedupe_key='{{ trigger.payload.repository.full_name }}:'
            '{{ trigger.payload.workflow_run.head_sha }}'
        )
        self.assertEqual(
            validation.dedupe_key(settings, WORKFLOW_RUN), 'octo/imbi:abc123'
        )
        # A run that lacks a value of the key is never a duplicate.
        self.assertIsNone(
            validation.dedupe_key(
                settings, {'payload': {'repository': {'full_name': 'x'}}}
            )
        )
        self.assertEqual(
            validation.dedupe_key(
                graph.Settings(dedupe_key='{{ trigger.n }}'), {'n': 7}
            ),
            '7',
        )

    def test_dedupe_key_blank_value(self) -> None:
        settings = graph.Settings(dedupe_key='{{ trigger.n }}')
        self.assertIsNone(validation.dedupe_key(settings, {'n': '   '}))
        for value, key in ((0, '0'), (False, 'False'), (' a ', ' a ')):
            with self.subTest(value=value):
                self.assertEqual(
                    validation.dedupe_key(settings, {'n': value}), key
                )

    def test_dedupe_key_too_long(self) -> None:
        settings = graph.Settings(dedupe_key='{{ trigger.n }}')
        limit = validation.MAX_DEDUPE_KEY_BYTES
        self.assertEqual(
            validation.dedupe_key(settings, {'n': 'a' * limit}), 'a' * limit
        )
        # A longer key would not fit the dedupe index: never skipped.
        self.assertIsNone(
            validation.dedupe_key(settings, {'n': 'a' * (limit + 1)})
        )
        # The limit is in bytes, not characters.
        self.assertIsNone(
            validation.dedupe_key(settings, {'n': 'é' * (limit // 2 + 1)})
        )
