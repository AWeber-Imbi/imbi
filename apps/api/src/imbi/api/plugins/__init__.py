"""Plugin infrastructure for imbi-api."""

import asyncio
import json
import os
import typing
from collections.abc import Awaitable

import fastapi

PLUGIN_TIMEOUT_SECONDS = float(
    os.environ.get('IMBI_PLUGIN_TIMEOUT_SECONDS', '10')
)


def parse_options(raw: typing.Any) -> dict[str, typing.Any]:
    """Parse a Plugin/edge ``options`` value to a dict.

    AGE returns property maps as JSON strings on round-trip; for nested
    dict properties we serialize on write and decode here on read.
    """
    if isinstance(raw, str):
        parsed: dict[str, typing.Any] = json.loads(raw)
        return parsed
    return raw or {}


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
