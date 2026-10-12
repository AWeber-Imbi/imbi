"""Tests for the workflow definition endpoints (ADR 0021).

These run against the live Postgres that ``root:services`` boots: the
graph for the organization and the team, and the ``workflows`` schema
for definitions. Each test makes its own organization.
"""

import datetime
import typing
import uuid

import httpx

from apps.api.tests import support
from imbi.api import models, workflows
from imbi.api.auth import permissions
from imbi.common import graph

ALL_PERMISSIONS = frozenset(
    {
        'workflow:read',
        'workflow:create',
        'workflow:write',
        'workflow:delete',
        'project:deployment:write',
    }
)


def _node(
    node_id: str, step: str, params: dict[str, typing.Any] | None = None
) -> dict[str, typing.Any]:
    return {
        'id': node_id,
        'key': node_id,
        'type': step,
        'title': node_id.title(),
        'position': {'x': 0, 'y': 0},
        'params': params or {},
    }


DEPLOY_GRAPH = {
    'nodes': [
        _node('start', 'manual'),
        _node(
            'ship',
            'deploy',
            {
                'project_id': 'p1',
                'environment': 'staging',
                'version': '{{ trigger.version }}',
            },
        ),
    ],
    'edges': [{'source': 'start', 'port': 0, 'target': 'ship'}],
}


