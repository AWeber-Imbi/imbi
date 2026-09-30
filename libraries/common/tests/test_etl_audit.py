"""Tests for the pre-migration audit, ``imbi-common etl audit`` (WP1.9)."""

import asyncio
import json
import os
import pathlib
import tempfile
import typing
import unittest
import uuid

import psycopg
from psycopg import conninfo, sql
from typer import testing

from imbi.common.db.etl.audit import (
    appendix_e,
    checks,
    cli,
    rules,
    runner,
    sources,
    tables,
)

#: A graph with one row for most rules. Each value is synthetic.
GRAPH = """
CREATE (o:Organization {id: 'org1', slug: 'acme', name: 'Acme',
        created_at: '2026-01-01T00:00:00+00:00'})
CREATE (t1:Team {id: 'team1', slug: 'core', name: 'Core',
        created_at: '2026-01-01T00:00:00+00:00'})
CREATE (t2:Team {id: 'team2', slug: 'core', name: 'Core 2',
        created_at: '2026-01-01T00:00:00+00:00'})
CREATE (t1)-[:BELONGS_TO]->(o)
CREATE (t2)-[:BELONGS_TO]->(o)
CREATE (p1:Project {id: 'p1', slug: 'svc', name: 'Svc', links: '{}',
        identifiers: '{}', created_at: '2026-01-01T00:00:00+00:00'})
CREATE (p1)-[:OWNED_BY]->(t1)
CREATE (p2:Project {id: 'p2', slug: 'Not A Slug', name: 'Two',
        created_at: 'not a date'})
CREATE (r1:Release {id: 'r1', title: 'One', committish: 'abc1234',
        created_by: 'someone', links: '[]',
        created_at: '2026-01-01T00:00:00+00:00'})
CREATE (p1)-[:HAS_RELEASE]->(r1)
CREATE (r2:Release {id: 'r2', title: 'Two', committish: 'abc1235', tag: '',
        created_by: 'someone', links: '[]',
        created_at: '2026-01-01T00:00:00+00:00'})
CREATE (:OAuthIdentity {id: 'oauth1'})
CREATE (:Role {slug: 'admin', name: 'Admin'})
CREATE (g1:Tag {id: 'tag1', slug: 'dup', name: 'Dup'})
CREATE (g2:Tag {id: 'tag2', slug: 'dup', name: 'Dup 2'})
CREATE (g1)-[:BELONGS_TO]->(o)
CREATE (g2)-[:BELONGS_TO]->(o)
CREATE (:CommentThread {id: 'thread1', kind: 'page', created_by: 'x'})
CREATE (k:APIKey {id: 'key1', revoked: false,
        revoked_at: '2026-01-01T00:00:00+00:00'})
RETURN 1
"""


def _url(dbname: str) -> str:
    return conninfo.make_conninfo(os.environ['POSTGRES_URL'], dbname=dbname)


async def _admin() -> psycopg.AsyncConnection[typing.Any]:
    return await psycopg.AsyncConnection.connect(
        _url('postgres'), autocommit=True
    )


class ExpandTestCase(unittest.TestCase):
    """The placeholder dialect of ``rules.py``."""

    def test_placeholders(self) -> None:
        self.assertEqual(
            rules.placeholders(
                "SELECT 1 FROM {Project} v JOIN {OWNED_BY} e ON '{{}}' <> ''"
            ),
            {'Project', 'OWNED_BY'},
        )

    def test_edge_type(self) -> None:
        self.assertTrue(rules.is_edge_type('OWNED_BY'))
        self.assertFalse(rules.is_edge_type('APIKey'))
        self.assertFalse(rules.is_edge_type('MCPServer'))

    def test_missing_label_is_empty(self) -> None:
        composed = rules.expand('SELECT * FROM {Project} v', 'imbi', set())
        self.assertIn('WHERE false', repr(composed))

    def test_existing_label(self) -> None:
        composed = rules.expand(
            'SELECT * FROM {Project} v', 'imbi', {'Project'}
        )
        self.assertIn("Identifier('imbi', 'Project')", repr(composed))


class BuildTestCase(unittest.TestCase):
    """``checks.build`` makes one rule for each schema rule it can see."""

    def build(
        self, table: str, columns: list[str]
    ) -> tuple[list[rules.Rule], list[checks.NotCovered]]:
        source = checks.Source(table, 'SELECT 1')
        return checks.build(source, columns, {table: (source, columns)})

    def test_rules_of_tags(self) -> None:
        found, gaps = self.build(
            'tags', ['id', 'organization_id', 'name', 'slug']
        )
        ids = {rule.id for rule in found}
        self.assertIn('schema:tags.slug.domain', ids)
        self.assertIn('schema:tags.name.not_null', ids)
        self.assertIn('schema:tags.check.name_not_empty', ids)
        self.assertIn('schema:tags.unique.tags_pkey', ids)
        unique = next(
            rule
            for rule in found
            if rule.id == 'schema:tags.unique.tags_organization_id_slug_key'
        )
        self.assertEqual(unique.covered_by, 'E3')
        self.assertIn(
            checks.NotCovered(
                'tags',
                'fk.tags_organization_id_fkey',
                'organizations has no source query',
            ),
            gaps,
        )

    def test_missing_not_null_column_is_a_gap(self) -> None:
        _found, gaps = self.build('tags', ['id'])
        self.assertIn(
            checks.NotCovered(
                'tags', 'name.not_null', 'the source query has no value for it'
            ),
            gaps,
        )

    def test_unknown_column_is_a_gap(self) -> None:
        _found, gaps = self.build('tags', ['id', 'colour'])
        self.assertIn(
            checks.NotCovered('tags', 'colour', 'not a column of the table'),
            gaps,
        )

    def test_references(self) -> None:
        self.assertEqual(
            checks.references(
                "((kind <> 'inline'::text) OR (anchor_quote <> ''::text))",
                ['kind', 'anchor_quote', 'inline', 'text'],
            ),
            {'kind', 'anchor_quote', 'text'},
        )

    def test_every_source_is_a_table(self) -> None:
        for source in sources.SOURCES:
            self.assertIn(source.table, tables.TABLES)

    def test_covered_rules_exist(self) -> None:
        ids = {rule.id for rule in appendix_e.RULES}
        for rule_id in appendix_e.COVERED.values():
            self.assertIn(rule_id, ids)

    def test_rule_ids_are_unique(self) -> None:
        ids = [rule.id for rule in appendix_e.RULES]
        self.assertEqual(len(ids), len(set(ids)))


