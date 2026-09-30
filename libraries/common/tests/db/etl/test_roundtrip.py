"""Round trip: an AGE graph into the relational schema, and back out.

The source is a real AGE graph. The target is a copy of the relational
template (``schemata/`` deployed, owners set), and the ETL connects as
``imbi_maintenance``. The test skips when the template is missing.
"""

import asyncio
import datetime
import json
import pathlib
import tempfile
import typing
import unittest

import psycopg
from typer import testing

from imbi.common.db.etl import cli, ids, reconcile, runner
from libraries.common.tests.db.etl import support

TABLES = ('tenants', 'organizations', 'tags')

GRAPH = (
    "CREATE (:Organization {id: 'o1', name: 'One', slug: 'one',"
    " description: 'First', created_at: '2026-01-01T00:00:00+00:00',"
    " updated_at: '2026-01-02T00:00:00+00:00',"
    " tag_formats: [{label: 'semver', pattern: '^v[0-9]+'}],"
    " previous_slugs: ['uno'], document_analytics_identities: 'enabled',"
    " region: 'us'})",
    "CREATE (:Organization {id: 'o2', name: 'Two', slug: 'two',"
    " created_at: '2026-03-01T00:00:00+00:00',"
    ' tag_formats: \'[{"label": "any", "pattern": ".*"}]\'})',
    "MATCH (o:Organization {id: 'o1'})"
    " CREATE (:Tag {id: 't1', name: 'Alpha', slug: 'alpha',"
    " created_at: '2026-01-05T00:00:00+00:00'})-[:BELONGS_TO]->(o)",
    "MATCH (o:Organization {id: 'o2'})"
    " CREATE (:Tag {id: 't2', name: 'Beta', slug: 'beta', icon: 'star',"
    " created_at: '2026-03-05T00:00:00+00:00'})-[:BELONGS_TO]->(o)",
    "CREATE (:Tag {id: 't3', name: 'Orphan', slug: 'orphan',"
    " created_at: '2026-03-06T00:00:00+00:00'})",
)


async def _checksums(url: str) -> dict[str, str]:
    async with await psycopg.AsyncConnection.connect(url) as conn:
        return {t: await reconcile.table_checksum(conn, t) for t in TABLES}


class _Databases:
    """The target and the AGE source, shared by the tests of this module.

    A ``DROP DATABASE`` waits for a checkpoint, which takes seconds for a
    copy of the full schema. Each test starts with a run, which
    truncates the tables, so the tests can share one pair.

    """

    target: str | None = None
    source: str | None = None


def setUpModule() -> None:
    asyncio.run(_create())


def tearDownModule() -> None:
    asyncio.run(_drop())


async def _create() -> None:
    _Databases.target = await support.relational_database()
    try:
        _Databases.source = await support.create_database('source')
        async with await psycopg.AsyncConnection.connect(
            support.url(_Databases.source)
        ) as conn:
            await support.age_graph(conn, 'imbi', *GRAPH)
    except BaseException:
        await _drop()
        raise


async def _drop() -> None:
    for name in (_Databases.source, _Databases.target):
        if name is not None:
            await support.drop_database(name)


def _urls() -> tuple[str, str]:
    """Return the source URL and the imbi_maintenance target URL."""
    assert _Databases.source is not None
    assert _Databases.target is not None
    return (
        support.url(_Databases.source),
        support.maintenance_url(_Databases.target),
    )


class RoundTripTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.source_url, self.target_url = _urls()

    async def _run(self) -> runner.RunResult:
        async with (
            await psycopg.AsyncConnection.connect(self.source_url) as source,
            await psycopg.AsyncConnection.connect(self.target_url) as target,
        ):
            return await runner.run(source, target, allow_pending=True)

    async def _reconcile(self) -> reconcile.Report:
        async with (
            await psycopg.AsyncConnection.connect(self.source_url) as source,
            await psycopg.AsyncConnection.connect(self.target_url) as target,
        ):
            return await reconcile.reconcile(source, target, only=TABLES)

    async def _rows(self, query: str) -> list[tuple[typing.Any, ...]]:
        async with await psycopg.AsyncConnection.connect(
            self.target_url
        ) as conn:
            cursor = await conn.execute(query)
            return await cursor.fetchall()

    async def test_round_trip(self) -> None:
        result = await self._run()
        self.assertLess(
            result.order.index('tenants'), result.order.index('organizations')
        )
        self.assertLess(
            result.order.index('organizations'), result.order.index('tags')
        )
        self.assertEqual(
            {t: result.tables[t].rows for t in TABLES},
            {'tenants': 1, 'organizations': 2, 'tags': 2},
        )
        tenant_id = ids.derive_id('tenants', 'default')
        self.assertEqual(
            await self._rows('SELECT id, slug, created_at FROM tenants'),
            [
                (
                    tenant_id,
                    'default',
                    datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
                )
            ],
        )
        self.assertEqual(
            await self._rows(
                'SELECT id, tenant_id, slug, description, previous_slugs,'
                ' tag_formats, document_analytics_identities, attributes,'
                ' updated_at FROM organizations ORDER BY id'
            ),
            [
                (
                    'o1',
                    tenant_id,
                    'one',
                    'First',
                    ['uno'],
                    [{'label': 'semver', 'pattern': '^v[0-9]+'}],
                    'enabled',
                    {'region': 'us'},
                    datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC),
                ),
                (
                    'o2',
                    tenant_id,
                    'two',
                    None,
                    [],
                    [{'label': 'any', 'pattern': '.*'}],
                    'authors_only',
                    {},
                    None,
                ),
            ],
        )
        self.assertEqual(
            await self._rows(
                'SELECT id, organization_id, slug FROM tags ORDER BY id'
            ),
            [('t1', 'o1', 'alpha'), ('t2', 'o2', 'beta')],
        )
        self.assertEqual(
            result.tables['tags'].skipped, {'no-organization': ['t3']}
        )
        self.assertEqual(result.tables['tags'].changed, {'E35': 1})

        report = await self._reconcile()
        self.assertTrue(report.clean, json.dumps(report.as_dict(), indent=2))
        self.assertEqual(sorted(report.tables), sorted(TABLES))

    async def test_two_runs_give_the_same_checksums(self) -> None:
        await self._run()
        first = await _checksums(self.target_url)
        await self._run()
        self.assertEqual(await _checksums(self.target_url), first)
        self.assertEqual(len(set(first.values())), 3)

    async def test_reconcile_finds_a_missing_row(self) -> None:
        await self._run()
        async with await psycopg.AsyncConnection.connect(
            self.target_url
        ) as conn:
            await conn.execute("DELETE FROM tags WHERE id = 't1'")
            await conn.commit()
        report = await self._reconcile()
        self.assertFalse(report.clean)
        self.assertEqual(
            report.tables['tags'].mismatches,
            ['count: target 1, expected 2'],
        )
        self.assertTrue(report.tables['organizations'].clean)


class CommandTestCase(unittest.TestCase):
    """``imbi-common etl run`` and ``reconcile`` on the round-trip data."""

    def setUp(self) -> None:
        self.source_url, self.target_url = _urls()

    def _invoke(self, *args: str) -> testing.Result:
        return testing.CliRunner().invoke(
            cli.main,
            [
                'etl',
                *args,
                '--source-url',
                self.source_url,
                '--target-url',
                self.target_url,
            ],
        )

    def test_run_and_reconcile(self) -> None:
        refused = self._invoke('run')
        self.assertEqual(refused.exit_code, 1)
        self.assertIn('have no mapping yet', refused.output)

        loaded = self._invoke('run', '--allow-pending')
        self.assertEqual(loaded.exit_code, 0, loaded.output)
        self.assertIn('tags: 2 rows, 1 skipped, 1 changed', loaded.output)

        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'report.json'
            options = ['--output', str(path)]
            for table in ('tenants', 'organizations', 'tags'):
                options.extend(['--table', table])
            checked = self._invoke('reconcile', *options)
            self.assertEqual(checked.exit_code, 0, checked.output)
            report = json.loads(path.read_text())
            self.assertTrue(report['clean'])
            self.assertEqual(len(report['pending']), 71)

            asyncio.run(self._delete_tag())
            failed = self._invoke('reconcile', *options)
            self.assertEqual(failed.exit_code, 1)
            self.assertIn('tags: count: target 1, expected 2', failed.output)

    def test_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'rows.jsonl'
            before = asyncio.run(_checksums(self.target_url))
            result = self._invoke(
                'run', '--allow-pending', '--dry-run', '--output', str(path)
            )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(asyncio.run(_checksums(self.target_url)), before)
            lines = [
                json.loads(line) for line in path.read_text().splitlines()
            ]
        self.assertEqual(
            sorted(
                (line['table'], line['kind'])
                for line in lines
                if line['kind'] == 'row'
            ),
            [
                ('organizations', 'row'),
                ('organizations', 'row'),
                ('tags', 'row'),
                ('tags', 'row'),
                ('tenants', 'row'),
            ],
        )

    def test_dry_run_to_stdout(self) -> None:
        result = self._invoke('run', '--allow-pending', '--dry-run')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('"kind": "row"', result.output)

    def test_bad_url(self) -> None:
        result = testing.CliRunner().invoke(
            cli.main,
            [
                'etl',
                'reconcile',
                '--source-url',
                self.source_url,
                '--target-url',
                self.target_url,
                '--output',
                '/nonexistent/report.json',
                '--table',
                'nothing',
            ],
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn('Tables with no mapping: nothing', result.output)

    async def _delete_tag(self) -> None:
        async with await psycopg.AsyncConnection.connect(
            self.target_url
        ) as conn:
            await conn.execute("DELETE FROM tags WHERE id = 't1'")
            await conn.commit()
