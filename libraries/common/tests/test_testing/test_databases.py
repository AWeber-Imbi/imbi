"""The per-process test databases, and the RLS index regression test."""

import collections.abc
import os
import typing
import unittest

import psycopg
from psycopg import rows

from imbi.common.testing import databases, factories


def _nodes(
    plan: dict[str, typing.Any],
) -> collections.abc.Iterator[dict[str, typing.Any]]:
    yield plan
    for child in plan.get('Plans', []):
        yield from _nodes(child)


class IsolatedDatabaseTestCase(unittest.TestCase):
    result: databases.IsolatedDatabases

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.result = databases.isolated_database()

    def test_one_result_for_each_process(self) -> None:
        self.assertIs(databases.isolated_database(), self.result)
        suffix = self.result.relational.removeprefix('imbi_test_')
        self.assertTrue(suffix.startswith(f'{os.getpid()}_'))
        self.assertEqual(self.result.graph, f'imbi_graph_test_{suffix}')

    def test_the_settings_point_at_the_copies(self) -> None:
        self.assertEqual(os.environ['POSTGRES_URL'], self.result.graph_url)
        self.assertEqual(os.environ['DATABASE_URL'], self.result.app_url)
        self.assertEqual(
            os.environ['ADMIN_DATABASE_URL'], self.result.admin_url
        )
        self.assertEqual(
            os.environ['MAINTENANCE_DATABASE_URL'],
            self.result.maintenance_url,
        )
        self.assertEqual(
            os.environ['IMBI_TEST_FACTORY_URL'], self.result.factory_url
        )

    def test_graph_copy_has_age(self) -> None:
        with psycopg.connect(self.result.graph_url) as conn:
            row = conn.execute(
                'SELECT current_database(),'
                '       EXISTS (SELECT FROM pg_extension'
                "                WHERE extname = 'age')"
            ).fetchone()
        self.assertEqual(row, (self.result.graph, True))

    def test_relational_copy_has_the_schema_and_no_age(self) -> None:
        with psycopg.connect(self.result.app_url) as conn:
            row = conn.execute(
                'SELECT current_user, current_database(),'
                "       to_regclass('public.tenants') IS NOT NULL,"
                '       EXISTS (SELECT FROM pg_extension'
                "                WHERE extname = 'age')"
            ).fetchone()
        self.assertEqual(
            row, ('imbi_app', self.result.relational, True, False)
        )

    def test_each_url_logs_in_as_its_role(self) -> None:
        for url, role in (
            (self.result.admin_url, 'imbi_admin'),
            (self.result.maintenance_url, 'imbi_maintenance'),
            (self.result.factory_url, 'postgres'),
        ):
            with self.subTest(role=role), psycopg.connect(url) as conn:
                row = conn.execute(
                    'SELECT current_user, current_database()'
                ).fetchone()
                self.assertEqual(row, (role, self.result.relational))


class ProjectsIndexConditionTestCase(unittest.TestCase):
    """RLS on ``projects`` is an index condition, not a filter.

    The policy compares ``organization_id`` with an InitPlan, so the
    planner can use it as an index condition (review G3). If a change
    makes it a filter, every organization query reads all organizations.
    """

    def setUp(self) -> None:
        result = databases.isolated_database()
        self.app_url = result.app_url
        with factories.connect() as conn:
            self.organization = factories.organization(conn)
            factories.project(conn, organization_id=self.organization['id'])
            factories.project(conn)

    def _in_organization(self, conn: psycopg.Connection[typing.Any]) -> None:
        conn.execute(
            "SELECT set_config('imbi.organization_id', %s, true)",
            [self.organization['id']],
        )

    def test_imbi_app_sees_only_its_organization(self) -> None:
        with psycopg.connect(self.app_url) as conn:
            self._in_organization(conn)
            row = conn.execute(
                'SELECT count(*), count(DISTINCT organization_id)'
                '  FROM public.projects'
            ).fetchone()
        self.assertEqual(row, (1, 1))

    def test_organization_is_an_index_condition(self) -> None:
        with psycopg.connect(self.app_url, row_factory=rows.tuple_row) as conn:
            self._in_organization(conn)
            conn.execute('SET LOCAL enable_seqscan = off')
            row = conn.execute(
                'EXPLAIN (FORMAT JSON)'
                ' SELECT id, name FROM public.projects'
                '  WHERE archived_at IS NULL ORDER BY name'
            ).fetchone()
        self.assertIsNotNone(row)
        nodes = list(_nodes(row[0][0]['Plan']))  # type: ignore[index]
        conditions = [node.get('Index Cond', '') for node in nodes]
        filters = [node.get('Filter', '') for node in nodes]
        self.assertTrue(
            any('organization_id' in cond for cond in conditions), nodes
        )
        self.assertFalse(
            any('organization_id' in cond for cond in filters), nodes
        )