async def _create_graph(database: str) -> None:
    async with await _admin() as conn:
        await conn.execute(
            sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database))
        )
    async with await psycopg.AsyncConnection.connect(
        _url(database), autocommit=True
    ) as conn:
        await conn.execute('CREATE EXTENSION age')
        await conn.execute("LOAD 'age'")
        await conn.execute('SET search_path = ag_catalog, public')
        await conn.execute("SELECT create_graph('imbi')")
        await conn.execute(
            sql.SQL(
                "SELECT * FROM cypher('imbi', $$ {} $$) AS (x agtype)"
            ).format(sql.SQL(GRAPH))  # type: ignore[arg-type]
        )


async def _audit(database: str) -> runner.Report:
    async with await psycopg.AsyncConnection.connect(_url(database)) as conn:
        return await runner.run(
            conn,
            appendix_e.RULES,
            sources.SOURCES,
            not_covered=sources.NOT_COVERED,
            covered=appendix_e.COVERED,
            id_limit=1,
        )


async def _drop(database: str) -> None:
    async with await _admin() as conn:
        await conn.execute(
            sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(
                sql.Identifier(database)
            )
        )


@unittest.skipUnless('POSTGRES_URL' in os.environ, 'needs POSTGRES_URL')
class AuditTestCase(unittest.TestCase):
    """The audit on a real AGE graph. The graph and the run are shared."""

    database: typing.ClassVar[str]
    report: typing.ClassVar[runner.Report]

    @classmethod
    def setUpClass(cls) -> None:
        cls.database = f'e_audit_{os.getpid()}_{uuid.uuid4().hex[:8]}'
        asyncio.run(_create_graph(cls.database))
        try:
            cls.report = asyncio.run(_audit(cls.database))
        except Exception:
            asyncio.run(_drop(cls.database))
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        asyncio.run(_drop(cls.database))

    def result(self, rule_id: str) -> runner.Result:
        for result in self.report.results:
            if result.rule.id == rule_id:
                return result
        raise AssertionError(f'no result for {rule_id}')

    def test_no_rule_fails_to_run(self) -> None:
        self.assertEqual(
            [
                (result.rule.id, result.error)
                for result in self.report.results
                if result.error
            ],
            [],
        )

    def test_counts(self) -> None:
        expected = {
            'E1': 0,
            'E8': 1,
            'E13': 1,
            'E15.Release': 1,
            'E36': 1,
            'E37.CommentThread': 1,
            'E38.json_text': 2,
            'E38.release_tag': 1,
            'E39': 2,
            'E10.APIKey': 1,
            'schema:roles.id.not_null': 0,
            'schema:tags.unique.tags_organization_id_slug_key': 2,
            'schema:projects.slug.domain': 1,
            'schema:projects.created_at.type': 1,
            'schema:teams.unique.teams_organization_id_slug_key': 2,
            'schema:releases.project_id.not_null': 1,
        }
        self.assertEqual(
            {rule_id: self.result(rule_id).count for rule_id in expected},
            expected,
        )

    def test_covered_rule_takes_the_fate(self) -> None:
        result = self.result('schema:releases.project_id.not_null')
        self.assertEqual(result.rule.covered_by, 'E15.Release')
        self.assertEqual(result.rule.fate, 'skipped')

    def test_e39_decides_the_tag_duplicates(self) -> None:
        rule = self.result(
            'schema:tags.unique.tags_organization_id_slug_key'
        ).rule
        self.assertEqual((rule.covered_by, rule.fate), ('E39', 'blocking'))

    def test_id_limit(self) -> None:
        result = self.result(
            'schema:teams.unique.teams_organization_id_slug_key'
        )
        self.assertEqual(result.ids, ['team1'])

    def test_missing_embeddings_table(self) -> None:
        result = self.result('E28')
        self.assertEqual(result.count, 0)
        self.assertEqual(result.note, 'public.embeddings does not exist')

    def test_blocking_rows_fail_the_audit(self) -> None:
        self.assertTrue(self.report.failed)
        self.assertEqual(self.report.as_dict()['exit_code'], 1)

    def test_tables_without_source(self) -> None:
        self.assertIn(
            checks.NotCovered('tenants', '*', sources.NOT_COVERED['tenants']),
            self.report.not_covered,
        )

    def test_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / 'audit.json'
            result = testing.CliRunner().invoke(
                cli.app,
                [
                    'audit',
                    '--source-url',
                    _url(self.database),
                    '--output',
                    str(output),
                    '--rule',
                    'E13',
                ],
            )
            report = json.loads(output.read_text())
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(
            [(rule['id'], rule['count']) for rule in report['rules']],
            [('E13', 1)],
        )
