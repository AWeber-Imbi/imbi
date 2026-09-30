"""Each table in ``schemata/tables/public/`` has a mapping module."""

import os
import pathlib
import types
import unittest
from unittest import mock

from imbi.common.db.etl import mapping, mappings
from imbi.common.db.etl.mappings import _pending
from libraries.common.tests.db.etl import fakes

TABLES = pathlib.Path(__file__).resolve().parents[5] / 'schemata/tables/public'


class RegistryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tables = {path.stem for path in TABLES.glob('*.yaml')}
        self.mapped = set(mappings.discover())
        self.pending = set(mappings.pending())

    def test_schema_tables_found(self) -> None:
        self.assertEqual(len(self.tables), 74)

    def test_every_table_has_a_mapping(self) -> None:
        missing = sorted(self.tables - self.mapped - self.pending)
        self.assertEqual(
            missing,
            [],
            'Tables with no mapping module and not in'
            f' mappings/_pending.py: {missing}',
        )

    def test_no_mapping_without_a_table(self) -> None:
        extra = sorted(self.mapped - self.tables)
        self.assertEqual(extra, [], f'Mappings with no table: {extra}')

    def test_no_pending_table_without_a_table(self) -> None:
        extra = sorted(self.pending - self.tables)
        self.assertEqual(
            extra, [], f'Pending tables not in schemata/: {extra}'
        )

    @unittest.skipUnless(
        os.environ.get('IMBI_ETL_REQUIRE_COMPLETE') == '1',
        'The Wave 2 exit runs this with IMBI_ETL_REQUIRE_COMPLETE=1',
    )
    def test_nothing_pending(self) -> None:
        self.assertEqual(
            mappings.pending(),
            (),
            'Tables in mappings/_pending.py, with no mapping module yet',
        )

    def test_mapped_tables_are_not_pending(self) -> None:
        both = {
            agent: sorted(set(tables) & self.mapped)
            for agent, tables in _pending.PENDING.items()
            if set(tables) & self.mapped
        }
        self.assertEqual(
            both,
            {},
            f'Delete these from mappings/_pending.py: {both}',
        )

    def test_pending_tables_listed_once(self) -> None:
        listed = [t for tables in _pending.PENDING.values() for t in tables]
        self.assertEqual(len(listed), len(set(listed)))

    def test_pending_agents(self) -> None:
        self.assertLessEqual(set(_pending.PENDING), set('KLMNOPQRSTU'))


class DiscoverTestCase(unittest.TestCase):
    def _discover(self, value: object) -> None:
        module = types.ModuleType('fake')
        module.MAPPING = value  # type: ignore[attr-defined]
        with mock.patch('importlib.import_module', return_value=module):
            mappings.discover()

    def test_module_without_mapping(self) -> None:
        with self.assertRaisesRegex(mapping.EtlError, 'no MAPPING'):
            self._discover(None)

    def test_module_name_must_be_the_table(self) -> None:
        with self.assertRaisesRegex(mapping.EtlError, 'module name'):
            self._discover(fakes.Static('other', ('id',), []))
