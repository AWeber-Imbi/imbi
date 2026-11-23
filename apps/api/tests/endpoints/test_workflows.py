"""Tests for the workflow definition endpoints (ADR 0021).

These run against the live Postgres that ``root:services`` boots: the
graph for the organization and the team, and the ``workflows`` schema
for definitions. Each test makes its own organization.
"""

import datetime
import typing
import uuid
from unittest import mock

import httpx

from apps.api.tests import support
from imbi.api import models, workflows
from imbi.api.auth import permissions
from imbi.api.endpoints import prompts
from imbi.api.endpoints import workflows as workflows_endpoints
from imbi.common import graph
from imbi.common.workflows import script_runner

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
                'project_id': '{{ trigger.project }}',
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
        # Resources in the org, and the same kinds in a foreign org.
        self.team2 = f'team2-{suffix}'
        self.project = f'proj-{suffix}'
        self.webhook = f'hook-{suffix}'
        self.member = f'member-{suffix}'
        self.foreign = {
            'org': f'wf-foreign-{suffix}',
            'team': f'fteam-{suffix}',
            'project': f'fproj-{suffix}',
            'webhook': f'fhook-{suffix}',
            'user': f'fuser-{suffix}',
        }
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
            CREATE (u)-[:MEMBER_OF]->(t)
            CREATE (t2:Team {{id: {team2}, slug: {team2}, name: 'Dev'}})
            CREATE (t2)-[:BELONGS_TO]->(o)
            CREATE (p:Project {{id: {project}, slug: {project}, name: 'P'}})
            CREATE (p)-[:OWNED_BY]->(t)
            CREATE (w:Webhook {{id: {webhook}, name: 'W'}})
            CREATE (w)-[:BELONGS_TO]->(o)
            CREATE (m:User {{id: {member}, email: {member}}})
            CREATE (m)-[:MEMBER_OF {{role: 'developer'}}]->(o)
            CREATE (fo:Organization {{id: {f_org}, slug: {f_org}}})
            CREATE (ft:Team {{id: {f_team}, slug: {f_team}}})
            CREATE (ft)-[:BELONGS_TO]->(fo)
            CREATE (fp:Project {{id: {f_project}, slug: {f_project}}})
            CREATE (fp)-[:OWNED_BY]->(ft)
            CREATE (fw:Webhook {{id: {f_webhook}}})
            CREATE (fw)-[:BELONGS_TO]->(fo)
            CREATE (fu:User {{id: {f_user}, email: {f_user}}})
            CREATE (fu)-[:MEMBER_OF {{role: 'developer'}}]->(fo)
            RETURN o.id AS id
            """,
            {
                'org': self.org,
                'team': self.team,
                'email': self.email,
                'team2': self.team2,
                'project': self.project,
                'webhook': self.webhook,
                'member': self.member,
            }
            | {f'f_{k}': v for k, v in self.foreign.items()},
            ['id'],
        )

        self.permissions = set(ALL_PERMISSIONS)
        self.user = user = models.User(
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
        overrides[workflows.run_store] = lambda: workflows.RunStore(self.pool)
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
            {
                'ids': [
                    self.org,
                    self.team,
                    self.email,
                    self.team2,
                    self.project,
                    self.webhook,
                    self.member,
                    *self.foreign.values(),
                ]
            },
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

    async def test_create_with_empty_derived_slug(self) -> None:
        response = await self._create(name='!!!')
        self.assertEqual(response.status_code, 422, response.text)
        response = await self._create(name='!!!', slug='bangs')
        self.assertEqual(response.status_code, 201, response.text)

    async def test_create_with_unknown_team(self) -> None:
        response = await self._create(owner_team_slug='nope')
        self.assertEqual(response.status_code, 422)

    async def test_validate(self) -> None:
        graph_body = {
            'nodes': [
                _node('start', 'manual'),
                _node('x', 'carrier_pigeon'),
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

    async def test_activate_allows_a_condition_type_mismatch(self) -> None:
        check = _node(
            'check',
            'condition',
            {
                'conditions': [
                    {
                        'a': '{{ ship.status }}',
                        'operator': 'greater_than',
                        'b': '5',
                    }
                ]
            },
        )
        response = await self._create(
            graph={
                'nodes': [*DEPLOY_GRAPH['nodes'], check],
                'edges': [
                    *DEPLOY_GRAPH['edges'],
                    {'source': 'ship', 'port': 0, 'target': 'check'},
                ],
            }
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(
            [
                i['code']
                for i in response.json()['version']['validation']['issues']
            ],
            ['condition_type_mismatch'],
        )
        response = await self.client.post(f'{self.base}/deploy-guard/activate')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'active')

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
        self.assertEqual(types['condition']['ports'], ['True', 'False'])
        self.assertEqual(types['condition']['category'], 'logic')
        self.assertTrue(types['manual']['trigger'])

    async def _resource_issues(
        self, step: str, params: dict[str, typing.Any]
    ) -> list[str]:
        response = await self.client.post(
            f'{self.base}/anything/validate',
            json={
                'graph': {
                    'nodes': [
                        _node('start', 'manual'),
                        _node('x', step, params),
                    ],
                    'edges': [{'source': 'start', 'port': 0, 'target': 'x'}],
                }
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return [
            i['message']
            for i in response.json()['issues']
            if i['code'] == 'resource_not_in_organization'
        ]

    async def test_project_must_be_in_org(self) -> None:
        deployed = {'environment': 'staging', 'version': '1'}
        released = {
            'from_environment': 'testing',
            'environment': 'staging',
            'commit': 'abc1234',
        }
        for project, expected in (
            (self.project, 0),
            ('{{ trigger.project }}', 0),
            (self.foreign['project'], 1),
            ('missing', 1),
        ):
            for step, params in (
                ('deploy', deployed),
                ('rollback', deployed),
                ('release', released),
            ):
                issues = await self._resource_issues(
                    step, {**params, 'project_id': project}
                )
                self.assertEqual(len(issues), expected, (step, project))

    async def test_webhook_must_be_in_org(self) -> None:
        for webhook, expected in (
            (self.webhook, 0),
            (self.foreign['webhook'], 1),
        ):
            issues = await self._resource_issues(
                'webhook', {'webhook_id': webhook}
            )
            self.assertEqual(len(issues), expected, webhook)

    async def test_email_team_must_be_in_org(self) -> None:
        issues = await self._resource_issues(
            'email',
            {
                'subject': 's',
                'body': 'b',
                'to': [
                    {'kind': 'team', 'id': self.team2},
                    {'kind': 'team', 'id': self.foreign['team']},
                ],
            },
        )
        self.assertEqual(len(issues), 1)
        self.assertIn(self.foreign['team'], issues[0])

    async def test_email_user_must_be_org_member(self) -> None:
        issues = await self._resource_issues(
            'email',
            {
                'subject': 's',
                'body': 'b',
                'to': [
                    {'kind': 'user', 'id': self.member},
                    {'kind': 'user', 'id': self.foreign['user']},
                    {'kind': 'user', 'id': '{{ trigger.user }}'},
                ],
            },
        )
        self.assertEqual(len(issues), 1)
        self.assertIn(self.foreign['user'], issues[0])

    async def _join(self, team: str) -> None:
        await self.graph.execute(
            """
            MATCH (u:User {{id: {email}}}), (t:Team {{id: {team}}})
            CREATE (u)-[:MEMBER_OF]->(t)
            RETURN t.id AS id
            """,
            {'email': self.email, 'team': team},
            ['id'],
        )

    async def _leave_team(self) -> None:
        await self.graph.execute(
            """
            MATCH (:User {{id: {email}}})-[r:MEMBER_OF]->(:Team {{id: {team}}})
            DELETE r
            RETURN 1 AS ok
            """,
            {'email': self.email, 'team': self.team},
            ['ok'],
        )

    async def test_delete_without_delete_permission(self) -> None:
        await self._create()
        self.permissions.discard('workflow:delete')
        url = f'{self.base}/deploy-guard'
        await self._leave_team()
        response = await self.client.delete(url)
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'owner_team_forbidden'
        )
        await self._join(self.team)
        response = await self.client.delete(url)
        self.assertEqual(response.status_code, 204, response.text)
        response = await self.client.delete(url)
        self.assertEqual(response.status_code, 404, response.text)

    async def test_create_needs_owner_team_member_or_admin(self) -> None:
        response = await self._create(owner_team_slug=self.team2)
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'owner_team_forbidden'
        )
        self.user.is_admin = True
        response = await self._create(owner_team_slug=self.team2)
        self.assertEqual(response.status_code, 201, response.text)

    async def test_owner_team_change_needs_member_or_admin(self) -> None:
        await self._create()
        await self._leave_team()
        body = {'name': 'Deploy guard', 'owner_team_slug': self.team2}
        url = f'{self.base}/deploy-guard'
        response = await self.client.put(url, json=body)
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'owner_team_forbidden'
        )

        # A save that keeps the owner team needs no membership.
        response = await self.client.put(
            url, json=body | {'owner_team_slug': self.team}
        )
        self.assertEqual(response.status_code, 200, response.text)

        await self.graph.execute(
            """
            MATCH (u:User {{id: {email}}}), (t:Team {{id: {team}}})
            CREATE (u)-[:MEMBER_OF]->(t)
            RETURN t.id AS id
            """,
            {'email': self.email, 'team': self.team},
            ['id'],
        )
        response = await self.client.put(url, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['owner_team_slug'], self.team2)

        # An admin can move it back without being a member of team2.
        self.user.is_admin = True
        response = await self.client.put(
            url, json=body | {'owner_team_slug': self.team}
        )
        self.assertEqual(response.status_code, 200, response.text)

    async def test_save_conflicts_when_owner_team_changed(self) -> None:
        await self._create()
        real_get = self.store.get

        async def stale_get(org_id: str, slug: str) -> dict[str, typing.Any]:
            # The owner team as it was before someone else changed it.
            row = await real_get(org_id, slug)
            assert row is not None
            return row | {'owner_team_id': self.team2}

        with mock.patch.object(self.store, 'get', side_effect=stale_get):
            self.user.is_admin = True
            response = await self.client.put(
                f'{self.base}/deploy-guard',
                json={'name': 'Renamed', 'owner_team_slug': self.team},
            )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['error'], 'conflict')
        response = await self.client.get(f'{self.base}/deploy-guard')
        self.assertEqual(response.json()['name'], 'Deploy guard')
        self.assertEqual(response.json()['latest_version'], 1)

    async def _set_org_slug(self, slug: str) -> None:
        await self.graph.execute(
            'MATCH (o:Organization {{id: {org}}})'
            ' SET o.slug = {slug} RETURN o.id AS id',
            {'org': self.org, 'slug': slug},
            ['id'],
        )

    async def test_save_conflicts_when_org_renamed(self) -> None:
        # #780: a rename that commits after the checks of a save moves
        # the prompt references that the save checked.
        self.addAsyncCleanup(self._set_org_slug, self.org)
        await self._create()
        real_get = self.store.get

        async def renaming_get(
            org_id: str, slug: str
        ) -> dict[str, typing.Any] | None:
            row = await real_get(org_id, slug)
            await self._set_org_slug(f'{self.org}-new')
            return row

        with mock.patch.object(self.store, 'get', side_effect=renaming_get):
            response = await self.client.put(
                f'{self.base}/deploy-guard',
                json={'name': 'Renamed', 'owner_team_slug': self.team},
            )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('renamed', response.json()['detail']['message'])
        await self._set_org_slug(self.org)
        response = await self.client.get(f'{self.base}/deploy-guard')
        self.assertEqual(response.json()['latest_version'], 1)

    async def test_delete_conflicts_when_org_renamed(self) -> None:
        # #829: a rename that commits after the org lookup of a delete
        # would leave the prompts of the workflow unarchived.
        self.addAsyncCleanup(self._set_org_slug, self.org)
        await self._create()
        real_delete = self.store.delete

        async def renaming_delete(
            *args: typing.Any, **kwargs: typing.Any
        ) -> str:
            await self._set_org_slug(f'{self.org}-new')
            return await real_delete(*args, **kwargs)

        with mock.patch.object(
            self.store, 'delete', side_effect=renaming_delete
        ):
            response = await self.client.delete(f'{self.base}/deploy-guard')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('renamed', response.json()['detail']['message'])
        await self._set_org_slug(self.org)
        response = await self.client.get(f'{self.base}/deploy-guard')
        self.assertEqual(response.status_code, 200)

    async def test_create_conflicts_when_org_renamed(self) -> None:
        # #780: the slug check runs on the connection of the create.
        self.addAsyncCleanup(self._set_org_slug, self.org)
        real_check = workflows_endpoints._check_llm_call

        async def renaming_check(*args: typing.Any) -> None:
            await real_check(*args)
            await self._set_org_slug(f'{self.org}-new')

        with mock.patch.object(
            workflows_endpoints, '_check_llm_call', renaming_check
        ):
            response = await self._create()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('renamed', response.json()['detail']['message'])
        await self._set_org_slug(self.org)
        response = await self.client.get(f'{self.base}/deploy-guard')
        self.assertEqual(response.status_code, 404)

    async def _codes(
        self, step: str, params: dict[str, typing.Any]
    ) -> set[str]:
        response = await self.client.post(
            f'{self.base}/anything/validate',
            json={
                'graph': {
                    'nodes': [
                        _node('start', 'manual'),
                        _node('x', step, params),
                    ],
                    'edges': [{'source': 'start', 'port': 0, 'target': 'x'}],
                }
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {i['code'] for i in response.json()['issues']}

    async def test_resource_id_templates_must_be_plain_references(
        self,
    ) -> None:
        params = {'environment': 'staging', 'version': '1'}
        for value in (
            "{{ 'x' }}",
            f"{{{{ '{self.foreign['project']}' }}}}",
            'a{{ trigger.p }}',
            '{{ trigger.p | lower }}',
            '{{ trigger }}',
            f'{self.foreign["project"]}{{# #}}',
            '{% if true %}x{% endif %}',
        ):
            codes = await self._codes(
                'deploy', {**params, 'project_id': value}
            )
            self.assertIn('invalid_reference', codes, value)
        codes = await self._codes(
            'deploy', {**params, 'project_id': '{{ trigger.project }}'}
        )
        self.assertNotIn('invalid_reference', codes)
        codes = await self._codes(
            'email',
            {
                'subject': 's',
                'body': 'b',
                'to': [{'kind': 'team', 'id': "{{ 'x' }}"}],
            },
        )
        self.assertIn('invalid_reference', codes)

    async def test_webhook_id_must_be_literal(self) -> None:
        codes = await self._codes(
            'webhook', {'webhook_id': '{{ trigger.webhook }}'}
        )
        self.assertIn('invalid_reference', codes)
        codes = await self._codes('webhook', {'webhook_id': self.webhook})
        self.assertNotIn('invalid_reference', codes)

    async def test_agent_must_be_in_org_and_literal(self) -> None:
        agent, foreign = (f'agent-{uuid.uuid4().hex[:8]}' for _ in range(2))
        await self.graph.execute(
            """
            MATCH (o:Organization {{id: {org}}}),
                  (fo:Organization {{id: {f_org}}})
            CREATE (a:Agent {{id: {agent}, slug: {agent}}})
            CREATE (a)-[:BELONGS_TO]->(o)
            CREATE (fa:Agent {{id: {foreign}, slug: {foreign}}})
            CREATE (fa)-[:BELONGS_TO]->(fo)
            RETURN a.id AS id
            """,
            {
                'org': self.org,
                'f_org': self.foreign['org'],
                'agent': agent,
                'foreign': foreign,
            },
            ['id'],
        )
        self.addAsyncCleanup(
            self.graph.execute,
            'MATCH (a:Agent) WHERE a.id IN {ids} DETACH DELETE a'
            ' RETURN 1 AS ok',
            {'ids': [agent, foreign]},
            ['ok'],
        )
        for agent_id, project, expected in (
            (agent, self.project, 0),
            (foreign, None, 1),
            (agent, self.foreign['project'], 1),
        ):
            issues = await self._resource_issues(
                'agent',
                {
                    'agent_id': agent_id,
                    'instruction': 'Look.',
                    'project_id': project,
                },
            )
            self.assertEqual(len(issues), expected, (agent_id, project))
        # A task completed trigger filters on an agent of the org only.
        for agent_id, expected in ((agent, 0), (foreign, 1)):
            issues = await self._resource_issues(
                'ticket_state_changed', {'agent_id': agent_id}
            )
            self.assertEqual(len(issues), expected, agent_id)
        codes = await self._codes(
            'ticket_state_changed', {'agent_id': '{{ trigger.agent }}'}
        )
        self.assertIn('invalid_reference', codes)
        # Run input must not choose the agent. The project can be one
        # plain reference, such as an earlier step's output, and no more.
        for params in (
            {'agent_id': '{{ trigger.agent }}'},
            {'agent_id': agent, 'project_id': '{{ trigger.payload.p | x }}'},
            {'agent_id': agent, 'project_id': 'p-{{ review.result.p }}'},
        ):
            codes = await self._codes('agent', {**params, 'instruction': 'x'})
            self.assertIn('invalid_reference', codes, params)
        for project in (
            '{{ review.result.project }}',
            '{{ trigger.payload.p }}',
        ):
            codes = await self._codes(
                'agent',
                {'agent_id': agent, 'project_id': project, 'instruction': 'x'},
            )
            self.assertNotIn('invalid_reference', codes, project)
        # The webhook's project comes from the run's origin, so it is
        # allowed, but only when every trigger is a webhook.
        hooked = {
            'agent_id': agent,
            'instruction': 'x',
            'project_id': '{{ trigger.project }}',
        }
        codes = await self._codes('agent', hooked)
        self.assertNotIn('invalid_reference', codes)
        self.assertIn('trigger_project_needs_webhook', codes)
        response = await self.client.post(
            f'{self.base}/anything/validate',
            json={
                'graph': {
                    'nodes': [
                        _node(
                            'start', 'webhook', {'webhook_id': self.webhook}
                        ),
                        _node('x', 'agent', hooked),
                    ],
                    'edges': [{'source': 'start', 'port': 0, 'target': 'x'}],
                }
            },
        )
        self.assertEqual(response.json()['issues'], [], response.text)

        graph_ = {
            'nodes': [
                _node('start', 'manual'),
                _node('x', 'agent', {'agent_id': agent, 'instruction': 'x'}),
            ],
            'edges': [{'source': 'start', 'port': 0, 'target': 'x'}],
        }
        response = await self._create(graph=graph_)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['agent_ids'], [agent])
        self.assertEqual(await self.store.agent_references(self.org, agent), 1)
        self.assertEqual(
            await self.store.agent_references(self.org, foreign), 0
        )
        # A ticket_state_changed trigger that names the agent also uses it.
        response = await self._create(
            name='Task chain',
            graph={
                'nodes': [
                    _node('start', 'ticket_state_changed', {'agent_id': agent})
                ],
                'edges': [],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(await self.store.agent_references(self.org, agent), 2)


class ScriptPreviewTestCase(WorkflowTestCase):
    """``POST .../workflows/script-preview`` in the real sandbox."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        runner = await self.enterAsyncContext(
            script_runner.open_runner(
                processes=1, max_memory=16 * 1024 * 1024, max_seconds=2.0
            )
        )
        self.runner: script_runner.Runner | None = runner
        self.test_app.dependency_overrides[
            workflows_endpoints._script_runner
        ] = lambda: self.runner

    async def _preview(self, **body: typing.Any) -> httpx.Response:
        return await self.client.post(
            f'{self.base}/script-preview',
            json={
                'code': "{'count': n * 2}",
                'inputs': {'n': 3},
                'output_fields': [{'name': 'count', 'type': 'integer'}],
            }
            | body,
        )

    async def test_result(self) -> None:
        response = await self._preview(
            code="print('hi')\n{'count': n, 'branch': 'b'}",
            branches=['a', 'b'],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                'output': {
                    'result': {'count': 3},
                    'branch': 'b',
                    'stdout': 'hi\n',
                },
                'port': 1,
                'error': None,
                'message': None,
            },
        )

    async def test_script_error_is_a_result(self) -> None:
        response = await self._preview(code="raise ValueError('nope')")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                'output': None,
                'port': None,
                'error': 'script_error',
                'message': 'ValueError: nope',
            },
        )

    async def test_invalid_params(self) -> None:
        response = await self._preview(inputs={'lambda': 1})
        self.assertEqual(response.status_code, 422, response.text)

    async def test_needs_workflow_write(self) -> None:
        self.permissions.discard('workflow:write')
        response = await self._preview()
        self.assertEqual(response.status_code, 403, response.text)

    async def test_no_sandbox(self) -> None:
        self.runner = None
        response = await self._preview()
        self.assertEqual(response.status_code, 503, response.text)


