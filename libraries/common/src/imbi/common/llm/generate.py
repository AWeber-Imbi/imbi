"""Send one generative prompt to a catalog model and return the answer.

:func:`generate` is the one entry point. It selects the adapter of the
provider driver:

- ``anthropic``: the ``anthropic`` SDK, ``messages.create``.
- ``openai``, ``openai_compatible``: ``POST /chat/completions``.
- ``bedrock``: the Converse API, ``POST /model/<id>/converse``.
- ``vertex``: Gemini ``generateContent`` (no Claude on Vertex).

With ``output_fields``, the model must give a structured answer:

- ``anthropic`` and ``bedrock``: one forced tool whose input schema is
  the schema of the fields.
- ``openai``, ``openai_compatible``: a strict ``json_schema``
  ``response_format``. Strict mode needs every property in
  ``required``, so each optional field becomes a required field that
  can be ``null``.
- ``vertex``: ``responseMimeType: application/json`` with
  ``responseJsonSchema``.

The answer is checked against the original schema (a ``null`` optional
field counts as a missing field), then completed with
:func:`agent.complete_result`. ``text`` is then the JSON of the result.

Each failure is a :class:`GenerateError` with a code and a ``retry``
flag. This module logs nothing: the credential, the prompt, and the
provider body never go into a log or an error message.

Needs the ``llm`` (``anthropic``) and ``script`` (``jsonschema``)
extras of imbi-common.
"""

import dataclasses
import json
import typing
import urllib.parse

import anthropic
import httpx
import jsonschema

from imbi.common import models
from imbi.common.llm.discovery import OAUTH_BETA
from imbi.common.workflows.registry import agent

__all__ = ['GenerateError', 'Request', 'Result', 'Usage', 'generate']

#: Anthropic needs ``max_tokens``; this is used when the prompt has none.
DEFAULT_MAX_TOKENS = 4096

#: The name of the forced tool that carries a structured answer.
TOOL = 'submit_result'
_TOOL_DESCRIPTION = 'Submit the result.'

#: Words in a 400 body that tell the provider refused structured output.
_UNSUPPORTED = ('response_format', 'schema', 'tool')


