"""Tests for scoring recompute triggers."""

from __future__ import annotations

import unittest
from unittest import mock


class AffectedProjectsTests(unittest.IsolatedAsyncioTestCase):
    async def test_affected_projects_returns_ids(self) -> None:
        from imbi_common.scoring import AttributePolicy

        from imbi_api.scoring import queue

        policy = AttributePolicy(
            name='Lang',
            slug='lang',
            attribute_name='programming_language',
            weight=10,
            value_score_map={'Python': 100},
        )
        db = mock.AsyncMock()
        # blueprints.get_model returns model whose model_fields includes
        # the attribute_name.
        fake_model = mock.MagicMock()
        fake_model.model_fields = {'programming_language': object()}
        with mock.patch(
            'imbi_api.scoring.queue.blueprints.get_model',
            mock.AsyncMock(return_value=fake_model),
        ):
            db.execute = mock.AsyncMock(
                return_value=[{'id': 'p1'}, {'id': 'p2'}]
            )
            ids = await queue.affected_projects(db, policy)
        self.assertEqual(ids, ['p1', 'p2'])

    async def test_affected_projects_empty_when_attr_missing(self) -> None:
        from imbi_common.scoring import AttributePolicy

        from imbi_api.scoring import queue

        policy = AttributePolicy(
            name='Lang',
            slug='lang',
            attribute_name='nonexistent',
            weight=10,
            value_score_map={'a': 100},
        )
        db = mock.AsyncMock()
        fake_model = mock.MagicMock()
        fake_model.model_fields = {'name': object()}
        with mock.patch(
            'imbi_api.scoring.queue.blueprints.get_model',
            mock.AsyncMock(return_value=fake_model),
        ):
            ids = await queue.affected_projects(db, policy)
        self.assertEqual(ids, [])
