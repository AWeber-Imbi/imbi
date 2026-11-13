"""Tests for the ``script`` step type and its runner (ADR 0026)."""

import time
import typing
import unittest

import pydantic

from imbi.common.workflows import graph, registry, script_runner, validation
from imbi.common.workflows.registry import script

FIELDS: list[dict[str, typing.Any]] = [
    {'name': 'count', 'type': 'integer'},
    {'name': 'note', 'type': 'string', 'required': False},
]


def _params(**overrides: typing.Any) -> script.Params:
    return script.Params.model_validate(
        {'code': "{'count': 1}", 'output_fields': FIELDS} | overrides
    )


class ParamsTestCase(unittest.TestCase):
    def test_valid(self) -> None:
        params = _params(inputs={'runs': [1, 2]}, branches=['a', 'b'])
        self.assertEqual(params.inputs, {'runs': [1, 2]})

    def test_invalid(self) -> None:
        for overrides, message in (
            ({'inputs': {'Bad': 1}}, 'not a valid input name'),
            ({'inputs': {'lambda': 1}}, 'Python keyword'),
            ({'inputs': {f'i{n}': n for n in range(21)}}, 'at most 20'),
            ({'code': 'x' * (16 * 1024 + 1)}, 'larger than'),
            (
                {'output_fields': [{'name': 'branch', 'type': 'string'}]},
                'reserved',
            ),
            ({'output_fields': []}, 'at least 1'),
            ({'branches': ['a', 'a']}, 'unique'),
        ):
            with (
                self.subTest(message),
                self.assertRaisesRegex(pydantic.ValidationError, message),
            ):
                _params(**overrides)

    def test_ports(self) -> None:
        step = registry.STEP_TYPES['script']
        self.assertEqual(step.ports_for({}), [''])
        self.assertEqual(step.ports_for({'branches': ['a', 'b']}), ['a', 'b'])


def _validate(
    code: str, reference: str = '{{ calc.result.count }}'
) -> list[graph.ValidationIssue]:
    wf_graph = graph.Graph.model_validate(
        {
            'nodes': [
                {
                    'id': 'start',
                    'key': 'start',
                    'type': 'manual',
                    'title': 'Start',
                    'position': {'x': 0, 'y': 0},
                },
                {
                    'id': 'calc',
                    'key': 'calc',
                    'type': 'script',
                    'title': 'Calc',
                    'position': {'x': 0, 'y': 0},
                    'params': {
                        'inputs': {'payload': '{{ trigger.payload }}'},
                        'code': code,
                        'output_fields': FIELDS,
                    },
                },
                {
                    'id': 'use',
                    'key': 'use',
                    'type': 'script',
                    'title': 'Use',
                    'position': {'x': 0, 'y': 0},
                    'params': {
                        'inputs': {'v': reference},
                        'code': "{'count': v}",
                        'output_fields': FIELDS,
                    },
                },
            ],
            'edges': [
                {'source': 'start', 'port': 0, 'target': 'calc'},
                {'source': 'calc', 'port': 0, 'target': 'use'},
            ],
        }
    )
    return validation.validate(wf_graph, graph.Settings()).issues


class ValidationTestCase(unittest.TestCase):
    def test_code_is_not_a_template(self) -> None:
        # Jinja cannot parse this, and it names no step.
        code = "x = {'a': {1}}\nf'{{x}} {% raw' \n{'count': 1, 'n': nope}"
        self.assertEqual(_validate(code), [])

    def test_result_fields_are_checked(self) -> None:
        issues = _validate("{'count': 1}", '{{ calc.result.missing }}')
        self.assertEqual([i.code for i in issues], ['unknown_output_field'])


