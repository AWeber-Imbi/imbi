"""Tests for task relations and associated projects (ADR 0020).

These run against the live Postgres that ``root:services`` boots, like
:mod:`apps.api.tests.endpoints.test_agent_tasks`. The org has the tasks
``T-1`` (with the primary project), ``T-2``, and ``T-3``.
"""

import typing
import uuid
from unittest import mock

import httpx
import psycopg.errors

from apps.api.tests.endpoints import test_agent_task_log, test_agent_tasks
from imbi.api import agent_tasks, models
from imbi.api.agent_tasks import sweeper
from imbi.api.auth import permissions
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
        self.agent_tasks: dict[str, dict[str, typing.Any]] = {}
        for body in ({'project_id': self.project_id}, {}, {}):
            task = (await self.create_task(**body)).json()
            self.agent_tasks[task['short_id']] = task

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
                'DELETE FROM agent_runtime.events WHERE task_id = %s',
                (uuid.UUID(self.agent_tasks[short_id]['id']),),
            )
            await conn.execute(
                'UPDATE agent_runtime.tasks SET log_archived_at = NOW()'
                ' WHERE id = %s',
                (uuid.UUID(self.agent_tasks[short_id]['id']),),
            )


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
                self.agent_tasks['T-1']['id'],
            )
            self.assertEqual(
                event['payload']['prerequisite_task_id'],
                self.agent_tasks['T-2']['id'],
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
                ['task.created', 'dependency.added', 'dependency.removed'],
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
        task_id = uuid.UUID(self.agent_tasks['T-1']['id'])
        with self.assertRaises(psycopg.errors.CheckViolation):
            async with self.pool.connection() as conn:
                await conn.execute(
                    'INSERT INTO agent_runtime.task_dependencies'
                    ' (organization_id, dependent_task_id,'
                    ' prerequisite_task_id, created_by_kind, created_by)'
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
                        'INSERT INTO agent_runtime.task_dependencies'
                        ' (organization_id, dependent_task_id,'
                        ' prerequisite_task_id, created_by_kind,'
                        " created_by) VALUES (%s, %s, %s, 'human', 'x')",
                        (
                            org,
                            uuid.UUID(self.agent_tasks['T-1']['id']),
                            uuid.UUID(other['id']),
                        ),
                    )
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            async with self.pool.connection() as conn:
                await conn.execute(
                    'INSERT INTO agent_runtime.task_projects'
                    ' (organization_id, task_id, project_id, project_slug,'
                    " added_by_kind, added_by) VALUES (%s, %s, 'p', 'p',"
                    " 'human', 'x')",
                    (self.other_org, uuid.UUID(self.agent_tasks['T-1']['id'])),
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
            self.agent_tasks['T-2']['id'],
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

    async def test_delegation_is_parent_and_children(self) -> None:
        parent = self.agent_tasks['T-2']
        child, _ = await self.store.create(
            agent_tasks.NewTask(
                organization_id=self.org,
                agent_id=parent['agent_id'],
                agent_version=1,
                prompt_version=None,
                service_account_id=parent['service_account_id'],
                project_id=None,
                title='Sub task',
                description='Delegated.',
                origin_kind='task',
                origin_id=parent['id'],
                origin={'kind': 'task', 'task_id': parent['id']},
                idempotency_key=None,
                owner=self.email,
                budget=None,
            ),
            agent_tasks.Actor('agent', parent['agent_id'], 'harness'),
            {},
        )
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
            [e['type'] for e in events], ['task.created', 'project.associated']
        )
        added = events[-1]['payload']
        self.assertEqual(added['project_id'], self.second_project)
        self.assertEqual(added['project_slug'], self.second_project)
        self.assertEqual(added['added_by'], self.email)
        self.assertIn('operation_id', added)

        primary, second = await self.projects('T-1')
        self.assertEqual(primary['project_id'], self.project_id)
        self.assertTrue(primary['primary'])
        self.assertTrue(primary['available'])
        self.assertEqual(primary['name'], 'Billing')
        self.assertFalse(second['primary'])
        self.assertTrue(second['available'])
        self.assertEqual(second['name'], 'Feed Proxy')
        self.assertEqual(second['added_by'], self.email)
        self.assertEqual(second['added_by_kind'], 'human')
        # T-2 has no primary project.
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

    async def test_primary_project_is_refused(self) -> None:
        response = await self.put(f'T-1/projects/{self.project_id}')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'primary_project')
        self.assertEqual(await self.last_seq('T-1'), 1)

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

    async def test_service_account_cannot_change_relations(self) -> None:
        # The agent's own service account, with every permission.
        (account,) = await self.service_accounts(
            self.agent_tasks['T-1']['agent_id']
        )

        async def agent() -> permissions.AuthContext:
            return permissions.AuthContext(
                service_account=models.ServiceAccount(
                    id=account['id'],
                    slug=account['slug'],
                    display_name='Triage Bot',
                ),
                auth_method='client_credentials',
                permissions=set(test_agent_tasks.ALL_PERMISSIONS),
            )

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            agent
        )
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