class GenerateError(Exception):
    """The model call failed.

    ``code`` is one of:

    - ``model_answer_invalid`` (retry): the answer did not parse, or did
      not match the schema.
    - ``model_unsupported``: the provider refused structured output.
    - ``rate_limited`` (retry): HTTP 429.
    - ``provider_unavailable`` (retry): HTTP 5xx.
    - ``provider_unreachable`` (retry): a transport error or a timeout.
    - ``provider_refused``: another HTTP 4xx.
    - ``provider_misconfigured``: the request is missing a value that
      the driver needs, such as a region.
    """

    def __init__(
        self, code: str, *, retry: bool = False, status: int | None = None
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retry = retry
        self.status = status


@dataclasses.dataclass(frozen=True, kw_only=True)
class Request:
    """One model call.

    Credentials, by driver:

    - ``anthropic``: ``credential`` is an API key, or a workload
      identity token when ``bearer`` is set.
    - ``openai``, ``openai_compatible``: ``credential`` is an API key or
      a workload identity token; both are sent as a bearer token.
    - ``bedrock``: ``credential`` is a Bedrock API key (a bearer token).
      For the runtime IAM role, ``auth`` signs each request (SigV4).
    - ``vertex``: ``credential`` is an API key (express mode), or an
      OAuth access token when ``bearer`` is set. ``auth`` can sign the
      request instead.
    """

    driver: models.AIProviderDriver
    model_id: str
    messages: list[models.PromptMessage]
    system: str = ''
    params: models.PromptParams = dataclasses.field(
        default_factory=models.PromptParams
    )
    output_fields: list[agent.OutputField] = dataclasses.field(
        default_factory=list[agent.OutputField]
    )
    #: Already resolved against the driver default.
    base_url: str | None = None
    credential: str | None = None
    bearer: bool = False
    auth: httpx.Auth | None = None
    #: bedrock / vertex
    region: str | None = None
    #: vertex. Without it, the call uses Vertex express mode (API key).
    project_id: str | None = None
    timeout: float = 120.0


class Usage(typing.TypedDict):
    input_tokens: int | None
    output_tokens: int | None


@dataclasses.dataclass(frozen=True)
class Result:
    text: str
    #: The structured answer; ``None`` without ``output_fields``.
    result: dict[str, typing.Any] | None
    usage: Usage
    request_id: str | None


@dataclasses.dataclass(frozen=True)
class _Answer:
    """What one adapter got from the provider, before the checks."""

    text: str
    #: The forced tool input, or ``None`` when the answer is ``text``.
    tool_input: object
    usage: Usage
    request_id: str | None


async def generate(
    request: Request, transport: httpx.AsyncBaseTransport | None = None
) -> Result:
    """Call the model of ``request`` once.

    ``transport`` is a test seam for :class:`httpx.MockTransport`.

    Raises:
        GenerateError: The call failed.

    """
    schema = agent.output_schema(request.output_fields)
    match request.driver:
        case 'anthropic':
            answer = await _anthropic(request, schema, transport)
        case 'openai' | 'openai_compatible':
            answer = await _openai(request, schema, transport)
        case 'bedrock':
            answer = await _bedrock(request, schema, transport)
        case 'vertex':
            answer = await _vertex(request, schema, transport)
        case _:
            raise GenerateError('provider_misconfigured')
    if schema is None:
        return Result(answer.text, None, answer.usage, answer.request_id)
    value = answer.tool_input
    if value is None:
        try:
            value = json.loads(answer.text)
        except ValueError:
            raise GenerateError('model_answer_invalid', retry=True) from None
    result = _check(request.output_fields, schema, value)
    return Result(json.dumps(result), result, answer.usage, answer.request_id)


def _check(
    fields: list[agent.OutputField],
    schema: dict[str, typing.Any],
    value: object,
) -> dict[str, typing.Any]:
    """Return the checked and completed structured answer."""
    # Before the schema check: an enum value in a different case is
    # not an error.
    value = agent.match_enum_case(schema, _drop_nulls(schema, value))
    try:
        # The schema is our own, so no check against the meta-schema.
        jsonschema.Draft202012Validator(schema).validate(value)
    except jsonschema.ValidationError:
        raise GenerateError('model_answer_invalid', retry=True) from None
    return agent.complete_result(
        fields, typing.cast('dict[str, typing.Any]', value)
    )


def _drop_nulls(schema: dict[str, typing.Any], value: object) -> object:
    """Remove each optional property whose value is ``null``."""
    if isinstance(value, dict) and 'properties' in schema:
        props: dict[str, typing.Any] = schema['properties']
        required = set(schema['required'])
        items = typing.cast('dict[str, object]', value)
        return {
            k: _drop_nulls(props.get(k, {}), v)
            for k, v in items.items()
            if v is not None or k in required
        }
    if isinstance(value, list) and 'items' in schema:
        values = typing.cast('list[object]', value)
        return [_drop_nulls(schema['items'], v) for v in values]
    return value


def _strict(schema: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Return ``schema`` for OpenAI strict mode.

    Each optional property becomes a required property that can be
    ``null``.
    """
    if schema['type'] == 'array':
        return {**schema, 'items': _strict(schema['items'])}
    if schema['type'] != 'object':
        return schema
    required = set(schema['required'])
    props = {
        k: _strict(v) if k in required else _nullable(_strict(v))
        for k, v in schema['properties'].items()
    }
    return {**schema, 'properties': props, 'required': list(props)}


def _nullable(schema: dict[str, typing.Any]) -> dict[str, typing.Any]:
    out = {**schema, 'type': [schema['type'], 'null']}
    if 'enum' in out:
        out['enum'] = [*out['enum'], None]
    return out


def _status_error(status: int, detail: str, structured: bool) -> GenerateError:
    if status == httpx.codes.TOO_MANY_REQUESTS:
        return GenerateError('rate_limited', retry=True, status=status)
    if status >= 500:
        return GenerateError('provider_unavailable', retry=True, status=status)
    detail = detail.lower()
    if (
        status == httpx.codes.BAD_REQUEST
        and structured
        and any(word in detail for word in _UNSUPPORTED)
    ):
        return GenerateError('model_unsupported', status=status)
    return GenerateError('provider_refused', status=status)


def _usage(input_tokens: object, output_tokens: object) -> Usage:
    def as_int(value: object) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    return Usage(
        input_tokens=as_int(input_tokens), output_tokens=as_int(output_tokens)
    )


def _omit_none(**values: object) -> dict[str, object]:
    return {k: v for k, v in values.items() if v not in (None, [])}


async def _post(
    request: Request,
    url: str,
    body: dict[str, typing.Any],
    headers: dict[str, str],
    structured: bool,
    transport: httpx.AsyncBaseTransport | None,
) -> httpx.Response:
    try:
        async with httpx.AsyncClient(
            timeout=request.timeout, auth=request.auth, transport=transport
        ) as client:
            response = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError:
        raise GenerateError('provider_unreachable', retry=True) from None
    if response.status_code >= 400:
        raise _status_error(response.status_code, response.text, structured)
    return response


def _json(response: httpx.Response) -> dict[str, typing.Any]:
    try:
        data: object = response.json()
    except ValueError:
        raise GenerateError('model_answer_invalid', retry=True) from None
    if not isinstance(data, dict):
        raise GenerateError('model_answer_invalid', retry=True)
    return typing.cast('dict[str, typing.Any]', data)


def _bearer(request: Request) -> dict[str, str]:
    if not request.credential:
        return {}
    return {'Authorization': f'Bearer {request.credential}'}


def _messages(request: Request) -> list[dict[str, str]]:
    return [m.model_dump() for m in request.messages]


# --- anthropic -----------------------------------------------------------


async def _anthropic(
    request: Request,
    schema: dict[str, typing.Any] | None,
    transport: httpx.AsyncBaseTransport | None,
) -> _Answer:
    if not request.credential:
        # Without one, the SDK reads ANTHROPIC_API_KEY of this process.
        raise GenerateError('provider_misconfigured')
    auth: dict[str, typing.Any] = (
        {
            'auth_token': request.credential,
            'default_headers': {'anthropic-beta': OAUTH_BETA},
        }
        if request.bearer
        else {'api_key': request.credential}
    )
    params = request.params
    kwargs: dict[str, typing.Any] = _omit_none(
        model=request.model_id,
        max_tokens=params.max_tokens or DEFAULT_MAX_TOKENS,
        messages=_messages(request),
        system=request.system or None,
        temperature=params.temperature,
        top_p=params.top_p,
        stop_sequences=params.stop_sequences,
    )
    if schema is not None:
        kwargs['tools'] = [
            {
                'name': TOOL,
                'description': _TOOL_DESCRIPTION,
                'input_schema': schema,
            }
        ]
        kwargs['tool_choice'] = {'type': 'tool', 'name': TOOL}
    try:
        async with anthropic.AsyncAnthropic(
            **auth,
            base_url=request.base_url,
            timeout=request.timeout,
            # The caller retries; a retry here would be a second call.
            max_retries=0,
            http_client=httpx.AsyncClient(transport=transport)
            if transport
            else None,
        ) as client:
            response = await client.messages.create(**kwargs)
    except anthropic.APIStatusError as exc:
        raise _status_error(
            exc.status_code, exc.message, schema is not None
        ) from None
    except anthropic.AnthropicError:
        raise GenerateError('provider_unreachable', retry=True) from None
    text = ''.join(b.text for b in response.content if b.type == 'text')
    tool_input = next(
        (b.input for b in response.content if b.type == 'tool_use'), None
    )
    return _Answer(
        text,
        tool_input,
        _usage(response.usage.input_tokens, response.usage.output_tokens),
        response._request_id,
    )


# --- openai, openai_compatible -------------------------------------------


async def _openai(
    request: Request,
    schema: dict[str, typing.Any] | None,
    transport: httpx.AsyncBaseTransport | None,
) -> _Answer:
    if not request.base_url:
        raise GenerateError('provider_misconfigured')
    params = request.params
    system = [{'role': 'system', 'content': request.system}]
    # OpenAI refuses max_tokens for its newer models; other servers
    # do not all know max_completion_tokens.
    max_key = (
        'max_completion_tokens' if request.driver == 'openai' else 'max_tokens'
    )
    body: dict[str, typing.Any] = _omit_none(
        model=request.model_id,
        messages=(system if request.system else []) + _messages(request),
        temperature=params.temperature,
        top_p=params.top_p,
        stop=params.stop_sequences,
        **{max_key: params.max_tokens},
    )
    if schema is not None:
        body['response_format'] = {
            'type': 'json_schema',
            'json_schema': {
                'name': TOOL,
                'strict': True,
                'schema': _strict(schema),
            },
        }
    headers = _bearer(request)
    response = await _post(
        request,
        f'{request.base_url.rstrip("/")}/chat/completions',
        body,
        headers,
        schema is not None,
        transport,
    )
    data = _json(response)
    try:
        text = data['choices'][0]['message'].get('content') or ''
        usage = data.get('usage') or {}
    except (KeyError, IndexError, TypeError, AttributeError):
        raise GenerateError('model_answer_invalid', retry=True) from None
    return _Answer(
        str(text),
        None,
        _usage(usage.get('prompt_tokens'), usage.get('completion_tokens')),
        response.headers.get('x-request-id'),
    )


# --- bedrock -------------------------------------------------------------


async def _bedrock(
    request: Request,
    schema: dict[str, typing.Any] | None,
    transport: httpx.AsyncBaseTransport | None,
) -> _Answer:
    base = request.base_url or (
        request.region
        and f'https://bedrock-runtime.{request.region}.amazonaws.com'
    )
    if not base:
        raise GenerateError('provider_misconfigured')
    params = request.params
    body: dict[str, typing.Any] = _omit_none(
        messages=[
            {'role': m.role, 'content': [{'text': m.content}]}
            for m in request.messages
        ],
        system=[{'text': request.system}] if request.system else None,
        inferenceConfig=_omit_none(
            maxTokens=params.max_tokens,
            temperature=params.temperature,
            topP=params.top_p,
            stopSequences=params.stop_sequences,
        )
        or None,
    )
    if schema is not None:
        body['toolConfig'] = {
            'tools': [
                {
                    'toolSpec': {
                        'name': TOOL,
                        'description': _TOOL_DESCRIPTION,
                        'inputSchema': {'json': schema},
                    }
                }
            ],
            'toolChoice': {'tool': {'name': TOOL}},
        }
    headers = _bearer(request)
    model = urllib.parse.quote(request.model_id, safe='')
    response = await _post(
        request,
        f'{base.rstrip("/")}/model/{model}/converse',
        body,
        headers,
        schema is not None,
        transport,
    )
    data = _json(response)
    try:
        content: list[dict[str, typing.Any]] = data['output']['message'][
            'content'
        ]
        text = ''.join(str(c['text']) for c in content if 'text' in c)
        tool_input = next(
            (c['toolUse']['input'] for c in content if 'toolUse' in c), None
        )
        usage = data.get('usage') or {}
    except (KeyError, TypeError, AttributeError):
        raise GenerateError('model_answer_invalid', retry=True) from None
    return _Answer(
        text,
        tool_input,
        _usage(usage.get('inputTokens'), usage.get('outputTokens')),
        response.headers.get('x-amzn-requestid'),
    )


# --- vertex (Gemini) -----------------------------------------------------


def _vertex_url(request: Request) -> str:
    model = urllib.parse.quote(request.model_id, safe='')
    host = 'aiplatform.googleapis.com'
    path = f'/publishers/google/models/{model}:generateContent'
    if request.project_id:
        region = request.region or 'global'
        if region != 'global':
            host = f'{region}-{host}'
        path = f'/projects/{request.project_id}/locations/{region}{path}'
    return (request.base_url or f'https://{host}').rstrip('/') + '/v1' + path


async def _vertex(
    request: Request,
    schema: dict[str, typing.Any] | None,
    transport: httpx.AsyncBaseTransport | None,
) -> _Answer:
    params = request.params
    body: dict[str, typing.Any] = _omit_none(
        contents=[
            {
                'role': 'model' if m.role == 'assistant' else 'user',
                'parts': [{'text': m.content}],
            }
            for m in request.messages
        ],
        systemInstruction={'parts': [{'text': request.system}]}
        if request.system
        else None,
        generationConfig=_omit_none(
            maxOutputTokens=params.max_tokens,
            temperature=params.temperature,
            topP=params.top_p,
            stopSequences=params.stop_sequences,
            responseMimeType='application/json' if schema else None,
            responseJsonSchema=schema,
        )
        or None,
    )
    headers = (
        {'x-goog-api-key': request.credential}
        if request.credential and not request.bearer
        else _bearer(request)
    )
    response = await _post(
        request,
        _vertex_url(request),
        body,
        headers,
        schema is not None,
        transport,
    )
    data = _json(response)
    try:
        parts: list[dict[str, typing.Any]] = data['candidates'][0]['content'][
            'parts'
        ]
        text = ''.join(
            str(p['text'])
            for p in parts
            if 'text' in p and not p.get('thought')
        )
        usage = data.get('usageMetadata') or {}
    except (KeyError, IndexError, TypeError, AttributeError):
        raise GenerateError('model_answer_invalid', retry=True) from None
    return _Answer(
        text,
        None,
        _usage(
            usage.get('promptTokenCount'), usage.get('candidatesTokenCount')
        ),
        data.get('responseId'),
    )