class ResultTestCase(unittest.TestCase):
    """The checks on the value of a script, with no sandbox."""

    def test_result(self) -> None:
        done = script_runner.result(_params(), {'count': 2}, 'hi\n')
        self.assertEqual(
            done.output,
            {
                'result': {'count': 2, 'note': None},
                'branch': None,
                'stdout': 'hi\n',
            },
        )
        self.assertEqual(done.port, 0)

    def test_conversion(self) -> None:
        import datetime
        import decimal

        params = _params(
            output_fields=[
                {'name': 'at', 'type': 'string'},
                {'name': 'n', 'type': 'number'},
                {'name': 'ids', 'type': 'array', 'items': 'integer'},
            ]
        )
        done = script_runner.result(
            params,
            {
                'at': datetime.datetime(
                    2026, 1, 1, 9, 30, tzinfo=datetime.UTC
                ),
                'n': decimal.Decimal('1.5'),
                'ids': (1, 2),
            },
            '',
        )
        self.assertEqual(
            done.output['result'],
            {'at': '2026-01-01T09:30:00+00:00', 'n': 1.5, 'ids': [1, 2]},
        )
        self.assertIsNone(done.output['stdout'])

    def test_branch(self) -> None:
        params = _params(branches=['low', 'high'])
        done = script_runner.result(params, {'count': 9, 'branch': 'high'}, '')
        self.assertEqual(done.port, 1)
        self.assertEqual(done.output['branch'], 'high')
        self.assertNotIn('branch', done.output['result'])

    def test_invalid(self) -> None:
        branched = _params(branches=['low', 'high'])
        for index, (params, value, code) in enumerate(
            (
                (_params(), 42, 'script_output_invalid'),
                (_params(), {'count': 'one'}, 'script_output_invalid'),
                (_params(), {'count': 1, 'extra': 1}, 'script_output_invalid'),
                (_params(), {'count': float('nan')}, 'script_output_invalid'),
                (_params(), {1: 'int key'}, 'script_output_invalid'),
                (_params(), {'count': object()}, 'script_output_invalid'),
                (
                    _params(),
                    {'count': 1, 'branch': 'low'},
                    'script_output_invalid',
                ),
                (branched, {'count': 1}, 'script_branch_invalid'),
                (
                    branched,
                    {'count': 1, 'branch': 'mid'},
                    'script_branch_invalid',
                ),
                (
                    _params(),
                    {'count': 1, 'note': 'x' * 70_000},
                    'script_output_too_large',
                ),
                (_params(), {'count': 2**64}, 'script_output_invalid'),
                (_params(), {'count': 10**5000}, 'script_output_invalid'),
            )
        ):
            with (
                self.subTest(index),
                self.assertRaises(script_runner.ScriptError) as raised,
            ):
                script_runner.result(params, value, '')
            self.assertEqual(raised.exception.code, code)
            self.assertFalse(raised.exception.retry)

    def test_too_deep(self) -> None:
        value: typing.Any = 1
        for _ in range(40):
            value = [value]
        with self.assertRaises(script_runner.ScriptError) as raised:
            script_runner.result(_params(), {'count': value}, '')
        self.assertIn('nests deeper', raised.exception.message)

    def test_shared_references_stop_early(self) -> None:
        # A billion items by reference: the walk must stop at the cap
        # without expanding them.
        shared: typing.Any = [0] * 1000
        for _ in range(2):
            shared = [shared] * 1000
        start = time.perf_counter()
        with self.assertRaises(script_runner.ScriptError) as raised:
            script_runner.result(_params(), {'count': shared}, '')
        self.assertEqual(raised.exception.code, 'script_output_too_large')
        self.assertLess(time.perf_counter() - start, 1.0)


class RunnerTestCase(unittest.IsolatedAsyncioTestCase):
    """Scripts in the real sandbox."""

    async def asyncSetUp(self) -> None:
        self.runner = await self.enterAsyncContext(
            script_runner.open_runner(
                processes=2, max_memory=16 * 1024 * 1024, max_seconds=1.0
            )
        )

    async def _run(
        self, code: str, **params: typing.Any
    ) -> script_runner.Result:
        return await self.runner.run(_params(code=code, **params))

    async def _error(
        self, code: str, **params: typing.Any
    ) -> script_runner.ScriptError:
        with self.assertRaises(script_runner.ScriptError) as raised:
            await self._run(code, **params)
        return raised.exception

    async def test_inputs_and_result(self) -> None:
        done = await self._run(
            "failed = [r for r in runs if r['status'] == 'failure']\n"
            "print(f'{{n}}={len(failed)}')\n"
            "{'count': len(failed)}",
            inputs={'runs': [{'status': 'failure'}, {'status': 'ok'}]},
        )
        self.assertEqual(
            done.output,
            {
                'result': {'count': 1, 'note': None},
                'branch': None,
                'stdout': '{n}=1\n',
            },
        )

    async def test_branch(self) -> None:
        done = await self._run(
            "{'count': n, 'branch': 'high' if n > 5 else 'low'}",
            inputs={'n': 9},
            branches=['low', 'high'],
        )
        self.assertEqual((done.port, done.output['branch']), (1, 'high'))

    async def test_errors(self) -> None:
        for code, expected in (
            ('def (', 'script_syntax_error'),
            ('while True:\n    pass', 'script_timeout'),
            ('x = [0] * 100_000_000', 'script_memory'),
            ("open('/etc/passwd').read()", 'script_error'),
            ('import socket', 'script_error'),
            ('x = 1', 'script_output_invalid'),
        ):
            with self.subTest(expected):
                error = await self._error(code)
                self.assertEqual(error.code, expected)
                self.assertFalse(error.retry)

    async def test_raise_keeps_the_message(self) -> None:
        error = await self._error("raise ValueError('bad input')")
        self.assertEqual(str(error), 'script_error: ValueError: bad input')

    async def test_max_seconds_lowers_the_limit(self) -> None:
        with self.assertRaises(script_runner.ScriptError) as raised:
            await self.runner.run(
                _params(code='while True:\n    pass'), max_seconds=0.1
            )
        self.assertEqual(raised.exception.code, 'script_timeout')

    async def test_no_state_crosses_runs(self) -> None:
        await self._run("secret = 1\n{'count': secret}")
        error = await self._error("{'count': secret}")
        self.assertIn('NameError', error.message)

    async def test_shared_reference_fan_out_is_refused(self) -> None:
        error = await self._error(
            'a = [0] * 1000\nb = [a] * 1000\nc = [b] * 1000\n{"count": c}'
        )
        self.assertEqual(error.code, 'script_output_too_large')
