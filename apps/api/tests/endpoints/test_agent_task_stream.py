"""Tests for the task event stream and the NOTIFY of each task event.

These run against the live Postgres that ``root:services`` boots. The
stream tests read the endpoint's generator directly: the test client
collects a whole response before it returns, and a stream does not end.
"""

import asyncio
import json
import typing
import uuid
from collections import abc
from unittest import mock

import fastapi.sse
import psycopg
from psycopg import sql

from apps.api.tests.endpoints import test_agent_tasks
from apps.api.tests.test_agent_task_stream_hub import aclose
from imbi.api import agent_tasks
from imbi.api.endpoints import agent_tasks as endpoint

TIMEOUT = 5.0

type Stream = abc.AsyncGenerator[fastapi.sse.ServerSentEvent]


class TaskEventStreamTests(test_agent_tasks.AgentTaskTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.make_agent()
        response = await self.create_task()
        self.assertEqual(response.status_code, 201, response.text)

    async def task(self) -> dict[str, typing.Any]:
        task = await self.store.get(self.org, 'T-1')
        assert task is not None
        return task

    def stream(
        self, task: dict[str, typing.Any], after_seq: int = 0, **kwargs: int
    ) -> Stream:
        gen = typing.cast(
            'Stream',
            endpoint.stream_agent_task_events(
                task, self.store, after_seq=after_seq, **kwargs
            ),
        )
        self.addAsyncCleanup(aclose, gen)
        return gen

    async def take(
        self, gen: Stream, count: int
    ) -> list[dict[str, typing.Any]]:
        """Read ``count`` events; return their data, checking the SSE."""
        result: list[dict[str, typing.Any]] = []
        for _ in range(count):
            sse = await asyncio.wait_for(anext(gen), TIMEOUT)
            self.assertEqual(sse.event, 'task_event')
            assert sse.raw_data is not None
            data = json.loads(sse.raw_data)
            self.assertEqual(sse.id, str(data['seq']))
            result.append(data)
        return result

    async def test_backlog_then_new_events(self) -> None:
        await self.client.post(self.url('T-1/pause'))
        gen = self.stream(await self.task())
        backlog = await self.take(gen, 3)
        self.assertEqual([e['seq'] for e in backlog], [1, 2, 3])
        self.assertEqual(backlog[0]['type'], 'task.created')
        self.assertEqual(
            {e['type'] for e in backlog[1:]},
            {'state.changed', 'control.changed'},
        )
        # The same JSON as the events list.
        listed = (await self.client.get(self.url('T-1/events'))).json()
        self.assertEqual(backlog, listed)

        response = await self.client.post(self.url('T-1/resume'))
        self.assertEqual(response.status_code, 200, response.text)
        new = await self.take(gen, 2)
        self.assertEqual([e['seq'] for e in new], [4, 5])
        self.assertIn('state.changed', {e['type'] for e in new})

    async def test_resumes_from_last_event_id(self) -> None:
        await self.client.post(self.url('T-1/pause'))
        task = await self.task()
        first = self.stream(task)
        self.assertEqual(
            [e['seq'] for e in await self.take(first, 3)], [1, 2, 3]
        )
        await first.aclose()

        await self.client.post(self.url('T-1/resume'))
        # Last-Event-ID wins over a smaller after_seq.
        again = self.stream(task, after_seq=1, last_event_id=3)
        self.assertEqual([e['seq'] for e in await self.take(again, 2)], [4, 5])

    async def test_after_seq_wins_over_smaller_last_event_id(self) -> None:
        await self.client.post(self.url('T-1/pause'))
        gen = self.stream(await self.task(), after_seq=2, last_event_id=1)
        self.assertEqual([e['seq'] for e in await self.take(gen, 1)], [3])

    async def test_closed_task_streams_new_events(self) -> None:
        await self.client.post(self.url('T-1/cancel'))
        task = await self.task()
        self.assertEqual(task['status'], 'closed')
        gen = self.stream(task, after_seq=task['last_seq'])
        # A relation event is written on a closed task while its log is
        # not archived.
        response = await self.client.put(
            self.url(f'T-1/projects/{self.project_id}')
        )
        self.assertEqual(response.status_code, 204, response.text)
        (event,) = await self.take(gen, 1)
        self.assertEqual(event['type'], 'project.associated')

    async def test_unsubscribes_on_close(self) -> None:
        gen = self.stream(await self.task())
        await self.take(gen, 1)
        self.assertEqual(self.store.hub.streams, 1)
        await gen.aclose()
        self.assertEqual(self.store.hub.streams, 0)

    async def test_refused_without_permission(self) -> None:
        self.permissions = set(test_agent_tasks.ALL_PERMISSIONS) - {
            'agent_task:read'
        }
        response = await self.client.get(self.url('T-1/events/stream'))
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn('agent_task:read', response.text)

    async def test_refused_when_full(self) -> None:
        with mock.patch.object(
            self.store.hub, '_count', agent_tasks.stream.MAX_STREAMS
        ):
            response = await self.client.get(self.url('T-1/events/stream'))
        self.assertEqual(response.status_code, 503, response.text)

    async def test_unknown_task_is_404(self) -> None:
        response = await self.client.get(self.url('T-9/events/stream'))
        self.assertEqual(response.status_code, 404, response.text)


class NotifyTests(test_agent_tasks.AgentTaskTestCase):
    async def test_event_insert_notifies(self) -> None:
        await self.make_agent()
        conn = await psycopg.AsyncConnection.connect(
            str(self.pool.conninfo), autocommit=True
        )
        self.addAsyncCleanup(conn.close)
        await conn.execute(
            sql.SQL('LISTEN {}').format(
                sql.Identifier(agent_tasks.stream.NOTIFY_CHANNEL)
            )
        )
        response = await self.create_task()
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()
        notices = [
            json.loads(notice.payload)
            async for notice in conn.notifies(timeout=TIMEOUT, stop_after=1)
        ]
        self.assertEqual(
            notices,
            [
                {
                    'organization_id': self.org,
                    'task_id': task['id'],
                    'short_id': 'T-1',
                    'seq': 1,
                }
            ],
        )

    async def test_rolled_back_event_does_not_notify(self) -> None:
        await self.make_agent()
        response = await self.create_task()
        task_id = uuid.UUID(response.json()['id'])
        conn = await psycopg.AsyncConnection.connect(
            str(self.pool.conninfo), autocommit=True
        )
        self.addAsyncCleanup(conn.close)
        await conn.execute(
            sql.SQL('LISTEN {}').format(
                sql.Identifier(agent_tasks.stream.NOTIFY_CHANNEL)
            )
        )
        async with self.pool.connection() as writer:
            async with writer.transaction(force_rollback=True):
                await agent_tasks.store._append_event(
                    writer,
                    task_id,
                    'turn',
                    {'body': 'never'},
                    agent_tasks.Actor('system', 'test', 'api'),
                )
        notices = [
            notice async for notice in conn.notifies(timeout=0.5, stop_after=1)
        ]
        self.assertEqual(notices, [])
