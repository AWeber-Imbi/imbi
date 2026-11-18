"""Unit tests for the task event hub and stream, with a fake ``LISTEN``
connection and a fake store."""

import asyncio
import datetime
import types
import typing
import unittest
import uuid
from collections import abc

import fastapi.sse
import orjson
import psycopg

from imbi.api.agent_tasks import stream
from imbi.api.endpoints import agent_tasks as endpoint

TIMEOUT = 2.0


async def aclose(gen: abc.AsyncGenerator[typing.Any]) -> None:
    """Close a generator in a cleanup, which awaits only coroutines."""
    await gen.aclose()


class FakeConnection:
    """Enough of an autocommit connection for :class:`stream.EventHub`."""

    def __init__(self) -> None:
        self.notices: asyncio.Queue[str | None] = asyncio.Queue()
        self.executed: list[str] = []
        self.closed = False

    async def __aenter__(self) -> typing.Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        self.closed = True

    async def execute(self, query: typing.Any) -> None:
        self.executed.append(
            query.as_string() if hasattr(query, 'as_string') else str(query)
        )

    async def notifies(self) -> abc.AsyncGenerator[types.SimpleNamespace]:
        while True:
            payload = await self.notices.get()
            if payload is None:
                raise psycopg.OperationalError('connection lost')
            yield types.SimpleNamespace(payload=payload)


def notice(task_id: uuid.UUID, seq: int = 1) -> str:
    return orjson.dumps(
        {
            'organization_id': 'org',
            'task_id': str(task_id),
            'short_id': 'T-1',
            'seq': seq,
        }
    ).decode()


class EventHubTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.connections: list[FakeConnection] = []

        async def connect() -> typing.Any:
            conn = FakeConnection()
            self.connections.append(conn)
            return conn

        self.hub = stream.EventHub(connect, max_streams=2)
        self.addAsyncCleanup(self.hub.close)

    async def wait_set(self, wake: asyncio.Event) -> None:
        await asyncio.wait_for(wake.wait(), TIMEOUT)

    async def test_wakes_only_the_streams_of_the_task(self) -> None:
        first, second = uuid.uuid4(), uuid.uuid4()
        async with (
            self.hub.subscribe(first) as wake_first,
            self.hub.subscribe(second) as wake_second,
        ):
            (conn,) = self.connections
            self.assertEqual(conn.executed, ['LISTEN "agent_task_events"'])
            # Connecting wakes every stream, to resync.
            wake_first.clear()
            wake_second.clear()
            conn.notices.put_nowait(notice(first))
            await self.wait_set(wake_first)
            self.assertFalse(wake_second.is_set())

    async def test_ignores_a_bad_payload(self) -> None:
        task_id = uuid.uuid4()
        async with self.hub.subscribe(task_id) as wake:
            wake.clear()
            conn = self.connections[0]
            conn.notices.put_nowait('not json')
            conn.notices.put_nowait('{}')
            conn.notices.put_nowait(notice(task_id))
            await self.wait_set(wake)

    async def test_one_listener_closed_after_the_last_stream(self) -> None:
        task_id = uuid.uuid4()
        async with self.hub.subscribe(task_id):
            async with self.hub.subscribe(task_id):
                self.assertEqual(self.hub.streams, 2)
            self.assertEqual(len(self.connections), 1)
            self.assertFalse(self.connections[0].closed)
        self.assertEqual(self.hub.streams, 0)
        self.assertTrue(self.connections[0].closed)
        async with self.hub.subscribe(task_id):
            self.assertEqual(len(self.connections), 2)

    async def test_refuses_more_than_max_streams(self) -> None:
        async with (
            self.hub.subscribe(uuid.uuid4()),
            self.hub.subscribe(uuid.uuid4()),
        ):
            with self.assertRaises(stream.TooManyStreams):
                async with self.hub.subscribe(uuid.uuid4()):
                    pass
            self.assertEqual(self.hub.streams, 2)

    async def test_reconnect_wakes_every_stream(self) -> None:
        stream.RETRY_MIN_DELAY, saved = 0.0, stream.RETRY_MIN_DELAY
        self.addCleanup(setattr, stream, 'RETRY_MIN_DELAY', saved)
        task_id = uuid.uuid4()
        async with self.hub.subscribe(task_id) as wake:
            wake.clear()
            self.connections[0].notices.put_nowait(None)
            await self.wait_set(wake)
            self.assertEqual(len(self.connections), 2)

    async def test_listener_unavailable(self) -> None:
        async def refuse() -> typing.Any:
            raise psycopg.OperationalError('down')

        hub = stream.EventHub(refuse, ready_timeout=0.05)
        self.addAsyncCleanup(hub.close)
        with self.assertRaises(stream.ListenerUnavailable):
            async with hub.subscribe(uuid.uuid4()):
                pass
        self.assertEqual(hub.streams, 0)


