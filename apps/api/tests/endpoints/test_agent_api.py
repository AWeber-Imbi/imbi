"""The agent API token (harness plan P7): where it works, and where not.

The token is minted at the claim and renewed by the runner heartbeat.
It works on the normal routes with the service account's roles, only in
its organization, and is refused on the auth, token, service account,
role, secret, and harness routes, and after its lease.
"""

import typing
import uuid
from unittest import mock

import httpx
import jwt

from apps.api.tests.endpoints import test_harness
from imbi.api.auth import agent_api
from imbi.api.endpoints import harness as harness_api
from imbi.api.harness import store as harness_store
from imbi.api.harness import tokens
from imbi.common.auth import permissions as common_permissions


class AgentApiTestCase(test_harness.RunnerTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.runner = await self.register()
        claim = await self.claim(self.runner)
        assert claim is not None
        self.claimed = claim
        self.api_token = str(claim['api_token'])
        # The agent's service account reads projects (H28: its roles).
        self.role = f'agent-reader-{self.org}'
        await self.graph.execute(
            'MERGE (p:Permission {{name: "project:read"}})'
            ' CREATE (r:Role {{slug: {role}, name: {role}}})'
            ' CREATE (r)-[:GRANTS]->(p)'
            ' WITH r MATCH (:ServiceAccount {{slug: {slug}}})'
            '-[m:MEMBER_OF]->() SET m.role = {role} RETURN 1 AS ok',
            {'role': self.role, 'slug': self.account.slug},
            ['ok'],
        )
        self.addAsyncCleanup(self._drop_role)
        # The real authentication, not the test override.
        self.test_app.dependency_overrides.pop(
            common_permissions.get_current_user
        )
        # The tests have no lifespan: the project check uses this graph.
        self.test_app.dependency_overrides[agent_api.graph_for] = (
            lambda: self.graph
        )
        self.addCleanup(
            self.test_app.dependency_overrides.pop, agent_api.graph_for
        )

    async def _drop_role(self) -> None:
        await self.graph.execute(
            'MATCH (r:Role {{slug: {role}}}) DETACH DELETE r RETURN 1 AS ok',
            {'role': self.role},
            ['ok'],
        )

    async def call(
        self,
        method: str,
        path: str,
        token: str | None = None,
        **kw: typing.Any,
    ) -> httpx.Response:
        return await self.client.request(
            method,
            path,
            headers={'Authorization': f'Bearer {token or self.api_token}'},
            **kw,
        )

    def assert_refused(self, response: httpx.Response) -> None:
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'agent_api_forbidden'
        )


class ClaimTests(AgentApiTestCase):
    def test_claim_has_a_lease_long_token(self) -> None:
        claims = jwt.decode(
            self.api_token, options={'verify_signature': False}
        )
        self.assertEqual(claims['aud'], 'imbi-agent-api')
        self.assertEqual(claims['type'], 'agent_api')
        self.assertEqual(claims['sub'], self.account.slug)
        self.assertEqual(claims['task'], self.claimed['task']['id'])
        self.assertEqual(claims['chain'], self.claimed['chain_id'])
        self.assertEqual(claims['agent'], self.agent_id)
        self.assertTrue(claims['jti'])
        self.assertLessEqual(
            claims['exp'] - claims['iat'], harness_store.LEASE_SECONDS
        )

    async def test_heartbeat_renews_the_open_tasks_only(self) -> None:
        response = await self.runner_post(
            self.runner, 'heartbeat', json={'tasks': ['T-1', 'T-99']}
        )
        self.assertEqual(response.status_code, 200, response.text)
        renewed = response.json()['api_tokens']
        self.assertEqual(set(renewed), {'T-1'})
        self.assertNotEqual(renewed['T-1']['token'], self.api_token)
        response = await self.call(
            'GET',
            f'/organizations/{self.org}/projects/',
            token=renewed['T-1']['token'],
        )
        self.assertEqual(response.status_code, 200, response.text)
        # No body: the lease only, as before.
        response = await self.runner_post(self.runner, 'heartbeat')
        self.assertEqual(response.json()['api_tokens'], {})


class RenewalFailureTests(AgentApiTestCase):
    async def test_heartbeat_keeps_the_lease(self) -> None:
        """A renewal error (a graph outage) must not fence the runner."""
        before = await self.runner_post(self.runner, 'heartbeat')
        with (
            mock.patch.object(
                harness_api,
                '_renew_api_tokens',
                mock.AsyncMock(side_effect=RuntimeError('graph down')),
            ),
            self.assertLogs('imbi.api.endpoints.harness', 'ERROR'),
        ):
            response = await self.runner_post(
                self.runner, 'heartbeat', json={'tasks': ['T-1']}
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['api_tokens'], {})
        self.assertGreaterEqual(
            body['lease_expires_at'], before.json()['lease_expires_at']
        )


