"""The deployment-array-drop maintenance operation, against the live graph."""

import typing
import unittest
import uuid
from unittest import mock

from imbi.api.maintenance import log, registry
from imbi.common import graph


class DeploymentArrayDropTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        suffix = uuid.uuid4().hex[:8]
        self.ids = {
            key: f'{key}-{suffix}'
            for key in ('release', 'orphan', 'prod', 'stage')
        }
        await graph.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.addAsyncCleanup(self.graph.close)
        # The orphan release has no project, like the 61 production
        # releases whose edges still hold an array.
        await self.graph.execute(
            """
            CREATE (r:Release {{id: {release}}})
            CREATE (o:Release {{id: {orphan}}})
            CREATE (p:Environment {{id: {prod}}})
            CREATE (s:Environment {{id: {stage}}})
            CREATE (r)-[:DEPLOYED_TO {{deployments: [{{status: 'success'}}],
                                      note: 'keep'}}]->(p)
            CREATE (r)-[:DEPLOYED_TO]->(s)
            CREATE (o)-[:DEPLOYED_TO {{deployments: []}}]->(p)
            RETURN 1 AS ok
            """,
            self.ids,
            ['ok'],
        )
        self.addAsyncCleanup(self._cleanup)

    async def _cleanup(self) -> None:
        await self.graph.execute(
            'MATCH (n) WHERE n.id IN {ids} DETACH DELETE n RETURN 1 AS ok',
            {'ids': list(self.ids.values())},
            ['ok'],
        )

    async def _edges(self) -> list[dict[str, typing.Any]]:
        rows = await self.graph.execute(
            """
            MATCH (r:Release)-[e:DEPLOYED_TO]->(:Environment)
            WHERE r.id IN {ids}
            RETURN properties(e) AS props
            """,
            {'ids': [self.ids['release'], self.ids['orphan']]},
            ['props'],
        )
        return [graph.parse_agtype(row['props']) for row in rows]

    async def _run(self) -> int:
        definition = registry.OPERATIONS['deployment-array-drop']
        self.assertFalse(definition.items_are_projects)
        (item,) = await definition.enumerate(self.graph)
        ctx = log.MaintenanceContext(
            run_id='run1',
            attempt_id='attempt1',
            item_id=item,
            project_id='',
            project_slug='',
            log=log.ItemLog(definition.slug, 'run1', 'attempt1', item),
        )
        outcome = await definition.execute(
            self.graph, mock.AsyncMock(), item, ctx=ctx
        )
        self.assertEqual(outcome, 'succeeded')
        return ctx.log.rows[-1].detail['removed']

    async def test_removes_only_the_array(self) -> None:
        self.assertGreaterEqual(await self._run(), 2)
        edges = await self._edges()
        # The edges stay; only the array goes.
        self.assertEqual(len(edges), 3)
        self.assertFalse(any('deployments' in edge for edge in edges))
        self.assertIn({'note': 'keep'}, edges)

        # A second run changes nothing.
        await self._run()
        self.assertEqual(await self._edges(), edges)
