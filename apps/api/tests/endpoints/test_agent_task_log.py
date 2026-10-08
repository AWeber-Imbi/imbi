"""Tests for the permanent agent task log in ClickHouse (ADR 0020).

These write through the real code and read the rows back from the live
ClickHouse that ``root:services`` boots.
:func:`apps.api.tests.support.sink_to_clickhouse` puts each publish
straight into its table, as the Iggy sink would.
"""

import decimal
import typing
import uuid
from unittest import mock

from apps.api.tests import support
from apps.api.tests.endpoints import (
    test_agent_task_harness,
    test_agent_tasks,
)
from imbi.api import agent_tasks
from imbi.api.agent_tasks import sweeper
from imbi.common import clickhouse, iggy
from imbi.common.clickhouse import client
from scripts import agent_task_client


class ClickHouseTestCase(test_agent_tasks.AgentTaskTestCase):
    """Agent task fixtures with a private ClickHouse client."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # The ClickHouse client binds to the loop that opened it, and each
        # test has its own loop, so each test takes its own client.
        previous = client.Clickhouse._instance
        client.Clickhouse._instance = None

        async def restore() -> None:
            await clickhouse.aclose()
            client.Clickhouse._instance = previous

        self.addAsyncCleanup(restore)
        await clickhouse.initialize()
        await clickhouse.setup_schema()
        sink = support.sink_to_clickhouse()
        sink.__enter__()
        self.addCleanup(sink.__exit__, None, None, None)

    async def stored_events(self, task_id: str) -> list[dict[str, typing.Any]]:
        """Return the ClickHouse rows of a task, with duplicates."""
        return await clickhouse.query(
            'SELECT * FROM imbi.agent_task_events'
            ' WHERE task_id = {task_id:String} ORDER BY seq',
            {'task_id': task_id},
        )

    async def postgres_events(
        self, task_id: str
    ) -> list[dict[str, typing.Any]]:
        return await self.store.events(uuid.UUID(task_id), 0, 1000)


class PublishTests(ClickHouseTestCase):
    async def test_every_event_reaches_clickhouse_once(self) -> None:
        await self.make_agent()
        task = (await self.create_task(project_id=self.project_id)).json()
        for action in ('pause', 'resume', 'cancel'):
            response = await self.client.post(self.url(f'T-1/{action}'))
            self.assertEqual(response.status_code, 200, response.text)

        expected = await self.postgres_events(task['id'])
        stored = await self.stored_events(task['id'])
        self.assertEqual(len(expected), 8)
        self.assertEqual(
            [row['seq'] for row in stored], [e['seq'] for e in expected]
        )
        for event, row in zip(expected, stored, strict=True):
            self.assertEqual(row['event_id'], str(event['event_id']))
            self.assertEqual(row['type'], event['type'])
            self.assertEqual(row['organization_id'], self.org)
            self.assertEqual(row['short_id'], 'T-1')
            self.assertEqual(row['agent_id'], task['agent_id'])
            self.assertEqual(row['agent_version'], 3)
            self.assertEqual(row['project_id'], self.project_id)
            self.assertEqual(row['actor_id'], self.email)
            self.assertEqual(row['channel'], 'web')
            self.assertEqual(clickhouse.as_utc(row['at']), event['at'])

    async def test_publish_failure_does_not_fail_the_write(self) -> None:
        await self.make_agent()
        failing = mock.AsyncMock(side_effect=RuntimeError('Iggy is down'))
        with mock.patch.object(iggy, 'publish_rows', failing):
            response = await self.create_task()
        self.assertEqual(response.status_code, 201, response.text)
        failing.assert_awaited_once()
        self.assertEqual(await self.stored_events(response.json()['id']), [])
        self.assertEqual(
            len(await self.postgres_events(response.json()['id'])), 1
        )


class SweepTests(ClickHouseTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.make_agent()
        self.task = (await self.create_task()).json()
        # The pause events never reach ClickHouse.
        failing = mock.AsyncMock(side_effect=RuntimeError('Iggy is down'))
        with mock.patch.object(iggy, 'publish_rows', failing):
            response = await self.client.post(self.url('T-1/pause'))
        self.assertEqual(response.status_code, 200, response.text)

    async def get_log(
        self, **params: typing.Any
    ) -> list[dict[str, typing.Any]]:
        response = await self.client.get(self.url('T-1/events'), params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_sweep_republishes_missing_rows(self) -> None:
        stored = await self.stored_events(self.task['id'])
        self.assertEqual([row['seq'] for row in stored], [1])
        result = await sweeper.sweep_once(self.store)
        self.assertGreaterEqual(result.republished_events, 2)
        stored = await self.stored_events(self.task['id'])
        self.assertEqual([row['seq'] for row in stored], [1, 2, 3])
        # A complete open task is not archived.
        await sweeper.sweep_once(self.store)
        task = await self.store.get(self.org, 'T-1')
        assert task is not None
        self.assertIsNone(task['log_archived_at'])
        self.assertEqual(len(await self.postgres_events(self.task['id'])), 3)
        self.assertEqual(len(await self.stored_events(self.task['id'])), 3)

    async def test_one_failed_task_does_not_stop_the_sweep(self) -> None:
        failing = mock.AsyncMock(side_effect=RuntimeError('Iggy is down'))
        with mock.patch.object(iggy, 'publish_rows', failing):
            other = (await self.create_task()).json()
        self.assertEqual(await self.stored_events(other['id']), [])
        # The sweep goes by task id, so the lower id is swept first.
        first, last = sorted((self.task['id'], other['id']))
        stored_seqs = sweeper.log.stored_seqs

        async def fail_first(task: dict[str, typing.Any]) -> set[int]:
            if str(task['id']) == first:
                raise RuntimeError('ClickHouse is down')
            return await stored_seqs(task)

        with mock.patch.object(sweeper.log, 'stored_seqs', fail_first):
            result = await sweeper.sweep_once(self.store)
        self.assertGreaterEqual(result.republished_events, 1)
        self.assertEqual(
            [row['seq'] for row in await self.stored_events(last)],
            [event['seq'] for event in await self.postgres_events(last)],
        )

    async def test_one_failed_session_close_does_not_stop_the_sweep(
        self,
    ) -> None:
        stale = [
            {
                'id': uuid.uuid4(),
                'organization_id': self.org,
                'short_id': 'T-1',
            }
            for _ in range(2)
        ]
        close = mock.AsyncMock(side_effect=RuntimeError('Postgres is down'))
        with (
            mock.patch.object(
                self.store,
                'stale_sessions',
                mock.AsyncMock(return_value=stale),
            ),
            mock.patch.object(self.store, 'close_session', close),
        ):
            result = await sweeper.sweep_once(self.store)
        self.assertEqual(close.await_count, 2)
        self.assertEqual(result.closed_sessions, 0)

    async def test_archive_moves_the_log_to_clickhouse(self) -> None:
        response = await self.client.post(self.url('T-1/cancel'))
        self.assertEqual(response.json()['status'], 'closed')
        before = await self.get_log()
        page = await self.get_log(after_seq=1, limit=2)
        self.assertEqual([e['seq'] for e in before], [1, 2, 3, 4, 5, 6])

        # The first round only republishes; the task is not complete.
        await sweeper.sweep_once(self.store)
        task = await self.store.get(self.org, 'T-1')
        assert task is not None
        self.assertIsNone(task['log_archived_at'])

        await sweeper.sweep_once(self.store)
        task = await self.store.get(self.org, 'T-1')
        assert task is not None
        self.assertIsNotNone(task['log_archived_at'])
        self.assertEqual(await self.postgres_events(self.task['id']), [])
        self.assertEqual(await self.get_log(), before)
        self.assertEqual(await self.get_log(after_seq=1, limit=2), page)
        self.assertEqual(await self.get_log(after_seq=6), [])
        # An archived task is not swept again.
        self.assertFalse(await self.store.archive(task['id'], 6))

    async def test_sweep_republishes_usage_rows(self) -> None:
        actor = agent_tasks.Actor('agent', 'agent-1', 'harness')
        prices: dict[str, decimal.Decimal | None] = {
            'input_cost_per_million': decimal.Decimal(3),
            'output_cost_per_million': decimal.Decimal(15),
            'cache_read_cost_per_million': None,
            'cache_write_cost_per_million': None,
        }
        failing = mock.AsyncMock(side_effect=RuntimeError('Iggy is down'))
        with mock.patch.object(iggy, 'publish_rows', failing):
            _task, row, _created = await self.store.report_usage(
                self.org,
                'T-1',
                agent_tasks.Usage('u-1', 'opus', 1000, 100, None, None, None),
                prices,
                actor=actor,
                system=actor,
            )
        query = (
            'SELECT * FROM imbi.agent_usage WHERE task_id = {task_id:String}'
        )
        params = {'task_id': self.task['id']}
        self.assertEqual(await clickhouse.query(query, params), [])
        result = await sweeper.sweep_once(self.store)
        self.assertGreaterEqual(result.republished_reports, 1)
        (stored,) = await clickhouse.query(query, params)
        self.assertEqual(stored['report_id'], str(row['id']))
        self.assertEqual(stored['model_id'], 'opus')
        self.assertEqual(stored['tokens_in'], 1000)
        self.assertIsNone(stored['cache_read_tokens'])
        self.assertEqual(stored['input_cost_per_million'], 3)
        self.assertIsNone(stored['cache_read_cost_per_million'])
        self.assertEqual(stored['cost'], decimal.Decimal('0.0045'))
        self.assertEqual(stored['short_id'], 'T-1')


class ReferenceClientTests(
    test_agent_task_harness.HarnessTestCase, ClickHouseTestCase
):
    """The reference client drives a task from ``queued`` to ``closed``."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.slug = f'opus-{uuid.uuid4().hex[:8]}'
        await self.make_model(self.slug, self.slug)

    async def test_run_task_end_to_end(self) -> None:
        harness = agent_task_client.HarnessClient(self.client, self.org, 'T-1')
        state = await agent_task_client.run_task(harness, model_id=self.slug)
        self.assertEqual(state['status'], 'closed')
        self.assertEqual(state['outcome'], 'done_acted')
        self.assertEqual(state['phase'], 'done')

        expected = await self.postgres_events(self.task['id'])
        self.assertEqual(
            [e['type'] for e in expected],
            [
                'task.created',
                'session.opened',
                'state.changed',
                'phase.changed',
                'turn',
                'tool.called',
                'usage.reported',
                'todos.updated',
                'check.reported',
                'phase.changed',
                'turn',
                'session.closed',
                'state.changed',
                'outcome.set',
            ],
        )
        # Every Postgres event has exactly one ClickHouse row.
        stored = await self.stored_events(self.task['id'])
        self.assertEqual(
            [(row['seq'], row['event_id']) for row in stored],
            [(e['seq'], str(e['event_id'])) for e in expected],
        )

        # The usage totals in Postgres match ClickHouse.
        task = await self.task_row()
        (usage,) = await clickhouse.query(
            'SELECT sum(tokens_in) AS tokens_in,'
            ' sum(tokens_out) AS tokens_out,'
            ' sum(cache_read_tokens) AS cache_read_tokens,'
            ' sum(cache_write_tokens) AS cache_write_tokens,'
            ' sum(cost) AS cost, count() AS reports'
            ' FROM imbi.agent_usage WHERE task_id = {task_id:String}',
            {'task_id': self.task['id']},
        )
        self.assertEqual(usage['reports'], 1)
        for column in (
            'tokens_in',
            'tokens_out',
            'cache_read_tokens',
            'cache_write_tokens',
        ):
            self.assertEqual(usage[column], task[column], column)
        self.assertEqual(usage['cost'], task['cost_total'])
        self.assertGreater(task['cost_total'], 0)

    async def test_run_task_with_a_request_leaves_it_blocked(self) -> None:
        harness = agent_task_client.HarnessClient(self.client, self.org, 'T-1')
        state = await agent_task_client.run_task(
            harness, model_id=self.slug, ask=True
        )
        self.assertEqual(state['status'], 'blocked')
        self.assertEqual((await self.task_row())['status'], 'blocked')


