"""Call a TypeSafe System One decision model.

A request is ``{model, state, questions}``; the answer for each question
is typed (``noul``, ``choice``, ``score``) with probabilities. See
https://docs.typesafe.ai/api.md.

Every failure is normalised to :class:`DecisionError`, whose message is
safe to show an admin: it names the transport or HTTP status that
failed. The API key, the request headers, and the response body never
appear in it, because the caller surfaces the message verbatim.
"""

import json
import typing

import httpx

__all__ = ['DecisionError', 'DecisionResult', 'decide']

#: Seconds to wait for a decision.
TIMEOUT = 30.0

#: Highest response size read from the provider, in bytes.
MAX_RESPONSE_BYTES = 1024 * 1024


class DecisionError(Exception):
    """The decision call failed."""


class DecisionResult(typing.TypedDict):
    model: str
    answers: dict[str, typing.Any]
    usage: dict[str, typing.Any]


async def decide(
    api_key: str,
    base_url: str,
    model: str,
    state: object,
    questions: dict[str, typing.Any],
    transport: httpx.AsyncBaseTransport | None = None,
) -> DecisionResult:
    """Ask ``model`` the ``questions`` about ``state``.

    Parameters:
        api_key: Decrypted credential for the provider.
        base_url: The provider endpoint, for example
            ``https://api.typesafe.ai/v1``.
        model: The model id, for example ``jev-latest``.
        state: A string, object, or array.
        questions: Question id to question, in the TypeSafe shape.
        transport: Test seam for :class:`httpx.MockTransport`.

    Raises:
        DecisionError: The call failed; the message is safe to show.

    """
    url = base_url.rstrip('/') + '/systemone'
    body = {'model': model, 'state': state, 'questions': questions}
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, transport=transport
        ) as client:
            async with client.stream(
                'POST',
                url,
                json=body,
                headers={'Authorization': f'Bearer {api_key}'},
            ) as response:
                if response.status_code >= 400:
                    raise DecisionError(
                        f'TypeSafe returned HTTP {response.status_code}'
                    )
                content = await _read_capped(response)
    except DecisionError:
        raise
    except httpx.TimeoutException as e:
        raise DecisionError('TypeSafe did not answer in time') from e
    except httpx.HTTPError as e:
        raise DecisionError(
            f'Could not reach TypeSafe ({type(e).__name__})'
        ) from e
    return _parse(content)


async def _read_capped(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise DecisionError(
                'TypeSafe returned a response that is too large'
            )
        chunks.append(chunk)
    return b''.join(chunks)


def _parse(content: bytes) -> DecisionResult:
    try:
        data: object = json.loads(content)
    except ValueError as e:
        raise DecisionError(
            'TypeSafe returned a response that is not JSON'
        ) from e
    if not isinstance(data, dict):
        raise DecisionError('TypeSafe returned an unexpected response')
    payload = typing.cast('dict[str, typing.Any]', data)
    answers = payload.get('answers')
    if not isinstance(answers, dict):
        raise DecisionError('TypeSafe returned no answers')
    usage = payload.get('usage')
    return DecisionResult(
        model=str(payload.get('model', '')),
        answers=typing.cast('dict[str, typing.Any]', answers),
        usage=(
            typing.cast('dict[str, typing.Any]', usage)
            if isinstance(usage, dict)
            else {}
        ),
    )
