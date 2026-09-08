"""Lifespan hooks for imbi-gateway."""

import contextlib
import logging
import typing

from imbi.common import clickhouse, iggy

if typing.TYPE_CHECKING:
    from collections import abc

LOGGER = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def clickhouse_hook() -> 'abc.AsyncGenerator[None]':
    """Initialize and manage the ClickHouse connection."""
    result = await clickhouse.initialize()
    if result is False:
        raise RuntimeError('ClickHouse initialization failed')
    async with contextlib.aclosing(clickhouse):
        yield


@contextlib.asynccontextmanager
async def iggy_hook() -> 'abc.AsyncGenerator[None]':
    """Initialize and manage the Iggy connection."""
    result = await iggy.initialize()
    if result is False:
        raise RuntimeError('Iggy initialization failed')
    async with contextlib.aclosing(iggy):
        yield
