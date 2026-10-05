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
