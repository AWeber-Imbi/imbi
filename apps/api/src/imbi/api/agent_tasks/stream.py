"""Wake the event streams of a task when it gets an event.

Each event write sends ``NOTIFY`` on :data:`NOTIFY_CHANNEL` in its
transaction (see :mod:`imbi.api.agent_tasks.store`).
:class:`EventHub` holds one ``LISTEN`` connection per process, opened
when the first stream subscribes and closed when the last one leaves,
and wakes the streams of the task in each notice.

A wake is a hint. The stream reads the events after its last ``seq``
from the table, so a notice that is lost or that comes two times costs
nothing. After the listener reconnects, it wakes every stream, because
notices sent while it was away are lost.

The listener uses its own connection, not one from the task store pool:
a connection that ends with ``LISTEN`` active must not go back to the
pool, and the stream count must not take pool connections away from
requests.
"""

import asyncio
import contextlib
import logging
import typing
import uuid
from collections import abc

import orjson
import psycopg
import psycopg_pool
from psycopg import sql

LOGGER = logging.getLogger(__name__)

#: ``NOTIFY`` channel of new task events. The payload is a JSON object
#: with ``organization_id``, ``task_id``, ``short_id``, and ``seq``.
NOTIFY_CHANNEL = 'agent_task_events'

#: The most streams that one process holds open. One more gets
#: :class:`TooManyStreams`.
MAX_STREAMS = 500

#: How long a new stream waits for the listener to connect.
READY_TIMEOUT = 5.0

#: Backoff bounds for reconnecting a lost listener.
RETRY_MIN_DELAY = 1.0
RETRY_MAX_DELAY = 30.0


class TooManyStreams(RuntimeError):
    """This process holds :data:`MAX_STREAMS` streams."""


class ListenerUnavailable(RuntimeError):
    """The listener did not connect within :data:`READY_TIMEOUT`."""


type Connection = psycopg.AsyncConnection[typing.Any]
type Connect = abc.Callable[[], abc.Awaitable[Connection]]


class EventHub:
    """One ``LISTEN`` connection that wakes the streams of each task."""

    def __init__(
        self,
        connect: Connect,
        *,
        max_streams: int = MAX_STREAMS,
        ready_timeout: float = READY_TIMEOUT,
    ) -> None:
        self._connect = connect
        self._max_streams = max_streams
        self._ready_timeout = ready_timeout
        self._wakes: dict[str, set[asyncio.Event]] = {}
        self._count = 0
        self._listener: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()

    @property
    def streams(self) -> int:
        """The number of streams that are subscribed."""
        return self._count

    @contextlib.asynccontextmanager
    async def subscribe(
        self, task_id: uuid.UUID
    ) -> abc.AsyncGenerator[asyncio.Event]:
        """Subscribe to the events of a task; yield its wake event.

        The listener is connected when this yields, so a stream that
        reads its backlog after this sees every later event: in that
        read, or by a wake. The caller clears the wake event.

        Raises:
            TooManyStreams: The process holds too many streams.
            ListenerUnavailable: The listener could not connect.

        """
        if self._count >= self._max_streams:
            raise TooManyStreams(str(self._count))
        key = str(task_id)
        wake = asyncio.Event()
        self._wakes.setdefault(key, set()).add(wake)
        self._count += 1
        try:
            if self._listener is None or self._listener.done():
                self._ready = asyncio.Event()
                self._listener = asyncio.create_task(self._listen(self._ready))
            try:
                await asyncio.wait_for(self._ready.wait(), self._ready_timeout)
            except TimeoutError as error:
                raise ListenerUnavailable from error
            yield wake
        finally:
            waiters = self._wakes.get(key, set())
            waiters.discard(wake)
            if not waiters:
                self._wakes.pop(key, None)
            self._count -= 1
            if self._count == 0:
                await self._stop()

    async def close(self) -> None:
        """Stop the listener. Streams that are open stay subscribed."""
        await self._stop()

    async def _stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is None:
            return
        listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener

    def _wake_all(self) -> None:
        for waiters in self._wakes.values():
            for wake in waiters:
                wake.set()

    def _dispatch(self, payload: str) -> None:
        try:
            task_id = orjson.loads(payload)['task_id']
        except (orjson.JSONDecodeError, KeyError, TypeError):
            LOGGER.warning('Ignoring a task event notice: %r', payload)
            return
        for wake in self._wakes.get(str(task_id), ()):
            wake.set()

    async def _listen(self, ready: asyncio.Event) -> None:
        """Hold ``LISTEN`` and reconnect with backoff until cancelled."""
        delay = RETRY_MIN_DELAY
        while True:
            try:
                async with await self._connect() as conn:
                    await conn.execute(
                        sql.SQL('LISTEN {}').format(
                            sql.Identifier(NOTIFY_CHANNEL)
                        )
                    )
                    delay = RETRY_MIN_DELAY
                    ready.set()
                    # Notices sent while no listener was connected are
                    # lost, so every stream reads again.
                    self._wake_all()
                    async for notice in conn.notifies():
                        self._dispatch(notice.payload)
            except (psycopg.Error, OSError):
                LOGGER.warning(
                    'Task event listener stopped; retrying in %ss',
                    delay,
                    exc_info=True,
                )
            else:
                LOGGER.warning(
                    'Task event listener: the connection ended;'
                    ' retrying in %ss',
                    delay,
                )
            ready.clear()
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX_DELAY)


def connector(
    pool: psycopg_pool.AsyncConnectionPool[typing.Any],
) -> Connect:
    """Return a :data:`Connect` for an autocommit connection to the
    database of ``pool``, outside the pool."""

    async def connect() -> Connection:
        if not isinstance(pool.conninfo, str):
            raise TypeError('The pool conninfo is not a string')
        return await psycopg.AsyncConnection.connect(
            pool.conninfo, autocommit=True
        )

    return connect
