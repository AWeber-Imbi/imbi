"""The org tag lookups of imbi.api.tags, against the live graph."""

import typing
import unittest
import uuid

import fastapi

from imbi.api import tags
from imbi.common import graph


class TagsTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        suffix = uuid.uuid4().hex[:8]
        self.org = f'tags-{suffix}'
        self.other = f'tags-other-{suffix}'
        self.ids = {'ops': f'ops-{suffix}', 'other': f'other-{suffix}'}
        self.node = f'agent-{suffix}'
        await graph.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.addAsyncCleanup(self.graph.close)
        await self.graph.execute(
            """
            CREATE (o:Organization {{id: {org}, slug: {org}}})
            CREATE (f:Organization {{id: {other}, slug: {other}}})
            CREATE (t:Tag {{id: {ops}, slug: 'ops', name: 'Ops',
                            color: '#3B82F6'}})-[:BELONGS_TO]->(o)
            CREATE (x:Tag {{id: {other_tag}, slug: 'other',
                            name: 'Other'}})-[:BELONGS_TO]->(f)
            CREATE (:Agent {{id: {node}}})-[:BELONGS_TO]->(o)
            RETURN 1 AS ok
            """,
            {
                'org': self.org,
                'other': self.other,
                'ops': self.ids['ops'],
                'other_tag': self.ids['other'],
                'node': self.node,
            },
            ['ok'],
        )
        self.addAsyncCleanup(self._cleanup)

    async def _cleanup(self) -> None:
        await self.graph.execute(
            'MATCH (n) WHERE n.id IN {ids} DETACH DELETE n RETURN 1 AS ok',
            {'ids': [self.org, self.other, self.node, *self.ids.values()]},
            ['ok'],
        )

    async def test_ids_by_slug(self) -> None:
        found = await tags.ids_by_slug(
            self.graph, self.org, ['ops', 'ops', 'other', 'nope']
        )
        self.assertEqual(found, {'ops': self.ids['ops']})
        self.assertEqual(await tags.ids_by_slug(self.graph, self.org, []), {})

    async def test_require_ids(self) -> None:
        found = await tags.require_ids(self.graph, self.org, ['ops'])
        self.assertEqual(found, {'ops': self.ids['ops']})
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await tags.require_ids(self.graph, self.org, ['ops', 'other'])
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(
            ctx.exception.detail, "Tag slug(s) not found: ['other']"
        )

    async def test_by_id(self) -> None:
        found = await tags.by_id(
            self.graph, self.org, [self.ids['ops'], self.ids['other']]
        )
        self.assertEqual(
            found,
            {
                self.ids['ops']: {
                    'id': self.ids['ops'],
                    'name': 'Ops',
                    'slug': 'ops',
                    'color': '#3B82F6',
                }
            },
        )

    async def _tag_slugs(self) -> list[str]:
        records = await self.graph.execute(
            'MATCH (:Agent {{id: {id}}})-[:TAGGED_WITH]->(t:Tag)'
            ' RETURN t.slug AS slug',
            {'id': self.node},
            ['slug'],
        )
        return sorted(str(graph.parse_agtype(r['slug'])) for r in records)

    async def test_attach_and_detach(self) -> None:
        node: typing.LiteralString = 'MATCH (n:Agent {{id: {id}}})'
        params = {'id': self.node}
        # A tag of another org is not attached; a repeat adds no edge.
        for _ in range(2):
            await tags.execute(
                self.graph,
                [
                    tags.attach_statement(
                        node, params, self.org, ['ops', 'other']
                    )
                ],
            )
        records = await self.graph.execute(
            'MATCH (:Agent {{id: {id}}})-[r:TAGGED_WITH]->(:Tag)'
            ' RETURN count(r) AS edges',
            params,
            ['edges'],
        )
        self.assertEqual(graph.parse_agtype(records[0]['edges']), 1)
        self.assertEqual(await self._tag_slugs(), ['ops'])

        await tags.execute(
            self.graph, tags.replace_statements(node, params, self.org, [])
        )
        self.assertEqual(await self._tag_slugs(), [])


class ParseRefsTestCase(unittest.TestCase):
    def test_parse_refs(self) -> None:
        self.assertEqual(tags.parse_refs(None), [])
        self.assertEqual(
            tags.parse_refs(
                [
                    {'name': 'Ops', 'slug': 'ops', 'color': '#3B82F6'},
                    {'name': 'No slug'},
                    'not a map',
                    {'slug': 'bare'},
                ]
            ),
            [
                {'name': 'Ops', 'slug': 'ops', 'color': '#3B82F6'},
                {'name': '', 'slug': 'bare', 'color': None},
            ],
        )
