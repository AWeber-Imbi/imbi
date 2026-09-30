import datetime
import io
import json
import unittest

import psycopg

from imbi.common.db.etl import catalog, mapping, runner
from libraries.common.tests.db.etl import fakes

NOW = datetime.datetime(2026, 9, 30, 12, 0, tzinfo=datetime.UTC)


class RunnerTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.source, self.target = await fakes.target(self)

    async def test_loads_in_foreign_key_order(self) -> None:
        registry = fakes.registry(
            parents=[fakes.parent('p1', data={'a': [1]}, labels=['x'])],
            children=[{'id': 'c1', 'parent_id': 'p1', 'created_at': NOW}],
            nodes=[{'id': 'n1', 'parent_id': None}],
        )
        result = await runner.run(
            self.source, self.target, registry=registry, pending=()
        )
        self.assertEqual(result.order, ['node', 'parent', 'child'])
        self.assertEqual(result.tables['parent'].rows, 1)
        self.assertEqual(
            await fakes.rows(self.target, 'SELECT * FROM parent'),
            [('p1', 'p1', {'a': [1]}, ['x'])],
        )
        self.assertEqual(
            await fakes.rows(self.target, 'SELECT * FROM child'),
            [('c1', 'p1', NOW)],
        )

    async def test_parents_first(self) -> None:
        registry = fakes.registry(
            nodes=[
                {'id': 'c', 'parent_id': 'b'},
                {'id': 'b', 'parent_id': 'a'},
                {'id': 'a', 'parent_id': None},
            ]
        )
        await runner.run(
            self.source, self.target, registry=registry, pending=()
        )
        self.assertEqual(
            await fakes.rows(self.target, 'SELECT id FROM node ORDER BY id'),
            [('a',), ('b',), ('c',)],
        )

    async def test_row_cycle(self) -> None:
        registry = fakes.registry(
            nodes=[
                {'id': 'a', 'parent_id': 'b'},
                {'id': 'b', 'parent_id': 'a'},
            ]
        )
        with self.assertRaisesRegex(mapping.EtlError, 'cycle'):
            await runner.run(
                self.source, self.target, registry=registry, pending=()
            )

    async def test_truncates_earlier_rows(self) -> None:
        await self.target.execute(
            "INSERT INTO parent (id, name) VALUES ('old', 'old')"
        )
        await self.target.execute("INSERT INTO node VALUES ('old', NULL)")
        await self.target.commit()
        registry = fakes.registry(parents=[fakes.parent('new')])
        await runner.run(
            self.source, self.target, registry=registry, pending=()
        )
        self.assertEqual(
            await fakes.rows(self.target, 'SELECT id FROM parent'),
            [('new',)],
        )
        self.assertEqual(
            await fakes.rows(self.target, 'SELECT id FROM node'), []
        )

    async def test_skips_and_changes(self) -> None:
        registry = fakes.registry(
            parents=[
                fakes.parent('p1'),
                mapping.Skip('no-organization', 'p2'),
                mapping.Change('E35', 'p1', 'icon not loaded'),
            ]
        )
        result = await runner.run(
            self.source, self.target, registry=registry, pending=()
        )
        self.assertEqual(
            result.tables['parent'].skipped, {'no-organization': ['p2']}
        )
        self.assertEqual(result.tables['parent'].changed, {'E35': 1})

    async def test_pending_refused(self) -> None:
        registry = fakes.registry()
        del registry['node']
        with self.assertRaisesRegex(mapping.EtlError, 'no mapping yet'):
            await runner.run(
                self.source, self.target, registry=registry, pending=['node']
            )

    async def test_pending_truncated_and_empty(self) -> None:
        await self.target.execute("INSERT INTO node VALUES ('old', NULL)")
        await self.target.commit()
        registry = fakes.registry()
        del registry['node']
        result = await runner.run(
            self.source,
            self.target,
            registry=registry,
            pending=['node'],
            allow_pending=True,
        )
        self.assertEqual(result.pending, ('node',))
        self.assertNotIn('node', result.tables)
        self.assertEqual(
            await fakes.rows(self.target, 'SELECT id FROM node'), []
        )

    async def test_uncovered_table_refused(self) -> None:
        registry = fakes.registry()
        del registry['node']
        with self.assertRaisesRegex(mapping.EtlError, 'no mapping: node'):
            await runner.run(
                self.source, self.target, registry=registry, pending=()
            )

    async def test_mapped_and_pending_refused(self) -> None:
        with self.assertRaisesRegex(mapping.EtlError, 'both mapped'):
            await runner.run(
                self.source,
                self.target,
                registry=fakes.registry(),
                pending=['node'],
                allow_pending=True,
            )

    async def test_absent_table_refused(self) -> None:
        with self.assertRaisesRegex(mapping.EtlError, 'not in the target'):
            await runner.run(
                self.source,
                self.target,
                registry=fakes.registry(),
                pending=['missing'],
                allow_pending=True,
            )

    async def test_row_with_other_columns(self) -> None:
        registry = fakes.registry(parents=[{'id': 'p1', 'name': 'x'}])
        with self.assertRaisesRegex(mapping.EtlError, 'has the columns'):
            await runner.run(
                self.source, self.target, registry=registry, pending=()
            )

    async def test_unknown_column(self) -> None:
        registry = fakes.registry()
        registry['node'] = fakes.Static(
            'node', ('id', 'other'), [{'id': 'n', 'other': 1}]
        )
        with self.assertRaisesRegex(mapping.EtlError, 'no such columns'):
            await runner.run(
                self.source, self.target, registry=registry, pending=()
            )

    async def test_failure_rolls_back(self) -> None:
        await self.target.execute(
            "INSERT INTO parent (id, name) VALUES ('old', 'old')"
        )
        await self.target.commit()
        registry = fakes.registry(
            children=[{'id': 'c1', 'parent_id': 'nobody', 'created_at': None}]
        )
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            await runner.run(
                self.source, self.target, registry=registry, pending=()
            )
        await self.target.rollback()
        self.assertEqual(
            await fakes.rows(self.target, 'SELECT id FROM parent'),
            [('old',)],
        )

    async def test_truncate_has_no_cascade(self) -> None:
        await self.target.execute(
            'CREATE SCHEMA other;'
            ' CREATE TABLE other.ref (id text REFERENCES public.parent)'
        )
        await self.target.commit()
        with self.assertRaises(psycopg.errors.FeatureNotSupported):
            await runner.run(
                self.source,
                self.target,
                registry=fakes.registry(),
                pending=(),
            )

    async def test_dry_run(self) -> None:
        stream = io.StringIO()
        registry = fakes.registry(
            parents=[fakes.parent('p1'), mapping.Skip('gone', 'p2')],
            children=[
                {'id': 'c1', 'parent_id': 'p1', 'created_at': NOW},
                mapping.Change('E1', 'c1', 'changed'),
            ],
        )
        result = await runner.run(
            self.source,
            self.target,
            registry=registry,
            pending=(),
            dry_run=stream,
        )
        self.assertTrue(result.dry_run)
        lines = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual(
            [(line['kind'], line['table']) for line in lines],
            [
                ('row', 'parent'),
                ('skip', 'parent'),
                ('row', 'child'),
                ('change', 'child'),
            ],
        )
        self.assertEqual(lines[2]['row']['created_at'], NOW.isoformat())
        self.assertEqual(
            await fakes.rows(self.target, 'SELECT id FROM parent'), []
        )

    async def test_source_in_transaction(self) -> None:
        await self.source.execute('SELECT 1')
        with self.assertRaisesRegex(mapping.EtlError, 'in a transaction'):
            await runner.run(
                self.source,
                self.target,
                registry=fakes.registry(),
                pending=(),
            )


