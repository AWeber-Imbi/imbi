"""Tests for the move of ``agent_runtime`` to ``tickets`` (ADR 0028).

Each test uses a database of its own, because the step moves the
fixed schema names. The schemata of release A-1 are fixtures, and so is
the SQL of its store and claim query: the pods of that release run it
through the views during the rolling deploy. The schemata of release A
(2.55.0) are fixtures too: release B removes the views and must run on
a database of release A, beside its pods.
"""

import os
import pathlib
import typing
import unittest
import urllib.parse
import uuid
from unittest import mock

import dotenv
import psycopg
from psycopg import rows, sql
from psycopg.types import json as pg_json

from imbi.api import harness, tickets
from imbi.common import relational, settings

dotenv.load_dotenv()

FIXTURES = pathlib.Path(__file__).parent / 'fixtures' / 'release_a_minus_1'
RELEASE_A = FIXTURES.parent / 'release_a'

ORG = 'org-1'
AGENT = 'agent-1'
ROOT = uuid.UUID('00000000-0000-0000-0000-000000000001')
CHILD = uuid.UUID('00000000-0000-0000-0000-000000000002')
NEW = uuid.UUID('00000000-0000-0000-0000-000000000003')
RUNNER = uuid.UUID('00000000-0000-0000-0000-0000000000aa')

# --- SQL of release A-1 ------------------------------------------------

OLD_NEXT_SHORT_ID = (
    'INSERT INTO agent_runtime.task_id_sequences'
    ' (organization_id, last_value) VALUES (%s, 1)'
    ' ON CONFLICT (organization_id) DO UPDATE'
    ' SET last_value = task_id_sequences.last_value + 1'
    ' RETURNING last_value'
)

OLD_INSERT_TASK = (
    'INSERT INTO agent_runtime.tasks (id, organization_id,'
    ' short_id, agent_id, agent_version, prompt_version,'
    ' service_account_id, title,'
    ' description, origin_kind, origin_id, origin,'
    ' idempotency_key, owner, budget, chain_id,'
    ' output_schema, platform_config_version) VALUES (%s,'
    ' %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,'
    ' %s, %s, %s, %s, (SELECT max(version)'
    ' FROM harness.platform_configs'
    ' WHERE organization_id = %s))'
)

OLD_COPY_PROJECTS = (
    'INSERT INTO agent_runtime.task_projects'
    ' (organization_id, task_id, project_id,'
    ' project_slug, added_by_kind, added_by)'
    ' SELECT organization_id, %s, project_id,'
    ' project_slug, %s, %s'
    ' FROM agent_runtime.task_projects'
    ' WHERE organization_id = %s AND task_id = %s::uuid'
)

OLD_INSERT_PROJECT = (
    'INSERT INTO agent_runtime.task_projects'
    ' (organization_id, task_id, project_id,'
    ' project_slug, added_by_kind, added_by)'
    ' VALUES (%s, %s, %s, %s, %s, %s)'
    ' ON CONFLICT DO NOTHING'
)

OLD_ASSOCIATE_PROJECT = (
    'INSERT INTO agent_runtime.task_projects (organization_id,'
    ' task_id, project_id, project_slug, added_by_kind, added_by)'
    ' VALUES (%s, %s, %s, %s, %s, %s)'
    ' ON CONFLICT DO NOTHING RETURNING *'
)

OLD_MOVE_LEGACY_PROJECTS = (
    'WITH moved AS (UPDATE agent_runtime.tasks AS t'
    ' SET project_id = NULL, project_slug = NULL'
    ' FROM agent_runtime.tasks AS o'
    ' WHERE o.id = t.id AND o.project_id IS NOT NULL'
    ' RETURNING t.organization_id, t.id, t.created_at,'
    ' o.project_id, o.project_slug)'
    ' INSERT INTO agent_runtime.task_projects (organization_id,'
    ' task_id, project_id, project_slug, added_by_kind,'
    ' added_by, added_at)'
    ' SELECT organization_id, id, project_id,'
    " coalesce(project_slug, project_id), 'system', 'migration',"
    ' created_at FROM moved ON CONFLICT DO NOTHING'
)

OLD_ADD_DEPENDENCY = (
    'INSERT INTO agent_runtime.task_dependencies'
    ' (organization_id, dependent_task_id, prerequisite_task_id,'
    ' created_by_kind, created_by) VALUES (%s, %s, %s, %s, %s)'
    ' ON CONFLICT DO NOTHING RETURNING *'
)

