"""Tests for the plain Postgres schema initializer.

These run against the live Postgres that ``root:services`` boots, in a
schema of their own.
"""

import unittest

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
