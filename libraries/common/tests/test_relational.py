"""Tests for the plain Postgres schema initializer.

These run against the live Postgres that ``root:services`` boots, in a
schema of their own.
"""

import unittest
import uuid

import dotenv
import psycopg
from psycopg import sql

from imbi.common import relational, settings

dotenv.load_dotenv()

SCHEMA = 'relational_test'

SCHEMATA = {
    'tables': [
        {
            'name': 'items',
            'columns': {'id': 'UUID NOT NULL', 'name': 'TEXT NOT NULL'},
            'primary_key': {'columns': ['id']},
            'indexes': [
                {'name': 'items_name_key', 'columns': ['name'], 'unique': True}
            ],
        }
    ]
}


class InitializeTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.conn = await psycopg.AsyncConnection.connect(
            str(settings.Postgres().url), autocommit=True
        )
        await self._drop()
        self.addAsyncCleanup(self.conn.close)
        self.addAsyncCleanup(self._drop)

    async def _drop(self) -> None:
        await self.conn.execute(
            sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(
                sql.Identifier(SCHEMA)
            )
        )

    async def _columns(self) -> set[str]:
        cursor = await self.conn.execute(
            'SELECT column_name FROM information_schema.columns'
            ' WHERE table_schema = %s AND table_name = %s',
            (SCHEMA, 'items'),
        )
        return {row[0] for row in await cursor.fetchall()}

    async def test_initialize_is_idempotent(self) -> None:
        await relational.initialize(SCHEMA, SCHEMATA, 'test.relational')
        await relational.initialize(SCHEMA, SCHEMATA, 'test.relational')
        self.assertEqual(await self._columns(), {'id', 'name'})
        cursor = await self.conn.execute(
            'SELECT indexname FROM pg_indexes WHERE schemaname = %s',
            (SCHEMA,),
        )
        names = {row[0] for row in await cursor.fetchall()}
        self.assertIn('items_name_key', names)

    async def test_restores_a_dropped_column(self) -> None:
        await relational.initialize(SCHEMA, SCHEMATA, 'test.relational')
        await self.conn.execute(
            sql.SQL('ALTER TABLE {} DROP COLUMN name').format(
                sql.Identifier(SCHEMA, 'items')
            )
        )
        await relational.initialize(SCHEMA, SCHEMATA, 'test.relational')
        self.assertEqual(await self._columns(), {'id', 'name'})

    async def test_new_table_refers_to_a_unique_index_added_later(
        self,
    ) -> None:
        # A deployed schema: the table exists without the unique index.
        await relational.initialize(SCHEMA, SCHEMATA, 'test.relational')
        items = SCHEMATA['tables'][0]
        upgraded = {
            'tables': [
                {
                    **items,
                    'indexes': [
                        *items['indexes'],
                        {
                            'name': 'items_name_id_key',
                            'columns': ['name', 'id'],
                            'unique': True,
                        },
                    ],
                },
                {
                    'name': 'links',
                    'columns': {
                        'name': 'TEXT NOT NULL',
                        'item_id': 'UUID NOT NULL',
                    },
                    'primary_key': {'columns': ['name', 'item_id']},
                    'constraints': [
                        'CONSTRAINT links_item_fkey FOREIGN KEY'
                        ' (name, item_id) REFERENCES'
                        f' {SCHEMA}.items (name, id)',
                        "CONSTRAINT links_name_check CHECK (name <> '')",
                    ],
                },
            ]
        }
        await relational.initialize(SCHEMA, upgraded, 'test.relational')
        await relational.initialize(SCHEMA, upgraded, 'test.relational')
        item_id = uuid.uuid4()
        insert = sql.SQL('INSERT INTO {} VALUES (%s, %s)')
        items_table = sql.Identifier(SCHEMA, 'items')
        links_table = sql.Identifier(SCHEMA, 'links')
        await self.conn.execute(insert.format(items_table), (item_id, 'a'))
        await self.conn.execute(insert.format(links_table), ('a', item_id))
        # No such (name, id) in items, and the check constraint.
        for name in ('b', ''):
            with self.assertRaises(psycopg.errors.IntegrityError):
                await self.conn.execute(
                    insert.format(links_table), (name, item_id)
                )

    async def test_step_runs_once(self) -> None:
        await relational.initialize(SCHEMA, SCHEMATA, 'test.relational')
        # A rename, and a guard that is false once it is done.
        step = {
            'name': 'rename-name-to-title',
            'when': (
                'SELECT EXISTS (SELECT 1 FROM information_schema.columns'
                f" WHERE table_schema = '{SCHEMA}'"
                " AND table_name = 'items' AND column_name = 'name')"
            ),
            'sql': f'ALTER TABLE {SCHEMA}.items RENAME COLUMN name TO title',
        }
        renamed = {
            'steps': [step],
            'tables': [
                {
                    'name': 'items',
                    'columns': {
                        'id': 'UUID NOT NULL',
                        'title': 'TEXT NOT NULL',
                    },
                    'primary_key': {'columns': ['id']},
                }
            ],
        }
        await relational.initialize(SCHEMA, renamed, 'test.relational')
        await relational.initialize(SCHEMA, renamed, 'test.relational')
        self.assertEqual(await self._columns(), {'id', 'title'})

    async def test_failed_step_rolls_back(self) -> None:
        await relational.initialize(SCHEMA, SCHEMATA, 'test.relational')
        # The guard writes a marker. Only the step transaction rolls it
        # back, because the guard and the step SQL are separate queries.
        await self.conn.execute(f'CREATE TABLE {SCHEMA}.markers (id INT)')
        failing = {
            **SCHEMATA,
            'steps': [
                {
                    'name': 'half-done',
                    'when': (
                        f'INSERT INTO {SCHEMA}.markers VALUES (1)'
                        ' RETURNING true'
                    ),
                    'sql': (
                        f'ALTER TABLE {SCHEMA}.items'
                        ' RENAME COLUMN name TO title;'
                        ' SELECT 1 / 0'
                    ),
                }
            ],
        }
        with self.assertRaises(psycopg.errors.DivisionByZero):
            await relational.initialize(SCHEMA, failing, 'test.relational')
        self.assertEqual(await self._columns(), {'id', 'name'})
        cursor = await self.conn.execute(
            f'SELECT count(*) FROM {SCHEMA}.markers'
        )
        self.assertEqual(await cursor.fetchone(), (0,))

    async def test_skips_a_view_of_a_declared_table(self) -> None:
        # A step moved the table and left a view under the old name; an
        # older release still declares the table and its index.
        await self.conn.execute(
            sql.SQL(
                'CREATE SCHEMA {schema};'
                ' CREATE TABLE {base} (id UUID PRIMARY KEY, name TEXT);'
                ' CREATE VIEW {view} AS SELECT id, name FROM {base}'
            ).format(
                schema=sql.Identifier(SCHEMA),
                base=sql.Identifier(SCHEMA, 'moved'),
                view=sql.Identifier(SCHEMA, 'items'),
            )
        )
        await relational.initialize(SCHEMA, SCHEMATA, 'test.relational')
        cursor = await self.conn.execute(
            'SELECT indexname FROM pg_indexes WHERE schemaname = %s',
            (SCHEMA,),
        )
        names = {row[0] for row in await cursor.fetchall()}
        self.assertNotIn('items_name_key', names)