class FakeStore:
    """The reads of :class:`TaskStore` that the stream uses."""

    def __init__(self, hub: stream.EventHub) -> None:
        self.hub = hub
        self.rows: list[dict[str, typing.Any]] = []

    def add(self, seq: int) -> None:
        self.rows.append(
            {
                'event_id': uuid.uuid4(),
                'seq': seq,
                'type': 'turn',
                'schema_version': 1,
                'actor_kind': 'agent',
                'actor_id': 'bot',
                'channel': 'harness',
                'session_id': None,
                'at': datetime.datetime.now(datetime.UTC),
                'payload': {'body': f'turn {seq}'},
            }
        )

    async def events(
        self, task_id: uuid.UUID, after_seq: int, limit: int
    ) -> list[dict[str, typing.Any]]:
        del task_id
        return [r for r in self.rows if r['seq'] > after_seq][:limit]


type Stream = abc.AsyncGenerator[fastapi.sse.ServerSentEvent]


class TaskEventStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.connections: list[FakeConnection] = []

        async def connect() -> typing.Any:
            conn = FakeConnection()
            self.connections.append(conn)
            return conn

        hub = stream.EventHub(connect)
        self.addAsyncCleanup(hub.close)
        self.store = FakeStore(hub)
        self.task: dict[str, typing.Any] = {
            'id': uuid.uuid4(),
            'short_id': 'T-1',
            'log_archived_at': None,
        }

    def open(self, after_seq: int = 0, **kwargs: typing.Any) -> Stream:
        gen = typing.cast(
            'Stream',
            endpoint.task_event_stream(
                typing.cast('typing.Any', self.store),
                self.task,
                after_seq,
                **kwargs,
            ),
        )
        self.addAsyncCleanup(aclose, gen)
        return gen

    async def seqs(self, gen: Stream, count: int) -> list[int]:
        result: list[int] = []
        for _ in range(count):
            sse = await asyncio.wait_for(anext(gen), TIMEOUT)
            self.assertEqual(sse.event, 'task_event')
            assert sse.raw_data is not None
            assert sse.id is not None
            self.assertEqual(orjson.loads(sse.raw_data)['seq'], int(sse.id))
            result.append(int(sse.id))
        return result

    def write(self, seq: int) -> None:
        self.store.add(seq)
        self.connections[-1].notices.put_nowait(notice(self.task['id'], seq))

    async def test_backlog_then_new_events_once_each(self) -> None:
        for seq in (1, 2):
            self.store.add(seq)
        gen = self.open()
        self.assertEqual(await self.seqs(gen, 2), [1, 2])
        self.write(3)
        # A repeated notice sends nothing again.
        self.connections[-1].notices.put_nowait(notice(self.task['id'], 3))
        self.write(4)
        self.assertEqual(await self.seqs(gen, 2), [3, 4])

    async def test_resumes_after_last_event_id(self) -> None:
        for seq in (1, 2, 3):
            self.store.add(seq)
        gen = typing.cast(
            'Stream',
            endpoint.stream_agent_task_events(
                self.task,
                typing.cast('typing.Any', self.store),
                after_seq=1,
                last_event_id=2,
            ),
        )
        self.addAsyncCleanup(aclose, gen)
        self.assertEqual(await self.seqs(gen, 1), [3])

    async def test_reads_again_without_a_wake(self) -> None:
        gen = self.open(resync=0.05)
        # Written with no notice, as when the listener was away.
        self.store.add(1)
        self.assertEqual(await self.seqs(gen, 1), [1])

    async def test_pages_through_a_long_backlog(self) -> None:
        last = endpoint.STREAM_PAGE + 2
        for seq in range(1, last + 1):
            self.store.add(seq)
        gen = self.open()
        self.assertEqual(await self.seqs(gen, last), list(range(1, last + 1)))

    async def test_ends_when_the_listener_is_unavailable(self) -> None:
        async def refuse() -> typing.Any:
            raise psycopg.OperationalError('down')

        self.store.hub = stream.EventHub(refuse, ready_timeout=0.05)
        self.addAsyncCleanup(self.store.hub.close)
        gen = self.open()
        with self.assertRaises(StopAsyncIteration):
            await asyncio.wait_for(anext(gen), TIMEOUT)