OLD_OPEN_SESSION = (
    'INSERT INTO agent_runtime.sessions'
    ' (id, task_id, session_key, harness_instance)'
    ' VALUES (%s, %s, %s, %s) RETURNING *'
)

OLD_NEXT_SEQ = (
    'UPDATE agent_runtime.tasks SET last_seq = last_seq + 1'
    ' WHERE id = %s RETURNING last_seq'
)

OLD_APPEND_EVENT = (
    'INSERT INTO agent_runtime.events (task_id, seq, event_id, type,'
    ' schema_version, actor_kind, actor_id, channel, session_id, at,'
    ' payload) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,'
    ' COALESCE(%s, NOW()), %s) RETURNING *'
)

OLD_OPEN_REQUEST = (
    'INSERT INTO agent_runtime.requests (id, task_id,'
    ' session_id, kind, title, why, options, artifacts,'
    ' artifact_digests, expires_at, request_key)'
    ' VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'
    ' RETURNING *'
)

OLD_RECORD_USAGE = (
    'INSERT INTO agent_runtime.budget_ledger (id, task_id,'
    ' session_id, idempotency_key, model_id, tokens_in,'
    ' tokens_out, cache_read_tokens, cache_write_tokens,'
    ' input_cost_per_million, output_cost_per_million,'
    ' cache_read_cost_per_million,'
    ' cache_write_cost_per_million, cost) VALUES (%s, %s,'
    ' %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'
    ' RETURNING *'
)

OLD_CLOSE = (
    "UPDATE agent_runtime.tasks AS t SET status = 'closed',"
    " outcome = 'done_acted', closed_at = NOW(), updated_at = NOW()"
    ' WHERE t.id = %s RETURNING t.*'
)

OLD_OUTBOX = 'INSERT INTO agent_runtime.trigger_outbox (task_id) VALUES (%s)'

OLD_CLAIM = """
SELECT t.*
  FROM agent_runtime.tasks AS t
  LEFT JOIN harness.chains AS c
    ON c.root_task_id = COALESCE(t.chain_id, t.id)
 WHERE t.status = 'queued'
   AND t.control = 'run'
   AND t.agent_id = ANY(%(agents)s)
   AND ((c.root_task_id IS NULL AND t.origin_kind <> 'task')
        OR c.state = 'queued')
   AND NOT (SELECT count(*) FROM agent_runtime.tasks AS b
             WHERE b.agent_id = t.agent_id AND b.status <> 'closed'
               AND EXISTS (SELECT 1 FROM agent_runtime.sessions AS s
                            WHERE s.task_id = b.id
                              AND s.closed_at IS NULL)) >= 5
 ORDER BY t.created_at, t.id LIMIT 1 FOR UPDATE OF t SKIP LOCKED
"""

OLD_PIN_CHAIN = (
    'INSERT INTO harness.chains (root_task_id, organization_id,'
    ' runner_id) VALUES (%s, %s, %s)'
    ' ON CONFLICT (root_task_id) DO UPDATE SET'
    " runner_id = EXCLUDED.runner_id, state = 'running',"
    ' claimed_at = NOW(), fenced_at = NULL,'
    ' fencers_ok_at = NULL, fence_error = NULL,'
    " updated_at = NOW() WHERE chains.state = 'queued'"
    ' RETURNING *'
)

OLD_RECORD_CLAIM = (
    'INSERT INTO harness.claims (task_id, attempt, chain_id, runner_id)'
    ' VALUES (%s, %s, %s, %s)'
)

#: Every table of release A-1 and its row count after the old writes.
OLD_TABLES = {
    'tasks': 2,
    'sessions': 1,
    'events': 1,
    'requests': 1,
    'budget_ledger': 1,
    'task_id_sequences': 1,
    'task_dependencies': 1,
    'task_projects': 2,
    'trigger_outbox': 0,
}

type Conn = psycopg.AsyncConnection[dict[str, typing.Any]]


def _database_url(name: str) -> str:
    url = urllib.parse.urlsplit(str(settings.Postgres().url))
    return urllib.parse.urlunsplit(url._replace(path=f'/{name}'))


async def _old_install() -> None:
    """Initialize as release A-1 does."""
    for schema, path in (
        ('agent_runtime', 'agent_runtime_schemata.toml'),
        ('harness', 'harness_schemata.toml'),
    ):
        await relational.initialize(
            schema,
            relational.load_schemata(FIXTURES / path),
            f'imbi.api.initialize.{schema}',
        )


