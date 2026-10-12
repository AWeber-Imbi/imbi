"""Tests for the trigger reconciler (ADR 0021, Triggers).

These run against the live Postgres and graph that ``root:services``
boots. imbi-scheduler is a fake behind ``httpx.MockTransport``.
"""

import json
import typing
import unittest
import uuid

import httpx

from imbi.api import workflows
from imbi.common import graph
from imbi.workflows import bindings, executors, settings


class FakeScheduler:
    """imbi-scheduler's task routes, and imbi-api's token route."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, typing.Any]] = {}
        self.calls: list[str] = []
        #: The status to answer every task call with, for a failure.
        self.fail: int | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith('/auth/token'):
            return httpx.Response(
                200, json={'access_token': 'token', 'expires_in': 900}
            )
        self.calls.append(request.method)
        if self.fail:
            return httpx.Response(self.fail, json={'detail': 'down'})
        slug = path.rsplit('/', 1)[1]
        task = self.tasks.get(slug)
        match request.method:
            case 'POST':
                body = json.loads(request.content)
                task = self.tasks[body['slug']] = {
                    **body,
                    'id': str(uuid.uuid4()),
                }
                return httpx.Response(201, json=task)
            case _ if task is None:
                return httpx.Response(404, json={'detail': 'not found'})
            case 'GET':
                return httpx.Response(200, json=task)
            case 'PATCH':
                for op in json.loads(request.content):
                    task[op['path'][1:]] = op['value']
                return httpx.Response(200, json=task)
            case _:
                del self.tasks[slug]
                return httpx.Response(204)


def _node(
    node_id: str, step: str, params: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    return {
        'id': node_id,
        'key': node_id,
        'type': step,
        'title': node_id,
        'position': {'x': 0, 'y': 0},
        'params': params,
    }


class ReconcilerTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        suffix = uuid.uuid4().hex[:10]
        self.org = f'wfb-{suffix}'
        self.webhook = f'wh-{suffix}'
        self.slug = f'wf-{suffix}'
        await graph.initialize()
        await workflows.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.pool = workflows.create_pool()
        await self.pool.open()
        self.definitions = workflows.WorkflowStore(self.pool)
        self.addAsyncCleanup(self._cleanup)
        await self.graph.execute(
            """
            CREATE (o:Organization {{id: {org}, slug: {org}, name: {org}}})
            CREATE (w:Webhook {{id: {webhook}, slug: {webhook},
                                name: 'Hook'}})
            CREATE (w)-[:BELONGS_TO]->(o)
            RETURN o.id AS id
            """,
            {'org': self.org, 'webhook': self.webhook},
            ['id'],
        )
        await self.definitions.create(
            self.org,
            self.slug,
            workflows.Definition(
                name='Nightly',
                description='',
                owner_team_id='team',
                graph={'nodes': [], 'edges': []},
                settings={},
                validation={'issues': []},
                author='ops@example.com',
            ),
        )
        self.scheduler = FakeScheduler()
        self.http = httpx.AsyncClient(
            transport=httpx.MockTransport(self.scheduler)
        )
        config = settings.Workflows(
            sa_client_id='client',
            sa_client_secret='secret',
            api_url='http://api',
            scheduler_url='http://scheduler/api',
        )
        self.reconciler = bindings.Reconciler(
            self.pool,
            self.http,
            executors.Executors(
                executors.Api(self.http, config), self.graph, config
            ),
            config,
        )

    async def _cleanup(self) -> None:
        await self.http.aclose()
        await self.graph.execute(
            """
            MATCH (r:WebhookRule)-[:ACTIONS]->(:Webhook {{id: {webhook}}})
            DETACH DELETE r
            RETURN 1 AS ok
            """,
            {'webhook': self.webhook},
            ['ok'],
        )
        await self.graph.execute(
            """
            MATCH (n) WHERE n.id IN {ids}
            DETACH DELETE n
            RETURN 1 AS ok
            """,
            {'ids': [self.org, self.webhook]},
            ['ok'],
        )
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM workflows.trigger_bindings'
                ' WHERE organization_id = %s',
                (self.org,),
            )
            await conn.execute(
                'DELETE FROM workflows.workflows WHERE organization_id = %s',
                (self.org,),
            )
        await self.pool.close()
        await self.graph.close()

    async def _activate(self, *triggers: workflows.Trigger) -> None:
        await self.definitions.activate(
            self.org, self.slug, 1, 'ops@example.com', list(triggers)
        )

    async def _bindings(self) -> list[dict[str, typing.Any]]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT id, node_id, sync_state, error, target_id'
                ' FROM workflows.trigger_bindings'
                ' WHERE organization_id = %s ORDER BY node_id',
                (self.org,),
            )
            names = [c.name for c in cur.description or []]
            return [
                dict(zip(names, r, strict=True)) for r in await cur.fetchall()
            ]

    async def _rules(self) -> list[dict[str, typing.Any]]:
        records = await self.graph.execute(
            """
            MATCH (r:WebhookRule)-[:ACTIONS]->(:Webhook {{id: {webhook}}})
            RETURN r.handler AS handler, r.handler_config AS config,
                   r.filter_expression AS filter
            """,
            {'webhook': self.webhook},
            ['handler', 'config', 'filter'],
        )
        return [
            {k: graph.parse_agtype(v) for k, v in r.items()} for r in records
        ]


class ScheduleTestCase(ReconcilerTestCase):
    trigger = workflows.Trigger('tick', 'schedule', {'cron': '0 9 * * *'})

    async def test_activation_pause_and_delete(self) -> None:
        await self._activate(self.trigger)
        await self.reconciler.reconcile()
        [binding] = await self._bindings()
        slug = f'workflow-{binding["id"]}'
        task = self.scheduler.tasks[slug]
        self.assertEqual(binding['sync_state'], 'synced')
        self.assertEqual(binding['target_id'], task['id'])
        self.assertEqual(task['organization'], self.org)
        self.assertTrue(task['enabled'])
        self.assertEqual(task['trigger']['expression'], '0 9 * * *')
        self.assertEqual(task['identity']['subject'], 'imbi-scheduler')
        self.assertEqual(
            task['target'],
            {
                'kind': 'api',
                'method': 'POST',
                'path': f'/workflows/{self.slug}/runs',
                'query': {},
                'body': {
                    'trigger': 'tick',
                    'payload': {'fired_at': '{{ run.fired_at }}'},
                },
                'organization': None,
            },
        )

        # A task that matches is left alone.
        self.scheduler.calls.clear()
        await self.reconciler.reconcile()
        self.assertEqual(self.scheduler.calls, ['GET'])

        await self.definitions.pause(self.org, self.slug)
        await self.reconciler.reconcile()
        self.assertFalse(self.scheduler.tasks[slug]['enabled'])
        self.assertEqual((await self._bindings())[0]['sync_state'], 'synced')

        await self.definitions.delete(self.org, self.slug)
        await self.reconciler.reconcile()
        self.assertEqual(self.scheduler.tasks, {})
        self.assertEqual(await self._bindings(), [])

    async def test_scheduler_failure_leaves_nothing_half_made(self) -> None:
        await self._activate(self.trigger)
        self.scheduler.fail = 500
        await self.reconciler.reconcile()
        [binding] = await self._bindings()
        self.assertEqual(binding['sync_state'], 'failed')
        self.assertIn('imbi-scheduler returned 500', binding['error'])
        self.assertIsNone(binding['target_id'])
        self.assertEqual(self.scheduler.tasks, {})
        row = await self.definitions.get(self.org, self.slug)
        assert row is not None
        self.assertEqual(row['status'], 'active')

        # The next pass syncs it.
        self.scheduler.fail = None
        await self.reconciler.reconcile()
        [binding] = await self._bindings()
        self.assertEqual(binding['sync_state'], 'synced')
        self.assertIsNone(binding['error'])
        self.assertEqual(len(self.scheduler.tasks), 1)

    async def test_change_during_a_pass_stays_pending(self) -> None:
        await self._activate(self.trigger)
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT * FROM workflows.trigger_bindings'
                ' WHERE organization_id = %s',
                (self.org,),
            )
            names = [c.name for c in cur.description or []]
            row = dict(zip(names, await cur.fetchone() or (), strict=True))
        await self.definitions.pause(self.org, self.slug)
        await self.reconciler._record(row, 'task', None)  # pyright: ignore[reportPrivateUsage]
        self.assertEqual((await self._bindings())[0]['sync_state'], 'pending')


class WebhookTestCase(ReconcilerTestCase):
    def _trigger(self, rule_filter: str | None = None) -> workflows.Trigger:
        return workflows.Trigger(
            'hook',
            'webhook',
            {'webhook_id': self.webhook, 'filter': rule_filter},
        )

    async def test_rule_follows_the_binding(self) -> None:
        await self._activate(self._trigger())
        await self.reconciler.reconcile()
        [binding] = await self._bindings()
        self.assertEqual(binding['sync_state'], 'synced')
        self.assertEqual(binding['target_id'], self.webhook)
        config = {
            'workflow_slug': self.slug,
            'trigger': 'hook',
            'binding': str(binding['id']),
        }
        [rule] = await self._rules()
        self.assertEqual(rule['handler'], bindings.HANDLER)
        self.assertEqual(rule['filter'], 'true')
        self.assertEqual(json.loads(rule['config']), config)

        await self.reconciler.reconcile()
        self.assertEqual(len(await self._rules()), 1)

        # A new active version with a filter replaces the rule.
        await self._activate(self._trigger('payload.action == "opened"'))
        await self.reconciler.reconcile()
        [rule] = await self._rules()
        self.assertEqual(rule['filter'], 'payload.action == "opened"')

        # A pause keeps the rule: the run endpoint refuses with 409.
        await self.definitions.pause(self.org, self.slug)
        await self.reconciler.reconcile()
        self.assertEqual(len(await self._rules()), 1)

        await self.definitions.delete(self.org, self.slug)
        await self.reconciler.reconcile()
        self.assertEqual(await self._rules(), [])
        self.assertEqual(await self._bindings(), [])

    async def test_webhook_outside_the_org_fails(self) -> None:
        await self._activate(
            workflows.Trigger('hook', 'webhook', {'webhook_id': 'elsewhere'})
        )
        await self.reconciler.reconcile()
        [binding] = await self._bindings()
        self.assertEqual(binding['sync_state'], 'failed')
        self.assertIn(
            "'elsewhere' is not in the organization", binding['error']
        )
        self.assertEqual(await self._rules(), [])