class WorkflowTestCase(support.SharedAppAsyncTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        suffix = uuid.uuid4().hex[:10]
        self.org = f'wf-{suffix}'
        self.team = f'team-{suffix}'
        self.email = f'dev-{suffix}@example.com'
        self.base = f'/organizations/{self.org}/workflows'

        await graph.initialize()
        await workflows.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.pool = workflows.create_pool()
        await self.pool.open()
        self.store = workflows.WorkflowStore(self.pool)
        self.addAsyncCleanup(self._cleanup)

        await self.graph.execute(
            """
            CREATE (o:Organization {{id: {org}, slug: {org}, name: {org}}})
            CREATE (t:Team {{id: {team}, slug: {team}, name: 'Ops'}})
            CREATE (t)-[:BELONGS_TO]->(o)
            CREATE (u:User {{id: {email}, email: {email},
                             display_name: 'Dev', is_active: true}})
            CREATE (u)-[:MEMBER_OF {{role: 'developer'}}]->(o)
            RETURN o.id AS id
            """,
            {'org': self.org, 'team': self.team, 'email': self.email},
            ['id'],
        )

        self.permissions = set(ALL_PERMISSIONS)
        user = models.User(
            id=self.email,
            email=self.email,
            display_name='Dev',
            is_active=True,
            is_admin=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        async def current_user() -> permissions.AuthContext:
            return permissions.AuthContext(
                user=user,
                session_id='test-session',
                auth_method='jwt',
                permissions=set(self.permissions),
            )

        overrides = self.test_app.dependency_overrides
        overrides[permissions.get_current_user] = current_user
        overrides[graph._inject_graph] = lambda: self.graph
        overrides[workflows._inject_store] = lambda: self.store
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.test_app),
            base_url='http://test',
        )

    async def _cleanup(self) -> None:
        await self.client.aclose()
        await self.graph.execute(
            """
            MATCH (n) WHERE n.id IN {ids}
            DETACH DELETE n
            RETURN 1 AS ok
            """,
            {'ids': [self.org, self.team, self.email]},
            ['ok'],
        )
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM workflows.workflows WHERE organization_id = %s',
                (self.org,),
            )
        await self.pool.close()
        await self.graph.close()

    async def _create(self, **body: typing.Any) -> httpx.Response:
        return await self.client.post(
            self.base + '/',
            json={'name': 'Deploy guard', 'owner_team_slug': self.team} | body,
        )

    async def test_create_save_and_versions(self) -> None:
        response = await self._create()
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body['slug'], 'deploy-guard')
        self.assertEqual(body['status'], 'draft')
        self.assertEqual(body['owner_team_slug'], self.team)
        self.assertEqual(body['latest_version'], 1)
        self.assertIsNone(body['active_version'])
        self.assertEqual(body['agent_ids'], [])
        self.assertEqual(
            {i['code'] for i in body['version']['validation']['issues']},
            {'no_trigger'},
        )

        response = await self._create()
        self.assertEqual(response.status_code, 409)

        response = await self.client.put(
            f'{self.base}/deploy-guard',
            json={
                'name': 'Deploy guard',
                'description': 'Guards deploys',
                'owner_team_slug': self.team,
                'graph': DEPLOY_GRAPH,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['latest_version'], 2)
        self.assertEqual(body['trigger_types'], ['manual'])
        self.assertEqual(body['version']['validation'], {'issues': []})
        self.assertEqual(body['version']['created_by'], self.email)

        response = await self.client.get(self.base + '/')
        self.assertEqual(
            [w['slug'] for w in response.json()], ['deploy-guard']
        )

        response = await self.client.get(f'{self.base}/deploy-guard/versions')
        self.assertEqual([v['version'] for v in response.json()], [2, 1])
        response = await self.client.get(
            f'{self.base}/deploy-guard/versions/1'
        )
        self.assertEqual(response.json()['graph'], {'nodes': [], 'edges': []})
        response = await self.client.get(
            f'{self.base}/deploy-guard/versions/9'
        )
        self.assertEqual(response.status_code, 404)

    async def test_create_with_unknown_team(self) -> None:
        response = await self._create(owner_team_slug='nope')
        self.assertEqual(response.status_code, 422)

    async def test_validate(self) -> None:
        graph_body = {
            'nodes': [
                _node('start', 'manual'),
                _node('x', 'slack'),
                _node('a', 'wait', {'duration': '{{ ghost.out }}'}),
                _node('b', 'wait', {'duration': '1m'}),
            ],
            'edges': [
                {'source': 'start', 'port': 0, 'target': 'a'},
                {'source': 'a', 'port': 0, 'target': 'b'},
                {'source': 'b', 'port': 0, 'target': 'a'},
                {'source': 'b', 'port': 0, 'target': 'start'},
            ],
        }
        response = await self.client.post(
            f'{self.base}/anything/validate', json={'graph': graph_body}
        )
        self.assertEqual(response.status_code, 200, response.text)
        codes = {i['code'] for i in response.json()['issues']}
        self.assertTrue(
            {
                'unknown_type',
                'cycle',
                'unknown_reference',
                'edge_into_trigger',
            }
            <= codes,
            codes,
        )
        response = await self.client.get(self.base + '/')
        self.assertEqual(response.json(), [])

    async def test_activate_and_pause(self) -> None:
        await self._create(graph=DEPLOY_GRAPH)
        response = await self.client.post(f'{self.base}/deploy-guard/pause')
        self.assertEqual(response.status_code, 409)

        response = await self.client.post(f'{self.base}/deploy-guard/activate')
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['status'], 'active')
        self.assertEqual(body['active_version'], 1)
        self.assertEqual(body['activated_by'], self.email)
        self.assertIsNotNone(body['activated_at'])

        # A save does not change the active version.
        response = await self.client.put(
            f'{self.base}/deploy-guard',
            json={'name': 'Deploy guard', 'owner_team_slug': self.team},
        )
        self.assertEqual(response.json()['active_version'], 1)
        self.assertEqual(response.json()['latest_version'], 2)

        # Version 2 has no trigger, so it cannot be activated.
        response = await self.client.post(
            f'{self.base}/deploy-guard/activate', json={'version': 2}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()['detail']['error'], 'validation_failed'
        )

        response = await self.client.post(f'{self.base}/deploy-guard/pause')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'paused')

    async def test_activate_needs_step_permissions(self) -> None:
        await self._create(graph=DEPLOY_GRAPH)
        self.permissions.discard('project:deployment:write')
        response = await self.client.post(
            f'{self.base}/deploy-guard/activate', json={'version': 1}
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail'],
            {
                'error': 'missing_permissions',
                'permissions': ['project:deployment:write'],
            },
        )
        response = await self.client.get(f'{self.base}/deploy-guard')
        self.assertEqual(response.json()['status'], 'draft')

    async def test_delete(self) -> None:
        await self._create()
        response = await self.client.delete(f'{self.base}/deploy-guard')
        self.assertEqual(response.status_code, 204)
        response = await self.client.get(f'{self.base}/deploy-guard')
        self.assertEqual(response.status_code, 404)
        response = await self.client.delete(f'{self.base}/deploy-guard')
        self.assertEqual(response.status_code, 404)

    async def test_permission_required(self) -> None:
        self.permissions.discard('workflow:create')
        response = await self._create()
        self.assertEqual(response.status_code, 403)

    async def test_step_types(self) -> None:
        response = await self.client.get(
            f'/organizations/{self.org}/workflow-step-types/'
        )
        self.assertEqual(response.status_code, 200)
        types = {s['type']: s for s in response.json()}
        self.assertEqual(types['deploy']['ports'], ['Succeeded', 'Failed'])
        self.assertIsNone(types['model_decision']['ports'])
        self.assertTrue(types['manual']['trigger'])
