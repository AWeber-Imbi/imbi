"""Tests for ``Deployment`` node reads and writes.

These run against the live graph: the upsert leans on AGE-specific
behaviour (``MERGE`` on a path, list concatenation, ``WITH`` capturing
the pre-``SET`` state in place of ``ON CREATE SET``) that a mocked
connection would not exercise.

"""

import datetime
import typing
import unittest

import dotenv

from imbi.common import deployments, graph

dotenv.load_dotenv()

ORG = 'test-deployments-org'
PROJECT_ID = 'test-deployments-project'
RELEASE_ID = 'test-deployments-release'
ENV = 'test-deployments-env'


class DeploymentNodeTestCase(unittest.IsolatedAsyncioTestCase):
    """Fixtures for one project, environment, and release."""

    async def asyncSetUp(self) -> None:
        self.graph = graph.Graph()
        await self.graph.open()
        await self._cleanup()
        await self.graph.execute(
            """
            MERGE (o:Organization {{slug: {org}}})
            MERGE (p:Project {{id: {project_id}}})
            MERGE (e:Environment {{slug: {env}}})
            MERGE (e)-[:BELONGS_TO]->(o)
            MERGE (r:Release {{id: {release_id}}})
            MERGE (p)-[:HAS_RELEASE]->(r)
            RETURN p.id AS id
            """,
            {
                'org': ORG,
                'project_id': PROJECT_ID,
                'env': ENV,
                'release_id': RELEASE_ID,
            },
            ['id'],
        )

    async def asyncTearDown(self) -> None:
        await self._cleanup()
        await self.graph.close()

    async def _cleanup(self) -> None:
        await self.graph.execute(
            """
            MATCH (p:Project {{id: {project_id}}})
            OPTIONAL MATCH (p)<-[:BELONGS_TO]-(d:Deployment)
            DETACH DELETE d
            RETURN 1 AS ok
            """,
            {'project_id': PROJECT_ID},
            ['ok'],
        )
        for label, key, value in (
            ('Project', 'id', PROJECT_ID),
            ('Release', 'id', RELEASE_ID),
            ('Environment', 'slug', ENV),
            ('Organization', 'slug', ORG),
        ):
            await self.graph.execute(
                f'MATCH (n:{label} {{{{{key}: {{value}}}}}}) '
                'DETACH DELETE n RETURN 1 AS ok',
                {'value': value},
                ['ok'],
            )

    async def upsert(
        self, **overrides: typing.Any
    ) -> deployments.UpsertResult | None:
        kwargs: dict[str, typing.Any] = {
            'org_slug': ORG,
            'project_id': PROJECT_ID,
            'env_slug': ENV,
            'release_id': RELEASE_ID,
            'status': 'in_progress',
            'external_run_id': '4242',
        }
        kwargs.update(overrides)
        return await deployments.upsert_deployment(self.graph, **kwargs)

    async def nodes(self) -> list[dict[str, typing.Any]]:
        rows = await self.graph.execute(
            """
            MATCH (:Project {{id: {project_id}}})
                  <-[:BELONGS_TO]-(d:Deployment)
            RETURN d AS deployment
            """,
            {'project_id': PROJECT_ID},
            ['deployment'],
        )
        return [graph.parse_agtype(row['deployment']) for row in rows]


class UpsertTests(DeploymentNodeTestCase):
    async def test_run_id_identity_is_idempotent(self) -> None:
        first = await self.upsert(status='in_progress')
        second = await self.upsert(status='success')
        assert first is not None
        assert second is not None
        self.assertEqual('created', first.outcome)
        self.assertEqual('updated', second.outcome)
        self.assertEqual(first.id, second.id)
        nodes = await self.nodes()
        self.assertEqual(1, len(nodes))
        self.assertEqual('success', nodes[0]['status'])
        self.assertEqual(
            ['in_progress', 'success'],
            [entry['status'] for entry in nodes[0]['history']],
        )

    async def test_replay_is_a_noop(self) -> None:
        first = await self.upsert(status='success', note='shipped')
        second = await self.upsert(status='success', note='shipped')
        assert first is not None
        assert second is not None
        self.assertEqual('created', first.outcome)
        self.assertEqual('noop', second.outcome)
        nodes = await self.nodes()
        self.assertEqual(1, len(nodes))
        self.assertEqual(1, len(nodes[0]['history']))

    async def test_null_run_url_does_not_clear_a_known_one(self) -> None:
        await self.upsert(
            status='in_progress', external_run_url='https://example/run'
        )
        await self.upsert(status='success', external_run_url=None)
        nodes = await self.nodes()
        self.assertEqual('https://example/run', nodes[0]['external_run_url'])

    async def test_without_run_id_every_call_creates_a_node(self) -> None:
        await self.upsert(external_run_id=None, status='in_progress')
        await self.upsert(external_run_id=None, status='success')
        self.assertEqual(2, len(await self.nodes()))

    async def test_orphan_deployment_has_no_release(self) -> None:
        result = await self.upsert(release_id=None)
        assert result is not None
        by_project = await deployments.deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(1, len(by_project))
        self.assertIsNone(by_project[0].release)
        self.assertEqual(ENV, by_project[0].environment['slug'])
        self.assertEqual('in_progress', by_project[0].event.status)

    async def test_missing_environment_returns_none(self) -> None:
        self.assertIsNone(await self.upsert(env_slug='nope'))

    async def test_missing_release_returns_none(self) -> None:
        self.assertIsNone(await self.upsert(release_id='nope'))


class ReadTests(DeploymentNodeTestCase):
    async def test_node_renders_as_an_event(self) -> None:
        await self.upsert(
            status='success',
            note='via github',
            external_run_url='https://example/run',
            performed_by='alice@example.com',
        )
        rows = await deployments.deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        event = rows[0].event
        self.assertEqual('success', event.status)
        self.assertEqual('via github', event.note)
        self.assertEqual('4242', event.external_run_id)
        self.assertEqual('https://example/run', event.external_run_url)
        self.assertEqual('alice@example.com', event.performed_by)

    async def test_deployments_by_project_carries_release(self) -> None:
        await self.upsert(status='success')
        rows = await deployments.deployments_by_project(
            self.graph, [PROJECT_ID]
        )
        self.assertEqual(1, len(rows))
        assert rows[0].release is not None
        self.assertEqual(RELEASE_ID, rows[0].release['id'])

    async def test_deployments_by_project_empty_without_ids(self) -> None:
        self.assertEqual(
            [], await deployments.deployments_by_project(self.graph, [])
        )


class MergeEventsTests(unittest.TestCase):
    def test_orders_by_timestamp(self) -> None:
        from imbi.common import models

        older = models.DeploymentEvent(
            timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            status='pending',
        )
        newer = models.DeploymentEvent(
            timestamp=datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC),
            status='success',
        )
        self.assertEqual(
            [older, newer], deployments.merge_events([newer], [older])
        )
