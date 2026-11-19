"""Tests for task relations and associated projects (ADR 0020).

These run against the live Postgres that ``root:services`` boots, like
:mod:`apps.api.tests.endpoints.test_agent_tasks`. The org has the tasks
``T-1`` (with a project), ``T-2``, and ``T-3``.
"""

import asyncio
import typing
import uuid
from unittest import mock

import httpx
import psycopg.errors

from apps.api.tests.endpoints import test_agent_task_log, test_agent_tasks
from imbi.api import models, tickets
from imbi.api.auth import permissions
from imbi.api.tickets import sweeper
from imbi.common import iggy


class RelationTestCase(test_agent_tasks.AgentTaskTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.second_project = f'second-{self.project_id}'
        self.foreign_project = f'foreign-{self.project_id}'
        await self.graph.execute(
            """
            MATCH (t:Team {{id: {team}}})
            CREATE (p:Project {{id: {second}, slug: {second},
                                name: 'Feed Proxy'}})
            CREATE (p)-[:OWNED_BY]->(t)
            CREATE (f:Project {{id: {foreign}, slug: {foreign},
                                name: 'Elsewhere'}})
            RETURN p.id AS id
            """,
            {
                'team': self.team_id,
                'second': self.second_project,
                'foreign': self.foreign_project,
            },
            ['id'],
        )
        self.addAsyncCleanup(
            self.graph.execute,
            'MATCH (n) WHERE n.id IN {ids} DETACH DELETE n RETURN 1 AS ok',
            {'ids': [self.second_project, self.foreign_project]},
            ['ok'],
        )
        await self.make_agent()
        self.tickets: dict[str, dict[str, typing.Any]] = {}
        for body in ({'project_ids': [self.project_id]}, {}, {}):
            task = (await self.create_task(**body)).json()
            self.tickets[task['short_id']] = task

    async def put(self, path: str, org: str | None = None) -> httpx.Response:
        return await self.client.put(self.url(path, org))

    async def delete(
        self, path: str, org: str | None = None
    ) -> httpx.Response:
        return await self.client.delete(self.url(path, org))

    async def events(self, short_id: str) -> list[dict[str, typing.Any]]:
        response = await self.client.get(self.url(f'{short_id}/events'))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def last_seq(self, short_id: str) -> int:
        task = await self.store.get(self.org, short_id)
        assert task is not None
        return int(task['last_seq'])

    async def archive(self, short_id: str) -> None:
        """Close the task and archive its log, as the sweep would."""
        response = await self.client.post(self.url(f'{short_id}/cancel'))
        self.assertEqual(response.status_code, 200, response.text)
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM tickets.events WHERE ticket_id = %s',
                (uuid.UUID(self.tickets[short_id]['id']),),
            )
            await conn.execute(
                'UPDATE tickets.tickets SET log_archived_at = NOW()'
                ' WHERE id = %s',
                (uuid.UUID(self.tickets[short_id]['id']),),
            )

    async def delegate(
        self, parent: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        child, _ = await self.store.create(
            tickets.NewTask(
                organization_id=self.org,
                agent_id=parent['agent_id'],
                agent_version=1,
                prompt_version=None,
                service_account_id=parent['service_account_id'],
                title='Sub task',
                description='Delegated.',
                origin_kind='task',
                origin_id=parent['id'],
                origin={'kind': 'task', 'task_id': parent['id']},
                idempotency_key=None,
                owner=self.email,
                budget=None,
            ),
            tickets.Actor('agent', parent['agent_id'], 'harness'),
            {},
        )
        return child


class DependencyTests(RelationTestCase):
    async def test_add_writes_one_operation_on_both_tasks(self) -> None:
        response = await self.put('T-1/requires/t-2')
        self.assertEqual(response.status_code, 204, response.text)
        dependent = (await self.events('T-1'))[-1]
        prerequisite = (await self.events('T-2'))[-1]
        for event, side in (
            (dependent, 'dependent'),
            (prerequisite, 'prerequisite'),
        ):
            self.assertEqual(event['type'], 'dependency.added')
            self.assertEqual(event['actor_kind'], 'human')
            self.assertEqual(event['actor_id'], self.email)
            self.assertEqual(event['payload']['dependent_short_id'], 'T-1')
            self.assertEqual(event['payload']['prerequisite_short_id'], 'T-2')
            self.assertEqual(
                event['payload']['dependent_task_id'],
                self.tickets['T-1']['id'],
            )
            self.assertEqual(
                event['payload']['prerequisite_task_id'],
                self.tickets['T-2']['id'],
            )
            self.assertEqual(event['payload']['created_by'], self.email)
            self.assertEqual(event['payload']['created_by_kind'], 'human')
            self.assertEqual(event['payload']['side'], side)
        self.assertEqual(
            dependent['payload']['operation_id'],
            prerequisite['payload']['operation_id'],
        )

        relations = (await self.client.get(self.url('T-1/relations'))).json()
        (required,) = relations['requires']
        self.assertEqual(required['short_id'], 'T-2')
        self.assertEqual(required['linked_by'], self.email)
        self.assertEqual(required['linked_by_kind'], 'human')
        self.assertIsNotNone(required['linked_at'])
        self.assertEqual(relations['required_by'], [])
        self.assertIsNone(relations['parent'])
        self.assertEqual(relations['children'], [])
        relations = (await self.client.get(self.url('T-2/relations'))).json()
        self.assertEqual(
            [t['short_id'] for t in relations['required_by']], ['T-1']
        )
        self.assertEqual(relations['requires'], [])

    async def test_add_and_remove_are_idempotent(self) -> None:
        for _ in range(2):
            response = await self.put('T-1/requires/T-2')
            self.assertEqual(response.status_code, 204, response.text)
        seqs = (await self.last_seq('T-1'), await self.last_seq('T-2'))
        self.assertEqual(seqs, (2, 2))
        added = (await self.events('T-1'))[-1]['payload']

        for _ in range(2):
            response = await self.delete('T-1/requires/T-2')
            self.assertEqual(response.status_code, 204, response.text)
        for short_id in ('T-1', 'T-2'):
            events = await self.events(short_id)
            self.assertEqual(
                [e['type'] for e in events],
                ['ticket.created', 'dependency.added', 'dependency.removed'],
            )
            removed = events[-1]['payload']
            # The removal keeps the whole row that it removed.
            for key in (
                'organization_id',
                'dependent_task_id',
                'prerequisite_task_id',
                'created_by_kind',
                'created_by',
                'created_at',
            ):
                self.assertEqual(removed[key], added[key], key)
        # A dependency that never existed: no event.
        response = await self.delete('T-2/requires/T-3')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.last_seq('T-3'), 1)

    async def test_requires_and_required_by_are_one_row(self) -> None:
        await self.put('T-1/requires/T-2')
        await self.put('T-2/requires/T-1')  # a cycle is allowed
        relations = (await self.client.get(self.url('T-1/relations'))).json()
        self.assertEqual(
            [t['short_id'] for t in relations['requires']], ['T-2']
        )
        self.assertEqual(
            [t['short_id'] for t in relations['required_by']], ['T-2']
        )

    async def test_self_dependency_is_refused(self) -> None:
        response = await self.put('T-1/requires/T-1')
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(await self.last_seq('T-1'), 1)
        task_id = uuid.UUID(self.tickets['T-1']['id'])
        with self.assertRaises(psycopg.errors.CheckViolation):
            async with self.pool.connection() as conn:
                await conn.execute(
                    'INSERT INTO tickets.ticket_dependencies'
                    ' (organization_id, dependent_ticket_id,'
                    ' prerequisite_ticket_id, created_by_kind, created_by)'
                    " VALUES (%s, %s, %s, 'human', 'x')",
                    (self.org, task_id, task_id),
                )

    async def test_cross_org_link_is_refused(self) -> None:
        await self.make_agent(org=self.other_org)
        other = None
        for _ in range(4):
            other = (await self.create_task(self.other_org)).json()
        assert other is not None
        # T-4 is only in the other org; the route org decides.
        response = await self.put('T-1/requires/T-4')
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(await self.last_seq('T-1'), 1)
        # The keys refuse a row that joins two orgs.
        for org in (self.org, self.other_org):
            with (
                self.subTest(org=org),
                self.assertRaises(psycopg.errors.ForeignKeyViolation),
            ):
                async with self.pool.connection() as conn:
                    await conn.execute(
                        'INSERT INTO tickets.ticket_dependencies'
                        ' (organization_id, dependent_ticket_id,'
                        ' prerequisite_ticket_id, created_by_kind,'
                        " created_by) VALUES (%s, %s, %s, 'human', 'x')",
                        (
                            org,
                            uuid.UUID(self.tickets['T-1']['id']),
                            uuid.UUID(other['id']),
                        ),
                    )
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            async with self.pool.connection() as conn:
                await conn.execute(
                    'INSERT INTO tickets.ticket_projects'
                    ' (organization_id, ticket_id, project_id, project_slug,'
                    " added_by_kind, added_by) VALUES (%s, %s, 'p', 'p',"
                    " 'human', 'x')",
                    (self.other_org, uuid.UUID(self.tickets['T-1']['id'])),
                )

    async def test_unknown_task_is_404(self) -> None:
        for path in ('T-9/requires/T-1', 'T-1/requires/T-9'):
            response = await self.put(path)
            self.assertEqual(response.status_code, 404, response.text)
            self.assertIn('T-9', response.text)
        response = await self.client.get(self.url('T-9/relations'))
        self.assertEqual(response.status_code, 404, response.text)

    async def test_closed_task_takes_the_event(self) -> None:
        await self.client.post(self.url('T-2/cancel'))
        before = await self.last_seq('T-2')
        response = await self.put('T-1/requires/T-2')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.last_seq('T-2'), before + 1)

    async def test_archived_task_is_sealed(self) -> None:
        await self.archive('T-2')
        archived_seq = await self.last_seq('T-2')
        response = await self.put('T-1/requires/T-2')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.last_seq('T-2'), archived_seq)
        event = (await self.events('T-1'))[-1]
        self.assertEqual(event['type'], 'dependency.added')
        self.assertEqual(event['payload']['side'], 'dependent')
        self.assertEqual(event['payload']['prerequisite_short_id'], 'T-2')
        self.assertEqual(
            event['payload']['prerequisite_task_id'],
            self.tickets['T-2']['id'],
        )
        relations = (await self.client.get(self.url('T-2/relations'))).json()
        self.assertEqual(
            [t['short_id'] for t in relations['required_by']], ['T-1']
        )

        # Both archived: refused, and the row stays.
        await self.archive('T-1')
        seqs = (await self.last_seq('T-1'), archived_seq)
        for method in (self.put, self.delete):
            response = await method('T-1/requires/T-2')
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(
                response.json()['detail']['error'], 'task_archived'
            )
        self.assertEqual(
            (await self.last_seq('T-1'), await self.last_seq('T-2')), seqs
        )
        relations = (await self.client.get(self.url('T-1/relations'))).json()
        self.assertEqual(len(relations['requires']), 1)

    async def test_child_gets_the_projects_of_its_parent(self) -> None:
        response = await self.put(f'T-1/projects/{self.second_project}')
        self.assertEqual(response.status_code, 204, response.text)
        child = await self.delegate(self.tickets['T-1'])
        self.assertEqual(
            {p['project_id'] for p in child['projects']},
            {self.project_id, self.second_project},
        )

    async def test_delegation_is_parent_and_children(self) -> None:
        child = await self.delegate(self.tickets['T-2'])
        relations = (await self.client.get(self.url('T-2/relations'))).json()
        self.assertEqual(
            [t['short_id'] for t in relations['children']],
            [child['short_id']],
        )
        self.assertIsNone(relations['children'][0]['linked_by'])
        relations = (
            await self.client.get(self.url(f'{child["short_id"]}/relations'))
        ).json()
        self.assertEqual(relations['parent']['short_id'], 'T-2')

    async def test_delegation_from_closed_parent_is_refused(self) -> None:
        parent = self.tickets['T-2']
        response = await self.client.post(self.url('T-2/cancel'))
        self.assertEqual(response.status_code, 200, response.text)
        with self.assertRaises(tickets.TaskClosed):
            await self.delegate(parent)


