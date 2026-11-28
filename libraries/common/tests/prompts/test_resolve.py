"""Tests for the catalog access checks in the prompt resolver."""

import unittest
from unittest import mock

from imbi.common.prompts import resolve


class MayUseModelIdTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_grant_lookup_uses_the_row_organization(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = [
            [{'slug': 'chat', 'access_scope': 'restricted', 'org_id': 'a'}],
            [],
        ]
        with mock.patch.object(
            resolve.graph, 'parse_agtype', side_effect=lambda v: v
        ):
            allowed = await resolve.member_may_use_model_id(
                db, 'X', 'ada@example.com', org_ids=['a', 'b']
            )
        self.assertFalse(allowed)
        self.assertEqual(
            db.execute.await_args_list[1].args[1]['org_ids'], ['a']
        )
