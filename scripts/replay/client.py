"""Send requests and capture the responses.

Requests go one at a time, so the timings are not affected by other
requests of the tool.
"""

import hashlib
import json
import time
import typing

import httpx

from scripts.replay import diff, models, pointer

#: Text bodies up to this length are kept. Longer bodies, and bodies
#: that are not text, are kept as a SHA-256 digest and a length.
MAX_TEXT = 4096


class Response(typing.NamedTuple):
    status: int
    content_type: str | None
    body: typing.Any
    elapsed_ms: float
    error: str | None


def decode(response: httpx.Response) -> typing.Any:
    """Return the body of ``response`` in the recording form."""
    content_type = response.headers.get('content-type', '')
    content = response.content
    if not content:
        return None
    if 'json' in content_type:
        try:
            return json.loads(content)
        except ValueError:
            pass
    if content_type.startswith('text/') and len(content) <= MAX_TEXT:
        try:
            return {'$text': content.decode()}
        except UnicodeDecodeError:
            pass
    return {
        '$sha256': hashlib.sha256(content).hexdigest(),
        '$length': len(content),
    }


class Client:
    """An API client with one bearer token."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip('/'),
            headers={'Authorization': f'Bearer {token}'},
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def send(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
        body: typing.Any = None,
    ) -> Response:
        started = time.perf_counter()
        try:
            response = self._client.request(
                method,
                path,
                params=query or None,
                json=body,
            )
        except httpx.HTTPError as error:
            elapsed = (time.perf_counter() - started) * 1000
            return Response(0, None, None, elapsed, repr(error))
        elapsed = (time.perf_counter() - started) * 1000
        return Response(
            response.status_code,
            response.headers.get('content-type'),
            decode(response),
            elapsed,
            None,
        )


def capture(  # noqa: PLR0913 - the keyword arguments are the exchange fields
    client: Client,
    *,
    key: str,
    kind: models.ExchangeKind,
    route: str,
    method: models.HttpMethod,
    path: str,
    query: dict[str, str] | None = None,
    body: typing.Any = None,
    repeat: int = 1,
    placeholder: bool = False,
    normalize: list[str] | None = None,
) -> models.Exchange:
    """Send one request ``repeat`` times and return the exchange.

    The first response is the one that the recording keeps. The other
    responses give more timings. A field that changes between the
    responses is listed in ``unstable``, and the diff masks it on both
    sides.
    """
    first = client.send(method, path, query, body)
    timings = [first.elapsed_ms]
    unstable: list[str] = []
    for _ in range(repeat - 1):
        again = client.send(method, path, query, body)
        timings.append(again.elapsed_ms)
        for changed, _old, _new in diff.compare_values(first.body, again.body):
            text = pointer.to_pointer(changed)
            if text not in unstable:
                unstable.append(text)
    return models.Exchange(
        key=key,
        kind=kind,
        route=route,
        method=method,
        path=path,
        query=dict(query or {}),
        request_body=body,
        status=first.status,
        content_type=first.content_type,
        body=first.body,
        elapsed_ms=timings,
        placeholder=placeholder,
        unstable=unstable,
        error=first.error,
        normalize=list(normalize or []),
    )