class RouteTests(AgentApiTestCase):
    async def test_normal_route_with_the_roles(self) -> None:
        response = await self.call(
            'GET', f'/organizations/{self.org}/projects/'
        )
        self.assertEqual(response.status_code, 200, response.text)

    async def test_reads_its_own_permissions(self) -> None:
        """imbi-mcp lists the agent's tools with this route."""
        response = await self.call('GET', '/users/me/permissions')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {'is_admin': False, 'permissions': ['project:read']},
        )

    async def test_permission_is_still_checked(self) -> None:
        response = await self.call(
            'POST', f'/organizations/{self.org}/projects/', json={}
        )
        self.assertIn(response.status_code, {403, 422}, response.text)
        await self._drop_role()
        response = await self.call(
            'GET', f'/organizations/{self.org}/projects/'
        )
        self.assertEqual(response.status_code, 403, response.text)

    async def test_other_organization(self) -> None:
        self.assert_refused(
            await self.call(
                'GET', f'/organizations/{self.other_org}/projects/'
            )
        )
        self.assert_refused(
            await self.call('GET', f'/organizations/{self.other_org}')
        )

    async def other_project(self) -> str:
        """A project of another organization."""
        project = f'proj-other-{self.org}'
        await self.graph.execute(
            'MATCH (o:Organization {{id: {org}}})'
            ' CREATE (t:Team {{id: {team}, slug: {team}, name: "X"}})'
            '-[:BELONGS_TO]->(o)'
            ' CREATE (p:Project {{id: {project}, slug: {project},'
            ' name: "Other"}})-[:OWNED_BY]->(t)'
            ' RETURN p.id AS id',
            {
                'org': self.other_org,
                'team': f'team-other-{self.org}',
                'project': project,
            },
            ['id'],
        )
        self.addAsyncCleanup(
            self.graph.execute,
            'MATCH (p:Project {{id: {project}}})-[:OWNED_BY]->(t:Team)'
            ' DETACH DELETE p, t RETURN 1 AS ok',
            {'project': project},
            ['ok'],
        )
        return project

    async def test_project_of_another_organization(self) -> None:
        org = f'/organizations/{self.org}'
        response = await self.call('GET', f'{org}/projects/{self.project_id}')
        self.assertEqual(response.status_code, 200, response.text)
        other = await self.other_project()
        for path in (
            f'{org}/projects/{other}/events/',
            f'{org}/projects/{other}/operations-log/',
        ):
            with self.subTest(path=path):
                response = await self.call('GET', path)
                self.assertEqual(response.status_code, 404, response.text)

    async def grant(self, *names: str) -> None:
        for name in names:
            await self.graph.execute(
                'MERGE (p:Permission {{name: {name}}})'
                ' WITH p MATCH (r:Role {{slug: {role}}})'
                ' CREATE (r)-[:GRANTS]->(p) RETURN 1 AS ok',
                {'role': self.role, 'name': name},
                ['ok'],
            )

    async def test_environment_of_another_organization(self) -> None:
        """A plugin puts the environment into its own query: only an
        environment of the organization is accepted."""
        await self.grant('project:logs:read', 'project:configuration:read')
        project = f'/organizations/{self.org}/projects/{self.project_id}'
        for path in ('/logs/', '/logs/schema', '/configuration/'):
            with self.subTest(path=path):
                response = await self.call(
                    'GET',
                    f'{project}{path}',
                    params={'environment': 'x OR service:other'},
                )
                self.assertEqual(response.status_code, 422, response.text)
        # An environment of the organization passes the check (and then
        # finds no logs integration).
        env = f'env-{self.org}'
        await self.graph.execute(
            'MATCH (o:Organization {{slug: {org}}})'
            ' CREATE (e:Environment {{slug: {env}, name: {env}}})'
            '-[:BELONGS_TO]->(o) RETURN 1 AS ok',
            {'org': self.org, 'env': env},
            ['ok'],
        )
        self.addAsyncCleanup(
            self.graph.execute,
            'MATCH (e:Environment {{slug: {env}}}) DETACH DELETE e'
            ' RETURN 1 AS ok',
            {'env': env},
            ['ok'],
        )
        response = await self.call(
            'GET', f'{project}/logs/schema', params={'environment': env}
        )
        self.assertEqual(response.status_code, 404, response.text)

    async def test_org_query_parameter(self) -> None:
        response = await self.call(
            'GET', '/scores/rollup', params={'org': self.other_org}
        )
        self.assert_refused(response)

    async def test_operations_log_entry_of_another_project(self) -> None:
        await self.graph.execute(
            'MERGE (p:Permission {{name: "operations_log:create"}})'
            ' WITH p MATCH (r:Role {{slug: {role}}})'
            ' CREATE (r)-[:GRANTS]->(p) RETURN 1 AS ok',
            {'role': self.role},
            ['ok'],
        )
        other = await self.other_project()
        response = await self.call(
            'POST', '/operations-log/', json={'project_id': other}
        )
        self.assertEqual(response.status_code, 404, response.text)
        response = await self.call('POST', '/operations-log/', json={})
        self.assert_refused(response)

    async def test_refused_route_groups(self) -> None:
        org = f'/organizations/{self.org}'
        cases = {
            'auth': ('GET', '/auth/providers'),
            'tokens': ('GET', '/api-keys'),
            'client credentials': (
                'GET',
                '/service-accounts/x/client-credentials',
            ),
            'service accounts': ('GET', '/service-accounts'),
            'service account keys': ('GET', '/service-accounts/x/api-keys'),
            'roles': ('GET', '/roles/'),
            'secrets': ('GET', f'{org}/secret-providers/'),
            'secret grants': ('GET', f'{org}/secret-grants/'),
            'harness pools': ('GET', '/harness/pools'),
            'harness task routes': ('POST', f'{org}/agent-tasks/T-1/sessions'),
            'mcp servers': ('GET', '/mcp-servers/'),
            'user writes': ('PATCH', '/users/someone@example.com'),
            'agent writes': ('POST', f'{org}/agents/'),
            'own approval': (
                'POST',
                f'{org}/agent-tasks/T-1/requests/r1/resolve',
            ),
            'platform config': ('PUT', f'{org}/agent-platform-config/'),
            'graph query': ('POST', '/admin/graph/query'),
            'integration credentials': (
                'PUT',
                f'{org}/integrations/x/credentials',
            ),
            'webhooks': ('POST', f'{org}/webhooks/'),
            'configuration values': (
                'POST',
                f'{org}/projects/p/configuration/values:fetch',
            ),
            'team members': ('POST', f'{org}/teams/x/members'),
            'workflow runs': ('POST', f'{org}/workflows/x/runs'),
            'prompts': ('POST', '/prompts/'),
            'global lists': ('GET', '/users/'),
            'organizations': ('GET', '/organizations/'),
            'events by id': ('GET', '/events/e1'),
            'operations log by id': ('PATCH', '/operations-log/x'),
            'uploads': ('GET', '/uploads/u1'),
            'blueprint writes': ('POST', '/blueprints/'),
            'rescore': ('POST', '/scoring/rescore'),
            'admin reads': ('GET', '/admin/graph/schema'),
            'prompt library': ('GET', '/prompts/agents/other.agent/versions'),
            'ai models': ('GET', '/ai-models/'),
            'shared notes': (
                'GET',
                f'{org}/component-releases/r1/notes',
            ),
        }
        for name, (method, path) in cases.items():
            with self.subTest(name):
                response = await self.call(method, path, json={})
                self.assert_refused(response)

    async def test_harness_routes_refuse_the_api_token(self) -> None:
        response = await self.client.post(
            '/harness/tasks/T-1/tool-calls/check',
            json={'tool_key': 'a.b'},
            headers={'Authorization': f'Bearer {self.api_token}'},
        )
        self.assert_refused(response)

    async def test_expired_after_its_lease(self) -> None:
        grant = tokens.AgentGrant(
            chain_id=uuid.UUID(self.claimed['chain_id']),
            attempt=1,
            runner_id=uuid.UUID(self.runner['runner_id']),
            organization_id=jwt.decode(
                self.api_token, options={'verify_signature': False}
            )['org'],
        )
        expired, _ = tokens.mint_agent_api_token(
            self.account.slug,
            grant,
            organization_slug=self.org,
            agent_id=self.agent_id,
            task_id=self.claimed['task']['id'],
            lease_seconds=-1,
        )
        response = await self.call(
            'GET', f'/organizations/{self.org}/projects/', token=expired
        )
        self.assertEqual(response.status_code, 401, response.text)

    async def test_harness_agent_token_is_not_an_api_token(self) -> None:
        response = await self.call(
            'GET',
            f'/organizations/{self.org}/projects/',
            token=self.claimed['agent_token'],
        )
        self.assertEqual(response.status_code, 401, response.text)

    async def test_a_service_that_does_not_accept_it(self) -> None:
        with mock.patch.object(
            common_permissions, '_agent_api_accepted', False
        ):
            response = await self.call(
                'GET', f'/organizations/{self.org}/projects/'
            )
        self.assertEqual(response.status_code, 401, response.text)


