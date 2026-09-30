import unittest

from imbi.common.db.etl import mapping, reconcile, runner, schemata
from libraries.common.tests.db.etl import fakes

PAIR = """
CREATE TABLE pair (
    parent_id text REFERENCES parent,
    node_id text REFERENCES node,
    PRIMARY KEY (parent_id, node_id)
);
CREATE TABLE uniq (
    id text PRIMARY KEY,
    a text,
    b text,
    deleted boolean NOT NULL DEFAULT false,
    UNIQUE (a, b)
);
CREATE UNIQUE INDEX uniq_live ON uniq (a) WHERE NOT deleted;
CREATE UNIQUE INDEX uniq_lower ON uniq (lower(b));
CREATE TABLE loose (id text PRIMARY KEY, name text);
"""


class ReconcileTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.source, self.target = await fakes.target(self)

    async def _load(
        self, registry: dict[str, mapping.Mapping]
    ) -> reconcile.Report:
        await runner.run(
            self.source, self.target, registry=registry, pending=()
        )
        report = await reconcile.reconcile(
            self.source,
            self.target,
            schema_files=fakes.SCHEMA_FILES,
            registry=registry,
            pending=(),
        )
        await self.target.rollback()
        return report

    async def test_clean(self) -> None:
        registry = fakes.registry(nodes=[{'id': 'n1', 'parent_id': None}])
        registry['parent'] = fakes.Static(
            'parent',
            ('id', 'name', 'data', 'labels'),
            [
                fakes.parent('p1', data={'a': 1}),
                fakes.parent('p2', data=[1]),
                mapping.Skip('gone', 'p3'),
            ],
            mapping.Expected(
                count=2,
                skipped={'gone': frozenset({'p3'}), 'none': frozenset()},
            ),
        )
        report = await self._load(registry)
        self.assertTrue(report.clean, report.as_dict())
        parent = report.tables['parent']
        self.assertEqual(parent.target_count, 2)
        self.assertEqual(parent.skipped, {'gone': ['p3']})
        self.assertEqual(parent.orphans, {})
        self.assertEqual(
            report.tables['child'].orphans, {'child_parent_id_fkey': 0}
        )
        self.assertEqual(len(parent.checksum), 32)
        self.assertTrue(report.as_dict()['clean'])

    async def test_count_mismatch(self) -> None:
        registry = fakes.registry(parents=[fakes.parent('p1')])
        registry['parent'] = fakes.Static(
            'parent',
            ('id', 'name', 'data', 'labels'),
            [fakes.parent('p1')],
            mapping.Expected(count=2),
        )
        report = await self._load(registry)
        self.assertFalse(report.clean)
        self.assertEqual(
            report.tables['parent'].mismatches,
            ['count: target 1, expected 2'],
        )

    async def test_skips_differ(self) -> None:
        registry = fakes.registry()
        registry['parent'] = fakes.Static(
            'parent',
            ('id', 'name', 'data', 'labels'),
            [fakes.parent('p1'), mapping.Skip('gone', 'p1')],
            mapping.Expected(count=1),
        )
        report = await self._load(registry)
        self.assertEqual(
            report.tables['parent'].mismatches,
            [
                'skipped rows differ from the expected skips',
                'skipped ids in the target: 1',
            ],
        )

    async def test_json_string(self) -> None:
        registry = fakes.registry(parents=[fakes.parent('p1', data='text')])
        report = await self._load(registry)
        self.assertEqual(
            report.tables['parent'].json_not_container, {'data': 1}
        )
        self.assertFalse(report.clean)

    async def test_only(self) -> None:
        report = await self._load(fakes.registry())
        self.assertEqual(sorted(report.tables), ['child', 'node', 'parent'])
        report = await reconcile.reconcile(
            self.source,
            self.target,
            schema_files=fakes.SCHEMA_FILES,
            registry=fakes.registry(),
            pending=['x'],
            only=['node'],
        )
        self.assertEqual(sorted(report.tables), ['node'])
        self.assertEqual(report.pending, ['x'])

    async def test_unknown_tables(self) -> None:
        with self.assertRaisesRegex(mapping.EtlError, 'no mapping: x'):
            await reconcile.reconcile(
                self.source,
                self.target,
                schema_files=fakes.SCHEMA_FILES,
                registry=fakes.registry(),
                pending=(),
                only=['x'],
            )
        registry = fakes.registry()
        registry['x'] = fakes.Static('x', ('id',), [])
        with self.assertRaisesRegex(mapping.EtlError, 'not in the target'):
            await reconcile.reconcile(
                self.source,
                self.target,
                schema_files=fakes.SCHEMA_FILES,
                registry=registry,
                pending=(),
            )


class ConstraintChecksTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.source, self.target = await fakes.target(self)
        await self.target.execute(PAIR)
        await self.target.commit()
        self.registry = fakes.registry(
            parents=[fakes.parent('p1'), fakes.parent('p2')],
            nodes=[
                {'id': 'n1', 'parent_id': None},
                {'id': 'n2', 'parent_id': None},
            ],
        )
        self.registry['uniq'] = fakes.Static(
            'uniq',
            ('id', 'a', 'b', 'deleted'),
            [
                {'id': 'u1', 'a': 'x', 'b': None, 'deleted': False},
                {'id': 'u2', 'a': 'x', 'b': None, 'deleted': True},
            ],
        )
        self.registry['loose'] = fakes.Static('loose', ('id', 'name'), [])
        self.pairs = [
            {'parent_id': 'p1', 'node_id': 'n1'},
            {'parent_id': 'p1', 'node_id': 'n2'},
        ]

    async def _report(
        self, cardinality: mapping.Cardinality | None
    ) -> reconcile.TableReport:
        self.registry['pair'] = fakes.Static(
            'pair',
            ('parent_id', 'node_id'),
            self.pairs,
            mapping.Expected(count=2, cardinality=cardinality),
        )
        await runner.run(
            self.source, self.target, registry=self.registry, pending=()
        )
        report = await reconcile.reconcile(
            self.source,
            self.target,
            schema_files=fakes.SCHEMA_FILES,
            registry=self.registry,
            pending=(),
        )
        self.assertTrue(report.tables['uniq'].clean, report.as_dict())
        self.assertEqual(
            report.tables['uniq'].unique_keys,
            {
                'primary key (id)': 'schema-enforced',
                'unique (a, b)': 'schema-enforced',
                'uniq_a_b_named': 'schema-enforced',
                'uniq_live': 'schema-enforced',
                'uniq_lower': 'schema-enforced',
            },
        )
        self.assertEqual(
            report.tables['uniq'].not_null,
            {'id': 'schema-enforced', 'deleted': 'schema-enforced'},
        )
        return report.tables['pair']

    async def test_join_table_needs_cardinality(self) -> None:
        pair = await self._report(None)
        self.assertEqual(
            pair.mismatches, ['join table with no expected cardinality']
        )

    async def test_cardinality_clean(self) -> None:
        pair = await self._report(
            mapping.Cardinality(('parent_id',), {('p1',): 2, ('p2',): 0})
        )
        self.assertTrue(pair.clean, pair.mismatches)
        self.assertEqual(pair.cardinality, {})

    async def test_cardinality_differs(self) -> None:
        pair = await self._report(
            mapping.Cardinality(('parent_id',), {('p1',): 1, ('p2',): 1})
        )
        self.assertEqual(pair.cardinality, {'p1': 1, 'p2': -1})
        self.assertEqual(
            pair.mismatches,
            ['cardinality of (parent_id) differs for 2 keys'],
        )

    async def test_orphans(self) -> None:
        await self._report(None)
        await self.target.execute("SET session_replication_role = 'replica'")
        await self.target.execute("INSERT INTO pair VALUES ('p9', 'n1')")
        await self.target.commit()
        report = await reconcile.reconcile(
            self.source,
            self.target,
            schema_files=fakes.SCHEMA_FILES,
            registry=self.registry,
            pending=(),
            only=['pair'],
        )
        self.assertEqual(
            report.tables['pair'].orphans,
            {'pair_node_id_fkey': 0, 'pair_parent_id_fkey': 1},
        )

    async def test_declared_constraints_missing(self) -> None:
        await self._report(None)
        report = await reconcile.reconcile(
            self.source,
            self.target,
            schema_files=fakes.SCHEMA_FILES,
            registry=self.registry,
            pending=(),
            only=['loose'],
        )
        loose = report.tables['loose']
        self.assertEqual(
            loose.mismatches,
            [
                'NOT NULL column name missing from the target',
                'unique (name) missing from the target',
                'loose_lower missing from the target',
            ],
        )
        self.assertEqual(
            loose.unique_keys['primary key (id)'], 'schema-enforced'
        )

    async def test_no_schema_file(self) -> None:
        with self.assertRaisesRegex(mapping.EtlError, 'No schema file'):
            await reconcile.reconcile(
                self.source,
                self.target,
                schema_files=fakes.SCHEMA_FILES / 'nowhere',
                registry=self.registry,
                pending=(),
                only=['node'],
            )


class KeysTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.source, self.target = await fakes.target(self)

    async def test_missing_and_extra_keys(self) -> None:
        registry = fakes.registry(
            parents=[fakes.parent('p1'), fakes.parent('p2')]
        )
        await runner.run(
            self.source, self.target, registry=registry, pending=()
        )
        await self.target.execute("DELETE FROM parent WHERE id = 'p2'")
        await self.target.execute(
            "INSERT INTO parent (id, name) VALUES ('px', 'x')"
        )
        await self.target.commit()
        report = await reconcile.reconcile(
            self.source,
            self.target,
            schema_files=fakes.SCHEMA_FILES,
            registry=registry,
            pending=(),
            only=['parent'],
        )
        parent = report.tables['parent']
        self.assertEqual(parent.missing_keys, ['p2'])
        self.assertEqual(parent.extra_keys, ['px'])
        self.assertEqual(
            parent.mismatches,
            [
                'keys missing from the target: 1',
                'keys in the target that rows() does not give: 1',
            ],
        )

    async def test_key_not_in_columns(self) -> None:
        registry = fakes.registry()
        registry['node'] = fakes.Static('node', ('parent_id',), [])
        report = await reconcile.reconcile(
            self.source,
            self.target,
            schema_files=fakes.SCHEMA_FILES,
            registry=registry,
            pending=(),
            only=['node'],
        )
        self.assertEqual(
            report.tables['node'].mismatches,
            ['primary key not in the mapping columns: cannot compare keys'],
        )


class NormalizeTestCase(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(
            schemata.normalize('((embedding)::vector(384))'),
            'embedding)::vector(384',
        )
        self.assertEqual(schemata.normalize('lower(email)'), 'lower(email)')
        self.assertEqual(schemata.normalize('( a )'), 'a')
