import json
import typing
import unittest
import unittest.mock

import claude_agent_sdk as sdk

from imbi.harness import events, redact

MIB = 1024 * 1024


def event(kind: str, payload: dict[str, typing.Any]) -> events.Event:
    return {'event_id': 'e1', 'type': kind, 'payload': payload}


class SplitTestCase(unittest.TestCase):
    def join(self, parts: list[events.Event], field: str) -> str:
        return ''.join(part['payload'][field] for part in parts)

    def test_small_event_is_kept(self) -> None:
        small = event('tool.called', {'call_id': 'c', 'result': 'x'})
        self.assertEqual(events.split(small), [small])

    def test_three_mib_result_is_three_parts(self) -> None:
        result = 'x' * (3 * MIB)
        parts = events.split(
            event(
                'tool.called',
                {'call_id': 'c', 'tool': 'Bash', 'result': result},
            )
        )
        # A part is a little under 1 MiB, so 3 MiB needs a fourth part.
        self.assertEqual(len(parts), 4)
        self.assertEqual(self.join(parts, 'result'), result)
        for number, part in enumerate(parts, 1):
            payload = part['payload']
            self.assertLessEqual(events.size(payload), events.PAYLOAD_LIMIT)
            self.assertEqual(payload['call_id'], 'c')
            self.assertEqual(payload['part'], number)
            self.assertEqual(payload['parts'], len(parts))
            self.assertEqual(part['type'], 'tool.called')
        self.assertEqual(parts[0]['event_id'], 'e1')
        self.assertEqual(parts[0]['payload']['tool'], 'Bash')
        self.assertNotIn('tool', parts[1]['payload'])
        self.assertEqual(len({p['event_id'] for p in parts}), len(parts))

    def test_escaped_and_multibyte_text(self) -> None:
        body = ('"\\\n☃' * MIB)[: 2 * MIB]
        parts = events.split(event('turn', {'kind': 'text', 'body': body}))
        self.assertEqual(self.join(parts, 'body'), body)
        self.assertTrue(parts[0]['payload']['call_id'])
        for part in parts:
            self.assertLessEqual(
                events.size(part['payload']), events.PAYLOAD_LIMIT
            )

    def test_large_arguments_keep_a_preview(self) -> None:
        parts = events.split(
            event(
                'tool.called',
                {
                    'call_id': 'c',
                    'arguments': {'content': 'y' * (2 * MIB)},
                    'result': 'ok',
                },
            )
        )
        (part,) = parts
        self.assertTrue(part['payload']['arguments_truncated'])
        self.assertEqual(part['payload']['result'], 'ok')
        self.assertLessEqual(
            events.size(part['payload']), events.PAYLOAD_LIMIT
        )

    def test_other_types_are_not_split(self) -> None:
        todos = event('todos.updated', {'todos': ['x' * 1000]})
        self.assertEqual(events.split(todos), [todos])

    def test_other_types_over_the_small_limit_are_truncated(self) -> None:
        todos = event('todos.updated', {'todos': ['"x\u2603' * MIB]})
        with self.assertLogs('imbi.harness.events', 'WARNING') as logs:
            (part,) = events.split(todos)
        payload = part['payload']
        self.assertTrue(payload['truncated'])
        self.assertTrue(payload['preview'].startswith('{"todos"'))
        self.assertLessEqual(events.size(payload), events.SMALL_LIMIT)
        self.assertEqual(part['event_id'], 'e1')
        # The log has the type and size only, never the content.
        self.assertNotIn('\u2603', logs.output[0])

    def test_batches(self) -> None:
        big = [event('turn', {'body': 'x' * (MIB - 2048)}) for _ in range(6)]
        small = [event('turn', {'body': 'x'}) for _ in range(150)]
        sizes = [len(batch) for batch in events.batches(big + small)]
        # 4 large payloads fit in 4 MiB; then 100 events at most.
        self.assertEqual(sizes, [4, 100, 52])


class RecorderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.redactor = redact.Redactor()
        self.redactor.add('delivered-secret-value')
        self.recorder = events.Recorder(self.redactor)

    def test_turns_tools_and_todos(self) -> None:
        self.recorder.message(
            sdk.AssistantMessage(
                content=[
                    sdk.ThinkingBlock('I think', 'sig'),
                    sdk.TextBlock('Hello'),
                    sdk.ToolUseBlock('t1', 'Bash', {'command': 'ls'}),
                    sdk.ToolUseBlock(
                        't2',
                        'TodoWrite',
                        {
                            'todos': [
                                {'content': 'Fix', 'status': 'completed'},
                                {'content': 'Test', 'status': 'pending'},
                            ]
                        },
                    ),
                ],
                model='m',
                message_id='msg_1',
            )
        )
        self.recorder.message(
            sdk.UserMessage(
                content=[
                    sdk.ToolResultBlock(
                        't1',
                        [
                            {'type': 'text', 'text': 'delivered-secret-value'},
                            {'type': 'image', 'source': {}},
                        ],
                        False,
                    ),
                    sdk.ToolResultBlock('t2', None, None),
                ]
            )
        )
        found = self.recorder.take()
        self.assertEqual(self.recorder.take(), [])
        kinds = [(e['type'], e['payload'].get('kind')) for e in found]
        self.assertEqual(
            kinds,
            [
                ('turn', 'thinking'),
                ('todos.updated', None),
                ('turn', 'text'),
                ('tool.called', None),
                ('tool.called', None),
            ],
        )
        self.assertEqual(
            found[1]['payload']['todos'],
            [
                {'title': 'Fix', 'status': 'completed', 'done': True},
                {'title': 'Test', 'status': 'pending', 'done': False},
            ],
        )
        bash = found[3]['payload']
        self.assertEqual(bash['tool'], 'Bash')
        self.assertTrue(bash['mutating'])
        self.assertEqual(bash['arguments'], {'command': 'ls'})
        self.assertTrue(bash['result'].startswith('[REDACTED]\n'))
        self.assertGreaterEqual(bash['duration_ms'], 0)
        self.assertFalse(found[4]['payload']['mutating'])
        self.assertEqual(found[4]['payload']['result'], '')
        self.assertNotIn('delivered-secret-value', json.dumps(found))
        self.assertEqual({e['actor_kind'] for e in found}, {'agent'})

    def test_subagent_calls_have_a_parent(self) -> None:
        self.recorder.message(
            sdk.AssistantMessage(
                content=[sdk.ToolUseBlock('t9', 'Read', {})],
                model='m',
                parent_tool_use_id='t1',
            )
        )
        self.recorder.message(
            sdk.UserMessage(
                content=[sdk.ToolResultBlock('t9', 'text', True)],
                parent_tool_use_id='t1',
            )
        )
        (call,) = self.recorder.take()
        self.assertEqual(call['actor_kind'], 'subagent')
        self.assertEqual(call['payload']['parent_call_id'], 't1')
        self.assertTrue(call['payload']['is_error'])

    def test_unknown_result_and_other_messages(self) -> None:
        self.recorder.message(sdk.UserMessage(content='plain text'))
        self.recorder.message(sdk.SystemMessage('init', {}))
        self.recorder.message(
            sdk.UserMessage(content=[sdk.ToolResultBlock('zz', 'r', False)])
        )
        (call,) = self.recorder.take()
        self.assertEqual(call['payload']['tool'], 'unknown')


class RequeueTestCase(unittest.TestCase):
    def test_unsent_events_go_first(self) -> None:
        recorder = events.Recorder(redact.Redactor())
        new = event('turn', {'body': 'new'})
        recorder.pending = [new]
        old = [event('turn', {'body': 'old'})]
        recorder.requeue(old)
        self.assertEqual(recorder.take(), [*old, new])

    def test_bounded_with_a_warning(self) -> None:
        recorder = events.Recorder(redact.Redactor())
        big = [event('turn', {'body': 'x' * 1000}) for _ in range(10)]
        with (
            unittest.mock.patch.object(events, 'PENDING_LIMIT', 3500),
            self.assertLogs('imbi.harness.events', 'WARNING'),
        ):
            recorder.requeue(big)
        kept = recorder.take()
        self.assertEqual(kept[:3], big[-3:])
        (warning,) = kept[3:]
        self.assertEqual(warning['payload']['kind'], 'warning')
        self.assertIn('7 events', warning['payload']['body'])
