"""Tests for the agent task endpoints and the agent service accounts.

These run against the live Postgres that ``root:services`` boots: the
graph for organizations, agents, and service accounts, and the
``agent_runtime`` schema for task state. Each test makes its own
organizations, so tests do not share task counters.

The caller is a member of ``org`` and ``other_org``, and not of
``foreign_org``.
"""

import datetime
import decimal
import json
import typing
import uuid

import httpx
from psycopg import sql

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
        'agent_task:resolve',
    }
)


class AgentTaskTestCase(support.SharedAppAsyncTestCase):
    """Fixtures: two organizations, a team, a project, and a member."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        suffix = uuid.uuid4().hex[:10]
        self.org = f'at-{suffix}'
        self.other_org = f'at-other-{suffix}'
        self.foreign_org = f'at-foreign-{suffix}'
        self.team_id = f'team-{suffix}'
        # No 't-' in the slug, so that q='t-3' matches only T-3
        self.project_id = f'proj-{suffix}'
        self.member = f'member-{suffix}@example.com'
        self.email = f'dev-{suffix}@example.com'
        self.user_id = f'dev-{suffix}'

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
            CREATE (f:Organization {{id: {foreign}, slug: {foreign},
                                     name: {foreign}}})
            CREATE (t:Team {{id: {team}, slug: {team}, name: 'Ops'}})
            CREATE (t)-[:BELONGS_TO]->(o)
            CREATE (p:Project {{id: {project}, slug: {project},
                                name: 'Billing'}})
            CREATE (p)-[:OWNED_BY]->(t)
            CREATE (u:User {{id: {member}, email: {member},
                             display_name: 'Member', is_active: true}})
            CREATE (u)-[:MEMBER_OF {{role: 'developer'}}]->(o)
            CREATE (d:User {{id: {user_id}, email: {email},
                             display_name: 'Dev User', is_active: true}})
            CREATE (d)-[:MEMBER_OF {{role: 'developer'}}]->(o)
            CREATE (d)-[:MEMBER_OF {{role: 'developer'}}]->(x)
            RETURN o.id AS id
            """,
            {
                'org': self.org,
                'other': self.other_org,
                'foreign': self.foreign_org,
                'team': self.team_id,
                'project': self.project_id,
                'member': self.member,
                'user_id': self.user_id,
                'email': self.email,
            },
            ['id'],
        )

        self.permissions = set(ALL_PERMISSIONS)
        self.user = models.User(
            id=self.user_id,
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
        for org in (self.org, self.other_org, self.foreign_org):
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
                    self.foreign_org,
                    self.team_id,
                    self.project_id,
                    self.member,
                    self.user_id,
                ]
            },
            ['ok'],
        )
        async with self.pool.connection() as conn:
            # The relation keys RESTRICT the delete of a task.
            for table in ('task_dependencies', 'task_projects'):
                await conn.execute(
                    sql.SQL(
                        'DELETE FROM {} WHERE organization_id = ANY(%s)'
                    ).format(sql.Identifier('agent_runtime', table)),
                    ([self.org, self.other_org, self.foreign_org],),
                )
            await conn.execute(
                'DELETE FROM agent_runtime.tasks'
                ' WHERE organization_id = ANY(%s)',
                ([self.org, self.other_org, self.foreign_org],),
            )
            await conn.execute(
                'DELETE FROM agent_runtime.task_id_sequences'
                ' WHERE organization_id = ANY(%s)',
                ([self.org, self.other_org, self.foreign_org],),
            )
        await self.pool.close()
        await self.graph.close()

    # -- Fixtures ------------------------------------------------------

    async def act_as_service_account(self, *, member: bool) -> None:
        """Authenticate as a service account, a member of ``org`` or not."""
        account = models.ServiceAccount(
            slug=f'sa-{self.org}', display_name='Robot'
        )
        if member:
            await self.graph.execute(
                """
                MATCH (o:Organization {{slug: {org}}})
                CREATE (s:ServiceAccount {{id: {slug}, slug: {slug}}})
                CREATE (s)-[:MEMBER_OF]->(o)
                RETURN s.slug AS slug
                """,
                {'org': self.org, 'slug': account.slug},
                ['slug'],
            )
            self.addAsyncCleanup(
                self.graph.execute,
                'MATCH (s:ServiceAccount {{slug: {slug}}}) DETACH DELETE s'
                ' RETURN 1 AS ok',
                {'slug': account.slug},
                ['ok'],
            )

        async def service_account() -> permissions.AuthContext:
            return permissions.AuthContext(
                service_account=account,
                auth_method='client_credentials',
                permissions=set(self.permissions),
            )

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            service_account
        )

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

    async def test_budget_out_of_column_range_is_422(self) -> None:
        await self.make_agent()
        for budget in ('1000000000', '0.0000001'):
            response = await self.create_task(budget=budget)
            self.assertEqual(response.status_code, 422, budget)

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

    async def test_idempotency_key_is_per_principal(self) -> None:
        await self.make_agent()
        mine = await self.create_task(idempotency_key='shared')
        self.user = models.User(
            id=self.member,
            email=self.member,
            display_name='Member',
            is_active=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        theirs = await self.create_task(idempotency_key='shared')
        self.assertEqual(theirs.status_code, 201, theirs.text)
        self.assertNotEqual(theirs.json()['id'], mine.json()['id'])
        self.assertEqual(theirs.json()['owner'], self.member)
        repeat = await self.create_task(idempotency_key='shared')
        self.assertEqual(repeat.status_code, 200, repeat.text)
        self.assertEqual(repeat.json()['id'], theirs.json()['id'])

    async def test_short_ids_count_per_organization(self) -> None:
        await self.make_agent()
        await self.make_agent(org=self.other_org)
        ids = [(await self.create_task()).json()['short_id'] for _ in '12']
        other = (await self.create_task(self.other_org)).json()['short_id']
        self.assertEqual(ids, ['T-1', 'T-2'])
        self.assertEqual(other, 'T-1')

    async def test_service_account_cannot_create(self) -> None:
        await self.make_agent()
        await self.act_as_service_account(member=True)
        response = await self.create_task()
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn('requires user authentication', response.text)
        response = await self.client.get(self.url())
        self.assertEqual(response.status_code, 200, response.text)


class TriggerOriginTests(AgentTaskTestCase):
    """Tasks that the scheduler and the gateway make (P6, CC9)."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.make_agent()

    async def act_as_internal_service(self, slug: str) -> None:
        """Authenticate as one of Imbi's own services, a member of ``org``.

        The account can already exist in the shared database, from the
        setup of another test, so it is only deleted when made here.
        """
        if not await self.graph.execute(
            'MATCH (s:ServiceAccount {{slug: {slug}}}) RETURN s.slug AS slug',
            {'slug': slug},
            ['slug'],
        ):
            self.addAsyncCleanup(
                self.graph.execute,
                'MATCH (s:ServiceAccount {{slug: {slug}}}) DETACH DELETE s'
                ' RETURN 1 AS ok',
                {'slug': slug},
                ['ok'],
            )
        await self.graph.execute(
            """
            MATCH (o:Organization {{slug: {org}}})
            MERGE (s:ServiceAccount {{slug: {slug}}})
            MERGE (s)-[:MEMBER_OF]->(o)
            RETURN s.slug AS slug
            """,
            {'org': self.org, 'slug': slug},
            ['slug'],
        )
        account = models.ServiceAccount(slug=slug, display_name=slug)

        async def service_account() -> permissions.AuthContext:
            return permissions.AuthContext(
                service_account=account,
                auth_method='client_credentials',
                permissions={'agent_task:create', 'agent_task:read'},
            )

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            service_account
        )

    async def post(
        self, headers: dict[str, str], **body: typing.Any
    ) -> httpx.Response:
        payload: dict[str, typing.Any] = {
            'agent_slug': 'triage',
            'title': 'Nightly audit',
            'description': 'Audit the dependencies.',
            'owner': self.member,
        }
        payload.update(body)
        return await self.client.post(
            self.url(), json=payload, headers=headers
        )

    async def test_schedule_run_makes_one_task(self) -> None:
        await self.act_as_internal_service('imbi-scheduler')
        run = {'X-Imbi-Scheduled-Task': 'st-1', 'Idempotency-Key': 'run-1'}
        first = await self.post(run)
        self.assertEqual(first.status_code, 201, first.text)
        task = first.json()
        origin = {'kind': 'schedule', 'scheduled_task_id': 'st-1'}
        self.assertLessEqual(origin.items(), task['origin'].items())
        self.assertEqual(task['idempotency_key'], 'run-1')
        self.assertEqual(task['owner'], self.member)
        # No dispatch yet (D2): the task waits.
        self.assertEqual(task['status'], 'queued')

        # A retry of the same run returns the first task.
        repeat = await self.post(run, title='Other')
        self.assertEqual(repeat.status_code, 200, repeat.text)
        self.assertEqual(repeat.json()['id'], task['id'])
        # The next run, and the same key from another schedule, are new.
        for headers in (
            {'X-Imbi-Scheduled-Task': 'st-1', 'Idempotency-Key': 'run-2'},
            {'X-Imbi-Scheduled-Task': 'st-2', 'Idempotency-Key': 'run-1'},
        ):
            response = await self.post(headers)
            self.assertEqual(response.status_code, 201, response.text)
            self.assertNotEqual(response.json()['id'], task['id'])

        (event,) = (await self.client.get(self.url('T-1/events'))).json()
        self.assertEqual(event['type'], 'task.created')
        self.assertEqual(event['actor_kind'], 'system')
        self.assertEqual(event['actor_id'], 'imbi-scheduler')
        self.assertEqual(event['payload']['origin'], origin)

    async def test_webhook_delivery_makes_one_task(self) -> None:
        await self.act_as_internal_service('imbi-gateway')
        delivery = {'X-Imbi-Webhook': 'wh-1', 'X-Imbi-Delivery': 'd-1'}
        first = await self.post(delivery, idempotency_key='d-1/triage')
        self.assertEqual(first.status_code, 201, first.text)
        task = first.json()
        origin = {
            'kind': 'webhook',
            'webhook_id': 'wh-1',
            'delivery_id': 'd-1',
        }
        self.assertLessEqual(origin.items(), task['origin'].items())
        self.assertEqual(task['status'], 'queued')
        repeat = await self.post(delivery, idempotency_key='d-1/triage')
        self.assertEqual(repeat.status_code, 200, repeat.text)
        self.assertEqual(repeat.json()['id'], task['id'])
        (event,) = (await self.client.get(self.url('T-1/events'))).json()
        self.assertEqual(event['payload']['origin'], origin)
        self.assertEqual(event['actor_id'], 'imbi-gateway')

    async def test_service_names_its_origin_and_owner(self) -> None:
        await self.act_as_internal_service('imbi-scheduler')
        response = await self.post({})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn('X-Imbi-Scheduled-Task', response.text)
        # A webhook origin from the scheduler is not a schedule origin.
        response = await self.post(
            {'X-Imbi-Webhook': 'wh-1', 'X-Imbi-Delivery': 'd-1'}
        )
        self.assertEqual(response.status_code, 422, response.text)
        headers = {'X-Imbi-Scheduled-Task': 'st-1'}
        response = await self.post(headers, owner=None)
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.post(headers, owner='stranger@example.com')
        self.assertEqual(response.status_code, 422, response.text)

    async def test_person_cannot_name_an_origin(self) -> None:
        for headers in (
            {'X-Imbi-Scheduled-Task': 'st-1'},
            {'X-Imbi-Webhook': 'wh-1', 'X-Imbi-Delivery': 'd-1'},
        ):
            response = await self.post(headers, owner=None)
            self.assertEqual(response.status_code, 403, response.text)
            self.assertEqual(
                response.json()['detail']['error'], 'origin_forbidden'
            )
        response = await self.post({})
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.post({}, owner=None)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['origin']['kind'], 'human')

    async def test_origin_does_not_change(self) -> None:
        await self.act_as_internal_service('imbi-scheduler')
        created = await self.post({'X-Imbi-Scheduled-Task': 'st-1'})
        self.assertEqual(created.status_code, 201, created.text)
        await self.store.set_owner(
            self.org,
            'T-1',
            self.email,
            agent_tasks.Actor('human', self.email, 'web'),
        )
        task = await self.store.get(self.org, 'T-1')
        assert task is not None
        self.assertEqual(task['owner'], self.email)
        self.assertEqual(
            task['origin'], {'kind': 'schedule', 'scheduled_task_id': 'st-1'}
        )


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

    async def test_project_slug(self) -> None:
        response = await self.client.get(self.url('T-2'))
        self.assertEqual(response.json()['project_slug'], self.project_id)
        response = await self.client.get(self.url('T-1'))
        self.assertIsNone(response.json()['project_slug'])

    async def open_request(
        self,
        short_id: str,
        title: str,
        expires_at: datetime.datetime | None = None,
    ) -> None:
        await self.store.open_request(
            self.org,
            short_id,
            agent_tasks.NewRequest(
                kind='feedback',
                title=title,
                why=None,
                options=None,
                artifacts=None,
                artifact_digests=None,
                expires_at=expires_at,
                session_id=None,
            ),
            agent_tasks.Actor('agent', 'triage', 'harness'),
        )

    async def waiting(self) -> tuple[int, dict[str, str | None]]:
        """Return the waiting count and ``blocked_since`` by short id."""
        response = await self.client.get(self.url('waiting'))
        self.assertEqual(response.status_code, 200, response.text)
        tasks = (await self.client.get(self.url())).json()
        return response.json()['count'], {
            t['short_id']: t['blocked_since'] for t in tasks
        }

    async def test_blocked_since_and_waiting_count(self) -> None:
        self.assertEqual((await self.waiting())[0], 0)
        await self.open_request('T-3', 'First')
        await self.open_request('T-1', 'Second')
        await self.open_request('T-3', 'Third')
        count, since = await self.waiting()
        self.assertEqual(count, 2)
        self.assertIsNone(since['T-2'])
        assert since['T-1'] is not None and since['T-3'] is not None
        self.assertLess(since['T-3'], since['T-1'])
        response = await self.client.get(self.url('waiting', self.other_org))
        self.assertEqual(response.json(), {'count': 0})

    async def test_paused_task_with_open_request_still_waits(self) -> None:
        await self.open_request('T-1', 'Ask')
        response = await self.client.post(
            self.url('T-1/reply'), json={'body': 'Wait.', 'hold': True}
        )
        self.assertEqual(response.json()['status'], 'paused')
        count, since = await self.waiting()
        self.assertEqual(count, 1)
        self.assertIsNotNone(since['T-1'])

    async def test_closed_task_and_expired_request_do_not_wait(self) -> None:
        await self.open_request('T-1', 'Ask')
        await self.client.post(self.url('T-1/cancel'))
        past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=1
        )
        await self.open_request('T-2', 'Too late', expires_at=past)
        count, since = await self.waiting()
        self.assertEqual(count, 0)
        self.assertIsNone(since['T-1'])
        self.assertIsNone(since['T-2'])

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
            ('agent_task:read', 'GET', 'waiting', None),
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
            ('agent_task:manage', 'POST', 'T-1/reply', {'body': 'Hi.'}),
            (
                'agent_task:resolve',
                'POST',
                f'T-1/requests/{uuid.uuid4()}/resolve',
                {'status': 'answered', 'answer': 'yes'},
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
            origin_id=self.user_id,
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


class MembershipTests(AgentTaskTestCase):
    async def test_non_member_is_refused_on_every_route(self) -> None:
        await self.make_agent(org=self.foreign_org)
        await self.store.create(
            agent_tasks.NewTask(
                organization_id=self.foreign_org,
                agent_id='agent-1',
                agent_version=1,
                prompt_version=None,
                service_account_id='sa-1',
                project_id=None,
                title='Secret',
                description='Not for other orgs.',
                origin_kind='human',
                origin_id='someone',
                origin={'kind': 'human', 'user': 'someone@example.com'},
                idempotency_key=None,
                owner='someone@example.com',
                budget=None,
            ),
            agent_tasks.Actor('human', 'someone@example.com', 'web'),
            {},
        )
        cases: list[tuple[str, str, dict[str, typing.Any] | None]] = [
            (
                'POST',
                '',
                {'agent_slug': 'triage', 'title': 'x', 'description': 'y'},
            ),
            ('GET', '', None),
            ('GET', 'waiting', None),
            ('GET', 'T-1', None),
            ('GET', 'T-1/events', None),
            ('POST', 'T-1/pause', None),
            ('POST', 'T-1/resume', None),
            ('POST', 'T-1/cancel', None),
            ('POST', 'T-1/reassign', {'owner': self.member}),
            ('POST', 'T-1/reply', {'body': 'Hi.'}),
            (
                'POST',
                f'T-1/requests/{uuid.uuid4()}/resolve',
                {'status': 'answered', 'answer': 'yes'},
            ),
        ]
        for method, path, body in cases:
            with self.subTest(method=method, path=path):
                response = await self.client.request(
                    method, self.url(path, org=self.foreign_org), json=body
                )
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(
                    response.json()['detail']['error'],
                    'organization_forbidden',
                )
        task = await self.store.get(self.foreign_org, 'T-1')
        assert task is not None
        self.assertEqual(task['control'], 'run')
        self.assertEqual(task['last_seq'], 1)

    async def test_service_account_needs_membership(self) -> None:
        await self.act_as_service_account(member=False)
        response = await self.client.get(self.url())
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'organization_forbidden'
        )
