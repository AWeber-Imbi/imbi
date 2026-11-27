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
