"""Track in-flight event processing for graceful shutdown.

Socket Mode delivers events fire-and-forget; without tracking, a rolling
deploy can close the connection mid-reply. :func:`track` increments a
counter around each handler and :func:`wait_for_drain` lets shutdown wait
(bounded by :data:`SHUTDOWN_TIMEOUT`) for outstanding work to finish.

Adapted from the ``aj`` Slack bot.

"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import typing

if typing.TYPE_CHECKING:
    import collections.abc

LOGGER = logging.getLogger(__name__)

SHUTDOWN_TIMEOUT = 15
"""Maximum seconds to wait for in-flight requests during shutdown."""

_active: int = 0
_drain: asyncio.Event | None = None


def _get_drain() -> asyncio.Event:
    """Return the drain event, creating it on the running loop."""
    global _drain
    if _drain is None:
        _drain = asyncio.Event()
        _drain.set()
    return _drain


def reset() -> None:
    """Reset module state (for testing)."""
    global _active, _drain
    _active = 0
    _drain = None


@contextlib.asynccontextmanager
async def track() -> collections.abc.AsyncGenerator[None]:
    """Track an in-flight request for the duration of the context."""
    global _active
    drain = _get_drain()
    _active += 1
    drain.clear()
    try:
        yield
    finally:
        _active -= 1
        if _active == 0:
            drain.set()


async def wait_for_drain() -> None:
    """Block until all in-flight requests finish or the timeout elapses."""
    if _active == 0:
        return
    LOGGER.info(
        'Waiting for %i in-flight request(s) to complete (timeout %is)',
        _active,
        SHUTDOWN_TIMEOUT,
    )
    try:
        await asyncio.wait_for(_get_drain().wait(), timeout=SHUTDOWN_TIMEOUT)
        LOGGER.info('All in-flight requests completed')
    except TimeoutError:
        LOGGER.warning(
            'Shutdown timeout reached with %i request(s) still in flight',
            _active,
        )
