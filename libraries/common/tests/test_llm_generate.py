"""Tests for the generative driver adapters."""

import collections.abc
import json
import typing
import unittest

import httpx

from imbi.common import models
from imbi.common.llm import generate
from imbi.common.workflows.registry import agent

FIELDS = [
    agent.OutputField(name='verdict', type='string', enum=['Pass', 'Fail']),
    agent.OutputField(name='note', type='string', required=False),
]
ANSWER = {'verdict': 'pass', 'note': None}
EXPECTED = {'verdict': 'Pass', 'note': None}

Handler = typing.Callable[[httpx.Request], httpx.Response]


def _request(driver: str, **kwargs: typing.Any) -> generate.Request:
    defaults: dict[str, typing.Any] = {
        'driver': driver,
        'model_id': 'model-1',
        'system': 'Be brief.',
        'messages': [models.PromptMessage(role='user', content='Hello')],
        'params': models.PromptParams(max_tokens=50, temperature=0),
        'credential': 'secret',
        'base_url': {
            'anthropic': 'https://api.anthropic.com',
            'openai': 'https://api.openai.com/v1',
            'openai_compatible': 'https://llm.local/v1',
        }.get(driver),
        'region': 'us-east-1',
    }
    return generate.Request(**(defaults | kwargs))


def _anthropic_body(content: list[dict[str, typing.Any]]) -> dict[str, object]:
    return {
        'id': 'msg_1',
        'type': 'message',
        'role': 'assistant',
        'model': 'model-1',
        'content': content,
        'stop_reason': 'end_turn',
        'stop_sequence': None,
        'usage': {'input_tokens': 3, 'output_tokens': 5},
    }


def _openai_body(content: str) -> dict[str, object]:
    return {
        'choices': [{'message': {'role': 'assistant', 'content': content}}],
        'usage': {'prompt_tokens': 3, 'completion_tokens': 5},
    }


def _bedrock_body(content: list[dict[str, object]]) -> dict[str, object]:
    return {
        'output': {'message': {'role': 'assistant', 'content': content}},
        'stopReason': 'end_turn',
        'usage': {'inputTokens': 3, 'outputTokens': 5},
    }


def _vertex_body(text: str) -> dict[str, object]:
    return {
        'candidates': [
            {'content': {'role': 'model', 'parts': [{'text': text}]}}
        ],
        'usageMetadata': {'promptTokenCount': 3, 'candidatesTokenCount': 5},
        'responseId': 'resp-1',
    }


class GenerateTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sent: list[httpx.Request] = []

    async def _call(
        self,
        request: generate.Request,
        status: int,
        body: object,
        headers: dict[str, str] | None = None,
    ) -> generate.Result:
        def handler(req: httpx.Request) -> httpx.Response:
            self.sent.append(req)
            return httpx.Response(status, json=body, headers=headers)

        return await generate.generate(
            request, transport=httpx.MockTransport(handler)
        )

    def _body(self) -> dict[str, typing.Any]:
        return json.loads(self.sent[-1].content)

    # --- anthropic -------------------------------------------------------

    async def test_anthropic_text(self) -> None:
        result = await self._call(
            _request('anthropic'),
            200,
            _anthropic_body([{'type': 'text', 'text': 'Hi'}]),
            {'request-id': 'req-a'},
        )
        self.assertEqual(result.text, 'Hi')
        self.assertIsNone(result.result)
        self.assertEqual(result.usage, {'input_tokens': 3, 'output_tokens': 5})
        self.assertEqual(result.request_id, 'req-a')
        sent = self.sent[-1]
        self.assertEqual(sent.headers['x-api-key'], 'secret')
        body = self._body()
        self.assertEqual(body['system'], 'Be brief.')
        self.assertEqual(body['max_tokens'], 50)
        self.assertNotIn('tools', body)

    async def test_anthropic_bearer(self) -> None:
        await self._call(
            _request('anthropic', bearer=True),
            200,
            _anthropic_body([{'type': 'text', 'text': 'Hi'}]),
        )
        sent = self.sent[-1]
        self.assertEqual(sent.headers['authorization'], 'Bearer secret')
        self.assertNotIn('x-api-key', sent.headers)
        self.assertIn('oauth', sent.headers['anthropic-beta'])

    async def test_anthropic_structured(self) -> None:
        result = await self._call(
            _request('anthropic', output_fields=FIELDS),
            200,
            _anthropic_body(
                [
                    {
                        'type': 'tool_use',
                        'id': 't1',
                        'name': generate.TOOL,
                        'input': {'verdict': 'pass'},
                    }
                ]
            ),
        )
        self.assertEqual(result.result, EXPECTED)
        self.assertEqual(json.loads(result.text), EXPECTED)
        body = self._body()
        self.assertEqual(
            body['tool_choice'], {'type': 'tool', 'name': generate.TOOL}
        )
        self.assertEqual(
            body['tools'][0]['input_schema'], agent.output_schema(FIELDS)
        )

    async def test_anthropic_429_retries(self) -> None:
        with self.assertRaises(generate.GenerateError) as ctx:
            await self._call(
                _request('anthropic'),
                429,
                {'type': 'error', 'error': {'type': 'rate_limit_error'}},
            )
        self.assertEqual(ctx.exception.code, 'rate_limited')
        self.assertTrue(ctx.exception.retry)
        self.assertEqual(len(self.sent), 1)

    async def test_anthropic_needs_a_credential(self) -> None:
        with self.assertRaises(generate.GenerateError) as ctx:
            await generate.generate(_request('anthropic', credential=None))
        self.assertEqual(ctx.exception.code, 'provider_misconfigured')

    # --- openai ----------------------------------------------------------

    async def test_openai_text(self) -> None:
        result = await self._call(
            _request('openai'),
            200,
            _openai_body('Hi'),
            {'x-request-id': 'req-o'},
        )
        self.assertEqual(result.text, 'Hi')
        self.assertEqual(result.usage, {'input_tokens': 3, 'output_tokens': 5})
        self.assertEqual(result.request_id, 'req-o')
        sent = self.sent[-1]
        self.assertEqual(
            str(sent.url), 'https://api.openai.com/v1/chat/completions'
        )
        self.assertEqual(sent.headers['authorization'], 'Bearer secret')
        body = self._body()
        self.assertEqual(body['max_completion_tokens'], 50)
        self.assertEqual(body['temperature'], 0)
        self.assertEqual(body['messages'][0]['role'], 'system')

    async def test_openai_compatible_text(self) -> None:
        result = await self._call(
            _request('openai_compatible', credential=None),
            200,
            _openai_body('Hi'),
        )
        self.assertEqual(result.text, 'Hi')
        self.assertNotIn('authorization', self.sent[-1].headers)
        self.assertEqual(self._body()['max_tokens'], 50)

    async def test_openai_structured_nullable(self) -> None:
        result = await self._call(
            _request('openai_compatible', output_fields=FIELDS),
            200,
            _openai_body(json.dumps(ANSWER)),
        )
        self.assertEqual(result.result, EXPECTED)
        fmt = self._body()['response_format']
        self.assertEqual(fmt['type'], 'json_schema')
        self.assertTrue(fmt['json_schema']['strict'])
        schema = fmt['json_schema']['schema']
        self.assertEqual(schema['required'], ['verdict', 'note'])
        self.assertEqual(
            schema['properties']['note']['type'], ['string', 'null']
        )
        self.assertEqual(schema['properties']['verdict']['type'], 'string')

    def test_strict_nested(self) -> None:
        fields = [
            agent.OutputField(
                name='entries',
                type='array',
                items='object',
                required=False,
                fields=[
                    agent.ObjectField(
                        name='kind',
                        type='string',
                        enum=['a', 'b'],
                        required=False,
                    )
                ],
            )
        ]
        schema = generate._strict(agent.output_schema(fields) or {})
        items = schema['properties']['entries']
        self.assertEqual(items['type'], ['array', 'null'])
        kind = items['items']['properties']['kind']
        self.assertEqual(kind['type'], ['string', 'null'])
        self.assertEqual(kind['enum'], ['a', 'b', None])
        self.assertEqual(items['items']['required'], ['kind'])

    def test_strict_drops_unsupported_format(self) -> None:
        fields = [
            agent.OutputField(name='link', type='string', format='uri'),
            agent.OutputField(name='when', type='string', format='date'),
        ]
        original = agent.output_schema(fields) or {}
        schema = generate._strict(original)
        self.assertNotIn('format', schema['properties']['link'])
        self.assertEqual(schema['properties']['when']['format'], 'date')
        self.assertEqual(original['properties']['link']['format'], 'uri')

    async def test_openai_invalid_json(self) -> None:
        with self.assertRaises(generate.GenerateError) as ctx:
            await self._call(
                _request('openai', output_fields=FIELDS),
                200,
                _openai_body('not json'),
            )
        self.assertEqual(ctx.exception.code, 'model_answer_invalid')
        self.assertTrue(ctx.exception.retry)

    async def test_openai_wrong_type(self) -> None:
        with self.assertRaises(generate.GenerateError) as ctx:
            await self._call(
                _request('openai', output_fields=FIELDS),
                200,
                _openai_body(json.dumps({'verdict': 'Maybe'})),
            )
        self.assertEqual(ctx.exception.code, 'model_answer_invalid')

    async def test_answer_must_be_finite_and_match_the_format(self) -> None:
        for field, text in (
            (agent.OutputField(name='score', type='number'), '{"score": NaN}'),
            (
                agent.OutputField(
                    name='at', type='string', format='date-time'
                ),
                '{"at": "not-a-date"}',
            ),
            (
                # Strict mode does not get uri; the local check does.
                agent.OutputField(name='link', type='string', format='uri'),
                '{"link": "not a uri"}',
            ),
        ):
            with (
                self.subTest(field.name),
                self.assertRaises(generate.GenerateError) as ctx,
            ):
                await self._call(
                    _request('openai', output_fields=[field]),
                    200,
                    _openai_body(text),
                )
            self.assertEqual(ctx.exception.code, 'model_answer_invalid')
            self.assertTrue(ctx.exception.retry)

    async def test_openai_refuses_response_format(self) -> None:
        with self.assertRaises(generate.GenerateError) as ctx:
            await self._call(
                _request('openai', output_fields=FIELDS),
                400,
                {
                    'error': {
                        'message': "Invalid parameter: 'response_format' of "
                        "type 'json_schema' is not supported with this "
                        'model.'
                    }
                },
            )
        self.assertEqual(ctx.exception.code, 'model_unsupported')
        self.assertFalse(ctx.exception.retry)

    async def test_openai_other_400(self) -> None:
        with self.assertRaises(generate.GenerateError) as ctx:
            await self._call(
                _request('openai'), 400, {'error': {'message': 'bad'}}
            )
        self.assertEqual(ctx.exception.code, 'provider_refused')
        self.assertFalse(ctx.exception.retry)

    async def test_openai_5xx_and_transport_retry(self) -> None:
        with self.assertRaises(generate.GenerateError) as ctx:
            await self._call(_request('openai'), 503, {})
        self.assertEqual(ctx.exception.code, 'provider_unavailable')
        self.assertTrue(ctx.exception.retry)

        def fail(_req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError('down')

        with self.assertRaises(generate.GenerateError) as ctx:
            await generate.generate(
                _request('openai'), transport=httpx.MockTransport(fail)
            )
        self.assertEqual(ctx.exception.code, 'provider_unreachable')
        self.assertTrue(ctx.exception.retry)

    async def test_usage_normalized(self) -> None:
        body = _openai_body('Hi')
        body['usage'] = {'prompt_tokens': True, 'completion_tokens': '5'}
        result = await self._call(_request('openai'), 200, body)
        self.assertEqual(
            result.usage, {'input_tokens': None, 'output_tokens': None}
        )
        body.pop('usage')
        result = await self._call(_request('openai'), 200, body)
        self.assertEqual(
            result.usage, {'input_tokens': None, 'output_tokens': None}
        )
        body['usage'] = [1, 2]
        result = await self._call(_request('openai'), 200, body)
        self.assertEqual(
            result.usage, {'input_tokens': None, 'output_tokens': None}
        )

    async def test_openai_refusal(self) -> None:
        body = {
            'choices': [
                {
                    'message': {
                        'role': 'assistant',
                        'content': None,
                        'refusal': 'I cannot help with that.',
                    }
                }
            ],
        }
        for fields in ([], FIELDS):
            with (
                self.subTest(output_fields=bool(fields)),
                self.assertRaises(generate.GenerateError) as ctx,
            ):
                await self._call(
                    _request('openai', output_fields=fields), 200, body
                )
            self.assertEqual(ctx.exception.code, 'provider_refused')
            self.assertFalse(ctx.exception.retry)

    async def test_openai_cached_tokens(self) -> None:
        body = _openai_body('Hi')
        body['usage'] = {
            'prompt_tokens': 2048,
            'completion_tokens': 5,
            'prompt_tokens_details': {'cached_tokens': 1024},
        }
        result = await self._call(_request('openai'), 200, body)
        self.assertEqual(
            result.usage,
            {
                'input_tokens': 1024,
                'output_tokens': 5,
                'cache_read_tokens': 1024,
            },
        )

    async def test_negative_usage_is_unknown(self) -> None:
        body = _openai_body('Hi')
        body['usage'] = {
            'prompt_tokens': -3,
            'completion_tokens': -5,
            'prompt_tokens_details': {'cached_tokens': -1},
        }
        result = await self._call(_request('openai'), 200, body)
        self.assertEqual(
            result.usage, {'input_tokens': None, 'output_tokens': None}
        )

    async def test_null_key_kept_unless_declared(self) -> None:
        nested = [
            agent.OutputField(
                name='entry',
                type='object',
                fields=[agent.ObjectField(name='kind', type='string')],
            )
        ]
        for fields, answer in (
            (FIELDS, {'verdict': 'Pass', 'extra': None}),
            (nested, {'entry': {'kind': 'a', 'extra': None}}),
        ):
            with self.subTest(answer=answer):
                with self.assertRaises(generate.GenerateError) as ctx:
                    await self._call(
                        _request('openai', output_fields=fields),
                        200,
                        _openai_body(json.dumps(answer)),
                    )
                self.assertEqual(ctx.exception.code, 'model_answer_invalid')

    def test_credential_not_in_repr(self) -> None:
        request = _request('openai')
        self.assertNotIn(str(request.credential), repr(request))

    # --- bedrock ---------------------------------------------------------

    async def test_bedrock_text(self) -> None:
        result = await self._call(
            _request('bedrock', model_id='us.meta.llama:0'),
            200,
            _bedrock_body([{'text': 'Hi'}]),
            {'x-amzn-RequestId': 'req-b'},
        )
        self.assertEqual(result.text, 'Hi')
        self.assertEqual(result.usage, {'input_tokens': 3, 'output_tokens': 5})
        self.assertEqual(result.request_id, 'req-b')
        sent = self.sent[-1]
        self.assertEqual(
            str(sent.url),
            'https://bedrock-runtime.us-east-1.amazonaws.com'
            '/model/us.meta.llama%3A0/converse',
        )
        self.assertEqual(sent.headers['authorization'], 'Bearer secret')
        body = self._body()
        self.assertEqual(body['system'], [{'text': 'Be brief.'}])
        self.assertEqual(
            body['inferenceConfig'], {'maxTokens': 50, 'temperature': 0}
        )

    async def test_bedrock_structured(self) -> None:
        result = await self._call(
            _request('bedrock', output_fields=FIELDS),
            200,
            _bedrock_body(
                [
                    {
                        'toolUse': {
                            'toolUseId': 't1',
                            'name': generate.TOOL,
                            'input': ANSWER,
                        }
                    }
                ]
            ),
        )
        self.assertEqual(result.result, EXPECTED)
        config = self._body()['toolConfig']
        self.assertEqual(
            config['toolChoice'], {'tool': {'name': generate.TOOL}}
        )
        self.assertEqual(
            config['tools'][0]['toolSpec']['inputSchema']['json'],
            agent.output_schema(FIELDS),
        )

    async def test_bedrock_structured_without_tool_use(self) -> None:
        with self.assertRaises(generate.GenerateError) as ctx:
            await self._call(
                _request('bedrock', output_fields=FIELDS),
                200,
                _bedrock_body([{'text': 'Sorry'}]),
            )
        self.assertEqual(ctx.exception.code, 'model_answer_invalid')

    async def test_bedrock_needs_a_region(self) -> None:
        with self.assertRaises(generate.GenerateError) as ctx:
            await generate.generate(_request('bedrock', region=None))
        self.assertEqual(ctx.exception.code, 'provider_misconfigured')

    async def test_bedrock_auth_hook(self) -> None:
        class Signer(httpx.Auth):
            def auth_flow(
                self, request: httpx.Request
            ) -> collections.abc.Generator[httpx.Request, httpx.Response]:
                request.headers['Authorization'] = 'AWS4-HMAC-SHA256 x'
                yield request

        await self._call(
            _request('bedrock', credential=None, auth=Signer()),
            200,
            _bedrock_body([{'text': 'Hi'}]),
        )
        self.assertEqual(
            self.sent[-1].headers['authorization'], 'AWS4-HMAC-SHA256 x'
        )

    # --- vertex ----------------------------------------------------------

    async def test_vertex_text_express(self) -> None:
        result = await self._call(
            _request('vertex', model_id='gemini-2.5-flash'),
            200,
            _vertex_body('Hi'),
        )
        self.assertEqual(result.text, 'Hi')
        self.assertEqual(result.usage, {'input_tokens': 3, 'output_tokens': 5})
        self.assertEqual(result.request_id, 'resp-1')
        sent = self.sent[-1]
        self.assertEqual(
            str(sent.url),
            'https://aiplatform.googleapis.com/v1/publishers/google/models/'
            'gemini-2.5-flash:generateContent',
        )
        self.assertEqual(sent.headers['x-goog-api-key'], 'secret')
        body = self._body()
        self.assertEqual(
            body['systemInstruction'], {'parts': [{'text': 'Be brief.'}]}
        )
        self.assertEqual(
            body['generationConfig'],
            {'maxOutputTokens': 50, 'temperature': 0},
        )

    async def test_vertex_project_bearer(self) -> None:
        await self._call(
            _request(
                'vertex',
                model_id='gemini-2.5-flash',
                project_id='p1',
                bearer=True,
            ),
            200,
            _vertex_body('Hi'),
        )
        sent = self.sent[-1]
        self.assertEqual(
            str(sent.url),
            'https://us-east-1-aiplatform.googleapis.com/v1/projects/p1/'
            'locations/us-east-1/publishers/google/models/'
            'gemini-2.5-flash:generateContent',
        )
        self.assertEqual(sent.headers['authorization'], 'Bearer secret')

    async def test_vertex_thinking_tokens_are_output(self) -> None:
        body = _vertex_body('Hi')
        body['usageMetadata'] = {
            'promptTokenCount': 3,
            'candidatesTokenCount': 20,
            'thoughtsTokenCount': 1000,
        }
        result = await self._call(
            _request('vertex', model_id='gemini-2.5-flash'), 200, body
        )
        self.assertEqual(
            result.usage, {'input_tokens': 3, 'output_tokens': 1020}
        )

    async def test_vertex_thinking_tokens_absent_or_invalid(self) -> None:
        for metadata, output in (
            ({'candidatesTokenCount': 20}, 20),
            ({'candidatesTokenCount': 20, 'thoughtsTokenCount': -1}, None),
        ):
            with self.subTest(metadata=metadata):
                body = _vertex_body('Hi')
                body['usageMetadata'] = {'promptTokenCount': 3, **metadata}
                result = await self._call(
                    _request('vertex', model_id='gemini-2.5-flash'), 200, body
                )
                self.assertEqual(
                    result.usage, {'input_tokens': 3, 'output_tokens': output}
                )

    async def test_vertex_cached_tokens_above_prompt(self) -> None:
        for cached, usage in (
            (3072, {'input_tokens': None, 'output_tokens': 5}),
            (
                2048,
                {
                    'input_tokens': 0,
                    'output_tokens': 5,
                    'cache_read_tokens': 2048,
                },
            ),
        ):
            with self.subTest(cached=cached):
                body = _vertex_body('Hi')
                body['usageMetadata'] = {
                    'promptTokenCount': 2048,
                    'candidatesTokenCount': 5,
                    'cachedContentTokenCount': cached,
                }
                result = await self._call(
                    _request('vertex', model_id='gemini-2.5-flash'), 200, body
                )
                self.assertEqual(result.usage, usage)

    async def test_vertex_cached_tokens(self) -> None:
        body = _vertex_body('Hi')
        body['usageMetadata'] = {
            'promptTokenCount': 2048,
            'candidatesTokenCount': 5,
            'cachedContentTokenCount': 1024,
        }
        result = await self._call(
            _request('vertex', model_id='gemini-2.5-flash'), 200, body
        )
        self.assertEqual(
            result.usage,
            {
                'input_tokens': 1024,
                'output_tokens': 5,
                'cache_read_tokens': 1024,
            },
        )

    async def test_vertex_structured(self) -> None:
        result = await self._call(
            _request('vertex', output_fields=FIELDS),
            200,
            _vertex_body(json.dumps({'verdict': 'FAIL', 'note': 'x'})),
        )
        self.assertEqual(result.result, {'verdict': 'Fail', 'note': 'x'})
        config = self._body()['generationConfig']
        self.assertEqual(config['responseMimeType'], 'application/json')
        self.assertEqual(
            config['responseJsonSchema'], agent.output_schema(FIELDS)
        )