class OtherOrganizationMemberTests(test_harness.RunnerTestCase):
    """No token for a service account that is also in another
    organization: its roles there must not apply (plan P7)."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.other = f'other-{self.org}'
        await self.graph.execute(
            'CREATE (o:Organization {{id: {slug}, slug: {slug},'
            ' name: {slug}}})'
            ' WITH o MATCH (s:ServiceAccount {{slug: {account}}})'
            ' CREATE (s)-[:MEMBER_OF {{role: "admin"}}]->(o)'
            ' RETURN 1 AS ok',
            {'slug': self.other, 'account': self.account.slug},
            ['ok'],
        )
        self.addAsyncCleanup(self._drop_other)

    async def _drop_other(self) -> None:
        await self.graph.execute(
            'MATCH (o:Organization {{slug: {slug}}}) DETACH DELETE o'
            ' RETURN 1 AS ok',
            {'slug': self.other},
            ['ok'],
        )

    async def test_claim_and_heartbeat_mint_no_token(self) -> None:
        runner = await self.register()
        claim = await self.claim(runner)
        assert claim is not None
        self.assertIsNone(claim['api_token'])
        self.assertEqual(
            claim['api_token_error'], 'service_account_in_other_organizations'
        )
        self.assertTrue(claim['agent_token'])
        response = await self.runner_post(
            runner, 'heartbeat', json={'tasks': ['T-1']}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['api_tokens'], {})


class ClassificationTests(test_harness.RunnerTestCase):
    def test_every_route_is_classified(self) -> None:
        keys: dict[tuple[typing.Any, str], str] = (
            self.test_app.state.agent_api_routes
        )
        unclassified = sorted(
            key
            for (endpoint, method), key in keys.items()
            if not agent_api.refused(endpoint.__module__, method, key)
            and key not in agent_api.ALLOWED_ROUTES
        )
        self.assertEqual(
            unclassified,
            [],
            'Classify these routes for agent API tokens: add them to'
            ' ALLOWED_ROUTES in imbi/api/auth/agent_api_routes.py, or'
            ' refuse them in imbi/api/auth/agent_api.py',
        )

    def test_every_allowed_route_exists(self) -> None:
        """A stale entry would allow a later route with that key."""
        keys = set(self.test_app.state.agent_api_routes.values())
        self.assertEqual(agent_api.ALLOWED_ROUTES - keys, frozenset())
        self.assertEqual(agent_api.REFUSED_ROUTES - keys, frozenset())

    def test_allowed_routes_have_an_organization(self) -> None:
        """Every allowed route names the organization, or is reviewed
        as global but safe, with a reason."""
        unscoped = sorted(
            key
            for key in agent_api.ALLOWED_ROUTES
            if '{org_slug}' not in key
            and ' /organizations/{slug}' not in key
            and key not in agent_api.GLOBAL_SAFE
        )
        self.assertEqual(
            unscoped,
            [],
            'Scope these routes to the organization, refuse them, or add '
            'them to agent_api.GLOBAL_SAFE with the reason that they give '
            'no data of another organization',
        )
        self.assertEqual(
            set(agent_api.GLOBAL_SAFE) - agent_api.ALLOWED_ROUTES, set()
        )
        self.assertTrue(all(agent_api.GLOBAL_SAFE.values()))

    def test_no_route_is_allowed_and_refused(self) -> None:
        self.assertEqual(
            agent_api.ALLOWED_ROUTES & agent_api.REFUSED_ROUTES, frozenset()
        )
        for (
            endpoint,
            method,
        ), key in self.test_app.state.agent_api_routes.items():
            if agent_api.refused(endpoint.__module__, method):
                self.assertNotIn(key, agent_api.ALLOWED_ROUTES)

    def test_every_listed_module_has_routes(self) -> None:
        """A renamed module would drop out of the refusal silently."""
        modules = {
            endpoint.__module__
            for endpoint, _method in self.test_app.state.agent_api_routes
        }
        listed = agent_api.REFUSED_MODULES | agent_api.READ_ONLY_MODULES
        self.assertEqual(listed - modules, set())
