"""Reads across organizations (issue #414).

The user is a member of ``org`` and ``other_org``, not of
``foreign_org``.
"""

import json
import typing
from unittest import mock

import httpx

from apps.api.tests.endpoints import test_agent_tasks
from imbi.api import mcp_server_orgs
from imbi.api.endpoints import plugin_edges

STAMP = '2026-10-15T00:00:00+00:00'


class CrossOrgTestCase(test_agent_tasks.AgentTaskTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.made: list[str] = []
        self.addAsyncCleanup(self._drop_made)

    async def _drop_made(self) -> None:
        await self.graph.execute(
            'MATCH (n) WHERE n.id IN {ids} DETACH DELETE n RETURN 1 AS ok',
            {'ids': self.made},
            ['ok'],
        )

    async def node(self, cypher: str, **params: typing.Any) -> None:
        """Run a CREATE; ``params['id']`` is deleted after the test."""
        self.made.append(params['id'])
        await self.graph.execute(cypher, params, ['ok'])

    def get(
        self, path: str, **kw: typing.Any
    ) -> typing.Awaitable[httpx.Response]:
        return self.client.get(path, **kw)


class UserDocumentTests(CrossOrgTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.permissions |= {
            'document:create',
            'document:read',
            'document:write',
        }
        for target in ('record_created',):
            patcher = mock.patch(
                f'imbi.api.endpoints.documents._document_history.{target}',
                mock.AsyncMock(),
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch(
            'imbi.api.endpoints.documents._search_index.index',
            mock.AsyncMock(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def create(self, org: str) -> str:
        response = await self.client.post(
            f'/organizations/{org}/users/{self.email}/documents/',
            json={'title': f'Notes in {org}', 'content': 'x'},
        )
        self.assertEqual(response.status_code, 201, response.text)
        document = str(response.json()['id'])
        self.made.append(document)
        return document

    async def test_only_the_organization_it_was_made_in(self) -> None:
        document = await self.create(self.org)
        own = await self.get(f'/organizations/{self.org}/documents/{document}')
        self.assertEqual(own.status_code, 200, own.text)
        # The user is a member of other_org too: still not shown there.
        other = await self.get(
            f'/organizations/{self.other_org}/documents/{document}'
        )
        self.assertEqual(other.status_code, 404, other.text)
        listed = await self.get(
            f'/organizations/{self.other_org}/users/{self.email}/documents/'
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertNotIn(document, {d['id'] for d in listed.json()['data']})
        patched = await self.client.patch(
            f'/organizations/{self.other_org}/documents/{document}',
            json=[{'op': 'replace', 'path': '/title', 'value': 'Taken'}],
        )
        self.assertEqual(patched.status_code, 404, patched.text)
        comments = await self.get(
            f'/organizations/{self.other_org}/documents/{document}/comments'
        )
        self.assertEqual(comments.status_code, 404, comments.text)


class PromptTests(CrossOrgTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.permissions |= {'prompt:read'}
        for org in (self.org, self.foreign_org):
            await self.node(
                'CREATE (p:Prompt {{id: {id}, name: {slug}, slug: {slug},'
                ' namespace: "agents", type: "core_system",'
                ' default_label: "stable", labels: "[]",'
                ' created_at: {stamp}, updated_at: {stamp}}})'
                ' RETURN 1 AS ok',
                id=f'prm-{org}',
                slug=f'{org}.bot',
                stamp=STAMP,
            )

    async def test_agents_prompts_of_member_organizations_only(self) -> None:
        own = await self.get(f'/prompts/agents/{self.org}.bot')
        self.assertEqual(own.status_code, 200, own.text)
        for path in (
            f'/prompts/agents/{self.foreign_org}.bot',
            f'/prompts/agents/{self.foreign_org}.bot/versions',
            f'/prompts/agents/{self.foreign_org}.bot/versions/1',
        ):
            with self.subTest(path=path):
                response = await self.get(path)
                self.assertEqual(response.status_code, 404, response.text)
        resolved = await self.get(
            '/prompts/resolve',
            params={'ref': f'agents/{self.foreign_org}.bot@stable'},
        )
        self.assertEqual(resolved.status_code, 404, resolved.text)
        listed = await self.get('/prompts/', params={'namespace': 'agents'})
        slugs = {p['slug'] for p in listed.json()}
        self.assertIn(f'{self.org}.bot', slugs)
        self.assertNotIn(f'{self.foreign_org}.bot', slugs)

    async def test_a_platform_admin_reads_every_prompt(self) -> None:
        self.user.is_admin = True
        response = await self.get(f'/prompts/agents/{self.foreign_org}.bot')
        self.assertEqual(response.status_code, 200, response.text)


class AIModelTests(CrossOrgTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.permissions |= {'ai_model:read', 'ai_model:update'}
        self.foreign_team = f'team-foreign-{self.org}'
        await self.node(
            'MATCH (o:Organization {{slug: {org}}})'
            ' CREATE (t:Team {{id: {id}, slug: {id}, name: "Foreign"}})'
            '-[:BELONGS_TO]->(o) RETURN 1 AS ok',
            id=self.foreign_team,
            org=self.foreign_org,
        )
        self.provider = f'prv-{self.org}'
        await self.node(
            'CREATE (p:AIProvider {{id: {id}, name: {id}, slug: {id},'
            ' driver: "anthropic", enabled: true}}) RETURN 1 AS ok',
            id=self.provider,
        )
        self.model = f'mdl-{self.org}'
        await self.node(
            'MATCH (p:AIProvider {{id: {provider}}}),'
            ' (a:Team {{id: {own}}}), (b:Team {{id: {foreign}}})'
            ' CREATE (m:AIModel {{id: {id}, name: {id}, slug: {id},'
            ' model_id: "claude-x", access_scope: "restricted"}})'
            '-[:SERVED_BY]->(p)'
            ' CREATE (m)-[:ALLOWED_FOR]->(a) CREATE (m)-[:ALLOWED_FOR]->(b)'
            ' RETURN 1 AS ok',
            id=self.model,
            provider=self.provider,
            own=self.team_id,
            foreign=self.foreign_team,
        )

    async def teams(self) -> set[str]:
        response = await self.get(f'/ai-models/{self.model}')
        self.assertEqual(response.status_code, 200, response.text)
        return {t['id'] for t in response.json()['allowed_teams']}

    async def test_teams_of_member_organizations_only(self) -> None:
        self.assertEqual(await self.teams(), {self.team_id})
        listed = await self.get('/ai-models/')
        (model,) = [m for m in listed.json() if m['id'] == self.model]
        self.assertEqual(
            {t['id'] for t in model['allowed_teams']}, {self.team_id}
        )
        self.user.is_admin = True
        self.assertEqual(await self.teams(), {self.team_id, self.foreign_team})

    async def test_a_patch_keeps_the_hidden_teams(self) -> None:
        response = await self.client.patch(
            f'/ai-models/{self.model}',
            json=[{'op': 'replace', 'path': '/name', 'value': 'Renamed'}],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            {t['id'] for t in response.json()['allowed_teams']},
            {self.team_id},
        )
        self.user.is_admin = True
        self.assertEqual(await self.teams(), {self.team_id, self.foreign_team})


class PluginEdgeTargetTests(CrossOrgTestCase):
    async def test_target_without_or_in_the_organization(self) -> None:
        account = f'aws-{self.org}'
        await self.node(
            'CREATE (a:AwsAccount {{id: {id}}}) RETURN 1 AS ok', id=account
        )
        foreign_team = f'team-x-{self.org}'
        await self.node(
            'MATCH (o:Organization {{slug: {org}}})'
            ' CREATE (t:Team {{id: {id}, slug: {id}, name: "X"}})'
            '-[:BELONGS_TO]->(o) RETURN 1 AS ok',
            id=foreign_team,
            org=self.foreign_org,
        )
        cases = (
            ('AwsAccount', account, True),
            ('Team', self.team_id, True),
            ('Project', self.project_id, True),
            ('Team', foreign_team, False),
        )
        for label, target, expected in cases:
            with self.subTest(label=label, target=target):
                self.assertEqual(
                    await plugin_edges._target_in_org(
                        self.graph, label, target, self.org
                    ),
                    expected,
                )


class MCPServerTests(CrossOrgTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.permissions |= {
            'mcp_server:create',
            'mcp_server:delete',
            'mcp_server:read',
            'mcp_server:update',
        }

    async def create(self, org: str, slug: str) -> str:
        response = await self.client.post(
            f'/organizations/{org}/mcp-servers/',
            json={'name': slug, 'slug': slug, 'url': 'https://mcp.test'},
        )
        self.assertEqual(response.status_code, 201, response.text)
        server = str(response.json()['id'])
        self.made.append(server)
        return server

    async def test_only_the_organization_it_was_made_in(self) -> None:
        slug = f'mcp-{self.org}'
        server = await self.create(self.org, slug)
        base = f'/organizations/{self.other_org}/mcp-servers'
        own = await self.get(f'/organizations/{self.org}/mcp-servers/{server}')
        self.assertEqual(own.status_code, 200, own.text)
        other = await self.get(f'{base}/{server}')
        self.assertEqual(other.status_code, 404, other.text)
        listed = await self.get(f'{base}/')
        self.assertNotIn(server, {s['id'] for s in listed.json()})
        patched = await self.client.patch(
            f'{base}/{server}', json={'name': 'Taken'}
        )
        self.assertEqual(patched.status_code, 404, patched.text)
        deleted = await self.client.delete(f'{base}/{server}')
        self.assertEqual(deleted.status_code, 404, deleted.text)
        # Slugs are unique per organization, not across the install.
        await self.create(self.other_org, slug)
        again = await self.client.post(
            f'/organizations/{self.org}/mcp-servers/',
            json={'name': slug, 'slug': slug, 'url': 'https://mcp.test'},
        )
        self.assertEqual(again.status_code, 409, again.text)

    async def test_backfill_link(self) -> None:
        server = f'mcp-legacy-{self.org}'
        await self.node(
            'CREATE (s:MCPServer {{id: {id}, slug: {id}, name: {id},'
            ' url: "https://mcp.test", enabled: true}}) RETURN 1 AS ok',
            id=server,
        )
        # The test graph has many organizations: the server stays.
        with self.assertLogs('imbi.api.mcp_server_orgs', 'WARNING') as logs:
            await mcp_server_orgs.backfill(self.graph)
        self.assertTrue(any(server in line for line in logs.output))
        records = await self.graph.execute(
            'MATCH (o:Organization {{slug: {slug}}}) RETURN o.id AS id',
            {'slug': self.org},
            ['id'],
        )
        org_id = json.loads(str(records[0]['id']))
        await self.graph.execute(
            mcp_server_orgs._LINK, {'org': org_id}, ['id']
        )
        listed = await self.get(f'/organizations/{self.org}/mcp-servers/')
        self.assertIn(server, {s['id'] for s in listed.json()})
