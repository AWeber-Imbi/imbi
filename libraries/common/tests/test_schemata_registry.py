"""Check schemata/registry.toml against the table files of schemata/.

See meta:docs/age-to-relational-implementation-plan.md WP0.4, step 7.
"""

import pathlib
import tomllib
import typing
import unittest

import yaml

SCHEMATA = pathlib.Path(__file__).resolve().parents[3] / 'schemata'
TABLES = SCHEMATA / 'tables' / 'public'
SCOPES = frozenset({'organization', 'tenancy', 'instance', 'catalog'})
RLS_FORCED = {'enabled': True, 'forced': True}


def _tables() -> dict[str, dict[str, typing.Any]]:
    return {
        f'public.{path.stem}': yaml.safe_load(path.read_text())
        for path in sorted(TABLES.glob('*.yaml'))
    }


def _registry() -> dict[str, str]:
    registry = tomllib.loads((SCHEMATA / 'registry.toml').read_text())
    return {
        name: entry.get('scope')
        for name, entry in registry.get('tables', {}).items()
    }


class SchemataRegistryTestCase(unittest.TestCase):
    """Each table has a scope, and its row-level security fits it."""

    def setUp(self) -> None:
        self.tables = _tables()
        self.registry = _registry()

    def test_tables_exist(self) -> None:
        self.assertGreater(len(self.tables), 0, f'no tables in {TABLES}')

    def test_every_table_has_an_entry(self) -> None:
        self.assertEqual(
            sorted(set(self.tables) - set(self.registry)),
            [],
            'tables with no entry in schemata/registry.toml',
        )

    def test_every_entry_has_a_table(self) -> None:
        self.assertEqual(
            sorted(set(self.registry) - set(self.tables)),
            [],
            'registry.toml entries with no file in schemata/tables/public',
        )

    def test_every_scope_is_known(self) -> None:
        for name, scope in self.registry.items():
            with self.subTest(table=name):
                self.assertIn(scope, SCOPES)

    def test_organization_tables_are_isolated(self) -> None:
        names = [
            name
            for name, scope in self.registry.items()
            if scope == 'organization'
        ] + ['public.organizations']
        for name in names:
            table = self.tables.get(name)
            if table is None:
                continue
            with self.subTest(table=name):
                columns = {
                    column['name'] for column in table.get('columns', [])
                }
                if name != 'public.organizations':
                    self.assertIn('organization_id', columns)
                self.assertEqual(table.get('row_level_security'), RLS_FORCED)
                self.assertGreater(len(table.get('policies') or []), 0)

    def test_other_tables_have_no_row_level_security(self) -> None:
        for name, scope in self.registry.items():
            if scope == 'organization' or name == 'public.organizations':
                continue
            table = self.tables.get(name)
            if table is None:
                continue
            with self.subTest(table=name, scope=scope):
                rls = table.get('row_level_security') or {}
                self.assertFalse(rls.get('enabled', False))
                self.assertFalse(rls.get('forced', False))
                self.assertEqual(table.get('policies') or [], [])
