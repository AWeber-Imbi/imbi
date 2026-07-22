"""Tests for account_resolution.resolve_account."""

import typing
import unittest
from unittest import mock

from imbi_common.plugins.base import PluginContext

from imbi_plugin_aws import account_resolution
from imbi_plugin_aws.errors import AccountNotResolvedError


class _FakeDB:
    """Stub graph DB that returns canned execute results.

    ``mappings`` keys are ``(label, anchor_id)`` tuples; values are
    lists of dicts that mimic the agtype-parsed ``account`` payload.
    """

    def __init__(
        self, mappings: dict[tuple[str, str], list[dict[str, object]]]
    ) -> None:
        self.mappings = mappings
        self.execute = mock.AsyncMock(side_effect=self._execute)
        self.calls: list[tuple[str, str]] = []

    async def _execute(
        self,
        query: typing.Any,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
    ) -> list[dict[str, typing.Any]]:
        params = params or {}
        anchor_id = str(params.get('anchor_id', ''))
        # Extract the label between '(n:' and ' '.
        text = str(query)
        idx = text.find('(n:')
        label = text[idx + 3 :].split(' ', 1)[0] if idx >= 0 else ''
        self.calls.append((label, anchor_id))
        rows = self.mappings.get((label, anchor_id), [])
        return [{'account': r} for r in rows]


_ACC = {
    'id': 'a-1',
    'account_id': '111111111111',
    'name': 'Production',
    'default_role_name': 'PowerUserAccess',
    'default_region': 'us-east-1',
    'tags': {'tier': 'prod'},
}


def _ctx() -> PluginContext:
    return PluginContext(
        project_id='proj-1',
        project_slug='proj',
        org_slug='org',
        actor_user_id='u',
    )


class ResolveAccountTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_first_anchor_match_wins(self) -> None:
        db = _FakeDB({('Project', 'proj-1'): [_ACC]})
        with mock.patch.object(
            account_resolution,
            '_anchor_id_from_ctx',
            side_effect=lambda anchor, ctx: 'proj-1'
            if anchor == 'project'
            else None,
        ):
            result = await account_resolution.resolve_account(db, _ctx(), {})
        self.assertEqual(result.account_id, '111111111111')
        self.assertEqual(db.calls, [('Project', 'proj-1')])

    async def test_tag_filter_excludes_mismatched_account(self) -> None:
        non_prod = {**_ACC, 'tags': {'tier': 'dev'}}
        db = _FakeDB({('Project', 'proj-1'): [non_prod]})
        with mock.patch.object(
            account_resolution,
            '_anchor_id_from_ctx',
            side_effect=lambda anchor, ctx: 'proj-1'
            if anchor == 'project'
            else None,
        ):
            with self.assertRaises(AccountNotResolvedError):
                await account_resolution.resolve_account(
                    db, _ctx(), {'tag_filters': {'tier': 'prod'}}
                )

    async def test_no_match_raises_with_anchors_checked(self) -> None:
        db = _FakeDB({})
        with mock.patch.object(
            account_resolution,
            '_anchor_id_from_ctx',
            side_effect=lambda anchor, ctx: 'proj-1'
            if anchor == 'project'
            else None,
        ):
            with self.assertRaises(AccountNotResolvedError) as ctx_mgr:
                await account_resolution.resolve_account(db, _ctx(), {})
        self.assertIn('project', ctx_mgr.exception.anchors_checked)

    async def test_unknown_anchor_skipped(self) -> None:
        db = _FakeDB({('Project', 'proj-1'): [_ACC]})
        with mock.patch.object(
            account_resolution,
            '_anchor_id_from_ctx',
            side_effect=lambda anchor, ctx: 'proj-1'
            if anchor == 'project'
            else None,
        ):
            result = await account_resolution.resolve_account(
                db,
                _ctx(),
                {
                    'account_selector': [
                        'unknown_anchor',
                        'project',
                    ]
                },
            )
        self.assertEqual(result.id, 'a-1')
