"""Tests for the workflow graph validation and step type registry."""

import time
import typing
import unittest

from imbi.common.workflows import graph, registry, validation


def _node(
    node_id: str, step: str, params: dict[str, typing.Any] | None = None
) -> dict[str, typing.Any]:
    return {
        'id': node_id,
        'key': node_id,
        'type': step,
        'title': node_id.title(),
        'position': {'x': 0, 'y': 0},
        'params': params or {},
    }


DEPLOY = {'project_id': 'p1', 'environment': 'staging', 'version': '1.0'}
DECIDE = {'model_id': 'm1', 'prompt': 'Ship it?', 'branches': ['yes', 'no']}


def _check(
    nodes: list[dict[str, typing.Any]],
    edges: list[tuple[str, int, str]],
    settings: dict[str, typing.Any] | None = None,
) -> list[graph.ValidationIssue]:
    wf_graph = graph.Graph.model_validate(
        {
            'nodes': nodes,
            'edges': [
                {'source': s, 'port': p, 'target': t} for s, p, t in edges
            ],
        }
    )
    return validation.validate(
        wf_graph, graph.Settings.model_validate(settings or {})
    ).issues


def _codes(issues: list[graph.ValidationIssue]) -> set[str]:
    return {i.code for i in issues}


class ValidationTestCase(unittest.TestCase):
    def test_valid_graph(self) -> None:
        issues = _check(
            [
                _node('start', 'manual'),
                _node('decide', 'model_decision', DECIDE),
                _node('ship', 'deploy', DEPLOY),
                _node('pause', 'wait', {'duration': '10m'}),
            ],
            [
                ('start', 0, 'decide'),
                ('decide', 0, 'ship'),
                ('decide', 1, 'pause'),
            ],
        )
        self.assertEqual(issues, [])

    def test_unknown_type(self) -> None:
        issues = _check(
            [_node('start', 'manual'), _node('x', 'slack')],
            [('start', 0, 'x')],
        )
        self.assertIn('unknown_type', _codes(issues))

    def test_cycle(self) -> None:
        issues = _check(
            [
                _node('start', 'manual'),
                _node('a', 'wait', {'duration': '1m'}),
                _node('b', 'wait', {'duration': '1m'}),
            ],
            [('start', 0, 'a'), ('a', 0, 'b'), ('b', 0, 'a')],
        )
        self.assertIn('cycle', _codes(issues))

    def test_dangling_reference(self) -> None:
        issues = _check(
            [
                _node('start', 'manual'),
                _node('ship', 'deploy', {**DEPLOY, 'version': '{{ nope.v }}'}),
            ],
            [('start', 0, 'ship')],
        )
        self.assertIn('unknown_reference', _codes(issues))

    def test_reference_to_downstream_node(self) -> None:
        issues = _check(
            [
                _node('start', 'manual'),
                _node('ship', 'deploy', {**DEPLOY, 'version': '{{ wait1 }}'}),
                _node('wait1', 'wait', {'duration': '1m'}),
            ],
            [('start', 0, 'ship'), ('ship', 0, 'wait1')],
        )
        self.assertIn('unknown_reference', _codes(issues))

    def test_upstream_and_trigger_references(self) -> None:
        issues = _check(
            [
                _node('start', 'manual'),
                _node('decide', 'model_decision', DECIDE),
                _node(
                    'ship',
                    'deploy',
                    {
                        **DEPLOY,
                        'version': '{{ trigger.version }}',
                        'environment': '{{ decide.choice | upper }}',
                    },
                ),
            ],
            [('start', 0, 'decide'), ('decide', 0, 'ship')],
        )
        self.assertEqual(issues, [])

    def test_edge_into_trigger(self) -> None:
        issues = _check(
            [_node('start', 'manual'), _node('other', 'manual')],
            [('start', 0, 'other')],
        )
        self.assertIn('edge_into_trigger', _codes(issues))

    def test_no_trigger_and_unreachable(self) -> None:
        issues = _check([_node('a', 'wait', {'duration': '1m'})], [])
        self.assertEqual(_codes(issues), {'no_trigger', 'unreachable'})

    def test_port_out_of_range(self) -> None:
        issues = _check(
            [_node('start', 'manual'), _node('a', 'wait', {'duration': '1m'})],
            [('start', 1, 'a')],
        )
        self.assertIn('port_out_of_range', _codes(issues))

    def test_duplicate_key(self) -> None:
        second = _node('b', 'wait', {'duration': '1m'})
        second['key'] = 'a'
        nodes = [
            _node('start', 'manual'),
            _node('a', 'wait', {'duration': '1m'}),
            second,
        ]
        issues = _check(nodes, [('start', 0, 'a'), ('start', 0, 'b')])
        self.assertIn('duplicate_key', _codes(issues))

    def test_missing_param_is_warning_wrong_type_is_error(self) -> None:
        issues = _check(
            [
                _node('start', 'manual'),
                _node(
                    'decide',
                    'model_decision',
                    {**DECIDE, 'min_confidence': 'high', 'prompt': None},
                ),
                _node('ship', 'deploy', {}),
            ],
            [('start', 0, 'decide'), ('decide', 0, 'ship')],
        )
        by_code = {(i.code, i.severity, i.node_id) for i in issues}
        self.assertIn(('missing_param', 'warning', 'ship'), by_code)
        self.assertIn(('invalid_param', 'error', 'decide'), by_code)

    def test_duplicate_branches(self) -> None:
        issues = _check(
            [
                _node('start', 'manual'),
                _node(
                    'decide',
                    'model_decision',
                    {**DECIDE, 'branches': ['y', 'y']},
                ),
            ],
            [('start', 0, 'decide')],
        )
        self.assertEqual(
            [(i.code, i.node_id) for i in issues],
            [('invalid_param', 'decide')],
        )

    def test_any_join_overlap(self) -> None:
        nodes = [
            _node('start', 'manual'),
            _node('a', 'wait', {'duration': '1m'}),
            _node('b', 'wait', {'duration': '1m'}),
            _node('join', 'wait', {'duration': '1m'}),
        ]
        issues = _check(
            nodes,
            [
                ('start', 0, 'a'),
                ('start', 0, 'b'),
                ('a', 0, 'join'),
                ('b', 0, 'join'),
            ],
        )
        self.assertIn('any_join_overlap', _codes(issues))

    def test_any_join_on_exclusive_branches(self) -> None:
        issues = _check(
            [
                _node('start', 'manual'),
                _node('decide', 'model_decision', DECIDE),
                _node('a', 'wait', {'duration': '1m'}),
                _node('b', 'deploy', DEPLOY),
                _node('page', 'wait', {'duration': '1m'}),
            ],
            [
                ('start', 0, 'decide'),
                ('decide', 0, 'a'),
                ('decide', 1, 'b'),
                ('a', 0, 'page'),
                ('b', 1, 'page'),
            ],
        )
        self.assertEqual(issues, [])

    def test_one_per_key(self) -> None:
        settings = {
            'concurrency_mode': 'one_per_key',
            'concurrency_key': '{{ trigger.service }}',
        }
        nodes = [
            _node('start', 'manual'),
            _node('cron', 'schedule', {'cron': '0 * * * *'}),
            _node('a', 'wait', {'duration': '1m'}),
        ]
        edges = [('start', 0, 'a'), ('cron', 0, 'a')]
        codes = _codes(_check(nodes, edges, settings))
        self.assertIn('concurrency_key_input_missing', codes)
        self.assertIn('concurrency_key_with_schedule', codes)
        nodes = [
            _node('start', 'manual', {'inputs': [{'name': 'service'}]}),
            _node('a', 'wait', {'duration': '1m'}),
        ]
        self.assertEqual(_check(nodes, [('start', 0, 'a')], settings), [])

    def test_one_per_key_on_a_nested_webhook_field(self) -> None:
        settings = {
            'concurrency_mode': 'one_per_key',
            'concurrency_key': '{{ trigger.payload.repository.name }}',
        }
        hook = _node('hook', 'webhook', {'webhook_id': 'wh-1'})
        wait = _node('a', 'wait', {'duration': '1m'})
        self.assertEqual(
            _check([hook, wait], [('hook', 0, 'a')], settings), []
        )
        # A manual input is a scalar: it has no nested field.
        start = _node('start', 'manual', {'inputs': [{'name': 'payload'}]})
        codes = _codes(
            _check(
                [hook, start, wait],
                [('hook', 0, 'a'), ('start', 0, 'a')],
                settings,
            )
        )
        self.assertIn('concurrency_key_input_missing', codes)

    def test_size_limit(self) -> None:
        nodes = [_node('start', 'manual')] + [
            _node(f'n{i}', 'wait', {'duration': '1m'})
            for i in range(validation.MAX_NODES)
        ]
        self.assertEqual(_codes(_check(nodes, [])), {'too_many_nodes'})

    def test_duplicate_edge(self) -> None:
        issues = _check(
            [_node('start', 'manual'), _node('a', 'wait', {'duration': '1m'})],
            [('start', 0, 'a'), ('start', 0, 'a')],
        )
        self.assertEqual(
            [(i.code, i.edge_index) for i in issues], [('duplicate_edge', 1)]
        )

    def test_wide_any_join_at_limits_is_fast(self) -> None:
        # A chain of decisions, each with its second port into one join:
        # 100 nodes, 197 edges, and branch sets of up to 98 entries.
        count = validation.MAX_NODES - 2
        nodes = [
            _node('start', 'manual'),
            _node('join', 'wait', {'duration': '1m'}),
        ]
        nodes += [
            _node(f'd{i}', 'model_decision', DECIDE) for i in range(count)
        ]
        edges = [('start', 0, 'd0')]
        edges += [(f'd{i}', 0, f'd{i + 1}') for i in range(count - 1)]
        edges += [(f'd{i}', 1, 'join') for i in range(count)]
        edges.append((f'd{count - 1}', 0, 'join'))
        started = time.monotonic()
        issues = _check(nodes, edges)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(issues, [])


