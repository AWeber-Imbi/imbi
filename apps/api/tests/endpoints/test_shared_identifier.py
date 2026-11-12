"""Refuse an ``EXISTS_IN`` identifier another project holds (#639).

These run against the live graph that ``root:services`` boots. The
plugin manifest decides if projects can share an identifier: GitHub
can (a monorepo), Sentry cannot.
"""

import json
import uuid
from unittest import mock

from apps.api.tests.endpoints import test_agent_tasks
from imbi.api.endpoints import _helpers
from imbi.common.plugins.base import PluginContext, ServiceWriteback
from imbi.plugins.github.plugin import GitHubPlugin
from imbi.plugins.sentry.plugin import SentryPlugin

_MANIFESTS = {'github': GitHubPlugin.manifest, 'sentry': SentryPlugin.manifest}


class SharedIdentifierTestCase(test_agent_tasks.AgentTaskTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        suffix = uuid.uuid4().hex[:10]
        self.other_project = f'proj-b-{suffix}'
        self.integrations = {
            'github': f'github-{suffix}',
            'sentry': f'sentry-{suffix}',
        }
        await self.graph.execute(
            """
            MATCH (o:Organization {{slug: {org}}})
            MATCH (t:Team {{id: {team}}})
            CREATE (p:Project {{id: {other}, slug: {other}, name: 'B'}})
            CREATE (p)-[:OWNED_BY]->(t)
            CREATE (g:Integration {{id: {github}, slug: {github},
                                    name: {github}, plugin: 'github',
                                    options: {options}}})
            CREATE (s:Integration {{id: {sentry}, slug: {sentry},
                                    name: {sentry}, plugin: 'sentry',
                                    options: {options}}})
            CREATE (g)-[:BELONGS_TO]->(o)
            CREATE (s)-[:BELONGS_TO]->(o)
            RETURN p.id AS id
            """,
            {
                'org': self.org,
                'team': self.team_id,
                'other': self.other_project,
                'options': json.dumps({}),
                **self.integrations,
            },
            ['id'],
        )
        self.addAsyncCleanup(self._cleanup_fixtures)
        patcher = mock.patch.object(
            _helpers.plugin_registry,
            'get_plugin',
            side_effect=lambda slug: mock.Mock(manifest=_MANIFESTS[slug]),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _cleanup_fixtures(self) -> None:
        await self.graph.execute(
            'MATCH (n) WHERE n.id IN {ids} DETACH DELETE n RETURN 1 AS ok',
            {'ids': [self.other_project, *self.integrations.values()]},
            ['ok'],
        )

    async def link(self, project_id: str, plugin: str) -> str | None:
        return await _helpers.persist_service_writeback(
            self.graph,
            PluginContext(
                project_id=project_id,
                project_slug=project_id,
                org_slug=self.org,
                integration_slug=self.integrations[plugin],
                service_writeback=ServiceWriteback(
                    identifier='shared-id', canonical_url='https://api/x'
                ),
            ),
            mock.Mock(is_admin=True),
        )

    async def test_not_shareable_identifier_is_refused(self) -> None:
        self.assertIsNone(await self.link(self.project_id, 'sentry'))
        refusal = await self.link(self.other_project, 'sentry')
        self.assertIsNotNone(refusal)
        self.assertIn(self.project_id, str(refusal))
        edges = await _helpers.lookup_project_exists_in(
            self.graph, self.other_project
        )
        self.assertEqual(edges, [])

    async def test_own_edge_can_be_written_again(self) -> None:
        self.assertIsNone(await self.link(self.project_id, 'sentry'))
        self.assertIsNone(await self.link(self.project_id, 'sentry'))

    async def test_shareable_identifier_is_allowed(self) -> None:
        self.assertIsNone(await self.link(self.project_id, 'github'))
        self.assertIsNone(await self.link(self.other_project, 'github'))
        edges = await _helpers.lookup_project_exists_in(
            self.graph, self.other_project
        )
        self.assertEqual([e.identifier for e in edges], ['shared-id'])
