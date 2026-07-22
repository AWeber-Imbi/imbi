"""Plugin infrastructure for imbi-api."""

import asyncio
import json
import os
import typing
from collections.abc import Awaitable

import fastapi

from imbi.common import graph

PLUGIN_TIMEOUT_SECONDS = float(
    os.environ.get('IMBI_PLUGIN_TIMEOUT_SECONDS', '10')
)


def parse_options(raw: typing.Any) -> dict[str, typing.Any]:
    """Decode a Plugin/edge ``options`` value into a dict.

    Handles every layer these values arrive at: raw agtype column
    values (decoded via :func:`graph.parse_agtype`), the single
    JSON-encoded strings AGE returns for nested map properties, and
    already-parsed dicts. Anything that does not resolve to a dict
    (``None``, malformed JSON, a non-object) yields an empty dict so a
    bad ``options`` value never crashes a read path.
    """
    if raw is None:
        return {}
    parsed = graph.parse_agtype(raw)
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return {}
    if isinstance(parsed, dict):
        return typing.cast('dict[str, typing.Any]', parsed)
    return {}


async def call_with_timeout[T](coro: Awaitable[T]) -> T:
    """Run a plugin handler call with the configured timeout.

    Maps :class:`TimeoutError` to a 503 response with ``Retry-After``.
    """
    try:
        return await asyncio.wait_for(coro, timeout=PLUGIN_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise fastapi.HTTPException(
            status_code=503,
            detail='Plugin timed out',
            headers={'Retry-After': '5'},
        ) from exc
