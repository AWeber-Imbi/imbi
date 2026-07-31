"""Tests for the one-shot embedding backfill script."""

import asyncio
import unittest
from unittest import mock

import psycopg

from imbi.api import backfill_embeddings
from imbi.common import graph


def _patch_already_embedded(return_value: set[str]) -> mock._patch:
    return mock.patch(
        'imbi.api.backfill_embeddings._already_embedded_ids',
        new=mock.AsyncMock(return_value=return_value),
    )


class BackfillEmbeddingsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_run_embeds_all_nodes(self) -> None:
        mock_node = mock.MagicMock(id='node-1')
        mock_db = mock.AsyncMock()
        mock_db.match.return_value = [mock_node]

        with mock.patch.object(
            backfill_embeddings.graph, 'Graph', return_value=mock_db
        ):
            with _patch_already_embedded(set()):
                await backfill_embeddings.run(concurrency=2, force=False)

        expected = len(graph.embeddable_node_types())
        self.assertEqual(mock_db.match.await_count, expected)
        self.assertEqual(mock_db.embed_node.await_count, expected)
        mock_db.open.assert_awaited_once()
        mock_db.close.assert_awaited_once()

    async def test_run_closes_db_on_exception(self) -> None:
        mock_db = mock.AsyncMock()
        mock_db.match.side_effect = RuntimeError('simulated error')

        with mock.patch.object(
            backfill_embeddings.graph, 'Graph', return_value=mock_db
        ):
            with _patch_already_embedded(set()):
                with self.assertRaises(RuntimeError):
                    await backfill_embeddings.run(concurrency=2, force=False)

        mock_db.close.assert_awaited_once()

    async def test_embed_type_empty_nodes(self) -> None:
        mock_db = mock.AsyncMock()
        mock_db.match.return_value = []

        with _patch_already_embedded(set()):
            semaphore = asyncio.Semaphore(2)
            count = await backfill_embeddings._embed_type(
                mock_db,
                graph.embeddable_node_types()[0],
                semaphore=semaphore,
                force=False,
            )

        self.assertEqual(count, 0)
        mock_db.embed_node.assert_not_awaited()

    async def test_embed_type_skips_already_embedded(self) -> None:
        mock_node = mock.MagicMock(id='node-already')
        mock_db = mock.AsyncMock()
        mock_db.match.return_value = [mock_node]

        with _patch_already_embedded({'node-already'}):
            semaphore = asyncio.Semaphore(2)
            count = await backfill_embeddings._embed_type(
                mock_db,
                graph.embeddable_node_types()[0],
                semaphore=semaphore,
                force=False,
            )

        self.assertEqual(count, 0)
        mock_db.embed_node.assert_not_awaited()

    async def test_embed_type_force_re_embeds(self) -> None:
        mock_node = mock.MagicMock(id='node-already')
        mock_db = mock.AsyncMock()
        mock_db.match.return_value = [mock_node]

        with _patch_already_embedded({'node-already'}) as already_mock:
            semaphore = asyncio.Semaphore(2)
            count = await backfill_embeddings._embed_type(
                mock_db,
                graph.embeddable_node_types()[0],
                semaphore=semaphore,
                force=True,
            )

        self.assertEqual(count, 1)
        mock_db.embed_node.assert_awaited_once_with(
            mock_node, raise_on_error=True
        )
        already_mock.assert_not_called()

    async def test_embed_type_swallows_psycopg_error(self) -> None:
        mock_node_ok = mock.MagicMock(id='ok')
        mock_node_bad = mock.MagicMock(id='bad')
        mock_db = mock.AsyncMock()
        mock_db.match.return_value = [mock_node_ok, mock_node_bad]

        async def _embed(node: object, **_kwargs: object) -> None:
            if getattr(node, 'id', None) == 'bad':
                raise psycopg.OperationalError('boom')

        mock_db.embed_node.side_effect = _embed

        with _patch_already_embedded(set()):
            semaphore = asyncio.Semaphore(2)
            count = await backfill_embeddings._embed_type(
                mock_db,
                graph.embeddable_node_types()[0],
                semaphore=semaphore,
                force=False,
            )

        # One success, one swallowed psycopg failure.
        self.assertEqual(count, 1)
        self.assertEqual(mock_db.embed_node.await_count, 2)

    async def test_already_embedded_ids_queries_label(self) -> None:
        cursor = mock.AsyncMock()
        cursor.fetchall.return_value = [('a',), ('b',)]
        cursor.__aenter__.return_value = cursor
        cursor.__aexit__.return_value = None

        conn = mock.MagicMock()
        conn.cursor.return_value = cursor
        conn.__aenter__.return_value = conn
        conn.__aexit__.return_value = None

        connection_ctx = mock.MagicMock()
        connection_ctx.__aenter__.return_value = conn
        connection_ctx.__aexit__.return_value = None

        pool = mock.MagicMock()
        pool.connection.return_value = connection_ctx

        db = mock.MagicMock()
        db.pool = pool

        result = await backfill_embeddings._already_embedded_ids(db, 'Project')

        self.assertEqual(result, {'a', 'b'})
        cursor.execute.assert_awaited_once()
        args, _ = cursor.execute.await_args
        self.assertIn('public.embeddings', args[0])
        self.assertEqual(args[1], {'label': 'Project'})


class ParseArgsTestCase(unittest.TestCase):
    def test_defaults(self) -> None:
        with mock.patch('sys.argv', ['backfill_embeddings']):
            args = backfill_embeddings._parse_args()

        self.assertEqual(
            args.concurrency, backfill_embeddings._DEFAULT_CONCURRENCY
        )
        self.assertFalse(args.force)

    def test_flags(self) -> None:
        with mock.patch(
            'sys.argv',
            ['backfill_embeddings', '--concurrency', '8', '--force'],
        ):
            args = backfill_embeddings._parse_args()

        self.assertEqual(args.concurrency, 8)
        self.assertTrue(args.force)


if __name__ == '__main__':
    unittest.main()
