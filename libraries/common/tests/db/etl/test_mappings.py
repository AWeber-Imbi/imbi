"""The first mappings (tenants, organizations, tags) on a fake graph."""

import datetime
import typing
import unittest

import psycopg

from imbi.common.db.etl import ids, mapping, mappings, runner
from libraries.common.tests.db.etl import support

CREATED = '2026-01-01T00:00:00+00:00'
MISSING = datetime.datetime(2026, 9, 30, tzinfo=datetime.UTC)


def utc(*args: int) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=datetime.UTC)


class MappingsTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.conn = await psycopg.AsyncConnection.connect(
            support.url(await support.scratch_database())
        )
        self.addAsyncCleanup(self.conn.close)
        await support.reset(self.conn, 'g')
        self.registry = mappings.discover()

    async def _graph(
        self,
        vertices: dict[str, list[dict[str, typing.Any]]],
        edges: dict[str, list[tuple[str, str, str, str]]] | None = None,
        missing_timestamp: datetime.datetime | None = None,
    ) -> mapping.Context:
        await support.fake_graph(self.conn, 'g', vertices, edges)
        return mapping.Context(
            source=self.conn, graph='g', missing_timestamp=missing_timestamp
        )

    async def _collect(
        self, table: str, context: mapping.Context
    ) -> tuple[runner.Collected, mapping.Expected]:
        collected = await runner.collect(self.registry[table], context)
        expected = await self.registry[table].expected(context)
        await self.conn.rollback()
        return collected, expected

    async def test_empty_graph(self) -> None:
        context = await self._graph({})
        for table in ('tenants', 'organizations', 'tags'):
            collected, expected = await self._collect(table, context)
            self.assertEqual(collected.rows, [])
            self.assertEqual(expected, mapping.Expected(count=0))

    async def test_tenant(self) -> None:
        context = await self._graph(
            {
                'Organization': [
                    {'id': 'o1', 'created_at': '2026-02-01T00:00:00Z'},
                    {'id': 'o2', 'created_at': CREATED},
                ]
            }
        )
        collected, expected = await self._collect('tenants', context)
        self.assertEqual(
            collected.rows,
            [
                {
                    'id': ids.derive_id('tenants', 'default'),
                    'name': 'Default',
                    'slug': 'default',
                    'created_at': datetime.datetime(
                        2026, 1, 1, tzinfo=datetime.UTC
                    ),
                    'updated_at': None,
                }
            ],
        )
        self.assertEqual(expected.count, 1)

    async def test_tenant_needs_created_at(self) -> None:
        context = await self._graph({'Organization': [{'id': 'o1'}]})
        with self.assertRaisesRegex(mapping.EtlError, 'no created_at'):
            await self._collect('tenants', context)

    async def test_organization(self) -> None:
        context = await self._graph(
            {
                'Organization': [
                    {
                        'id': 'o1',
                        'name': 'One',
                        'slug': 'one',
                        'created_at': CREATED,
                        'tag_formats': '[{"label": "v", "pattern": "^v"}]',
                        'previous_slugs': ['uno'],
                        'region': 'us',
                        'tier': 1,
                    }
                ]
            }
        )
        collected, expected = await self._collect('organizations', context)
        self.assertEqual(expected.count, 1)
        [row] = collected.rows
        self.assertEqual(row['tenant_id'], ids.derive_id('tenants', 'default'))
        self.assertEqual(row['tag_formats'], [{'label': 'v', 'pattern': '^v'}])
        self.assertEqual(row['previous_slugs'], ['uno'])
        self.assertEqual(row['document_analytics_identities'], 'authors_only')
        self.assertEqual(row['attributes'], {'region': 'us', 'tier': 1})
        self.assertIsNone(row['updated_at'])

    async def test_tags(self) -> None:
        context = await self._graph(
            {
                'Organization': [{'id': 'o1'}, {'id': 'o2'}],
                'Tag': [
                    {
                        'id': 't1',
                        'name': 'A',
                        'slug': 'a',
                        'created_at': CREATED,
                    },
                    {'id': 't2', 'name': 'B', 'slug': 'b', 'icon': 'x'},
                    {'id': 't3', 'name': 'C', 'slug': 'c'},
                ],
                'Team': [{'id': 'team'}],
            },
            {
                'BELONGS_TO': [
                    ('Tag', 't1', 'Organization', 'o1'),
                    ('Tag', 't2', 'Organization', 'o2'),
                    ('Tag', 't3', 'Team', 'team'),
                ]
            },
            missing_timestamp=MISSING,
        )
        collected, expected = await self._collect('tags', context)
        self.assertEqual(
            [r['created_at'] for r in collected.rows],
            [utc(2026, 1, 1), MISSING],
        )
        self.assertEqual(
            [(r['id'], r['organization_id']) for r in collected.rows],
            [('t1', 'o1'), ('t2', 'o2')],
        )
        self.assertEqual(collected.skips, [mapping.Skip('E41', 't3')])
        self.assertEqual(
            collected.changes, [mapping.Change('E35', 't2', 'icon not loaded')]
        )
        self.assertEqual(
            expected,
            mapping.Expected(count=2, skipped={'E41': frozenset({'t3'})}),
        )

    async def test_tags_without_edges(self) -> None:
        context = await self._graph({'Tag': [{'id': 't1'}]})
        collected, expected = await self._collect('tags', context)
        self.assertEqual(collected.skips, [mapping.Skip('E41', 't1')])
        self.assertEqual(expected.skipped, {'E41': {'t1'}})

    async def test_tag_in_two_organizations(self) -> None:
        context = await self._graph(
            {
                'Organization': [{'id': 'o1'}, {'id': 'o2'}],
                'Tag': [{'id': 't1'}],
            },
            {
                'BELONGS_TO': [
                    ('Tag', 't1', 'Organization', 'o1'),
                    ('Tag', 't1', 'Organization', 'o2'),
                ]
            },
        )
        with self.assertRaisesRegex(mapping.EtlError, '2 organizations'):
            await self._collect('tags', context)

    async def test_seeded_organization(self) -> None:
        context = await self._graph(
            {
                'Organization': [
                    {'_ref': 'seed', 'slug': 'seed', 'name': 'Seed'}
                ],
                'Team': [{'id': 'team', 'created_at': '2026-01-03T00:00:00Z'}],
                'Project': [{'id': 'p', 'created_at': '2026-01-02T00:00:00Z'}],
                'User': [{'id': 'u', 'created_at': '2026-01-05T00:00:00Z'}],
                'Tag': [{'id': 't1', 'slug': 'a'}],
            },
            {
                'BELONGS_TO': [
                    ('Team', 'team', 'Organization', 'seed'),
                    ('Tag', 't1', 'Organization', 'seed'),
                ],
                'OWNED_BY': [('Project', 'p', 'Team', 'team')],
                'MEMBER_OF': [('User', 'u', 'Organization', 'seed')],
            },
        )
        seed_id = ids.derive_id('Organization', '1')
        collected, expected = await self._collect('organizations', context)
        self.assertEqual(expected.count, 1)
        [row] = collected.rows
        self.assertEqual(row['id'], seed_id)
        self.assertEqual(row['created_at'], utc(2026, 1, 2))
        self.assertIsNone(row['updated_at'])
        collected, _expected = await self._collect('tenants', context)
        self.assertEqual(collected.rows[0]['created_at'], utc(2026, 1, 2))
        collected, expected = await self._collect('tags', context)
        self.assertEqual(
            [(r['organization_id'], r['created_at']) for r in collected.rows],
            [(seed_id, utc(2026, 1, 2))],
        )
        self.assertEqual(expected.count, 1)

    async def test_member_times_count(self) -> None:
        context = await self._graph(
            {
                'Organization': [{'_ref': 'seed'}],
                'User': [{'id': 'u', 'updated_at': '2026-01-07T00:00:00Z'}],
            },
            {'MEMBER_OF': [('User', 'u', 'Organization', 'seed')]},
        )
        collected, _expected = await self._collect('organizations', context)
        self.assertEqual(collected.rows[0]['created_at'], utc(2026, 1, 7))

    async def test_seeded_organization_alone(self) -> None:
        context = await self._graph(
            {'Organization': [{'_ref': 'seed'}]}, missing_timestamp=MISSING
        )
        collected, _expected = await self._collect('organizations', context)
        self.assertEqual(collected.rows[0]['created_at'], MISSING)
        await support.reset(self.conn, 'g')
        context = await self._graph({'Organization': [{'_ref': 'seed'}]})
        with self.assertRaisesRegex(mapping.EtlError, 'missing-timestamp'):
            await self._collect('organizations', context)

    async def test_boolean_attributes(self) -> None:
        schema = (
            '{"properties": {"flag": {"type": "boolean"},'
            ' "maybe": {"type": ["boolean", "null"]},'
            ' "label": {"type": "string"}, "bad": 1}}'
        )
        context = await self._graph(
            {
                'Blueprint': [
                    {
                        'id': 'b1',
                        'type': 'Organization',
                        'json_schema': schema,
                    },
                    {
                        'id': 'b2',
                        'type': 'Team',
                        'json_schema': {
                            'properties': {'other': {'type': 'boolean'}}
                        },
                    },
                    {
                        'id': 'b3',
                        'kind': 'relationship',
                        'type': 'Organization',
                        'json_schema': {
                            'properties': {'other': {'type': 'boolean'}}
                        },
                    },
                ],
                'Organization': [
                    {
                        'id': 'o1',
                        'created_at': CREATED,
                        'flag': 'true',
                        'maybe': 'false',
                        'label': 'true',
                        'other': 'true',
                    }
                ],
            }
        )
        collected, _expected = await self._collect('organizations', context)
        self.assertEqual(
            collected.rows[0]['attributes'],
            {'flag': True, 'label': 'true', 'maybe': False, 'other': 'true'},
        )
        self.assertEqual(
            collected.changes,
            [
                mapping.Change(
                    'D32', 'o1', "attribute flag: 'true' to boolean"
                ),
                mapping.Change(
                    'D32', 'o1', "attribute maybe: 'false' to boolean"
                ),
            ],
        )
