"""Tests for the shared search-index hooks used by raw-Cypher writes."""

import unittest
from unittest import mock

from imbi.api.endpoints import _search_index
from imbi.common import models


class IndexTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_index_embeds_the_re_read_node(self) -> None:
        """The node is re-read at task time, not taken from the caller.

        Two concurrent edits schedule two background tasks in no
        particular order, so embedding whatever the caller wrote lets
        the older task run last and leave the index holding stale text.
        Re-reading makes last-writer-wins correct either way round.
        """
        persisted = models.Document.model_construct(
            id='doc-1',
            title='Runbook (v2)',
            content='The newer content.',
        )
        mock_db = mock.AsyncMock()
        mock_db.match.return_value = [persisted]

        embedded = await _search_index.index(mock_db, models.Document, 'doc-1')

        self.assertTrue(embedded)
        mock_db.match.assert_awaited_once_with(
            models.Document, {'id': 'doc-1'}
        )
        self.assertIs(persisted, mock_db.embed_node.await_args.args[0])
        self.assertFalse(
            mock_db.embed_node.await_args.kwargs['raise_on_error']
        )

    async def test_index_skips_a_node_that_is_gone(self) -> None:
        """A node deleted before the task runs is skipped, not an error.

        ``drop`` has already cleared its embedding rows, so there is
        nothing to do and nothing to report.
        """
        mock_db = mock.AsyncMock()
        mock_db.match.return_value = []

        embedded = await _search_index.index(mock_db, models.Document, 'doc-1')

        self.assertFalse(embedded)
        mock_db.embed_node.assert_not_awaited()

    async def test_index_forwards_raise_on_error(self) -> None:
        mock_db = mock.AsyncMock()
        mock_db.match.return_value = [
            models.Document.model_construct(id='doc-1', title='Runbook')
        ]
        await _search_index.index(
            mock_db,
            models.Document,
            'doc-1',
            raise_on_error=True,
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