class ProjectTests(RelationTestCase):
    async def projects(self, short_id: str) -> list[dict[str, typing.Any]]:
        response = await self.client.get(self.url(f'{short_id}/projects'))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_associate_and_dissociate(self) -> None:
        for _ in range(2):
            response = await self.put(f'T-1/projects/{self.second_project}')
            self.assertEqual(response.status_code, 204, response.text)
        events = await self.events('T-1')
        self.assertEqual(
            [e['type'] for e in events],
            ['ticket.created', 'project.associated'],
        )
        added = events[-1]['payload']
        self.assertEqual(added['project_id'], self.second_project)
        self.assertEqual(added['project_slug'], self.second_project)
        self.assertEqual(added['added_by'], self.email)
        self.assertIn('operation_id', added)

        first, second = await self.projects('T-1')
        self.assertEqual(first['project_id'], self.project_id)
        self.assertTrue(first['available'])
        self.assertEqual(first['name'], 'Billing')
        self.assertEqual(first['added_by'], self.email)
        self.assertEqual(second['project_id'], self.second_project)
        self.assertTrue(second['available'])
        self.assertEqual(second['name'], 'Feed Proxy')
        self.assertEqual(second['added_by'], self.email)
        self.assertEqual(second['added_by_kind'], 'human')
        # T-2 has no project.
        self.assertEqual(await self.projects('T-2'), [])

        for _ in range(2):
            response = await self.delete(f'T-1/projects/{self.second_project}')
            self.assertEqual(response.status_code, 204, response.text)
        events = await self.events('T-1')
        self.assertEqual(
            [e['type'] for e in events[1:]],
            ['project.associated', 'project.dissociated'],
        )
        removed = events[-1]['payload']
        for key in ('organization_id', 'task_id', 'project_slug', 'added_at'):
            self.assertEqual(removed[key], added[key], key)
        self.assertEqual(len(await self.projects('T-1')), 1)

    async def test_project_from_create_can_be_removed(self) -> None:
        response = await self.put(f'T-1/projects/{self.project_id}')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.last_seq('T-1'), 1)
        response = await self.delete(f'T-1/projects/{self.project_id}')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.projects('T-1'), [])
        response = await self.client.get(self.url('T-1'))
        self.assertEqual(response.json()['projects'], [])

    async def test_create_with_many_projects(self) -> None:
        response = await self.create_task(
            project_ids=[
                self.second_project,
                self.project_id,
                self.second_project,
            ]
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(
            [p['project_id'] for p in response.json()['projects']],
            sorted([self.second_project, self.project_id]),
        )
        short_id = response.json()['short_id']
        self.assertEqual(
            {p['project_id'] for p in await self.projects(short_id)},
            {self.second_project, self.project_id},
        )
        response = await self.create_task(
            project_ids=[self.project_id, self.foreign_project]
        )
        self.assertEqual(response.status_code, 422, response.text)

    async def test_project_must_be_in_the_org(self) -> None:
        for project_id in (self.foreign_project, 'nope'):
            response = await self.put(f'T-2/projects/{project_id}')
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(await self.last_seq('T-2'), 1)

    async def test_deleted_project_keeps_its_slug(self) -> None:
        await self.put(f'T-2/projects/{self.second_project}')
        await self.graph.execute(
            'MATCH (p:Project {{id: {id}}}) DETACH DELETE p RETURN 1 AS ok',
            {'id': self.second_project},
            ['ok'],
        )
        (project,) = await self.projects('T-2')
        self.assertFalse(project['available'])
        self.assertEqual(project['project_slug'], self.second_project)
        self.assertIsNone(project['name'])
        # It can still be removed.
        response = await self.delete(f'T-2/projects/{self.second_project}')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.projects('T-2'), [])

    async def test_archived_task_refuses_projects(self) -> None:
        await self.archive('T-2')
        response = await self.put(f'T-2/projects/{self.second_project}')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'task_archived')


