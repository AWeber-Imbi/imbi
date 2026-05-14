"""Tests for the one-shot embedding backfill script."""

import unittest
from unittest import mock

from imbi_api import backfill_embeddings


class BackfillEmbeddingsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_run_embeds_all_nodes(self) -> None:
        mock_node = mock.MagicMock()
        mock_db = mock.AsyncMock()
        mock_db.match.return_value = [mock_node]

        with mock.patch.object(
            backfill_embeddings.graph, 'Graph', return_value=mock_db
        ):
            with mock.patch(
                'imbi_api.backfill_embeddings._embeddable_fields',
                return_value=['name'],
            ):
                await backfill_embeddings.run()

        expected = len(backfill_embeddings._NODE_TYPES) + len(
            backfill_embeddings._GRAPH_MODEL_TYPES
        )
        self.assertEqual(mock_db.match.await_count, expected)
        self.assertEqual(mock_db._auto_embed.await_count, expected)
        mock_db.open.assert_awaited_once()
        mock_db.close.assert_awaited_once()

    async def test_run_skips_non_embeddable_nodes(self) -> None:
        mock_node = mock.MagicMock()
        mock_db = mock.AsyncMock()
        mock_db.match.return_value = [mock_node]

        with mock.patch.object(
            backfill_embeddings.graph, 'Graph', return_value=mock_db
        ):
            with mock.patch(
                'imbi_api.backfill_embeddings._embeddable_fields',
                return_value=[],
            ):
                await backfill_embeddings.run()

        mock_db._auto_embed.assert_not_awaited()

    async def test_run_closes_db_on_exception(self) -> None:
        mock_db = mock.AsyncMock()
        mock_db.match.side_effect = RuntimeError('simulated error')

        with mock.patch.object(
            backfill_embeddings.graph, 'Graph', return_value=mock_db
        ):
            with mock.patch(
                'imbi_api.backfill_embeddings._embeddable_fields',
                return_value=['name'],
            ):
                with self.assertRaises(RuntimeError):
                    await backfill_embeddings.run()

        mock_db.close.assert_awaited_once()

    async def test_embed_type_empty_nodes(self) -> None:
        mock_db = mock.AsyncMock()
        mock_db.match.return_value = []

        with mock.patch(
            'imbi_api.backfill_embeddings._embeddable_fields',
            return_value=['name'],
        ):
            count = await backfill_embeddings._embed_type(
                mock_db, backfill_embeddings._NODE_TYPES[0]
            )

        self.assertEqual(count, 0)
        mock_db._auto_embed.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
