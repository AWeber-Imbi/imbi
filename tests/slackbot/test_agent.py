from unittest import mock

import anthropic
import httpx

from imbi_slackbot import agent
from tests import helpers


class Block:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class Response:
    def __init__(self, content: list, stop_reason: str) -> None:
        self.content = content
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeClient:
    def __init__(self, responses: list) -> None:
        self.messages = FakeMessages(responses)


class FakeManager:
    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.executed: list = []

    async def execute_tool(self, name, tool_input, token):
        self.executed.append((name, tool_input, token))
        return self._results.pop(0)


def _text(text: str) -> Block:
    return Block(type='text', text=text)


def _tool(id_: str, name: str, tool_input: dict) -> Block:
    return Block(type='tool_use', id=id_, name=name, input=tool_input)


class CollectTests(helpers.TestCase):
    def test_collect_splits_blocks(self) -> None:
        text, blocks, tools = agent._collect(
            [_text('hi'), _tool('t1', 'list', {'a': 1})]
        )
        self.assertEqual('hi', text)
        self.assertEqual(2, len(blocks))
        self.assertEqual(1, len(tools))
        self.assertEqual('list', tools[0]['name'])

    def test_tool_result_block_flags_error(self) -> None:
        block = agent._tool_result_block('t1', 'oops', is_error=True)
        self.assertTrue(block['is_error'])
        ok = agent._tool_result_block('t1', 'fine', is_error=False)
        self.assertNotIn('is_error', ok)


class RunTurnTests(helpers.TestCase):
    def _patch(self, client: FakeClient, manager: FakeManager):
        return (
            mock.patch.object(agent.client, 'get_client', return_value=client),
            mock.patch.object(agent.mcp, 'get_manager', return_value=manager),
        )

    async def _run(self, client, manager, **overrides):
        patches = self._patch(client, manager)
        for patch in patches:
            patch.start()
        try:
            kwargs = {
                'messages': [{'role': 'user', 'content': 'hello'}],
                'system': 'sys',
                'tools': None,
                'auth_token': 'tok',
                'model': 'm',
                'max_tokens': 100,
                'max_rounds': 5,
            }
            kwargs.update(overrides)
            return await agent.run_turn(**kwargs)
        finally:
            for patch in patches:
                patch.stop()

    async def test_simple_text(self) -> None:
        client = FakeClient([Response([_text('Hello there')], 'end_turn')])
        answer = await self._run(client, FakeManager([]))
        self.assertEqual('Hello there', answer)

    async def test_tool_round(self) -> None:
        client = FakeClient(
            [
                Response(
                    [_text('let me check'), _tool('t1', 'list', {})],
                    'tool_use',
                ),
                Response([_text('Found 3 projects')], 'end_turn'),
            ]
        )
        manager = FakeManager([('{"count": 3}', False)])
        messages = [{'role': 'user', 'content': 'how many?'}]
        patches = self._patch(client, manager)
        for patch in patches:
            patch.start()
        try:
            answer = await agent.run_turn(
                messages=messages,
                system='sys',
                tools=[{'name': 'list'}],
                auth_token='tok',
                model='m',
                max_tokens=100,
                max_rounds=5,
            )
        finally:
            for patch in patches:
                patch.stop()
        self.assertIn('Found 3 projects', answer)
        self.assertEqual('tok', manager.executed[0][2])
        # The tool round was processed: the working message list grew with
        # the assistant tool_use + user tool_result turns.
        working = client.messages.calls[-1]['messages']
        self.assertEqual('assistant', working[1]['role'])
        self.assertEqual('user', working[2]['role'])
        # run_turn must not mutate the caller-supplied messages list.
        self.assertEqual(1, len(messages))

    async def test_max_rounds(self) -> None:
        client = FakeClient(
            [
                Response([_tool('t1', 'list', {})], 'tool_use'),
                Response([_tool('t2', 'list', {})], 'tool_use'),
            ]
        )
        manager = FakeManager([('a', False), ('b', False)])
        answer = await self._run(client, manager, max_rounds=2)
        self.assertIn('tool-call limit', answer)

    async def test_api_error(self) -> None:
        err = anthropic.APIError(
            'boom', request=httpx.Request('POST', 'http://x'), body=None
        )
        client = FakeClient([err])
        answer = await self._run(client, FakeManager([]))
        self.assertIn('error', answer.lower())

    async def _run_tools(self, client, manager, **overrides):
        kwargs = {
            'messages': [{'role': 'user', 'content': 'q'}],
            'system': 'sys',
            'tools': [{'name': 'list'}],
            'auth_token': 'tok',
            'model': 'm',
            'max_tokens': 100,
            'max_rounds': 5,
        }
        kwargs.update(overrides)
        patches = self._patch(client, manager)
        for patch in patches:
            patch.start()
        try:
            return await agent.run_turn(**kwargs)
        finally:
            for patch in patches:
                patch.stop()

    async def test_on_status_called_with_tools(self) -> None:
        client = FakeClient(
            [
                Response([_tool('t1', 'list', {})], 'tool_use'),
                Response([_text('done')], 'end_turn'),
            ]
        )
        statuses: list[str] = []

        async def on_status(text: str) -> None:
            statuses.append(text)

        await self._run_tools(
            client, FakeManager([('ok', False)]), on_status=on_status
        )
        self.assertEqual(['Looking up data with `list`…'], statuses)

    async def test_large_tool_result_replaced(self) -> None:
        client = FakeClient(
            [
                Response([_tool('t1', 'list', {})], 'tool_use'),
                Response([_text('done')], 'end_turn'),
            ]
        )
        await self._run_tools(
            client,
            FakeManager([('x' * 50, False)]),
            max_tool_result_chars=10,
        )
        working = client.messages.calls[-1]['messages']
        tool_result = working[2]['content'][0]
        self.assertTrue(tool_result['is_error'])
        self.assertIn('too much data', tool_result['content'])


class MapErrorTests(helpers.TestCase):
    @staticmethod
    def _resp(status: int) -> httpx.Response:
        return httpx.Response(
            status, request=httpx.Request('POST', 'http://x')
        )

    def test_rate_limit(self) -> None:
        err = anthropic.RateLimitError(
            'r', response=self._resp(429), body=None
        )
        self.assertEqual(agent._RATE_LIMIT_MESSAGE, agent._map_api_error(err))

    def test_overloaded_529(self) -> None:
        err = anthropic.APIStatusError(
            'o', response=self._resp(529), body=None
        )
        self.assertEqual(agent._OVERLOADED_MESSAGE, agent._map_api_error(err))

    def test_internal_server_error(self) -> None:
        err = anthropic.InternalServerError(
            'o', response=self._resp(500), body=None
        )
        self.assertEqual(agent._OVERLOADED_MESSAGE, agent._map_api_error(err))

    def test_prompt_too_long(self) -> None:
        err = anthropic.BadRequestError(
            'prompt is too long', response=self._resp(400), body=None
        )
        self.assertEqual(agent._TOO_LONG_MESSAGE, agent._map_api_error(err))

    def test_generic(self) -> None:
        err = anthropic.BadRequestError(
            'nope', response=self._resp(400), body=None
        )
        self.assertEqual(
            agent._GENERIC_ERROR_MESSAGE, agent._map_api_error(err)
        )

    def test_describe_tools_sorted_unique(self) -> None:
        self.assertEqual(
            'Looking up data with `a`, `b`…',
            agent._describe_tools(
                [{'name': 'b'}, {'name': 'a'}, {'name': 'a'}]
            ),
        )