class ParentTests(RelationTestCase):
    """Parent tickets (ADR 0028)."""

    async def move(self, short_id: str, parent: str | None) -> httpx.Response:
        return await self.client.put(
            self.url(f'{short_id}/parent'), json={'parent': parent}
        )

    async def relations(self, short_id: str) -> dict[str, typing.Any]:
        response = await self.client.get(self.url(f'{short_id}/relations'))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_agent_child_sets_parent(self) -> None:
        child = await self.delegate(self.tickets['T-2'])
        self.assertEqual(str(child['parent_id']), self.tickets['T-2']['id'])

    async def test_move_writes_parent_changed(self) -> None:
        response = await self.move('T-1', 't-2')
        self.assertEqual(response.status_code, 204, response.text)
        event = (await self.events('T-1'))[-1]
        self.assertEqual(event['type'], 'parent.changed')
        self.assertEqual(event['actor_id'], self.email)
        self.assertEqual(event['payload'], {'from': None, 'to': 'T-2'})
        relations = await self.relations('T-2')
        self.assertEqual(
            [t['short_id'] for t in relations['children']], ['T-1']
        )
        self.assertEqual(
            relations['tree'],
            {
                'root_short_id': 'T-2',
                'root_title': self.tickets['T-2']['title'],
                'tickets': 2,
                'open': 2,
            },
        )
        self.assertEqual(
            (await self.relations('T-1'))['parent']['short_id'], 'T-2'
        )
        # The same parent again: no event.
        response = await self.move('T-1', 'T-2')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.last_seq('T-1'), 2)

        response = await self.move('T-1', None)
        self.assertEqual(response.status_code, 204, response.text)
        event = (await self.events('T-1'))[-1]
        self.assertEqual(event['payload'], {'from': 'T-2', 'to': None})
        relations = await self.relations('T-1')
        self.assertIsNone(relations['parent'])
        self.assertEqual(relations['tree']['root_short_id'], 'T-1')
        self.assertEqual(relations['tree']['tickets'], 1)

    async def test_closed_ticket_moves_and_counts_in_tree(self) -> None:
        response = await self.client.post(self.url('T-1/cancel'))
        self.assertEqual(response.status_code, 200, response.text)
        response = await self.move('T-1', 'T-2')
        self.assertEqual(response.status_code, 204, response.text)
        tree = (await self.relations('T-1'))['tree']
        self.assertEqual((tree['tickets'], tree['open']), (2, 1))

    async def test_cycle_is_refused(self) -> None:
        await self.move('T-1', 'T-2')
        await self.move('T-2', 'T-3')
        for short_id, parent in (('T-3', 'T-1'), ('T-1', 'T-1')):
            with self.subTest(short_id=short_id, parent=parent):
                response = await self.move(short_id, parent)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(
                    response.json()['detail']['error'], 'parent_cycle'
                )
        self.assertIsNone((await self.relations('T-3'))['parent'])

    async def test_two_moves_cannot_make_a_cycle(self) -> None:
        # T-1 under T-2 and T-3 under T-4. Moving T-2 under T-3 and T-4
        # under T-1 at once would make T-1 > T-2 > T-3 > T-4 > T-1. The
        # two moves lock no row in common: only the advisory lock stops
        # the cycle.
        self.tickets['T-4'] = (await self.create_task()).json()
        await self.move('T-1', 'T-2')
        await self.move('T-3', 'T-4')
        actor = tickets.Actor('human', self.email, 'web')
        results = await asyncio.gather(
            self.store.set_parent(self.org, 'T-2', 'T-3', actor),
            self.store.set_parent(self.org, 'T-4', 'T-1', actor),
            return_exceptions=True,
        )
        self.assertEqual(
            sorted(type(r).__name__ for r in results),
            ['NoneType', 'ParentCycle'],
            results,
        )

    async def test_archived_ticket_cannot_move(self) -> None:
        await self.archive('T-1')
        response = await self.move('T-1', 'T-2')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'task_archived')

    async def test_unknown_parent_is_404(self) -> None:
        response = await self.move('T-1', 'T-99')
        self.assertEqual(response.status_code, 404, response.text)

    async def test_owner_or_manage_can_move(self) -> None:
        self.permissions = set(test_agent_tasks.ALL_PERMISSIONS) - {
            'agent_task:manage',
            'ticket:manage',
        }
        response = await self.move('T-1', 'T-2')
        self.assertEqual(response.status_code, 204, response.text)
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE tickets.tickets SET owner = 'other@example.com'"
                " WHERE organization_id = %s AND short_id = 'T-1'",
                (self.org,),
            )
        response = await self.move('T-1', None)
        self.assertEqual(response.status_code, 403, response.text)
        self.permissions = set(test_agent_tasks.ALL_PERMISSIONS)
        response = await self.move('T-1', None)
        self.assertEqual(response.status_code, 204, response.text)


