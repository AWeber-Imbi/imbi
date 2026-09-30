"""Each table of the relational schema has a builder that inserts a row.

A new table in ``schemata/tables/public/`` without a builder in
``imbi.common.testing.factories`` fails ``test_every_table_has_a_builder``.
"""

import pathlib
import unittest

from psycopg import sql

from imbi.common.testing import databases, factories

TABLES = pathlib.Path(__file__).parents[4] / 'schemata' / 'tables' / 'public'


class FactoryTestCase(unittest.TestCase):
    conn: factories.Connection

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        databases.isolated_database()
        cls.conn = factories.connect()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()
        super().tearDownClass()

    def _primary_key(self, table: str) -> list[str]:
        rows = self.conn.execute(
            'SELECT a.attname'
            '  FROM pg_index AS i'
            '  JOIN pg_attribute AS a'
            '    ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)'
            ' WHERE i.indrelid = %s::regclass AND i.indisprimary',
            [f'public.{table}'],
        ).fetchall()
        return [row['attname'] for row in rows]

    def _exists(self, table: str, row: factories.Row) -> bool:
        key = self._primary_key(table)
        found = self.conn.execute(
            sql.SQL(
                'SELECT count(*) AS found FROM {table} WHERE {cond}'
            ).format(
                table=sql.Identifier('public', table),
                cond=sql.SQL(' AND ').join(
                    sql.SQL('{} = %s').format(sql.Identifier(column))
                    for column in key
                ),
            ),
            [row[column] for column in key],
        ).fetchone()
        return found is not None and found['found'] == 1

    def test_every_table_has_a_builder(self) -> None:
        tables = {path.stem for path in TABLES.glob('*.yaml')}
        self.assertTrue(tables)
        self.assertEqual(sorted(tables - factories.BUILDERS.keys()), [])
        self.assertEqual(sorted(factories.BUILDERS.keys() - tables), [])

    def test_the_template_has_every_table(self) -> None:
        rows = self.conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
        self.assertEqual(
            {row['tablename'] for row in rows},
            {path.stem for path in TABLES.glob('*.yaml')},
        )

    def test_each_builder_inserts_a_valid_row(self) -> None:
        for table, builder in sorted(factories.BUILDERS.items()):
            with self.subTest(table=table):
                first = builder(self.conn)
                second = builder(self.conn)
                self.assertTrue(self._exists(table, second))
                if table != 'local_auth_settings':
                    self.assertTrue(self._exists(table, first))
                    key = self._primary_key(table)
                    self.assertNotEqual(
                        [first[column] for column in key],
                        [second[column] for column in key],
                    )

    def test_parents_share_the_organization(self) -> None:
        org = factories.organization(self.conn)
        project = factories.project(self.conn, organization_id=org['id'])
        team = factories.get(self.conn, 'teams', project['team_id'])
        self.assertEqual(team['organization_id'], org['id'])

        release = factories.release(self.conn, project_id=project['id'])
        self.assertEqual(release['organization_id'], org['id'])

        deployment = factories.deployment(self.conn, release_id=release['id'])
        self.assertEqual(deployment['organization_id'], org['id'])
        environment = factories.get(
            self.conn, 'environments', deployment['environment_id']
        )
        self.assertEqual(environment['organization_id'], org['id'])

    def test_values_replace_the_defaults(self) -> None:
        project = factories.project(
            self.conn, name='Billing', links={'docs': 'https://example.com'}
        )
        self.assertEqual(project['name'], 'Billing')
        self.assertEqual(project['links'], {'docs': 'https://example.com'})

    def test_instance_integration(self) -> None:
        integration = factories.integration(
            self.conn, organization_id=None, used_as_login=True
        )
        self.assertIsNone(integration['organization_id'])

    def test_a_builder_is_registered_once(self) -> None:
        with self.assertRaises(ValueError):
            factories.builds('projects')(factories.project)

    def test_get_raises_for_a_missing_row(self) -> None:
        with self.assertRaises(LookupError):
            factories.get(self.conn, 'projects', 'missing')
