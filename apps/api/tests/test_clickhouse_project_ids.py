"""Org-wide project-ID lists reach ClickHouse in one query (#593).

A bound ``Array(String)`` goes as one HTML form field, and ClickHouse
rejects a field longer than 131072 bytes -- about 5000 project IDs.
The ``project_ids`` external table goes as a file part instead.
"""

import unittest

from imbi.common import clickhouse
from imbi.common.clickhouse import client


class ProjectIdsExternalTableTestCase(unittest.IsolatedAsyncioTestCase):
    """Runs against the test ClickHouse server."""

    async def asyncSetUp(self) -> None:
        # The client binds to the loop that opened it; take a private
        # instance and hand the old one back, as test_component_facts
        # does.
        self._previous = client.Clickhouse._instance
        client.Clickhouse._instance = None
        self.addAsyncCleanup(self._restore_singleton)
        await clickhouse.initialize()

    async def _restore_singleton(self) -> None:
        await clickhouse.aclose()
        client.Clickhouse._instance = self._previous

    async def test_more_ids_than_a_form_field_holds(self) -> None:
        ids = [f'project-{n:013d}' for n in range(10000)]
        self.assertGreater(len(str(ids)), 131072)
        rows = await clickhouse.query(
            'SELECT count() AS n FROM project_ids'
            ' WHERE project_id IN (SELECT project_id FROM project_ids)'
            ' AND {x:String} = {x:String}',
            {'x': 'a'},
            project_ids=ids,
        )
        self.assertEqual(rows, [{'n': 10000}])