class OldPathParentTests(RelationTestCase):
    """The parent route at ``/agent-tasks``, which stays until release B."""

    prefix = 'agent-tasks'

    async def test_old_path_moves_the_ticket(self) -> None:
        response = await self.client.put(
            self.url('T-1/parent'), json={'parent': 'T-2'}
        )
        self.assertEqual(response.status_code, 204, response.text)
        relations = (await self.client.get(self.url('T-1/relations'))).json()
        self.assertEqual(relations['parent']['short_id'], 'T-2')


class GatingTests(RelationTestCase):
    """Gating dependencies (ADR 0028)."""

    actor = tickets.Actor('agent', 'triage', 'harness')

    async def gate(
        self, dependent: str, prerequisite: str, *, gates: bool = True
    ) -> httpx.Response:
        return await self.client.put(
            self.url(f'{dependent}/requires/{prerequisite}'),
            json={'gates': gates},
        )

    async def status(self, short_id: str) -> str:
        task = await self.store.get(self.org, short_id)
        assert task is not None
        return str(task['status'])

    async def close(self, short_id: str, outcome: tickets.Outcome) -> None:
        await self.store.set_outcome(
            self.org, short_id, outcome, None, self.actor
        )

    async def test_gate_holds_a_queued_ticket(self) -> None:
        response = await self.gate('T-1', 'T-2')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.status('T-1'), 'held')
        added, held = (await self.events('T-1'))[-2:]
        self.assertTrue(added['payload']['gates'])
        self.assertEqual(held['type'], 'state.changed')
        self.assertEqual(
            held['payload'],
            {'from': 'queued', 'to': 'held', 'reason': 'gated'},
        )
        relations = (await self.client.get(self.url('T-1/relations'))).json()
        self.assertTrue(relations['requires'][0]['gates'])
        # A plain link does not hold.
        response = await self.put('T-3/requires/T-2')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.status('T-3'), 'queued')

    async def test_gate_is_refused_on_a_started_ticket(self) -> None:
        await self.open_session(self.tickets['T-1']['id'])
        response = await self.gate('T-1', 'T-2')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'ticket_started')
        relations = (await self.client.get(self.url('T-1/relations'))).json()
        self.assertEqual(relations['requires'], [])
        self.assertEqual(await self.status('T-1'), 'running')
        # A plain link is still allowed.
        response = await self.put('T-1/requires/T-2')
        self.assertEqual(response.status_code, 204, response.text)

    async def test_done_close_releases_dependents(self) -> None:
        await self.gate('T-1', 'T-2')
        await self.close('T-2', 'done_acted')
        self.assertEqual(await self.status('T-1'), 'queued')
        released = (await self.events('T-1'))[-1]
        self.assertEqual(
            released['payload'],
            {'from': 'held', 'to': 'queued', 'reason': 'released'},
        )

    async def test_release_is_in_the_close_transaction(self) -> None:
        await self.gate('T-1', 'T-2')
        with (
            mock.patch.object(
                tickets.store,
                '_sync_gate',
                side_effect=RuntimeError('release failed'),
            ),
            self.assertRaises(RuntimeError),
        ):
            await self.close('T-2', 'done_nothing_to_act_on')
        # The close rolled back with the release.
        self.assertEqual(await self.status('T-2'), 'queued')
        self.assertEqual(await self.status('T-1'), 'held')

    async def test_other_outcomes_keep_dependents_held(self) -> None:
        await self.gate('T-1', 'T-2')
        await self.gate('T-3', 'T-1')
        await self.close('T-2', 'failed_external')
        self.assertEqual(await self.status('T-1'), 'held')
        response = await self.client.post(self.url('T-1/cancel'))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(await self.status('T-3'), 'held')
        # The owner removes the dependency: T-3 is released.
        response = await self.delete('T-3/requires/T-1')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.status('T-3'), 'queued')

    async def test_release_waits_for_every_gate(self) -> None:
        await self.gate('T-1', 'T-2')
        await self.gate('T-1', 'T-3')
        await self.close('T-2', 'done_acted')
        self.assertEqual(await self.status('T-1'), 'held')
        await self.close('T-3', 'done_acted')
        self.assertEqual(await self.status('T-1'), 'queued')

    async def test_closed_prerequisite_holds_unless_done(self) -> None:
        await self.close('T-2', 'done_acted')
        await self.gate('T-1', 'T-2')
        self.assertEqual(await self.status('T-1'), 'queued')
        self.tickets['T-4'] = (await self.create_task()).json()
        await self.close('T-4', 'failed_external')
        await self.gate('T-3', 'T-4')
        self.assertEqual(await self.status('T-3'), 'held')
        # The same dependency without ``gates`` releases it.
        response = await self.put('T-3/requires/T-4')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.status('T-3'), 'queued')
        relations = (await self.client.get(self.url('T-3/relations'))).json()
        self.assertFalse(relations['requires'][0]['gates'])

    async def test_held_ticket_keeps_its_control(self) -> None:
        await self.gate('T-1', 'T-2')
        for action in ('pause', 'resume'):
            response = await self.client.post(self.url(f'T-1/{action}'))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['status'], 'held')
        await self.client.post(self.url('T-1/pause'))
        await self.close('T-2', 'done_acted')
        self.assertEqual(await self.status('T-1'), 'paused')

    async def test_delete_of_a_prerequisite_releases(self) -> None:
        await self.gate('T-1', 'T-2')
        await self.archive('T-2')
        self.assertEqual(await self.status('T-1'), 'held')
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM tickets.trigger_outbox WHERE ticket_id = %s',
                (uuid.UUID(self.tickets['T-2']['id']),),
            )
        response = await self.client.delete(self.url('T-2'))
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.status('T-1'), 'queued')

    async def test_close_and_gate_at_once_never_strand(self) -> None:
        # Whichever commits first, the dependent ends queued: the gate
        # sees the done close, or the close sees the gate.
        human = tickets.Actor('human', self.email, 'web')
        for _ in range(5):
            dependent = (await self.create_task()).json()['short_id']
            prerequisite = (await self.create_task()).json()['short_id']
            results = await asyncio.gather(
                self.store.add_dependency(
                    self.org, dependent, prerequisite, human, gates=True
                ),
                self.close(prerequisite, 'done_acted'),
                return_exceptions=True,
            )
            self.assertEqual(results, [True, None])
            self.assertEqual(await self.status(dependent), 'queued')

    async def test_same_gate_on_a_started_ticket_changes_nothing(
        self,
    ) -> None:
        await self.gate('T-1', 'T-2')
        await self.close('T-2', 'failed_external')
        await self.client.post(self.url('T-1/cancel'))
        before = await self.last_seq('T-1')
        response = await self.gate('T-1', 'T-2')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(await self.last_seq('T-1'), before)
        # A new gate is still refused.
        response = await self.gate('T-1', 'T-3')
        self.assertEqual(response.status_code, 409, response.text)

    async def test_held_ticket_refuses_a_session(self) -> None:
        await self.gate('T-1', 'T-2')
        with self.assertRaises(tickets.TicketHeld):
            await self.store.open_session(
                self.org,
                'T-1',
                key='session-1',
                harness_instance=None,
                max_concurrent=None,
                actor=self.actor,
            )
        self.assertEqual(await self.status('T-1'), 'held')

    async def test_request_keeps_a_ticket_held(self) -> None:
        await self.gate('T-1', 'T-2')
        _, request, _ = await self.store.open_request(
            self.org,
            'T-1',
            tickets.NewRequest(
                kind='feedback',
                title='Which branch?',
                why=None,
                options=None,
                artifacts=None,
                artifact_digests=None,
                expires_at=None,
                session_id=None,
            ),
            self.actor,
        )
        self.assertEqual(await self.status('T-1'), 'held')
        await self.store.resolve_request(
            self.org,
            'T-1',
            request['id'],
            tickets.Resolution(
                status='answered',
                answer='main',
                constraints=None,
                artifact_digests=None,
            ),
            tickets.Actor('human', self.email, 'web'),
        )
        self.assertEqual(await self.status('T-1'), 'held')
        await self.close('T-2', 'done_acted')
        self.assertEqual(await self.status('T-1'), 'queued')

    async def test_release_with_an_open_request_blocks(self) -> None:
        await self.gate('T-1', 'T-2')
        _, request, _ = await self.store.open_request(
            self.org,
            'T-1',
            tickets.NewRequest(
                kind='feedback',
                title='Which branch?',
                why=None,
                options=None,
                artifacts=None,
                artifact_digests=None,
                expires_at=None,
                session_id=None,
            ),
            self.actor,
        )
        await self.close('T-2', 'done_acted')
        self.assertEqual(await self.status('T-1'), 'blocked')
        await self.store.resolve_request(
            self.org,
            'T-1',
            request['id'],
            tickets.Resolution(
                status='answered',
                answer='main',
                constraints=None,
                artifact_digests=None,
            ),
            tickets.Actor('human', self.email, 'web'),
        )
        self.assertEqual(await self.status('T-1'), 'queued')

    async def test_deadlock_runs_the_change_again(self) -> None:
        original = tickets.store._lock_tasks
        calls = 0

        async def deadlock_once(*args: typing.Any) -> typing.Any:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise psycopg.errors.DeadlockDetected('deadlock detected')
            return await original(*args)

        with mock.patch.object(tickets.store, '_lock_tasks', deadlock_once):
            response = await self.gate('T-1', 'T-2')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(calls, 2)
        self.assertEqual(await self.status('T-1'), 'held')


