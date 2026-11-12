"""Tests for the duplicate check before a unique index is created."""

import unittest
from unittest import mock

from imbi.common.graph import initializer

SCHEMATA = {
    'vlabel_indexes': [
        {'vlabel': 'AIModel', 'attributes': ['slug'], 'unique': True},
    ],
}


def cursor(index_exists: bool, duplicates: list[tuple[object, ...]]):
    cur = mock.AsyncMock()
    cur.fetchone.return_value = (1,) if index_exists else None
    cur.fetchall.return_value = duplicates
    return cur


def executed(cur: mock.AsyncMock) -> list[str]:
    return [str(call.args[0]) for call in cur.execute.await_args_list]


class UniqueIndexTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_existing_index_skips_the_scan(self) -> None:
        cur = cursor(index_exists=True, duplicates=[])
        await initializer._create_vlabel_indexes(cur, 'imbi', SCHEMATA)
        self.assertFalse(any('GROUP BY' in q for q in executed(cur)))
        self.assertTrue(any('CREATE' in q for q in executed(cur)))

    async def test_new_index_without_duplicates_is_created(self) -> None:
        cur = cursor(index_exists=False, duplicates=[])
        await initializer._create_vlabel_indexes(cur, 'imbi', SCHEMATA)
        queries = executed(cur)
        self.assertTrue(any('GROUP BY' in q for q in queries))
        self.assertTrue(any('CREATE' in q for q in queries))

    async def test_duplicates_stop_with_a_clear_message(self) -> None:
        cur = cursor(index_exists=False, duplicates=[('"default-chat"', 2)])
        with self.assertRaisesRegex(
            RuntimeError, r'aimodel_slug_unique_idx.*default-chat.*2 rows'
        ):
            await initializer._create_vlabel_indexes(cur, 'imbi', SCHEMATA)
        self.assertFalse(any('CREATE' in q for q in executed(cur)))


class InitializeLockTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_ddl_runs_under_an_advisory_lock(self) -> None:
        """Services that start together must not race on the DDL.

        Concurrent ``CREATE OR REPLACE FUNCTION`` fails with "tuple
        concurrently updated" (IMBI-5Q).
        """
        calls: list[str] = []
        conn = mock.AsyncMock()
        conn.__aenter__.return_value = conn
        conn.execute.side_effect = lambda q, *a: calls.append(str(q))
        conn.cursor = mock.MagicMock()
        steps = [
            '_create_extensions',
            '_create_graph',
            '_create_vlabels',
            '_create_vlabel_indexes',
            '_create_embeddings_table',
            '_create_functions',
        ]
        with (
            mock.patch.object(
                initializer.psycopg.AsyncConnection,
                'connect',
                new=mock.AsyncMock(return_value=conn),
            ),
            mock.patch.multiple(
                initializer,
                **{
                    name: mock.AsyncMock(
                        side_effect=lambda *a, n=name: calls.append(n)
                    )
                    for name in steps
                },
            ),
        ):
            await initializer.initialize()
        locks = [i for i, q in enumerate(calls) if 'advisory_lock' in q]
        self.assertTrue(locks, calls)
        self.assertLess(locks[0], calls.index('_create_extensions'))