class LoadOrderTestCase(unittest.TestCase):
    @staticmethod
    def _table(name: str, *refs: str) -> catalog.Table:
        return catalog.Table(
            name=name,
            columns=('id',),
            not_null=('id',),
            json_columns=frozenset(),
            foreign_keys=tuple(
                catalog.ForeignKey(f'{name}_{ref}', ('x',), ref, ('id',))
                for ref in refs
            ),
            unique_keys=(),
        )

    def test_cycle(self) -> None:
        tables = {
            'a': self._table('a', 'b'),
            'b': self._table('b', 'a'),
        }
        with self.assertRaisesRegex(mapping.EtlError, 'cycle'):
            catalog.load_order(tables, ['a', 'b'])

    def test_outside_reference_ignored(self) -> None:
        tables = {
            'a': self._table('a', 'z'),
            'b': self._table('b', 'a', 'b'),
        }
        self.assertEqual(catalog.load_order(tables, ['b', 'a']), ['a', 'b'])

    def test_join_table(self) -> None:
        table = catalog.Table(
            name='pair',
            columns=('a_id', 'b_id'),
            not_null=('a_id', 'b_id'),
            json_columns=frozenset(),
            foreign_keys=(
                catalog.ForeignKey('fa', ('a_id',), 'a', ('id',)),
                catalog.ForeignKey('fb', ('b_id',), 'b', ('id',)),
            ),
            unique_keys=(
                catalog.UniqueKey('pk', ('a_id', 'b_id'), None, False, True),
            ),
        )
        self.assertTrue(table.is_join_table)
        self.assertFalse(self._table('a', 'b').is_join_table)


class ParentsFirstTestCase(unittest.TestCase):
    """The row order of a self-referencing table, without a database."""

    table = catalog.Table(
        name='roles',
        columns=('organization_id', 'id', 'parent_id'),
        not_null=('organization_id', 'id'),
        json_columns=frozenset(),
        foreign_keys=(
            catalog.ForeignKey(
                'roles_parent',
                ('organization_id', 'parent_id'),
                'roles',
                ('organization_id', 'id'),
            ),
        ),
        unique_keys=(),
    )

    @staticmethod
    def _row(org: str, row_id: str, parent: str | None) -> mapping.Row:
        return {'organization_id': org, 'id': row_id, 'parent_id': parent}

    def _order(self, rows: list[mapping.Row]) -> list[str]:
        return [
            f'{r["organization_id"]}/{r["id"]}'
            for r in runner._parents_first(self.table, rows)
        ]

    def test_parents_before_children(self) -> None:
        rows = [
            self._row('o', 'grandchild', 'child'),
            self._row('o', 'child', 'root'),
            self._row('o', 'other', None),
            self._row('o', 'root', None),
        ]
        self.assertEqual(
            self._order(rows), ['o/other', 'o/root', 'o/child', 'o/grandchild']
        )

    def test_parent_in_another_organization_is_no_dependency(self) -> None:
        rows = [
            self._row('o1', 'child', 'root'),
            self._row('o2', 'root', None),
        ]
        self.assertEqual(self._order(rows), ['o1/child', 'o2/root'])

    def test_self_parent_is_no_dependency(self) -> None:
        self.assertEqual(self._order([self._row('o', 'a', 'a')]), ['o/a'])

    def test_no_self_reference_keeps_order(self) -> None:
        rows = [{'id': 'b'}, {'id': 'a'}]
        table = LoadOrderTestCase._table('plain')
        self.assertIs(runner._parents_first(table, rows), rows)
