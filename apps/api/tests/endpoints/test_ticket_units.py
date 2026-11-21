"""Tests for the run view of the ticket list (``group_by=run``).

A unit of work is the tickets of one workflow run with their
descendants, or a ticket without a run and its descendants. Fixtures
are in :mod:`apps.api.tests.endpoints.test_agent_tasks`.
"""

import datetime
import typing
import uuid

from psycopg.types import json as pg_json

from apps.api.tests.endpoints import test_agent_tasks
from imbi.api import tickets, workflows

T0 = datetime.datetime(2026, 11, 1, 12, 0, tzinfo=datetime.UTC)


class TicketUnitTests(test_agent_tasks.AgentTaskTestCase):
    """The org has:

    - run A of ``impl`` (Jira PSE-1): T-1 and T-2 closed, T-3 running,
      and T-4, a child of T-2 without a run id, closed;
    - T-5, a person ticket without a run, queued, with its child T-6
      and grandchild T-7, both queued;
    - run B of ``impl``: T-8 closed, without a subject;
    - T-9, without a run, closed;
    - T-10, without a run, waiting on a person.
    """

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await workflows.initialize()
        self.addAsyncCleanup(self._cleanup_runs)
        definitions = workflows.WorkflowStore(self.pool)
        await definitions.create(
            self.org,
            'impl',
            workflows.Definition(
                name='Ticket implementation',
                description='',
                owner_team_id='team',
                graph={'nodes': [], 'edges': []},
                settings={},
                validation={'issues': []},
                author='ops@example.com',
            ),
        )
        self.run_a = await self.make_run({'ticket_key': 'PSE-1'})
        self.run_b = await self.make_run({'count': 3})
        t1 = await self.ticket('Implement PSE-1', 1, run=self.run_a)
        t2 = await self.ticket('Review PSE-1: round 1', 2, run=self.run_a)
        await self.ticket('Merge check PSE-1', 3, run=self.run_a)
        t4 = await self.ticket('Run tests for T-2', 4, parent=t2)
        t5 = await self.ticket('Write the notes', 5)
        t6 = await self.ticket('Draft section 1', 6, parent=t5)
        await self.ticket('Check spelling', 7, parent=t6)
        t8 = await self.ticket('Implement PSE-2', 8, run=self.run_b)
        t9 = await self.ticket('Rotate keys', 9)
        await self.ticket('Ask about access', 10)
        for row, outcome, closed in [
            (t1, 'done_acted', 20),
            (t2, 'done_acted', 21),
            (t4, 'done_acted', 22),
            (t8, 'done_nothing_to_act_on', 30),
            (t9, 'failed', 25),
        ]:
            await self.close(row, outcome, closed)
        await self.set_status('T-3', 'running')
        await self.store.open_request(
            self.org,
            'T-10',
            tickets.NewRequest(
                kind='feedback',
                title='Which account?',
                why=None,
                options=None,
                artifacts=None,
                artifact_digests=None,
                expires_at=None,
                session_id=None,
            ),
            tickets.Actor('agent', 'triage', 'harness'),
        )

    async def _cleanup_runs(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM workflow_runtime.runs WHERE organization_id = %s',
                (self.org,),
            )
            await conn.execute(
                'DELETE FROM workflows.workflows WHERE organization_id = %s',
                (self.org,),
            )

    async def make_run(self, payload: dict[str, typing.Any]) -> str:
        run_id = uuid.uuid4()
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO workflow_runtime.runs (id, organization_id,'
                ' workflow_id, version, trigger_node_id, origin_kind,'
                ' origin_id, activated_by, payload)'
                ' SELECT %s, organization_id, id, 1, %s, %s, %s, %s, %s'
                ' FROM workflows.workflows'
                " WHERE organization_id = %s AND slug = 'impl'",
                (
                    run_id,
                    'trigger',
                    'human',
                    self.email,
                    self.email,
                    pg_json.Jsonb(payload),
                    self.org,
                ),
            )
        return str(run_id)

    async def ticket(
        self,
        title: str,
        minute: int,
        *,
        run: str | None = None,
        parent: dict[str, typing.Any] | None = None,
    ) -> dict[str, typing.Any]:
        """Make a ticket created ``minute`` minutes after T0."""
        origin: dict[str, typing.Any] = {'kind': 'human', 'user': self.email}
        if run is not None:
            origin |= {'workflow_run_id': run, 'node_key': f'step-{minute}'}
        if parent is not None:
            origin = {
                'kind': 'ticket',
                'task_id': str(parent['id']),
                'short_id': parent['short_id'],
            }
        row, _ = await self.store.create(
            tickets.NewTask(
                organization_id=self.org,
                agent_id='agent-1',
                agent_version=1,
                prompt_version=None,
                service_account_id='sa-1',
                title=title,
                description='',
                origin_kind=str(origin['kind']),
                origin_id=str(parent['id']) if parent else self.email,
                origin=origin,
                idempotency_key=None,
                owner=self.email,
                budget=None,
                chain_id=parent['chain_id'] if parent else None,
            ),
            tickets.Actor('human', self.email, 'api'),
            {},
        )
        at = T0 + datetime.timedelta(minutes=minute)
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE tickets.tickets SET created_at = %s, updated_at = %s,'
                ' cost_total = %s WHERE id = %s',
                (at, at, minute, row['id']),
            )
        return row

    async def set_status(self, short_id: str, status: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE tickets.tickets SET status = %s'
                ' WHERE organization_id = %s AND short_id = %s',
                (status, self.org, short_id),
            )

    async def close(
        self, row: dict[str, typing.Any], outcome: str, minute: int
    ) -> None:
        at = T0 + datetime.timedelta(minutes=minute)
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE tickets.tickets SET status = 'closed', outcome = %s,"
                ' closed_at = %s, updated_at = %s WHERE id = %s',
                (outcome, at, at, row['id']),
            )

    async def units(self, **params: typing.Any) -> list[dict[str, typing.Any]]:
        response = await self.client.get(
            self.url(), params={'group_by': 'run', **params}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return typing.cast('list[dict[str, typing.Any]]', response.json())

    async def counts(self, **params: typing.Any) -> dict[str, int]:
        response = await self.client.get(self.url('counts'), params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return typing.cast('dict[str, int]', response.json())

    @staticmethod
    def ids(rows: list[dict[str, typing.Any]]) -> list[str]:
        return [row['short_id'] for row in rows]

    async def test_default_mode_is_one_row_per_ticket(self) -> None:
        response = await self.client.get(self.url(), params={'limit': 100})
        rows = response.json()
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(row['unit'] is None for row in rows))
        self.assertEqual(
            await self.counts(),
            {'input': 1, 'running': 1, 'paused': 0, 'queued': 3, 'closed': 5},
        )

    async def test_counts_units_and_tickets(self) -> None:
        self.assertEqual(
            await self.counts(group_by='run'),
            {
                'input': 1,
                'running': 1,
                'paused': 0,
                'queued': 1,
                'closed': 2,
                'tickets': 10,
            },
        )

    async def test_groups_by_run_and_folds_children(self) -> None:
        rows = await self.units()
        # Input, running, queued, then closed newest close first.
        # The row of a unit is its most recently updated ticket in its
        # group: T-7 for T-5 and its descendants.
        self.assertEqual(self.ids(rows), ['T-10', 'T-3', 'T-7', 'T-8', 'T-9'])
        run = rows[1]['unit']
        self.assertEqual(run['run_id'], self.run_a)
        self.assertEqual(run['key'], f'run:{self.run_a}')
        self.assertEqual(run['workflow_slug'], 'impl')
        self.assertEqual(run['workflow_name'], 'Ticket implementation')
        self.assertEqual(run['subject'], 'PSE-1')
        self.assertEqual((run['tickets'], run['children']), (4, 1))
        self.assertEqual(float(run['cost_total']), 1 + 2 + 3 + 4)
        self.assertEqual(
            [i['short_id'] for i in run['items']], ['T-1', 'T-2', 'T-3', 'T-4']
        )
        child = run['items'][3]
        self.assertEqual(child['parent_short_id'], 'T-2')
        self.assertTrue(child['nested'])
        self.assertIsNone(child['node_key'])
        self.assertEqual(run['items'][0]['node_key'], 'step-1')
        self.assertEqual(run['items'][0]['outcome'], 'done_acted')
        self.assertFalse(run['truncated'])
        # A ticket without a run gathers its descendants.
        notes = rows[2]['unit']
        self.assertIsNone(notes['run_id'])
        self.assertIsNone(notes['workflow_slug'])
        self.assertEqual((notes['tickets'], notes['children']), (3, 2))
        self.assertEqual(
            [i['short_id'] for i in notes['items']], ['T-5', 'T-6', 'T-7']
        )
        # A run whose payload names no subject.
        self.assertIsNone(rows[3]['unit']['subject'])
        self.assertEqual(rows[3]['unit']['tickets'], 1)
        self.assertEqual(rows[4]['unit']['tickets'], 1)

    async def test_unit_takes_its_most_urgent_group(self) -> None:
        # One running ticket and three closed: the run is running, and
        # its row is its running ticket.
        rows = await self.units(group='running')
        self.assertEqual(self.ids(rows), ['T-3'])
        await self.set_status('T-3', 'paused')
        self.assertEqual(self.ids(await self.units(group='running')), [])
        self.assertEqual(self.ids(await self.units(group='paused')), ['T-3'])
        await self.close({'id': await self.id_of('T-3')}, 'done_acted', 40)
        # Closed: the row is the most recently updated ticket.
        rows = await self.units(group='closed')
        self.assertEqual(self.ids(rows), ['T-3', 'T-8', 'T-9'])
        self.assertEqual(rows[0]['unit']['tickets'], 4)

    async def id_of(self, short_id: str) -> uuid.UUID:
        row = await self.store.get(self.org, short_id)
        assert row is not None
        return typing.cast('uuid.UUID', row['id'])

    async def test_pages_over_units(self) -> None:
        self.assertEqual(
            self.ids(await self.units(group='closed', limit=1)), ['T-8']
        )
        self.assertEqual(
            self.ids(await self.units(group='closed', limit=1, offset=1)),
            ['T-9'],
        )
        self.assertEqual(
            self.ids(await self.units(limit=2, offset=2)), ['T-7', 'T-8']
        )
        response = await self.client.get(
            self.url(), params={'group_by': 'run', 'limit': 1}
        )
        self.assertNotIn('cursor=', response.headers.get('Link', ''))
        response = await self.client.get(
            self.url(), params={'group_by': 'run', 'cursor': 'x'}
        )
        self.assertEqual(response.status_code, 400, response.text)

    async def test_position_is_the_unit_of_the_ticket(self) -> None:
        for short_id, where in [
            ('T-10', {'group': 'input', 'index': 0}),
            ('T-1', {'group': 'running', 'index': 0}),
            ('t-4', {'group': 'running', 'index': 0}),
            ('T-7', {'group': 'queued', 'index': 0}),
            ('T-8', {'group': 'closed', 'index': 0}),
            ('T-9', {'group': 'closed', 'index': 1}),
        ]:
            response = await self.client.get(
                self.url(f'{short_id}/position'), params={'group_by': 'run'}
            )
            self.assertEqual(response.json(), where, short_id)
        response = await self.client.get(
            self.url('T-4/position'),
            params={'group_by': 'run', 'status': 'queued'},
        )
        self.assertEqual(response.status_code, 404, response.text)

    async def test_filters_pick_the_tickets_of_units(self) -> None:
        rows = await self.units(status='closed')
        self.assertEqual(self.ids(rows), ['T-8', 'T-9', 'T-4'])
        run = rows[2]['unit']
        self.assertEqual(
            [i['short_id'] for i in run['items']], ['T-1', 'T-2', 'T-4']
        )
        self.assertEqual(run['children'], 1)
        self.assertEqual(
            await self.counts(group_by='run', status='closed'),
            {
                'input': 0,
                'running': 0,
                'paused': 0,
                'queued': 0,
                'closed': 3,
                'tickets': 5,
            },
        )
        # A child that matches without its parent still folds under the
        # root it came from, and is not nested there.
        rows = await self.units(q='spelling')
        self.assertEqual(self.ids(rows), ['T-7'])
        self.assertEqual(rows[0]['unit']['key'].split(':')[0], 'ticket')
        self.assertFalse(rows[0]['unit']['items'][0]['nested'])
        key = rows[0]['unit']['key']
        rows = await self.units(q='section')
        self.assertEqual(rows[0]['unit']['key'], key)

    async def test_truncates_a_large_unit(self) -> None:
        run = await self.make_run({'ticket_key': 'PSE-3'})
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO tickets.tickets (id, organization_id, short_id,'
                ' agent_id, agent_version, service_account_id, title,'
                ' description, origin_kind, origin_id, origin, owner)'
                " SELECT gen_random_uuid(), %s, 'X-' || n, 'agent-1', 1,"
                " 'sa-1', 'Step ' || n, '', 'human', %s, %s, %s"
                ' FROM generate_series(1, 102) AS n',
                (
                    self.org,
                    self.email,
                    pg_json.Jsonb({'kind': 'human', 'workflow_run_id': run}),
                    self.email,
                ),
            )
        rows = await self.units(group='queued')
        unit = next(r['unit'] for r in rows if r['unit']['run_id'] == run)
        self.assertEqual(unit['tickets'], 102)
        self.assertEqual(len(unit['items']), tickets.store.UNIT_ITEMS)
        self.assertTrue(unit['truncated'])

    async def test_sorts_a_unit_by_the_tickets_of_its_group(self) -> None:
        # T-5 is the only queued ticket of its unit once T-6 and T-7
        # close, so the unit sorts by T-5's time: after a lone queued
        # ticket made after T-5 and before T-7.
        lone = await self.ticket('Lone ticket', 6)
        await self.close({'id': await self.id_of('T-6')}, 'done_acted', 40)
        await self.close({'id': await self.id_of('T-7')}, 'done_acted', 41)
        rows = await self.units(group='queued')
        self.assertEqual(self.ids(rows), [lone['short_id'], 'T-5'])
        response = await self.client.get(
            self.url('T-7/position'), params={'group_by': 'run'}
        )
        self.assertEqual(response.json(), {'group': 'queued', 'index': 1})

    async def insert_chain(
        self, length: int, origin: dict[str, typing.Any]
    ) -> list[uuid.UUID]:
        """Insert a root with ``origin`` and ``length`` descendants, each
        the child of the one before; return their ids, root first."""
        ids = [uuid.uuid4() for _ in range(length + 1)]
        async with self.pool.connection() as conn, conn.cursor() as cursor:
            await cursor.executemany(
                'INSERT INTO tickets.tickets (id, organization_id, short_id,'
                ' agent_id, agent_version, service_account_id, title,'
                ' description, origin_kind, origin_id, origin, owner,'
                ' parent_id) VALUES (%s, %s, %s, %s, 1, %s, %s, %s,'
                " 'human', %s, %s, %s, %s)",
                [
                    (
                        ticket_id,
                        self.org,
                        f'C-{n}',
                        'agent-1',
                        'sa-1',
                        f'Link {n}',
                        '',
                        self.email,
                        pg_json.Jsonb(origin if n == 0 else {'kind': 'human'}),
                        self.email,
                        ids[n - 1] if n else None,
                    )
                    for n, ticket_id in enumerate(ids)
                ],
            )
        return ids

    async def test_keeps_a_deep_chain_in_one_unit(self) -> None:
        run = await self.make_run({'ticket_key': 'PSE-4'})
        await self.insert_chain(120, {'kind': 'human', 'workflow_run_id': run})
        rows = await self.units(group='queued')
        units = [r['unit'] for r in rows if r['short_id'].startswith('C-')]
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]['run_id'], run)
        self.assertEqual(units[0]['tickets'], 121)
        response = await self.client.get(
            self.url('C-120/position'), params={'group_by': 'run'}
        )
        self.assertEqual(response.status_code, 200, response.text)

    async def test_ends_the_walk_at_a_parent_cycle(self) -> None:
        first, second = await self.insert_chain(1, {'kind': 'human'})
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE tickets.tickets SET parent_id = %s WHERE id = %s',
                (second, first),
            )
        rows = await self.units(group='queued')
        found = {
            item['short_id']
            for row in rows
            for item in row['unit']['items']
            if item['short_id'].startswith('C-')
        }
        self.assertEqual(found, {'C-0', 'C-1'})
