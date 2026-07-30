"""Tests for the shared search-index hooks used by raw-Cypher writes."""

import unittest
from unittest import mock

from imbi.api.endpoints import _search_index
from imbi.common import models


class IndexTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_index_builds_the_node_from_fields(self) -> None:
        mock_db = mock.AsyncMock()
        await _search_index.index(
            mock_db,
            models.Document,
            'doc-1',
            title='Runbook',
            content='Restart the thing.',
        )
        node = mock_db.embed_node.await_args.args[0]
        self.assertEqual('doc-1', node.id)
        self.assertEqual('Runbook', node.title)
        self.assertEqual('Restart the thing.', node.content)
        self.assertFalse(
            mock_db.embed_node.await_args.kwargs['raise_on_error']
        )

    async def test_index_forwards_raise_on_error(self) -> None:
        mock_db = mock.AsyncMock()
        await _search_index.index(
            mock_db,
            models.Document,
            'doc-1',
            raise_on_error=True,
            title='Runbook',
        )
        self.assertTrue(mock_db.embed_node.await_args.kwargs['raise_on_error'])


class DropTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_drop_deletes_by_label_and_id(self) -> None:
        mock_db = mock.AsyncMock()
        await _search_index.drop(mock_db, models.Comment, 'comment-1')
        mock_db.delete_node_embeddings.assert_awaited_once_with(
            'Comment', 'comment-1'
        )

    async def test_drop_swallows_failures(self) -> None:
        """A cleanup failure must not fail an already-committed delete.

        The node is gone by the time ``drop`` runs, so raising here
        would turn a successful delete into a 500 and make the client's
        retry 404.
        """
        mock_db = mock.AsyncMock()
        mock_db.delete_node_embeddings.side_effect = RuntimeError('boom')
        with self.assertLogs(_search_index.LOGGER, level='WARNING') as logs:
            await _search_index.drop(mock_db, models.Comment, 'comment-1')
        self.assertIn('search-reindex', logs.output[0])