class LLMCallStepTestCase(WorkflowTestCase):
    """The CMS prompt of an LLM Call step: checked on save, archived
    when the node or the workflow goes."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        suffix = uuid.uuid4().hex[:8]
        self.provider = f'prov-{suffix}'
        self.structured = f'chat-s-{suffix}'
        self.plain = f'chat-p-{suffix}'
        self.completion = f'text-c-{suffix}'
        await self.graph.execute(
            """
            CREATE (p:AIProvider {{id: {provider}, slug: {provider},
                                   name: 'P', driver: 'anthropic',
                                   enabled: true}})
            CREATE (s:AIModel {{id: {structured}, slug: {structured},
                                name: 'S', model_id: 's',
                                model_type: 'generative', enabled: true,
                                supports_structured_output: true}})
            CREATE (m:AIModel {{id: {plain}, slug: {plain}, name: 'M',
                                model_id: 'm', model_type: 'generative',
                                enabled: true,
                                supports_structured_output: false}})
            CREATE (c:AIModel {{id: {completion}, slug: {completion},
                                name: 'C', model_id: 'c',
                                model_type: 'generative', kind: 'completion',
                                enabled: true,
                                supports_structured_output: false}})
            CREATE (s)-[:SERVED_BY]->(p)
            CREATE (m)-[:SERVED_BY]->(p)
            CREATE (c)-[:SERVED_BY]->(p)
            RETURN p.id AS id
            """,
            {
                'provider': self.provider,
                'structured': self.structured,
                'plain': self.plain,
                'completion': self.completion,
            },
            ['id'],
        )
        self.addAsyncCleanup(self._cleanup_prompts)
        await self._prompt('sum', self.structured)
        await self._prompt('plain', self.plain)
        await self._prompt('ask', self.plain)
        await self._prompt('text', self.completion)

    async def _cleanup_prompts(self) -> None:
        await self.graph.execute(
            """
            MATCH (p:Prompt {{namespace: 'workflows'}})
            WHERE p.slug STARTS WITH {prefix}
            OPTIONAL MATCH (v:PromptVersion)-[:VERSION_OF]->(p)
            DETACH DELETE v, p
            RETURN 1 AS ok
            """,
            {'prefix': f'{self.org}.'},
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
                    self.provider,
                    self.structured,
                    self.plain,
                    self.completion,
                ]
            },
            ['ok'],
        )

    def _ref(self, key: str) -> str:
        return f'workflows/{self.org}.deploy-guard.{key}'

    async def _prompt(self, key: str, model: str) -> None:
        await prompts.insert_prompt(
            self.graph,
            prompts.PromptCreate(
                namespace='workflows',
                name=key,
                slug=self._ref(key).partition('/')[2],
                version=prompts.PromptVersionCreate(
                    system='Summarize {{ diff }}.',
                    model=model,
                    variable_schema={'diff': {'type': 'any'}},
                ),
            ),
            self.email,
            label_first_version=True,
        )

    def _graph(self, **nodes: dict[str, typing.Any]) -> dict[str, typing.Any]:
        return {
            'nodes': [
                _node('start', 'manual'),
                *(
                    _node(
                        key,
                        'llm_call',
                        {'prompt_ref': self._ref(key), 'prompt_version': 1}
                        | params,
                    )
                    for key, params in nodes.items()
                ),
            ],
            'edges': [
                {'source': 'start', 'port': 0, 'target': key} for key in nodes
            ],
        }

    async def _archived(self, key: str) -> bool:
        records = await self.graph.execute(
            """
            MATCH (p:Prompt {{namespace: 'workflows', slug: {slug}}})
            RETURN p.archived_at AS at
            """,
            {'slug': self._ref(key).partition('/')[2]},
            ['at'],
        )
        return graph.parse_agtype(records[0]['at']) is not None

    async def test_save_checks(self) -> None:
        fields = [{'name': 'risk', 'type': 'string'}]
        for nodes, message in (
            (
                {'sum': {'prompt_ref': f'workflows/{self.org}.other.sum'}},
                'the prompt must be',
            ),
            ({'sum': {'prompt_version': 9}}, 'no version 9'),
            ({'gone': {}}, 'not found'),
            ({'plain': {'output_fields': fields}}, 'structured output'),
            ({'text': {}}, 'is a completion model; choose a chat model'),
        ):
            with self.subTest(message):
                response = await self._create(graph=self._graph(**nodes))
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn(message, response.json()['detail'])
        # A shorter timeout can retry with a new key while the first
        # model call still runs.
        short = self._graph(sum={})
        short['nodes'][1]['timeout_seconds'] = 189
        response = await self._create(graph=short)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn('at least 190 seconds', response.json()['detail'])
        response = await self._create(
            graph=self._graph(sum={'output_fields': fields}, plain={})
        )
        self.assertEqual(response.status_code, 201, response.text)
        response = await self.client.put(
            f'{self.base}/deploy-guard',
            json={
                'name': 'Deploy guard',
                'owner_team_slug': self.team,
                'graph': self._graph(plain={'output_fields': fields}),
            },
        )
        self.assertEqual(response.status_code, 422, response.text)

    async def _restrict(self, model: str, *teams: str) -> None:
        """Make ``model`` restricted to ``teams``."""
        await self.graph.execute(
            """
            MATCH (m:AIModel {{id: {model}}})
            SET m.access_scope = 'restricted'
            WITH m
            MATCH (t:Team) WHERE t.id IN {teams}
            CREATE (m)-[:ALLOWED_FOR]->(t)
            RETURN m.id AS id
            """,
            {'model': model, 'teams': list(teams)},
            ['id'],
        )

    async def test_restricted_model_needs_an_allowed_saver(self) -> None:
        response = await self._create()
        self.assertEqual(response.status_code, 201, response.text)
        await self._leave_team()
        # The owner team is allowed; the saver is not a member of it.
        await self._restrict(self.plain, self.team)
        body = {
            'name': 'Deploy guard',
            'owner_team_slug': self.team,
            'graph': self._graph(plain={}),
        }
        url = f'{self.base}/deploy-guard'
        response = await self.client.put(url, json=body)
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'model_not_allowed'
        )
        self.user.is_admin = True
        response = await self.client.put(url, json=body)
        self.assertEqual(response.status_code, 200, response.text)

    async def test_restricted_model_needs_an_allowed_owner_team(
        self,
    ) -> None:
        # The saver is allowed through team2; the owner team is not.
        await self._restrict(self.plain, self.team2)
        await self._join(self.team2)
        response = await self._create(graph=self._graph(plain={}))
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'model_not_allowed'
        )
        # An admin cannot pin it for that owner team either.
        self.user.is_admin = True
        response = await self._create(graph=self._graph(plain={}))
        self.assertEqual(response.status_code, 403, response.text)
        self.user.is_admin = False
        await self._restrict(self.plain, self.team)
        response = await self._create(graph=self._graph(plain={}))
        self.assertEqual(response.status_code, 201, response.text)

    async def test_create_with_llm_call_needs_workflow_write(self) -> None:
        # The editor pins the prompts with an update after the create.
        self.permissions.discard('workflow:write')
        response = await self._create(graph=self._graph(sum={}))
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn('workflow:write', response.json()['detail'])
        response = await self._create(
            graph={'nodes': [_node('start', 'manual')], 'edges': []}
        )
        self.assertEqual(response.status_code, 201, response.text)

    async def test_unpinned_node_is_only_a_validation_issue(self) -> None:
        # The editor creates a new workflow before it writes the prompts.
        for params in ({}, {'prompt_ref': self._ref('sum')}):
            with self.subTest(params=params):
                response = await self._create(
                    slug=f'new-{len(params)}',
                    graph={
                        'nodes': [
                            _node('start', 'manual'),
                            _node('sum', 'llm_call', params),
                        ],
                        'edges': [
                            {'source': 'start', 'port': 0, 'target': 'sum'}
                        ],
                    },
                )
                self.assertEqual(response.status_code, 201, response.text)
                issues = response.json()['version']['validation']['issues']
                self.assertIn('sum', {i.get('node_id') for i in issues})

    async def test_removed_node_and_deleted_workflow_archive(self) -> None:
        response = await self._create(graph=self._graph(sum={}, plain={}))
        self.assertEqual(response.status_code, 201, response.text)
        response = await self.client.put(
            f'{self.base}/deploy-guard',
            json={
                'name': 'Deploy guard',
                'owner_team_slug': self.team,
                'graph': self._graph(sum={}),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(await self._archived('plain'))
        self.assertFalse(await self._archived('sum'))
        # Not a node of the workflow: a save archives what an earlier
        # save left.
        self.assertTrue(await self._archived('ask'))
        # A save of a graph that uses an archived prompt restores it.
        response = await self.client.put(
            f'{self.base}/deploy-guard',
            json={
                'name': 'Deploy guard',
                'owner_team_slug': self.team,
                'graph': self._graph(sum={}, plain={}),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(await self._archived('plain'))
        response = await self.client.delete(f'{self.base}/deploy-guard')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertTrue(await self._archived('sum'))

    async def test_failed_archive_rolls_back_the_delete(self) -> None:
        response = await self._create(graph=self._graph(sum={}))
        self.assertEqual(response.status_code, 201, response.text)
        with (
            mock.patch.object(
                workflows_endpoints,
                '_archive_prompts',
                mock.AsyncMock(side_effect=RuntimeError('graph down')),
            ),
            self.assertRaises(RuntimeError),
        ):
            await self.client.delete(f'{self.base}/deploy-guard')
        response = await self.client.get(f'{self.base}/deploy-guard')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(await self._archived('sum'))

    async def test_failed_write_after_archive_keeps_the_prompts(
        self,
    ) -> None:
        """The archive commits only with the workflow write (#783)."""
        response = await self._create(graph=self._graph(sum={}, plain={}))
        self.assertEqual(response.status_code, 201, response.text)
        archive = workflows_endpoints._archive_prompts

        class ArchivedError(Exception):
            """Raised only after the archive completes."""

        async def archive_then_fail(*args: typing.Any) -> None:
            await archive(*args)
            raise ArchivedError

        body = {
            'name': 'Deploy guard',
            'owner_team_slug': self.team,
            'graph': self._graph(sum={}),
        }
        url = f'{self.base}/deploy-guard'
        with mock.patch.object(
            workflows_endpoints, '_archive_prompts', archive_then_fail
        ):
            with self.assertRaises(ArchivedError):
                await self.client.put(url, json=body)
            self.assertFalse(await self._archived('plain'))
            with self.assertRaises(ArchivedError):
                await self.client.delete(url)
            self.assertFalse(await self._archived('sum'))
        response = await self.client.get(url)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['latest_version'], 1)