class OldPathGatingTests(RelationTestCase):
    """Gating at ``/agent-tasks``, which stays until release B."""

    prefix = 'agent-tasks'
    gate = GatingTests.gate
    status = GatingTests.status
    test_gate_holds_a_queued_ticket = (
        GatingTests.test_gate_holds_a_queued_ticket
    )
    test_gate_is_refused_on_a_started_ticket = (
        GatingTests.test_gate_is_refused_on_a_started_ticket
    )


class AccessTests(RelationTestCase):
    def routes(self) -> list[tuple[str, str, str]]:
        project = self.second_project
        return [
            ('agent_task:read', 'GET', 'T-1/relations'),
            ('agent_task:read', 'GET', 'T-1/projects'),
            ('agent_task:manage', 'PUT', 'T-1/requires/T-2'),
            ('agent_task:manage', 'DELETE', 'T-1/requires/T-2'),
            ('agent_task:manage', 'PUT', f'T-1/projects/{project}'),
            ('agent_task:manage', 'DELETE', f'T-1/projects/{project}'),
        ]

    async def test_each_route_needs_its_permission(self) -> None:
        for permission, method, path in self.routes():
            with self.subTest(method=method, path=path):
                self.permissions = set(test_agent_tasks.ALL_PERMISSIONS) - {
                    permission
                }
                response = await self.client.request(method, self.url(path))
                self.assertEqual(response.status_code, 403, response.text)
                self.assertIn(permission, response.text)
        self.assertEqual(await self.last_seq('T-1'), 1)

    async def test_non_member_is_refused(self) -> None:
        for _permission, method, path in self.routes():
            with self.subTest(method=method, path=path):
                response = await self.client.request(
                    method, self.url(path, self.foreign_org)
                )
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(
                    response.json()['detail']['error'],
                    'organization_forbidden',
                )

    async def test_own_service_account_needs_read_permission(self) -> None:
        # Its own task, but no agent_task:read: the relations show
        # other tasks and the people who linked them.
        await self.act_as_agent(set())
        for path in ('T-1/relations', 'T-1/projects'):
            with self.subTest(path=path):
                response = await self.client.get(self.url(path))
                self.assertEqual(response.status_code, 403, response.text)
                self.assertIn('agent_task:read', response.text)
        # It can still read its task.
        response = await self.client.get(self.url('T-1'))
        self.assertEqual(response.status_code, 200, response.text)

    async def act_as_agent(self, granted: set[str]) -> None:
        """Authenticate as the service account of the agent of T-1."""
        (account,) = await self.service_accounts(
            self.tickets['T-1']['agent_id']
        )

        async def agent() -> permissions.AuthContext:
            return permissions.AuthContext(
                service_account=models.ServiceAccount(
                    id=account['id'],
                    slug=account['slug'],
                    display_name='Triage Bot',
                ),
                auth_method='client_credentials',
                permissions=set(granted),
            )

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            agent
        )

    async def test_service_account_cannot_change_relations(self) -> None:
        # The agent's own service account, with every permission.
        await self.act_as_agent(set(test_agent_tasks.ALL_PERMISSIONS))
        for permission, method, path in self.routes():
            with self.subTest(method=method, path=path):
                response = await self.client.request(method, self.url(path))
                if permission == 'agent_task:read':
                    self.assertEqual(response.status_code, 200, response.text)
                    continue
                self.assertEqual(response.status_code, 403, response.text)
                self.assertIn('requires user authentication', response.text)
        self.assertEqual(await self.last_seq('T-1'), 1)


