"""The ``github_app`` provider trusts only a verified repository (#400).

These run against the live graph that ``root:services`` boots. A
project's repository is verified only when the GitHub plugin writes the
``EXISTS_IN`` edge (:func:`_helpers.persist_service_writeback`). A
manual edit of the edge or of the project links does not change it.
"""

import json
import uuid
from unittest import mock

from apps.api.tests.endpoints import test_agent_tasks
from imbi.api import lifespans
from imbi.api.endpoints import _helpers
from imbi.api.secret_broker import github_app, providers
from imbi.common.plugins.base import PluginContext, ServiceWriteback

VERIFIED = 101
OTHER = 202


class VerifiedRepositoryTestCase(test_agent_tasks.AgentTaskTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.permissions |= {'project:write'}
        self.integration = f'github-{uuid.uuid4().hex[:10]}'
        self.ghe = f'ghe-{uuid.uuid4().hex[:10]}'
        await self.graph.execute(
            """
            MATCH (o:Organization {{slug: {org}}})
            CREATE (i:Integration {{id: {slug}, slug: {slug}, name: {slug},
                                    plugin: 'github', options: {options}}})
            CREATE (g:Integration {{id: {ghe}, slug: {ghe}, name: {ghe},
                                    plugin: 'github', options: {ghe_options}}})
            CREATE (i)-[:BELONGS_TO]->(o)
            CREATE (g)-[:BELONGS_TO]->(o)
            RETURN i.id AS id
            """,
            {
                'org': self.org,
                'slug': self.integration,
                'options': json.dumps({'flavor': 'github'}),
                'ghe': self.ghe,
                'ghe_options': json.dumps(
                    {'flavor': 'ghec', 'host': 'acme.ghe.com'}
                ),
            },
            ['id'],
        )
        self.addAsyncCleanup(self._cleanup_integrations)
        patcher = mock.patch.object(lifespans, '_graph', self.graph)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _cleanup_integrations(self) -> None:
        await self.graph.execute(
            'MATCH (n:Integration) WHERE n.id IN {ids} DETACH DELETE n '
            'RETURN 1 AS ok',
            {'ids': [self.integration, self.ghe]},
            ['ok'],
        )

    def services_url(self, path: str = '') -> str:
        return (
            f'/organizations/{self.org}/projects/{self.project_id}'
            f'/services/{path}'
        )

    async def verify(self, integration: str, repository_id: int) -> None:
        """Write the edge as the GitHub plugin does."""
        await _helpers.persist_service_writeback(
            self.graph,
            PluginContext(
                project_id=self.project_id,
                project_slug=self.project_id,
                org_slug=self.org,
                integration_slug=integration,
                service_writeback=ServiceWriteback(
                    identifier=str(repository_id),
                    canonical_url=(
                        f'https://api.github.com/repositories/{repository_id}'
                    ),
                ),
            ),
        )

    async def assert_refused(self, host: str = 'github.com') -> None:
        with self.assertRaises(providers.BrokerError) as ctx:
            await github_app.project_repository_ids(host, self.project_id)
        self.assertEqual(
            (ctx.exception.code, ctx.exception.reason),
            ('secret_access_denied', 'project_repository_unverified'),
        )

    async def test_a_manual_edge_is_not_verified(self) -> None:
        await self.assert_refused()
        response = await self.client.post(
            self.services_url(),
            json={
                'integration_slug': self.integration,
                'identifier': str(OTHER),
                'canonical_url': f'https://api.github.com/repositories/{OTHER}',
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        await self.assert_refused()

    async def test_a_manual_edit_keeps_the_verified_repository(self) -> None:
        await self.verify(self.integration, VERIFIED)
        self.assertEqual(
            await github_app.project_repository_ids(
                'github.com', self.project_id
            ),
            [VERIFIED],
        )
        response = await self.client.put(
            self.services_url(self.integration),
            json={
                'integration_slug': self.integration,
                'identifier': str(OTHER),
                'canonical_url': f'https://api.github.com/repositories/{OTHER}',
                'dashboard_url': 'https://github.com/octo/other',
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        await _helpers.merge_project_links(
            self.graph,
            self.project_id,
            add={'github-repository': 'https://github.com/octo/other'},
        )
        self.assertEqual(
            await github_app.project_repository_ids(
                'github.com', self.project_id
            ),
            [VERIFIED],
        )
        # The doctor sees that the edge no longer matches what GitHub
        # verified.
        [connection] = await _helpers.lookup_project_exists_in(
            self.graph, self.project_id
        )
        self.assertEqual(connection.identifier, str(OTHER))
        self.assertEqual(connection.verified_identifier, str(VERIFIED))

    async def test_only_the_binding_host_counts(self) -> None:
        await self.verify(self.ghe, VERIFIED)
        await self.assert_refused('github.com')
        self.assertEqual(
            await github_app.project_repository_ids(
                'acme.ghe.com', self.project_id
            ),
            [VERIFIED],
        )
