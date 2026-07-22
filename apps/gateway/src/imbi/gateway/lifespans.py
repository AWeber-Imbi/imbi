"""Lifespan hooks for imbi-gateway."""

import contextlib
import logging
import typing

from imbi_common import clickhouse

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
