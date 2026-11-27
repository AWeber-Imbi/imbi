"""Tests for the MCP server organization backfill rules."""

import unittest
from unittest import mock

from imbi.api import mcp_server_orgs


def graph(candidates: list[str], orgs: list[str]) -> mock.AsyncMock:
    db = mock.AsyncMock()

    async def execute(query: str, params: object, columns: object) -> list:
        if query is mcp_server_orgs._CANDIDATES:
            return [{'slug': c} for c in candidates]
        if query is mcp_server_orgs._ORGS:
            return [{'id': o} for o in orgs]
        return [{'id': c} for c in candidates]

    db.execute.side_effect = execute
    return db


def links(db: mock.AsyncMock) -> list[object]:
    return [
        c.args[1]
        for c in db.execute.await_args_list
        if c.args[0] is mcp_server_orgs._LINK
    ]


@mock.patch('imbi.common.graph.parse_agtype', side_effect=lambda x: x)
class BackfillTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_one_organization_gets_every_server(self, _: object) -> None:
        db = graph(['a', 'b'], ['org-1'])
        self.assertEqual(await mcp_server_orgs.backfill(db), 2)
        self.assertEqual(links(db), [{'org': 'org-1'}])

    async def test_two_organizations_link_nothing(self, _: object) -> None:
        db = graph(['a'], ['org-1', 'org-2'])
        with self.assertLogs('imbi.api.mcp_server_orgs', 'WARNING'):
            self.assertEqual(await mcp_server_orgs.backfill(db), 0)
        self.assertEqual(links(db), [])

    async def test_no_candidates_reads_no_organizations(
        self, _: object
    ) -> None:
        db = graph([], ['org-1'])
        self.assertEqual(await mcp_server_orgs.backfill(db), 0)
        self.assertEqual(db.execute.await_count, 1)


class MaintenanceOperationTestCase(unittest.IsolatedAsyncioTestCase):
    """The backfills run one time, as maintenance operations."""

    async def test_operations_call_the_backfills(self) -> None:
        from imbi.api import conversation_orgs
        from imbi.api.maintenance import registry

        cases = (
            ('mcp-server-org-backfill', mcp_server_orgs, 'linked'),
            ('conversation-org-backfill', conversation_orgs, 'changed'),
        )
        for slug, module, key in cases:
            with self.subTest(slug=slug):
                definition = registry.OPERATIONS[slug]
                self.assertFalse(definition.items_are_projects)
                db, ctx = mock.AsyncMock(), mock.Mock()
                with mock.patch.object(
                    module, 'backfill', mock.AsyncMock(return_value=2)
                ) as backfill:
                    items = await definition.enumerate(db)
                    outcome = await definition.execute(
                        db, mock.AsyncMock(), items[0], ctx=ctx
                    )
                self.assertEqual(items, ['all'])
                self.assertEqual(outcome, 'succeeded')
                backfill.assert_awaited_once_with(db)
                self.assertEqual(ctx.log.record.call_args.kwargs[key], 2)