class OpsLogTests(test_agent_task_harness.HarnessTestCase, ClickHouseTestCase):
    """Resolutions and outcomes of project tasks go to the Operations Log."""

    async def resolve_and_close(self, short_id: str) -> list[str]:
        """Approve a request and close the task; return the event ids."""
        response = await self.post(
            'requests',
            {
                'kind': 'approval',
                'title': 'Merge the secret fix',
                'artifact_digests': ['sha256:ab'],
            },
            short_id,
        )
        request_id = response.json()['request']['id']
        response = await self.as_user(
            'POST',
            f'{short_id}/requests/{request_id}/resolve',
            json={'status': 'approved', 'artifact_digests': ['sha256:ab']},
        )
        self.assertEqual(response.status_code, 201, response.text)
        await self.post('outcome', {'outcome': 'done_acted'}, short_id)
        task = await self.task_row(short_id)
        return [
            str(e['event_id'])
            for e in await self.postgres_events(str(task['id']))
            if e['type'] in ('request.resolved', 'outcome.set')
        ]

    async def opslog(self, ids: list[str]) -> list[dict[str, typing.Any]]:
        return await clickhouse.query(
            'SELECT * FROM imbi.operations_log FINAL'
            ' WHERE id IN {ids:Array(String)} ORDER BY occurred_at',
            {'ids': ids},
        )

    async def test_project_task_rows(self) -> None:
        self.act_as_user()
        response = await self.create_task(project_id=self.project_id)
        self.act_as(self.account)
        ids = await self.resolve_and_close('T-2')
        rows = await self.opslog(ids)
        self.assertEqual(
            [
                (
                    row['id'],
                    row['entry_type'],
                    row['description'],
                    row['performed_by'],
                    row['project_id'],
                    row['project_slug'],
                )
                for row in rows
            ],
            [
                (
                    ids[0],
                    'Agent Task',
                    'T-2: approval request approved',
                    self.email,
                    self.project_id,
                    self.project_id,
                ),
                (
                    ids[1],
                    'Agent Task',
                    'T-2 closed: done_acted',
                    response.json()['agent_id'],
                    self.project_id,
                    self.project_id,
                ),
            ],
        )
        for row in rows:
            self.assertIsNotNone(row['completed_at'])

        # A republish by the sweep collapses on the id.
        task = await self.task_row('T-2')
        await agent_tasks.log.publish(
            task, await self.postgres_events(str(task['id']))
        )
        self.assertEqual(len(await self.opslog(ids)), 2)

    async def test_task_without_project_has_no_rows(self) -> None:
        ids = await self.resolve_and_close('T-1')
        self.assertEqual(len(ids), 2)
        self.assertEqual(await self.opslog(ids), [])