async def _new_install() -> None:
    """Initialize as release A does: tickets, then the harness."""
    for schema, path, lock_key in (
        ('tickets', 'tickets_schemata.toml', tickets.LOCK_KEY),
        ('harness', 'harness_schemata.toml', 'imbi.api.initialize.harness'),
    ):
        await relational.initialize(
            schema, relational.load_schemata(RELEASE_A / path), lock_key
        )
    await relational.initialize_deleted_organizations()


async def _release_b_install() -> None:
    """Initialize as this release (B) does: tickets, then the harness."""
    await tickets.initialize()
    await harness.initialize()


async def _insert_ticket(
    conn: Conn, ticket_id: uuid.UUID, origin_kind: str, key: str | None
) -> None:
    """Write a child of ``ROOT`` with the SQL of release A or B."""
    await conn.execute(
        'INSERT INTO tickets.tickets (id, organization_id, short_id,'
        ' agent_id, agent_version, service_account_id, title,'
        ' description, origin_kind, origin_id, origin, idempotency_key,'
        ' owner, chain_id) VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s, %s,'
        ' %s, %s, %s, %s)',
        (
            ticket_id,
            ORG,
            f'T-{ticket_id.int}',
            AGENT,
            'sa-1',
            't',
            'd',
            origin_kind,
            str(ROOT),
            pg_json.Jsonb({'kind': origin_kind}),
            key,
            'owner@example.com',
            ROOT,
        ),
    )


async def _new_task(
    conn: Conn, task_id: uuid.UUID, origin_kind: str, origin_id: str
) -> None:
    cursor = await conn.execute(OLD_NEXT_SHORT_ID, (ORG,))
    row = await cursor.fetchone()
    assert row is not None
    await conn.execute(
        OLD_INSERT_TASK,
        (
            task_id,
            ORG,
            f'T-{row["last_value"]}',
            AGENT,
            1,
            None,
            'sa-1',
            'Title',
            'Description',
            origin_kind,
            origin_id,
            pg_json.Jsonb({'kind': origin_kind}),
            None,
            'owner@example.com',
            None,
            ROOT,
            None,
            ORG,
        ),
    )


class DatabaseTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.databases: list[str] = []
        self.addAsyncCleanup(self._drop_databases)
        await self._use_database()

    async def _use_database(self) -> None:
        """Create a database and point the settings at it."""
        name = f'tickets_rename_{uuid.uuid4().hex[:12]}'
        async with await psycopg.AsyncConnection.connect(
            str(settings.Postgres().url), autocommit=True
        ) as admin:
            await admin.execute(
                sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name))
            )
        self.databases.append(name)
        patcher = mock.patch.dict(
            os.environ, {'POSTGRES_URL': _database_url(name)}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _drop_databases(self) -> None:
        # The environment patches are undone by now.
        async with await psycopg.AsyncConnection.connect(
            str(settings.Postgres().url), autocommit=True
        ) as admin:
            for name in self.databases:
                await admin.execute(
                    sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(
                        sql.Identifier(name)
                    )
                )

    async def _connect(self) -> Conn:
        conn = await psycopg.AsyncConnection.connect(
            str(settings.Postgres().url),
            autocommit=True,
            row_factory=rows.dict_row,
        )
        self.addAsyncCleanup(conn.close)
        return conn

    async def _write_as_release_a_minus_1(self, conn: Conn) -> None:
        """Write one row to every table with the old SQL."""
        await _new_task(conn, ROOT, 'human', 'user-1')
        await conn.execute(
            OLD_INSERT_PROJECT,
            (ORG, ROOT, 'p-1', 'project-1', 'human', 'u'),
        )
        await _new_task(conn, CHILD, 'task', str(ROOT))
        await conn.execute(OLD_COPY_PROJECTS, (CHILD, 'agent', 'a', ORG, ROOT))
        await conn.execute(
            OLD_ADD_DEPENDENCY, (ORG, CHILD, ROOT, 'human', 'u')
        )
        session = uuid.uuid4()
        await conn.execute(OLD_OPEN_SESSION, (session, ROOT, 'key', 'pod'))
        cursor = await conn.execute(OLD_NEXT_SEQ, (ROOT,))
        seq = await cursor.fetchone()
        assert seq is not None
        await conn.execute(
            OLD_APPEND_EVENT,
            (
                ROOT,
                seq['last_seq'],
                uuid.uuid4(),
                'task.created',
                1,
                'human',
                'u',
                'web',
                None,
                None,
                pg_json.Jsonb({}),
            ),
        )
        await conn.execute(
            OLD_OPEN_REQUEST,
            (
                uuid.uuid4(),
                ROOT,
                session,
                'question',
                'Title',
                None,
                None,
                None,
                None,
                None,
                'request-key',
            ),
        )
        await conn.execute(
            OLD_RECORD_USAGE,
            (uuid.uuid4(), ROOT, session, 'usage-key', 'm', 1, 2, 3, 4)
            + (None,) * 5,
        )
        await conn.execute(
            'INSERT INTO harness.pools (name, service_account)'
            " VALUES ('pool', 'sa-1')"
        )
        await conn.execute(
            'INSERT INTO harness.runners (id, pool, runner_token_hash,'
            ' executor_token_hash, lease_expires_at)'
            " VALUES (%s, 'pool', 'r', 'e', NOW())",
            (RUNNER,),
        )
        await conn.execute(OLD_PIN_CHAIN, (ROOT, ORG, RUNNER))
        await conn.execute(OLD_RECORD_CLAIM, (ROOT, 1, ROOT, RUNNER))

    async def _catalog(self, conn: Conn) -> dict[str, list[typing.Any]]:
        """The objects of the ``tickets`` and ``harness`` schemas."""
        queries = {
            'columns': (
                'SELECT table_schema, table_name, column_name, data_type,'
                ' is_nullable, column_default'
                ' FROM information_schema.columns'
                " WHERE table_schema IN ('tickets', 'harness')"
            ),
            'constraints': (
                'SELECT n.nspname, r.relname, c.conname,'
                ' pg_get_constraintdef(c.oid) AS definition'
                ' FROM pg_constraint AS c'
                ' JOIN pg_class AS r ON r.oid = c.conrelid'
                ' JOIN pg_namespace AS n ON n.oid = c.connamespace'
                " WHERE n.nspname IN ('tickets', 'harness')"
            ),
            'indexes': (
                'SELECT schemaname, tablename, indexname, indexdef'
                ' FROM pg_indexes'
                " WHERE schemaname IN ('tickets', 'harness')"
            ),
            'triggers': (
                'SELECT tgrelid::regclass::text AS relation, tgname,'
                ' pg_get_triggerdef(oid) AS definition FROM pg_trigger'
                ' WHERE NOT tgisinternal'
            ),
            'relations': (
                'SELECT n.nspname, c.relname, c.relkind FROM pg_class AS c'
                ' JOIN pg_namespace AS n ON n.oid = c.relnamespace'
                " WHERE n.nspname IN ('tickets', 'harness')"
                " AND c.relkind IN ('r', 'v')"
            ),
        }
        catalog: dict[str, list[typing.Any]] = {}
        for name, query in queries.items():
            cursor = await conn.execute(query)
            catalog[name] = sorted(
                tuple(row.values()) for row in await cursor.fetchall()
            )
        return catalog

    async def _migrated(self) -> Conn:
        """Install release A-1 with rows, then initialize release A."""
        await _old_install()
        conn = await self._connect()
        await self._write_as_release_a_minus_1(conn)
        await _new_install()
        return conn


class RenameTestCase(DatabaseTestCase):
    """Release A on a database of release A-1."""

    async def test_moves_every_row(self) -> None:
        conn = await self._migrated()
        for old, count in OLD_TABLES.items():
            new = old.replace('task', 'ticket')
            cursor = await conn.execute(
                sql.SQL('SELECT count(*) AS n FROM {}').format(
                    sql.Identifier('tickets', new)
                )
            )
            self.assertEqual(await cursor.fetchone(), {'n': count}, new)
        cursor = await conn.execute(
            'SELECT root_task_id, root_ticket_id FROM harness.chains'
        )
        self.assertEqual(
            await cursor.fetchall(),
            [{'root_task_id': ROOT, 'root_ticket_id': ROOT}],
        )
        cursor = await conn.execute(
            'SELECT task_id, ticket_id FROM harness.claims'
        )
        self.assertEqual(
            await cursor.fetchall(), [{'task_id': ROOT, 'ticket_id': ROOT}]
        )

    async def test_migrated_install_matches_a_new_install(self) -> None:
        migrated = await self._catalog(await self._migrated())
        await self._use_database()
        await _new_install()
        self.assertEqual(migrated, await self._catalog(await self._connect()))

    async def test_views_have_every_old_column(self) -> None:
        conn = await self._migrated()
        old = relational.load_schemata(
            FIXTURES / 'agent_runtime_schemata.toml'
        )
        for table in old['tables']:
            cursor = await conn.execute(
                'SELECT c.relkind FROM pg_class AS c'
                ' JOIN pg_namespace AS n ON n.oid = c.relnamespace'
                " WHERE n.nspname = 'agent_runtime' AND c.relname = %s",
                (table['name'],),
            )
            self.assertEqual(await cursor.fetchone(), {'relkind': 'v'})
            cursor = await conn.execute(
                'SELECT column_name FROM information_schema.columns'
                " WHERE table_schema = 'agent_runtime' AND table_name = %s"
                ' ORDER BY ordinal_position',
                (table['name'],),
            )
            self.assertEqual(
                [row['column_name'] for row in await cursor.fetchall()],
                list(table['columns']),
            )

    async def test_old_sql_works_through_the_views(self) -> None:
        conn = await self._migrated()
        # A queued chain makes both tasks claimable, so another claim
        # gets the child only when the lock on the root holds.
        await conn.execute("UPDATE harness.chains SET state = 'queued'")
        async with conn.transaction():
            cursor = await conn.execute(OLD_CLAIM, {'agents': [AGENT]})
            claimed = await cursor.fetchone()
            self.assertIsNotNone(claimed)
            assert claimed is not None
            self.assertEqual(claimed['id'], ROOT)
            other = await psycopg.AsyncConnection.connect(
                str(settings.Postgres().url), row_factory=rows.dict_row
            )
            async with other:
                cursor = await other.execute(OLD_CLAIM, {'agents': [AGENT]})
                second = await cursor.fetchone()
                self.assertIsNotNone(second)
                assert second is not None
                self.assertEqual(second['id'], CHILD)
            cursor = await conn.execute(OLD_PIN_CHAIN, (ROOT, ORG, RUNNER))
            pinned = await cursor.fetchone()
            assert pinned is not None
            self.assertEqual(pinned['attempt'], 1)
            self.assertEqual(pinned['root_ticket_id'], ROOT)
            await conn.execute(OLD_RECORD_CLAIM, (ROOT, 2, ROOT, RUNNER))
        # The next short id and a new task, with defaults from the table.
        await _new_task(conn, NEW, 'human', 'user-1')
        cursor = await conn.execute(
            'SELECT short_id, status, control, last_seq'
            ' FROM tickets.tickets WHERE id = %s',
            (NEW,),
        )
        self.assertEqual(
            await cursor.fetchone(),
            {
                'short_id': 'T-3',
                'status': 'queued',
                'control': 'run',
                'last_seq': 0,
            },
        )
        # A repeated idempotency key: release A-1 finds it by the name
        # of the index in the error.
        for short_id in ('T-90', 'T-91'):
            params = (
                uuid.uuid4(), ORG, short_id, AGENT, 1, None, 'sa-1', 't',
                'd', 'human', 'user-1', pg_json.Jsonb({}), 'k',
                'owner@example.com', None, ROOT, None, ORG,
            )  # fmt: skip
            if short_id == 'T-90':
                await conn.execute(OLD_INSERT_TASK, params)
                continue
            with self.assertRaises(psycopg.errors.UniqueViolation) as raised:
                await conn.execute(OLD_INSERT_TASK, params)
            self.assertEqual(
                raised.exception.diag.constraint_name,
                'tasks_origin_idempotency_key',
            )
        # ON CONFLICT DO NOTHING RETURNING: a repeat returns no row.
        cursor = await conn.execute(
            OLD_ASSOCIATE_PROJECT, (ORG, NEW, 'p-2', 'project-2', 'h', 'u')
        )
        self.assertEqual((await cursor.fetchone() or {})['task_id'], NEW)
        cursor = await conn.execute(
            OLD_ASSOCIATE_PROJECT, (ORG, NEW, 'p-2', 'project-2', 'h', 'u')
        )
        self.assertIsNone(await cursor.fetchone())
        cursor = await conn.execute(
            OLD_ADD_DEPENDENCY, (ORG, CHILD, ROOT, 'human', 'u')
        )
        self.assertIsNone(await cursor.fetchone())
        await conn.execute(
            OLD_INSERT_PROJECT, (ORG, NEW, 'p-2', 'project-2', 'h', 'u')
        )
        # The start of every pod of release A-1.
        await conn.execute(
            "UPDATE agent_runtime.tasks SET project_id = 'p-3' WHERE id = %s",
            (NEW,),
        )
        cursor = await conn.execute(OLD_MOVE_LEGACY_PROJECTS)
        self.assertEqual(cursor.rowcount, 1)
        cursor = await conn.execute(
            'SELECT project_id FROM tickets.ticket_projects'
            ' WHERE ticket_id = %s ORDER BY project_id',
            (NEW,),
        )
        self.assertEqual(
            [row['project_id'] for row in await cursor.fetchall()],
            ['p-2', 'p-3'],
        )
        # UPDATE ... RETURNING and the outbox row of a close.
        cursor = await conn.execute(OLD_CLOSE, (NEW,))
        closed = await cursor.fetchone()
        assert closed is not None
        self.assertEqual(closed['status'], 'closed')
        await conn.execute(OLD_OUTBOX, (NEW,))
        cursor = await conn.execute(
            'SELECT ticket_id FROM tickets.trigger_outbox'
        )
        self.assertEqual(await cursor.fetchall(), [{'ticket_id': NEW}])
        # A delete through a view.
        await conn.execute(
            'DELETE FROM agent_runtime.trigger_outbox WHERE task_id = %s',
            (NEW,),
        )
        cursor = await conn.execute(
            'SELECT count(*) AS n FROM tickets.trigger_outbox'
        )
        self.assertEqual(await cursor.fetchone(), {'n': 0})

    async def test_harness_trigger_mirrors_the_ticket_ids(self) -> None:
        conn = await self._migrated()
        await _new_task(conn, NEW, 'human', 'user-1')
        # A writer of this release gives the new column only.
        cursor = await conn.execute(
            'INSERT INTO harness.chains (root_ticket_id, organization_id)'
            ' VALUES (%s, %s) RETURNING root_task_id, root_ticket_id',
            (NEW, ORG),
        )
        self.assertEqual(
            await cursor.fetchone(),
            {'root_task_id': NEW, 'root_ticket_id': NEW},
        )
        cursor = await conn.execute(
            'INSERT INTO harness.claims'
            ' (ticket_id, attempt, chain_id, runner_id)'
            ' VALUES (%s, 1, %s, %s) RETURNING task_id, ticket_id',
            (NEW, NEW, RUNNER),
        )
        self.assertEqual(
            await cursor.fetchone(), {'task_id': NEW, 'ticket_id': NEW}
        )
        # A writer of release A-1 gives the old column only: see
        # test_moves_every_row. A writer that gives both must agree.
        for statement, params in (
            (
                'INSERT INTO harness.chains'
                ' (root_task_id, root_ticket_id, organization_id)'
                ' VALUES (%s, %s, %s)',
                (CHILD, ROOT, ORG),
            ),
            (
                'INSERT INTO harness.claims'
                ' (task_id, ticket_id, attempt, chain_id, runner_id)'
                ' VALUES (%s, %s, 3, %s, %s)',
                (NEW, ROOT, NEW, RUNNER),
            ),
            (
                'UPDATE harness.chains SET root_task_id = %s,'
                ' root_ticket_id = %s WHERE root_task_id = %s',
                (CHILD, ROOT, NEW),
            ),
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(psycopg.errors.CheckViolation):
                    await conn.execute(statement, params)
        # An update of one column changes the other.
        await conn.execute(
            'DELETE FROM harness.chains WHERE root_task_id = %s', (ROOT,)
        )
        cursor = await conn.execute(
            'UPDATE harness.chains SET root_task_id = %s'
            ' WHERE root_ticket_id = %s RETURNING root_ticket_id',
            (ROOT, NEW),
        )
        self.assertEqual(await cursor.fetchone(), {'root_ticket_id': ROOT})

    async def test_a_second_run_changes_nothing(self) -> None:
        conn = await self._migrated()
        before = await self._catalog(conn)
        with self.assertNoLogs('imbi.common.relational', 'INFO'):
            await _new_install()
            # A pod of release A-1 that starts after the move.
            await _old_install()
        self.assertEqual(before, await self._catalog(conn))


class ReleaseBTestCase(DatabaseTestCase):
    """Release B on a database of release A, with rows of release A-1."""

    async def _release_b(self) -> Conn:
        conn = await self._migrated()
        await _release_b_install()
        return conn

    async def test_a_second_run_changes_nothing(self) -> None:
        conn = await self._release_b()
        before = await self._catalog(conn)
        with self.assertNoLogs('imbi.common.relational', 'INFO'):
            await _release_b_install()
            # A pod of release A that starts during the rollout.
            await _new_install()
        self.assertEqual(before, await self._catalog(conn))

    async def test_drops_the_views_and_rewrites_child_kinds(self) -> None:
        conn = await self._release_b()
        cursor = await conn.execute(
            "SELECT to_regnamespace('agent_runtime') AS schema"
        )
        self.assertEqual(await cursor.fetchone(), {'schema': None})
        cursor = await conn.execute(
            "SELECT origin_kind, origin ->> 'kind' AS kind"
            ' FROM tickets.tickets WHERE id = %s',
            (CHILD,),
        )
        self.assertEqual(
            await cursor.fetchone(),
            {'origin_kind': 'ticket', 'kind': 'ticket'},
        )
        # A child that a pod of release A writes during the rollout:
        # the next start rewrites it.
        await _insert_ticket(conn, NEW, 'task', None)
        await _release_b_install()
        cursor = await conn.execute(
            'SELECT origin_kind FROM tickets.tickets WHERE id = %s', (NEW,)
        )
        self.assertEqual(await cursor.fetchone(), {'origin_kind': 'ticket'})

    async def test_child_kinds_share_one_idempotency_key(self) -> None:
        conn = await self._release_b()
        # Release A writes `task`, release B `ticket`: in either order,
        # the second insert fails on the index that release A knows.
        for first, second in (('task', 'ticket'), ('ticket', 'task')):
            key = f'key-{first}'
            await _insert_ticket(conn, uuid.uuid4(), first, key)
            with self.subTest(first=first):
                with self.assertRaises(
                    psycopg.errors.UniqueViolation
                ) as raised:
                    await _insert_ticket(conn, uuid.uuid4(), second, key)
                self.assertEqual(
                    raised.exception.diag.constraint_name,
                    'tasks_origin_idempotency_key',
                )
        # Other kinds keep their own key.
        await _insert_ticket(conn, uuid.uuid4(), 'human', 'key-task')

    async def test_release_a_reads_the_old_harness_columns(self) -> None:
        conn = await self._release_b()
        await _insert_ticket(conn, NEW, 'human', None)
        # A writer of release B gives the new columns only.
        await conn.execute(
            'INSERT INTO harness.chains (root_ticket_id, organization_id)'
            ' VALUES (%s, %s)',
            (NEW, ORG),
        )
        await conn.execute(
            'INSERT INTO harness.claims'
            ' (ticket_id, attempt, chain_id, runner_id)'
            ' VALUES (%s, 1, %s, %s)',
            (NEW, NEW, RUNNER),
        )
        # The SQL of release A reads the old columns.
        cursor = await conn.execute(
            'SELECT count(*) AS n FROM harness.chains WHERE root_task_id = %s',
            (NEW,),
        )
        self.assertEqual(await cursor.fetchone(), {'n': 1})
        cursor = await conn.execute(
            'SELECT count(*) AS n FROM harness.claims WHERE task_id = %s',
            (NEW,),
        )
        self.assertEqual(await cursor.fetchone(), {'n': 1})

    async def test_a_new_install_has_only_the_new_names(self) -> None:
        await _release_b_install()
        conn = await self._connect()
        catalog = await self._catalog(conn)
        columns = {row[2] for row in catalog['columns'] if row[0] == 'harness'}
        self.assertIn('root_ticket_id', columns)
        self.assertNotIn('root_task_id', columns)
        self.assertNotIn('task_id', columns)
        self.assertEqual(
            [t for t in catalog['triggers'] if t[0].startswith('harness.')],
            [],
        )
        cursor = await conn.execute(
            'SELECT pg_get_constraintdef(oid) AS definition'
            " FROM pg_constraint WHERE conname = 'chains_pkey'"
        )
        self.assertEqual(
            await cursor.fetchone(),
            {'definition': 'PRIMARY KEY (root_ticket_id)'},
        )

    async def test_child_gets_its_parent_from_its_origin(self) -> None:
        conn = await self._release_b()
        cursor = await conn.execute(
            'SELECT id, parent_id FROM tickets.tickets ORDER BY id'
        )
        self.assertEqual(
            await cursor.fetchall(),
            [
                {'id': ROOT, 'parent_id': None},
                {'id': CHILD, 'parent_id': ROOT},
            ],
        )
        # The step runs once: a child that a person made a root stays
        # a root.
        await conn.execute(
            'UPDATE tickets.tickets SET parent_id = NULL WHERE id = %s',
            (CHILD,),
        )
        await _release_b_install()
        cursor = await conn.execute(
            'SELECT parent_id FROM tickets.tickets WHERE id = %s', (CHILD,)
        )
        self.assertEqual(await cursor.fetchone(), {'parent_id': None})
        # A writer of the previous release gives no parent: the trigger
        # takes it from the origin.
        await _insert_ticket(conn, NEW, 'task', None)
        cursor = await conn.execute(
            'SELECT parent_id FROM tickets.tickets WHERE id = %s', (NEW,)
        )
        self.assertEqual(await cursor.fetchone(), {'parent_id': ROOT})


PERSON_TICKETS = FIXTURES.parent / 'release_person_tickets'


async def _person_tickets_install() -> None:
    """Initialize ``tickets`` as the previous release (person tickets)
    does."""
    await relational.initialize(
        'tickets',
        relational.load_schemata(PERSON_TICKETS / 'tickets_schemata.toml'),
        tickets.LOCK_KEY,
    )


class ReopenReleaseTestCase(DatabaseTestCase):
    """This release (reopen) on a database of the previous release."""

    async def _reopen_release(self) -> Conn:
        conn = await self._migrated()
        await _person_tickets_install()
        await _release_b_install()
        return conn

    async def test_previous_release_restart_changes_nothing(self) -> None:
        conn = await self._reopen_release()
        before = await self._catalog(conn)
        with self.assertNoLogs('imbi.common.relational', 'INFO'):
            await _person_tickets_install()
            await _release_b_install()
        self.assertEqual(before, await self._catalog(conn))

    async def test_outbox_key_matches_a_new_install(self) -> None:
        conn = await self._reopen_release()
        query = (
            'SELECT conname, pg_get_constraintdef(oid) AS definition'
            ' FROM pg_constraint'
            " WHERE conrelid = 'tickets.trigger_outbox'::regclass"
            " AND contype = 'p'"
        )
        cursor = await conn.execute(query)
        migrated = await cursor.fetchall()
        self.assertEqual(
            migrated,
            [
                {
                    'conname': 'trigger_outbox_pkey',
                    'definition': 'PRIMARY KEY (ticket_id, close_id)',
                }
            ],
        )
        await self._use_database()
        await _release_b_install()
        cursor = await (await self._connect()).execute(query)
        self.assertEqual(await cursor.fetchall(), migrated)

    async def test_previous_release_writes_the_first_close(self) -> None:
        conn = await self._reopen_release()
        # The SQL of the previous release, which names no close.
        await conn.execute(
            'INSERT INTO tickets.trigger_outbox (ticket_id) VALUES (%s)',
            (ROOT,),
        )
        await conn.execute(
            'INSERT INTO tickets.trigger_outbox (ticket_id, close_id)'
            ' VALUES (%s, %s)',
            (ROOT, NEW),
        )
        # A ticket that the previous release writes is in its first cycle.
        await _insert_ticket(conn, NEW, 'ticket', None)
        cursor = await conn.execute(
            'SELECT close_id FROM tickets.tickets WHERE id = %s', (NEW,)
        )
        self.assertEqual(
            await cursor.fetchone(),
            {'close_id': tickets.store.FIRST_CLOSE_ID},
        )
        cursor = await conn.execute(
            'SELECT close_id FROM tickets.trigger_outbox ORDER BY close_id'
        )
        self.assertEqual(
            await cursor.fetchall(),
            [{'close_id': tickets.store.FIRST_CLOSE_ID}, {'close_id': NEW}],
        )
        await conn.execute(
            'DELETE FROM tickets.trigger_outbox WHERE ticket_id = %s', (ROOT,)
        )

    async def test_old_children_get_the_chain_of_their_origin(self) -> None:
        conn = await self._reopen_release()
        # A grandchild of ROOT, and rows made before `chain_id` existed.
        await _insert_ticket(conn, NEW, 'ticket', None)
        await conn.execute(
            'UPDATE tickets.tickets SET origin_id = %s WHERE id = %s',
            (str(CHILD), NEW),
        )
        await conn.execute('UPDATE tickets.tickets SET chain_id = NULL')
        # A child whose origin ticket is gone.
        orphan = uuid.UUID('00000000-0000-0000-0000-000000000004')
        await _insert_ticket(conn, orphan, 'ticket', None)
        await conn.execute(
            'UPDATE tickets.tickets SET origin_id = %s, chain_id = NULL'
            ' WHERE id = %s',
            (str(uuid.uuid4()), orphan),
        )
        await _release_b_install()
        cursor = await conn.execute(
            'SELECT id, chain_id FROM tickets.tickets ORDER BY id'
        )
        self.assertEqual(
            await cursor.fetchall(),
            [
                {'id': ROOT, 'chain_id': None},
                {'id': CHILD, 'chain_id': ROOT},
                {'id': NEW, 'chain_id': ROOT},
                {'id': orphan, 'chain_id': orphan},
            ],
        )
        with self.assertNoLogs('imbi.common.relational', 'INFO'):
            await _release_b_install()
