"""Tests for the agent task endpoints and the agent service accounts.

These run against the live Postgres that ``root:services`` boots: the
graph for organizations, agents, and service accounts, and the
``agent_runtime`` schema for task state. Each test makes its own
organizations, so tests do not share task counters.
"""

import datetime
import decimal
import json
import typing
import uuid

import httpx

from apps.api.tests import support
from imbi.api import agent_tasks, models
from imbi.api.auth import permissions
from imbi.api.graph_sql import props_template
from imbi.common import graph

ALL_PERMISSIONS = frozenset(
    {
        'agent:create',
        'agent:delete',
        'agent_task:read',
        'agent_task:create',
        'agent_task:manage',
    }
)


class AgentTaskTestCase(support.SharedAppAsyncTestCase):
    """Fixtures: two organizations, a team, a project, and a member."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        suffix = uuid.uuid4().hex[:10]
        self.org = f'at-{suffix}'
        self.other_org = f'at-other-{suffix}'
        self.team_id = f'team-{suffix}'
        self.project_id = f'project-{suffix}'
        self.member = f'member-{suffix}@example.com'
        self.email = f'dev-{suffix}@example.com'

        await graph.initialize()
        await agent_tasks.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.pool = agent_tasks.create_pool()
        await self.pool.open()
        self.store = agent_tasks.TaskStore(self.pool)
        self.addAsyncCleanup(self._cleanup)

        await self.graph.execute(
            """
            CREATE (o:Organization {{id: {org}, slug: {org},
                                     name: {org}}})
            CREATE (x:Organization {{id: {other}, slug: {other},
                                     name: {other}}})
            CREATE (t:Team {{id: {team}, slug: {team}, name: 'Ops'}})
            CREATE (t)-[:BELONGS_TO]->(o)
            CREATE (p:Project {{id: {project}, slug: {project},
                                name: 'Billing'}})
            CREATE (p)-[:OWNED_BY]->(t)
            CREATE (u:User {{id: {member}, email: {member},
                             display_name: 'Member', is_active: true}})
            CREATE (u)-[:MEMBER_OF {{role: 'developer'}}]->(o)
            RETURN o.id AS id
            """,
            {
                'org': self.org,
                'other': self.other_org,
                'team': self.team_id,
                'project': self.project_id,
                'member': self.member,
            },
            ['id'],
        )

        self.permissions = set(ALL_PERMISSIONS)
        self.user = models.User(
            email=self.email,
            display_name='Dev User',
            is_active=True,
            is_admin=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_method: typing.Literal['jwt', 'api_key'] = 'jwt'

        async def current_user() -> permissions.AuthContext:
            return permissions.AuthContext(
                user=self.user,
                session_id='test-session',
                auth_method=self.auth_method,
                permissions=set(self.permissions),
            )

        overrides = self.test_app.dependency_overrides
        overrides[permissions.get_current_user] = current_user
        overrides[graph._inject_graph] = lambda: self.graph
        overrides[agent_tasks._inject_store] = lambda: self.store
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.test_app),
            base_url='http://test',
        )

    async def _cleanup(self) -> None:
        await self.client.aclose()
        for org in (self.org, self.other_org):
            await self.graph.execute(
                """
                MATCH (a:Agent)-[:BELONGS_TO]->(:Organization {{slug: {org}}})
                OPTIONAL MATCH (a)-[:ACTS_AS]->(s:ServiceAccount)
                OPTIONAL MATCH (v:AgentVersion)-[:VERSION_OF]->(a)
                DETACH DELETE v, s, a
                RETURN 1 AS ok
                """,
                {'org': org},
                ['ok'],
            )
        await self.graph.execute(
            """
            MATCH (n) WHERE n.id IN {ids}
            DETACH DELETE n
            RETURN 1 AS ok
            """,
            {
                'ids': [
                    self.org,
                    self.other_org,
                    self.team_id,
                    self.project_id,
                    self.member,
                ]
            },
            ['ok'],
        )
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM agent_runtime.tasks'
                ' WHERE organization_id = ANY(%s)',
                ([self.org, self.other_org],),
            )
            await conn.execute(
                'DELETE FROM agent_runtime.task_id_sequences'
                ' WHERE organization_id = ANY(%s)',
                ([self.org, self.other_org],),
            )
        await self.pool.close()
        await self.graph.close()

    # -- Fixtures ------------------------------------------------------

    async def make_agent(
        self,
        slug: str = 'triage',
        *,
        org: str | None = None,
        name: str = 'Triage Bot',
        enabled: bool = True,
        settings: dict[str, typing.Any] | None = None,
        version: int = 3,
        prompt_version: int | None = 7,
    ) -> str:
        """Make an agent node without a service account; return its id.

        An agent made like this is the same as one made before agents
        had service accounts.
        """
        org = org or self.org
        agent_id = f'{slug}-{uuid.uuid4().hex[:8]}'
        props: dict[str, typing.Any] = {
            'id': agent_id,
            'slug': slug,
            'name': name,
            'enabled': enabled,
            'settings': json.dumps(settings or {}),
            'version': version,
            'prompt_version': prompt_version,
            'org_id': org,
            'created_at': '2026-10-07T12:00:00+00:00',
        }
        await self.graph.execute(
            'MATCH (o:Organization {{slug: {org_slug}}})'
            f' CREATE (a:Agent {props_template(props)})'
            ' CREATE (a)-[:BELONGS_TO]->(o)'
            ' RETURN a.id AS id',
            {**props, 'org_slug': org},
            ['id'],
        )
        return agent_id

    async def service_accounts(self, agent_id: str) -> list[dict[str, str]]:
        """Return the service accounts that the agent acts as."""
        records = await self.graph.execute(
            """
            MATCH (:Agent {{id: {id}}})-[:ACTS_AS]->(s:ServiceAccount)
            OPTIONAL MATCH (s)-[m:MEMBER_OF]->(o:Organization)
            RETURN s.id AS id, s.slug AS slug, o.slug AS org, m.role AS role
            """,
            {'id': agent_id},
            ['id', 'slug', 'org', 'role'],
        )
        return [
            {k: graph.parse_agtype(v) for k, v in record.items()}
            for record in records
        ]

    def url(self, path: str = '', org: str | None = None) -> str:
        return f'/organizations/{org or self.org}/agent-tasks/{path}'

    async def create_task(
        self, org: str | None = None, **body: typing.Any
    ) -> httpx.Response:
        payload: dict[str, typing.Any] = {
            'agent_slug': 'triage',
            'title': 'Look at the build',
            'description': 'Find why the build fails.',
        }
        payload.update(body)
        return await self.client.post(self.url(org=org), json=payload)

    async def open_session(self, task_id: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO agent_runtime.sessions (id, task_id)'
                ' VALUES (%s, %s)',
                (uuid.uuid4(), uuid.UUID(task_id)),
            )
            await conn.execute(
                "UPDATE agent_runtime.tasks SET status = 'running'"
                ' WHERE id = %s',
                (uuid.UUID(task_id),),
            )

    async def event_types(self, short_id: str) -> list[str]:
        response = await self.client.get(self.url(f'{short_id}/events'))
        self.assertEqual(response.status_code, 200, response.text)
        return [event['type'] for event in response.json()]


class CreateTaskTests(AgentTaskTestCase):
    async def test_create_pins_versions_and_writes_event(self) -> None:
        agent_id = await self.make_agent(settings={'task_budget': '5'})
        response = await self.create_task(project_id=self.project_id)
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()
        self.assertEqual(task['short_id'], 'T-1')
        self.assertEqual(task['agent_id'], agent_id)
        self.assertEqual(task['agent_version'], 3)
        self.assertEqual(task['prompt_version'], 7)
        self.assertEqual(task['project_id'], self.project_id)
        self.assertEqual(task['status'], 'queued')
        self.assertEqual(task['control'], 'run')
        self.assertEqual(task['owner'], self.email)
        self.assertEqual(task['origin'], {'kind': 'human', 'user': self.email})
        self.assertEqual(decimal.Decimal(task['budget']), 5)
        self.assertEqual(task['last_seq'], 1)

        response = await self.client.get(self.url('T-1/events'))
        (event,) = response.json()
        self.assertEqual(event['seq'], 1)
        self.assertEqual(event['type'], 'task.created')
        self.assertEqual(event['actor_kind'], 'human')
        self.assertEqual(event['actor_id'], self.email)
        self.assertEqual(event['channel'], 'web')
        self.assertEqual(event['payload']['agent_version'], 3)
        self.assertEqual(event['payload']['prompt_version'], 7)
        self.assertEqual(event['payload']['budget'], '5')
        self.assertEqual(event['payload']['title'], 'Look at the build')

    async def test_api_key_caller_writes_api_channel(self) -> None:
        await self.make_agent()
        self.auth_method = 'api_key'
        response = await self.create_task()
        self.assertEqual(response.status_code, 201, response.text)
        events = (await self.client.get(self.url('T-1/events'))).json()
        self.assertEqual(events[0]['channel'], 'api')

    async def test_budget_can_be_lowered_not_raised(self) -> None:
        await self.make_agent(settings={'task_budget': '5'})
        response = await self.create_task(budget='2.5')
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(decimal.Decimal(response.json()['budget']), 2.5)
        response = await self.create_task(budget='10')
        self.assertEqual(response.status_code, 422, response.text)

    async def test_no_agent_budget_means_no_task_budget(self) -> None:
        await self.make_agent()
        response = await self.create_task()
        self.assertIsNone(response.json()['budget'])
        response = await self.create_task(budget='3')
        self.assertEqual(decimal.Decimal(response.json()['budget']), 3)

    async def test_disabled_agent_is_refused(self) -> None:
        await self.make_agent(enabled=False)
        response = await self.create_task()
        self.assertEqual(response.status_code, 409, response.text)

    async def test_unknown_agent_or_project_is_refused(self) -> None:
        await self.make_agent()
        response = await self.create_task(agent_slug='nope')
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.create_task(project_id='nope')
        self.assertEqual(response.status_code, 422, response.text)

    async def test_unknown_org_is_404(self) -> None:
        response = await self.create_task(org='no-such-org')
        self.assertEqual(response.status_code, 404, response.text)

    async def test_idempotent_repeat_returns_first_task(self) -> None:
        await self.make_agent()
        await self.make_agent(org=self.other_org)
        first = await self.create_task(idempotency_key='k-1')
        self.assertEqual(first.status_code, 201, first.text)
        repeat = await self.create_task(idempotency_key='k-1', title='Other')
        self.assertEqual(repeat.status_code, 200, repeat.text)
        self.assertEqual(repeat.json()['id'], first.json()['id'])
        self.assertEqual(repeat.json()['title'], 'Look at the build')
        # The key is per organization.
        other = await self.create_task(self.other_org, idempotency_key='k-1')
        self.assertEqual(other.status_code, 201, other.text)
        self.assertNotEqual(other.json()['id'], first.json()['id'])
        # The repeat took no short id.
        response = await self.create_task()
        self.assertEqual(response.json()['short_id'], 'T-2')

    async def test_short_ids_count_per_organization(self) -> None:
        await self.make_agent()
        await self.make_agent(org=self.other_org)
        ids = [(await self.create_task()).json()['short_id'] for _ in '12']
        other = (await self.create_task(self.other_org)).json()['short_id']
        self.assertEqual(ids, ['T-1', 'T-2'])
        self.assertEqual(other, 'T-1')

    async def test_service_account_cannot_create(self) -> None:
        await self.make_agent()

        async def service_account() -> permissions.AuthContext:
            return permissions.AuthContext(
                service_account=models.ServiceAccount(
                    slug='robot', display_name='Robot'
                ),
                auth_method='client_credentials',
                permissions=set(self.permissions),
            )

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            service_account
        )
        response = await self.create_task()
        self.assertEqual(response.status_code, 403, response.text)


class ReadTaskTests(AgentTaskTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.make_agent()
        await self.make_agent('deploy', name='Deployer')
        await self.make_agent(org=self.other_org)
        await self.create_task(title='Fix the build')
        await self.create_task(
            agent_slug='deploy', title='Ship it', project_id=self.project_id
        )
        await self.create_task(title='Rotate keys')

    async def list_ids(self, **params: typing.Any) -> list[str]:
        response = await self.client.get(self.url(), params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return [task['short_id'] for task in response.json()]

    async def test_get_by_short_id(self) -> None:
        response = await self.client.get(self.url('t-2'))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['title'], 'Ship it')
        response = await self.client.get(self.url('T-99'))
        self.assertEqual(response.status_code, 404, response.text)

    async def test_list_is_newest_first(self) -> None:
        self.assertEqual(await self.list_ids(), ['T-3', 'T-2', 'T-1'])

    async def test_list_pages_with_cursor(self) -> None:
        response = await self.client.get(self.url(), params={'limit': 2})
        self.assertEqual(
            [t['short_id'] for t in response.json()], ['T-3', 'T-2']
        )
        next_link = response.links['next']['url']
        response = await self.client.get(next_link)
        self.assertEqual([t['short_id'] for t in response.json()], ['T-1'])
        self.assertNotIn('next', response.links)
        response = await self.client.get(self.url(), params={'cursor': 'x'})
        self.assertEqual(response.status_code, 400, response.text)

    async def test_text_query(self) -> None:
        self.assertEqual(await self.list_ids(q='BUILD'), ['T-1'])
        self.assertEqual(await self.list_ids(q='t-3'), ['T-3'])
        self.assertEqual(await self.list_ids(q='deployer'), ['T-2'])
        self.assertEqual(await self.list_ids(q=self.project_id), ['T-2'])
        self.assertEqual(await self.list_ids(q='%'), [])

    async def test_filters(self) -> None:
        await self.client.post(self.url('T-1/pause'))
        await self.client.post(self.url('T-2/cancel'))
        self.assertEqual(
            await self.list_ids(status=['paused', 'closed']), ['T-2', 'T-1']
        )
        self.assertEqual(await self.list_ids(status='queued'), ['T-3'])
        deploy = (await self.client.get(self.url('T-2'))).json()['agent_id']
        self.assertEqual(await self.list_ids(agent_id=deploy), ['T-2'])
        await self.client.post(
            self.url('T-3/reassign'), json={'owner': self.member}
        )
        self.assertEqual(await self.list_ids(owner=self.member), ['T-3'])
        self.assertEqual(await self.list_ids(mine='true'), ['T-2', 'T-1'])

    async def test_events_page_by_seq(self) -> None:
        await self.client.post(self.url('T-1/pause'))
        await self.client.post(self.url('T-1/resume'))
        response = await self.client.get(
            self.url('T-1/events'), params={'after_seq': 2, 'limit': 2}
        )
        self.assertEqual(response.status_code, 200, response.text)
        events = response.json()
        self.assertEqual([e['seq'] for e in events], [3, 4])
        self.assertEqual(
            [e['type'] for e in events], ['state.changed', 'control.changed']
        )
        response = await self.client.get(
            self.url('T-1/events'), params={'after_seq': 5}
        )
        self.assertEqual(response.json(), [])

    async def test_org_isolation(self) -> None:
        other = (await self.create_task(self.other_org)).json()
        self.assertEqual(other['short_id'], 'T-1')
        response = await self.client.get(self.url(org=self.other_org))
        self.assertEqual([t['id'] for t in response.json()], [other['id']])
        response = await self.client.get(self.url('T-2', org=self.other_org))
        self.assertEqual(response.status_code, 404, response.text)
        response = await self.client.post(
            self.url('T-2/cancel', org=self.other_org)
        )
        self.assertEqual(response.status_code, 404, response.text)
        response = await self.client.get(self.url('T-1'))
        self.assertNotEqual(response.json()['id'], other['id'])


class ControlTests(AgentTaskTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.make_agent()
        self.task = (await self.create_task()).json()

    async def post(self, action: str, **body: typing.Any) -> httpx.Response:
        return await self.client.post(
            self.url(f'T-1/{action}'), json=body or None
        )

    async def test_pause_and_resume_without_session(self) -> None:
        response = await self.post('pause')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['control'], 'pause')
        self.assertEqual(response.json()['status'], 'paused')
        response = await self.post('pause')
        self.assertEqual(response.json()['last_seq'], 3)
        response = await self.post('resume')
        self.assertEqual(response.json()['control'], 'run')
        self.assertEqual(response.json()['status'], 'queued')
        self.assertEqual(
            await self.event_types('T-1'),
            [
                'task.created',
                'control.changed',
                'state.changed',
                'control.changed',
                'state.changed',
            ],
        )
        events = (await self.client.get(self.url('T-1/events'))).json()
        self.assertEqual(
            events[1]['payload'],
            {'from': 'run', 'to': 'pause', 'actor': self.email},
        )
        self.assertEqual(
            events[2]['payload'],
            {'from': 'queued', 'to': 'paused', 'reason': 'control_changed'},
        )

    async def test_cancel_without_session_closes(self) -> None:
        response = await self.post('cancel')
        self.assertEqual(response.status_code, 200, response.text)
        task = response.json()
        self.assertEqual(task['status'], 'closed')
        self.assertEqual(task['control'], 'cancel')
        self.assertEqual(task['outcome'], 'cancelled_by_human')
        self.assertEqual(
            task['outcome_reason'], agent_tasks.store.CANCELLED_WITHOUT_SESSION
        )
        self.assertIsNotNone(task['closed_at'])
        self.assertEqual(
            await self.event_types('T-1'),
            [
                'task.created',
                'control.changed',
                'state.changed',
                'outcome.set',
            ],
        )

    async def test_open_session_changes_only_control(self) -> None:
        await self.open_session(self.task['id'])
        response = await self.post('pause')
        self.assertEqual(response.json()['control'], 'pause')
        self.assertEqual(response.json()['status'], 'running')
        response = await self.post('cancel')
        self.assertEqual(response.json()['control'], 'cancel')
        self.assertEqual(response.json()['status'], 'running')
        self.assertIsNone(response.json()['outcome'])
        # A cancel waits for the harness; nothing undoes it.
        for action in ('pause', 'resume'):
            response = await self.post(action)
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            await self.event_types('T-1'),
            ['task.created', 'control.changed', 'control.changed'],
        )

    async def test_closed_task_refuses_changes(self) -> None:
        await self.post('cancel')
        for action in ('pause', 'resume', 'cancel'):
            response = await self.post(action)
            self.assertEqual(response.status_code, 409, response.text)
        response = await self.post('reassign', owner=self.member)
        self.assertEqual(response.status_code, 409, response.text)

    async def test_reassign(self) -> None:
        response = await self.post('reassign', owner=self.member)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['owner'], self.member)
        events = (await self.client.get(self.url('T-1/events'))).json()
        self.assertEqual(events[-1]['type'], 'owner.changed')
        self.assertEqual(
            events[-1]['payload'], {'from': self.email, 'to': self.member}
        )
        response = await self.post('reassign', owner='stranger@example.com')
        self.assertEqual(response.status_code, 422, response.text)

    async def test_unknown_task_is_404(self) -> None:
        response = await self.client.post(self.url('T-9/pause'))
        self.assertEqual(response.status_code, 404, response.text)
        response = await self.client.post(
            self.url('T-9/reassign'), json={'owner': self.member}
        )
        self.assertEqual(response.status_code, 404, response.text)


class PermissionTests(AgentTaskTestCase):
    async def test_each_endpoint_needs_its_permission(self) -> None:
        await self.make_agent()
        await self.create_task()
        cases: list[tuple[str, str, str, dict[str, typing.Any] | None]] = [
            (
                'agent_task:create',
                'POST',
                '',
                {'agent_slug': 'triage', 'title': 'x', 'description': 'y'},
            ),
            ('agent_task:read', 'GET', '', None),
            ('agent_task:read', 'GET', 'T-1', None),
            ('agent_task:read', 'GET', 'T-1/events', None),
            ('agent_task:manage', 'POST', 'T-1/pause', None),
            ('agent_task:manage', 'POST', 'T-1/resume', None),
            ('agent_task:manage', 'POST', 'T-1/cancel', None),
            (
                'agent_task:manage',
                'POST',
                'T-1/reassign',
                {'owner': self.member},
            ),
        ]
        for permission, method, path, body in cases:
            with self.subTest(permission=permission, path=path):
                self.permissions = set(ALL_PERMISSIONS) - {permission}
                response = await self.client.request(
                    method, self.url(path), json=body
                )
                self.assertEqual(response.status_code, 403, response.text)
                self.assertIn(permission, response.text)


class ServiceAccountTests(AgentTaskTestCase):
    async def create_agent(self, slug: str) -> dict[str, typing.Any]:
        response = await self.client.post(
            f'/organizations/{self.org}/agents/',
            json={'name': slug.title(), 'slug': slug, 'team': self.team_id},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def test_agent_create_makes_service_account(self) -> None:
        agent = await self.create_agent('triage')
        (account,) = await self.service_accounts(agent['id'])
        self.assertEqual(account['slug'], f'agent-{agent["id"]}')
        self.assertEqual(account['org'], self.org)
        # No role, so no permissions.
        self.assertIsNone(account['role'])

    async def test_duplicate_gets_its_own_service_account(self) -> None:
        first = await self.create_agent('triage')
        copy = await self.create_agent('triage-copy')
        (one,) = await self.service_accounts(first['id'])
        (two,) = await self.service_accounts(copy['id'])
        self.assertNotEqual(one['id'], two['id'])

    async def test_agent_delete_removes_service_account(self) -> None:
        agent = await self.create_agent('triage')
        (account,) = await self.service_accounts(agent['id'])
        response = await self.client.delete(
            f'/organizations/{self.org}/agents/triage'
        )
        self.assertEqual(response.status_code, 204, response.text)
        records = await self.graph.execute(
            'MATCH (s:ServiceAccount {{slug: {slug}}}) RETURN s.id AS id',
            {'slug': account['slug']},
            ['id'],
        )
        self.assertEqual(records, [])

    async def test_task_create_ensures_service_account(self) -> None:
        agent_id = await self.make_agent()
        self.assertEqual(await self.service_accounts(agent_id), [])
        first = (await self.create_task()).json()
        (account,) = await self.service_accounts(agent_id)
        self.assertEqual(account['org'], self.org)
        self.assertEqual(first['service_account_id'], account['id'])
        second = (await self.create_task()).json()
        self.assertEqual(second['service_account_id'], account['id'])
        self.assertEqual(len(await self.service_accounts(agent_id)), 1)

    async def test_task_keeps_service_account_of_agent(self) -> None:
        agent = await self.create_agent('triage')
        (account,) = await self.service_accounts(agent['id'])
        task = (await self.create_task()).json()
        self.assertEqual(task['service_account_id'], account['id'])


class StoreTests(AgentTaskTestCase):
    def new_task(self, key: str | None) -> agent_tasks.NewTask:
        return agent_tasks.NewTask(
            organization_id=self.org,
            agent_id='agent-1',
            agent_version=1,
            prompt_version=None,
            service_account_id='sa-1',
            project_id=None,
            title='Race',
            description='Two requests with one key.',
            origin_kind='human',
            origin={'kind': 'human', 'user': self.email},
            idempotency_key=key,
            owner=self.email,
            budget=None,
        )

    async def test_key_collision_returns_first_task(self) -> None:
        # The endpoint checks the key first. Two concurrent requests can
        # both pass that check; the unique index stops the second.
        actor = agent_tasks.Actor('human', self.email, 'api')
        first, created = await self.store.create(self.new_task('k'), actor, {})
        self.assertTrue(created)
        second, created = await self.store.create(
            self.new_task('k'), actor, {}
        )
        self.assertFalse(created)
        self.assertEqual(second['id'], first['id'])
        third, _ = await self.store.create(self.new_task(None), actor, {})
        self.assertEqual(third['short_id'], 'T-2')