class StaleSessionTests(
    test_agent_task_harness.HarnessTestCase, ClickHouseTestCase
):
    agent_settings: typing.ClassVar[dict[str, typing.Any]] = {
        'max_concurrent_tasks': 2
    }

    async def backdate(self, session_id: str, opened: int, beat: int) -> None:
        """Move a session's opened_at and heartbeat_at minutes back."""
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE agent_runtime.sessions'
                ' SET opened_at = NOW() - make_interval(mins => %s),'
                ' heartbeat_at = NOW() - make_interval(mins => %s)'
                ' WHERE id = %s',
                (opened, beat, uuid.UUID(session_id)),
            )

    async def test_sweep_closes_stale_sessions(self) -> None:
        self.act_as_user()
        for _ in range(2):
            await self.create_task()
        self.act_as(self.account)
        stale = (await self.open_session())['session']
        fresh = (await self.open_session(short_id='T-2'))['session']
        # The heartbeat, not the open time, is the last sign of life.
        await self.backdate(stale['id'], opened=10, beat=6)
        await self.backdate(fresh['id'], opened=10, beat=1)
        response = await self.post('sessions', {'session_key': 'c'}, 'T-3')
        self.assertEqual(response.status_code, 409, response.text)

        result = await sweeper.sweep_once(self.store)
        self.assertGreaterEqual(result.closed_sessions, 1)
        task = await self.task_row()
        self.assertEqual(task['status'], 'queued')
        events = await self.events()
        self.assertEqual(
            [e['type'] for e in events[-2:]],
            ['session.closed', 'state.changed'],
        )
        self.assertEqual(
            events[-2]['payload'],
            {'session_id': stale['id'], 'reason': 'heartbeat_lost'},
        )
        self.assertEqual(events[-2]['actor_kind'], 'system')
        self.assertEqual(
            events[-1]['payload'],
            {'from': 'running', 'to': 'queued', 'reason': 'session_closed'},
        )
        # The fresh session is not touched.
        state = await self.post(
            f'sessions/{fresh["id"]}/heartbeat', None, 'T-2'
        )
        self.assertEqual(state.status_code, 200, state.text)
        self.assertEqual(state.json()['status'], 'running')
        # The stale session no longer counts toward the limit.
        response = await self.post('sessions', {'session_key': 'c'}, 'T-3')
        self.assertEqual(response.status_code, 201, response.text)