class RegistryTestCase(unittest.TestCase):
    def test_describe(self) -> None:
        described = {
            name: step.describe() for name, step in registry.STEP_TYPES.items()
        }
        self.assertEqual(
            set(described),
            {
                'manual',
                'schedule',
                'webhook',
                'wait',
                'model_decision',
                'email',
                'deploy',
                'rollback',
                'agent',
            },
        )
        self.assertIsNone(described['model_decision']['ports'])
        self.assertEqual(described['deploy']['ports'], ['Succeeded', 'Failed'])
        self.assertEqual(described['wait']['ports'], [''])
        self.assertIn('properties', described['email']['params_schema'])

    def test_required_permissions(self) -> None:
        for name in ('deploy', 'rollback'):
            self.assertEqual(
                registry.STEP_TYPES[name].required_permissions({}),
                {'project:deployment:write'},
            )
        self.assertEqual(
            registry.STEP_TYPES['wait'].required_permissions({}), set()
        )
        self.assertEqual(
            registry.STEP_TYPES['agent'].required_permissions({}),
            {'agent_task:create'},
        )

    def test_agent_budget_follows_the_task_budget(self) -> None:
        # The limits of AgentTaskCreate.budget: 14 digits, 6 places.
        for budget, codes in (
            (0.5, set()),
            ('12345678.123456', set()),
            (0.0000001, {'invalid_param'}),
            ('123456789.5', {'invalid_param'}),
            (-1, {'invalid_param'}),
        ):
            issues = _check(
                [
                    _node('start', 'manual'),
                    _node(
                        'ask',
                        'agent',
                        {
                            'agent_id': 'a1',
                            'instruction': 'Go.',
                            'budget': budget,
                        },
                    ),
                ],
                [('start', 0, 'ask')],
            )
            self.assertEqual(_codes(issues), codes, budget)

    def test_sample_outputs_match_output_schema(self) -> None:
        for step in registry.STEP_TYPES.values():
            step.output.model_validate(step.sample_output)
