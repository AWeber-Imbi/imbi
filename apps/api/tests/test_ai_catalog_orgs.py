"""The move of a global AI catalog into the organizations, against the
live graph."""

import typing
import unittest
import uuid

from imbi.api import ai_catalog_orgs
from imbi.api.endpoints import prompts
from imbi.common import graph
from imbi.common.prompts import resolve


class MigrateTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.suffix = uuid.uuid4().hex[:8]
        self.orgs = [f'cat-a-{self.suffix}', f'cat-b-{self.suffix}']
        self.teams = [f'team-a-{self.suffix}', f'team-b-{self.suffix}']
        await graph.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.addAsyncCleanup(self.graph.close)
        self.addAsyncCleanup(self._cleanup)
        await self.graph.execute(
            """
            CREATE (a:Organization {{id: {a}, slug: {a}, name: {a}}})
            CREATE (b:Organization {{id: {b}, slug: {b}, name: {b}}})
            CREATE (ta:Team {{id: {ta}, slug: {ta}, name: {ta}}})
                   -[:BELONGS_TO]->(a)
            CREATE (tb:Team {{id: {tb}, slug: {tb}, name: {tb}}})
                   -[:BELONGS_TO]->(b)
            CREATE (p:AIProvider {{id: {p}, name: {name}, slug: 'anthropic',
                                   driver: 'anthropic', enabled: true,
                                   credentials_encrypted: 'enc:key',
                                   credential_hint: 'abcd',
                                   created_at: '2026-01-01T00:00:00Z'}})
            CREATE (m:AIModel {{id: {m}, name: {name}, slug: 'default-chat',
                                model_id: 'claude-x', enabled: true,
                                access_scope: 'restricted'}})
            CREATE (m)-[:SERVED_BY]->(p)
            CREATE (m)-[:ALLOWED_FOR]->(ta)
            CREATE (m)-[:ALLOWED_FOR]->(tb)
            RETURN 1 AS ok
            """,
            {
                'a': self.orgs[0],
                'b': self.orgs[1],
                'ta': self.teams[0],
                'tb': self.teams[1],
                'p': f'prv-{self.suffix}',
                'm': f'mdl-{self.suffix}',
                'name': self.name,
            },
            ['ok'],
        )

    @property
    def name(self) -> str:
        return f'catalog-{self.suffix}'

    async def _cleanup(self) -> None:
        # The migration copies to every organization of the database.
        for label in ('AIModel', 'AIProvider'):
            await self.graph.execute(
                f'MATCH (n:{label} {{{{name: {{name}}}}}}) DETACH DELETE n',
                {'name': self.name},
            )
        await self.graph.execute(
            'MATCH (n) WHERE n.id IN {ids} DETACH DELETE n',
            {'ids': [*self.orgs, *self.teams]},
        )

    async def _rows(self, org: str) -> list[dict[str, typing.Any]]:
        records = await self.graph.execute(
            """
            MATCH (m:AIModel {{name: {name}}})
                  -[:BELONGS_TO]->(:Organization {{id: {org}}})
            MATCH (m)-[:SERVED_BY]->(p:AIProvider)
                  -[:BELONGS_TO]->(:Organization {{id: {org}}})
            OPTIONAL MATCH (m)-[:ALLOWED_FOR]->(t:Team)
            RETURN m, p, t.id AS team
            """,
            {'name': self.name, 'org': org},
            ['m', 'p', 'team'],
        )
        return [
            {k: graph.parse_agtype(v) for k, v in r.items()} for r in records
        ]

    async def test_copies_to_each_org_and_removes_the_originals(
        self,
    ) -> None:
        self.assertGreaterEqual(await ai_catalog_orgs.migrate(self.graph), 2)
        seen: set[str] = set()
        for org, team in zip(self.orgs, self.teams, strict=True):
            rows = await self._rows(org)
            self.assertEqual(len(rows), 1, org)
            model, provider = rows[0]['m'], rows[0]['p']
            # Only the team of the same organization is kept.
            self.assertEqual(rows[0]['team'], team)
            self.assertEqual(model['slug'], 'default-chat')
            self.assertEqual(model['org_id'], org)
            self.assertEqual(provider['slug'], 'anthropic')
            self.assertEqual(provider['org_id'], org)
            self.assertEqual(provider['credentials_encrypted'], 'enc:key')
            self.assertEqual(provider['credential_hint'], 'abcd')
            self.assertEqual(provider['created_at'], '2026-01-01T00:00:00Z')
            seen |= {model['id'], provider['id']}
        self.assertEqual(len(seen), 4)
        self.assertNotIn(f'prv-{self.suffix}', seen)
        originals = await self.graph.execute(
            'MATCH (n) WHERE n.id IN {ids} RETURN n.id AS id',
            {'ids': [f'prv-{self.suffix}', f'mdl-{self.suffix}']},
            ['id'],
        )
        self.assertEqual(originals, [])
        # A second run has nothing to do.
        self.assertEqual(await ai_catalog_orgs.migrate(self.graph), 0)
        self.assertEqual(len(await self._rows(self.orgs[0])), 1)

    async def test_lookups_read_only_the_given_orgs(self) -> None:
        await ai_catalog_orgs.migrate(self.graph)
        info = await resolve.model_info(
            self.graph, 'default-chat', org_ids=[self.orgs[0]]
        )
        self.assertIsNotNone(info)
        self.assertIsNone(
            await resolve.model_info(
                self.graph, 'default-chat', org_ids=['no-such-org']
            )
        )
        self.assertTrue(
            await resolve.team_allowed(
                self.graph,
                'default-chat',
                self.teams[0],
                org_ids=[self.orgs[0]],
            )
        )
        # The team of org B is allowed only by the copy in org B.
        self.assertFalse(
            await resolve.team_allowed(
                self.graph,
                'default-chat',
                self.teams[1],
                org_ids=[self.orgs[0]],
            )
        )

    async def test_prompt_model_query(self) -> None:
        """A prompt of an org reads its org; a global prompt any org."""
        await ai_catalog_orgs.migrate(self.graph)
        for org, expected in ((self.orgs[0], 1), ('no-such-org', 0)):
            records = await self.graph.execute(
                prompts._MODEL_QUERY,
                {'slug': 'default-chat', 'org': org},
                ['model_id', 'enabled', 'model_type'],
            )
            self.assertEqual(len(records), expected, org)
        records = await self.graph.execute(
            prompts._MODEL_QUERY,
            {'slug': 'default-chat', 'org': None},
            ['model_id', 'enabled', 'model_type'],
        )
        self.assertGreaterEqual(len(records), 2)

    async def test_a_multi_org_lookup_prefers_an_enabled_model(self) -> None:
        """The same slug in two orgs: the enabled copy wins, whatever
        the order of the orgs."""
        await ai_catalog_orgs.migrate(self.graph)
        await self.graph.execute(
            'MATCH (m:AIModel {{name: {name}, org_id: {org}}})'
            ' SET m.enabled = false, m.model_id = {model_id}',
            {'name': self.name, 'org': self.orgs[0], 'model_id': 'off'},
        )
        for org_ids in (self.orgs, self.orgs[::-1]):
            info = await resolve.model_info(
                self.graph, 'default-chat', org_ids=org_ids
            )
            assert info is not None
            self.assertTrue(info.enabled)
            self.assertEqual(info.model_id, 'claude-x')
        # With both enabled, the org with the first slug wins.
        await self.graph.execute(
            'MATCH (m:AIModel {{name: {name}, org_id: {org}}})'
            ' SET m.enabled = true',
            {'name': self.name, 'org': self.orgs[0]},
        )
        info = await resolve.model_info(
            self.graph, 'default-chat', org_ids=self.orgs[::-1]
        )
        assert info is not None
        self.assertEqual(info.model_id, 'off')

    async def test_a_workload_identity_stays_only_in_its_org(self) -> None:
        """Org A keeps the identity; org B sets up its own. An identity
        of an organization that is gone is dropped everywhere."""
        for slug, org in (('wif', self.orgs[0]), ('gone', 'no-such-org')):
            await self.graph.execute(
                'CREATE (p:AIProvider {{id: {id}, name: {name},'
                " slug: {slug}, driver: 'anthropic', enabled: true,"
                ' workload_identity: {wif}}})',
                {
                    'id': f'prv-{slug}-{self.suffix}',
                    'name': self.name,
                    'slug': slug,
                    'wif': {'organization_id': org, 'target': {}},
                },
            )
        await ai_catalog_orgs.migrate(self.graph)
        records = await self.graph.execute(
            'MATCH (p:AIProvider {{name: {name}}})'
            ' WHERE p.org_id IN {orgs} AND p.slug <> {skip}'
            ' RETURN p.slug AS slug, p.org_id AS org,'
            ' p.workload_identity AS wif',
            {'name': self.name, 'orgs': self.orgs, 'skip': 'anthropic'},
            ['slug', 'org', 'wif'],
        )
        kept = {
            (graph.parse_agtype(r['slug']), graph.parse_agtype(r['org'])): (
                graph.parse_agtype(r['wif'])
            )
            for r in records
        }
        self.assertEqual(len(kept), 4)
        self.assertIsNotNone(kept['wif', self.orgs[0]])
        self.assertIsNone(kept['wif', self.orgs[1]])
        self.assertIsNone(kept['gone', self.orgs[0]])
        self.assertIsNone(kept['gone', self.orgs[1]])