class SweepTests(test_agent_task_log.ClickHouseTestCase):
    """Dependency events raise ``last_seq``; the archive still waits for
    ClickHouse to have every one."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.make_agent()
        self.first = (await self.create_task()).json()
        await self.create_task()
        await self.client.post(self.url('T-1/cancel'))

    async def test_sweep_archives_after_dependency_events(self) -> None:
        failing = mock.AsyncMock(side_effect=RuntimeError('Iggy is down'))
        with mock.patch.object(iggy, 'publish_rows', failing):
            response = await self.client.put(self.url('T-2/requires/T-1'))
        self.assertEqual(response.status_code, 204, response.text)
        task = await self.store.get(self.org, 'T-1')
        assert task is not None
        last_seq = task['last_seq']
        self.assertEqual(
            (await self.postgres_events(self.first['id']))[-1]['type'],
            'dependency.added',
        )

        # The first round publishes the missing event, the next archives.
        await sweeper.sweep_once(self.store)
        task = await self.store.get(self.org, 'T-1')
        assert task is not None
        self.assertIsNone(task['log_archived_at'])
        await sweeper.sweep_once(self.store)
        task = await self.store.get(self.org, 'T-1')
        assert task is not None
        self.assertIsNotNone(task['log_archived_at'])
        stored = {
            row['seq']: row['type']
            for row in await self.stored_events(self.first['id'])
        }
        self.assertEqual(sorted(stored), list(range(1, last_seq + 1)))
        self.assertEqual(stored[last_seq], 'dependency.added')

    async def test_archive_refuses_a_stale_last_seq(self) -> None:
        task = await self.store.get(self.org, 'T-1')
        assert task is not None
        await self.client.put(self.url('T-2/requires/T-1'))
        self.assertFalse(
            await self.store.archive(task['id'], task['last_seq'])
        )
