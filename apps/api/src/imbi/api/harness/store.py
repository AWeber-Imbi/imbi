"""Postgres repository for runner pools and dispatch (ADR 0022).

Dispatch is pull: a runner claims the oldest ``queued`` root task that
it may run, and the claim pins the whole chain (the root task and its
child tasks) to the runner until every task in it is closed.

The chain row keeps an ``attempt`` number. When a runner is lost, the
lease sweep bumps it, so the agent tokens of the old attempt stop
working at once, and puts the chain back in the queue only after the
fencers succeed and the grace period passes (see
:mod:`imbi.api.harness.sweeper`).
"""

import datetime
import typing
import uuid

import psycopg
import psycopg.errors
import psycopg_pool
from psycopg import rows, sql
from psycopg.types import json as pg_json

from imbi.api.agent_tasks import log
from imbi.api.agent_tasks import store as task_store
from imbi.api.harness import tokens

type Pool = psycopg_pool.AsyncConnectionPool[
    psycopg.AsyncConnection[typing.Any]
]
type Row = dict[str, typing.Any]
type Conn = psycopg.AsyncConnection[typing.Any]
type _Query = typing.LiteralString | sql.Composed

SCHEMA = 'harness'

#: A runner that does not heartbeat for this long is lost.
LEASE_SECONDS = 60
#: The wait after the fencers succeed before a lost runner's chain goes
#: back in the queue. Longer than the runner's stop time (its lease
#: safety margin) plus the allowed clock skew.
GRACE_SECONDS = 120

RunnerState = typing.Literal['idle', 'busy', 'offline', 'fenced']
ChainState = typing.Literal['running', 'fencing', 'stuck', 'queued', 'done']
#: The chain states that hold the chain away from other runners.
PINNED: tuple[ChainState, ...] = ('running', 'fencing', 'stuck')

_SYSTEM = task_store.Actor('system', 'imbi', 'harness')

#: Serializes claims, so two claims cannot both take the last place of
#: an agent under ``max_concurrent_tasks``.
# ponytail: one lock for all claims; take a lock per agent if claim
# throughput ever matters.
_CLAIM_LOCK = 'harness.claim'

#: The oldest task that a runner may claim. ``%(agents)s`` are the
#: agents that the runner may run; ``%(limits)s`` maps an agent id to its
#: ``max_concurrent_tasks``. A root task needs no chain row; any task of
#: a chain that is back in the queue (``queued``) is claimable too.
_CLAIM_QUERY: typing.LiteralString = """
SELECT t.*
  FROM agent_runtime.tasks AS t
  LEFT JOIN harness.chains AS c
    ON c.root_task_id = COALESCE(t.chain_id, t.id)
 WHERE t.status = 'queued'
   AND t.control = 'run'
   AND t.agent_id = ANY(%(agents)s)
   AND (cardinality(%(orgs)s::text[]) = 0
        OR t.organization_id = ANY(%(orgs)s))
   AND ((c.root_task_id IS NULL AND t.origin_kind <> 'task')
        OR c.state = 'queued')
   AND NOT EXISTS (
       SELECT 1 FROM jsonb_each_text(%(limits)s) AS l(agent_id, max)
        WHERE l.agent_id = t.agent_id
          AND (SELECT count(*) FROM agent_runtime.tasks AS b
                WHERE b.agent_id = t.agent_id
                  AND b.status <> 'closed'
                  AND (EXISTS (SELECT 1 FROM harness.chains AS bc
                                WHERE bc.root_task_id
                                      = COALESCE(b.chain_id, b.id)
                                  AND bc.state = ANY(%(pinned)s))
                       OR EXISTS (SELECT 1 FROM agent_runtime.sessions AS s
                                   WHERE s.task_id = b.id
                                     AND s.closed_at IS NULL))
              ) >= l.max::int)
 ORDER BY t.created_at, t.id
 LIMIT 1
   FOR UPDATE OF t SKIP LOCKED
"""

_CHAIN_CLAIM_QUERY: typing.LiteralString = """
SELECT t.*
  FROM agent_runtime.tasks AS t
 WHERE t.chain_id = %(chain)s
   AND t.origin_kind = 'task'
   AND t.status = 'queued'
   AND t.control = 'run'
   AND NOT EXISTS (SELECT 1 FROM harness.claims AS k
                    WHERE k.task_id = t.id AND k.attempt = %(attempt)s)
 ORDER BY t.created_at, t.id
 LIMIT 1
   FOR UPDATE OF t SKIP LOCKED
"""

#: The runners that are not offline, with the current labels of their
#: pool, their chain, and its root task.
_RUNNERS_QUERY: typing.LiteralString = """
SELECT r.id, r.pool, r.instance, p.labels, r.state, r.chain_id,
       r.image_version, r.registered_at, r.last_heartbeat,
       r.lease_expires_at, c.attempt, c.state AS chain_state,
       c.organization_id AS chain_organization_id, c.fence_error,
       t.short_id AS chain_short_id
  FROM harness.runners AS r
  JOIN harness.pools AS p ON p.name = r.pool
  LEFT JOIN harness.chains AS c ON c.root_task_id = r.chain_id
  LEFT JOIN agent_runtime.tasks AS t ON t.id = r.chain_id
 WHERE r.state <> 'offline'
   AND (%(pools)s::text[] IS NULL OR r.pool = ANY(%(pools)s))
 ORDER BY r.pool, r.registered_at, r.id
"""


class PoolExists(ValueError):
    """A pool with this name exists."""


class PoolInUse(ValueError):
    """The pool has runners that are not offline."""


class RunnerBusy(ValueError):
    """The runner holds a chain; it cannot claim another one."""


class MarketplaceExists(ValueError):
    """The organization has a marketplace with this slug."""


class HarnessStore:
    """Repository over the ``harness`` schema."""

    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    # --- Pools ---------------------------------------------------------

    async def pools(self) -> list[Row]:
        """Return every pool, by name."""
        return await self._fetch_all(
            'SELECT * FROM harness.pools ORDER BY name', ()
        )

    async def pool(self, name: str) -> Row | None:
        """Return the pool ``name``."""
        return await self._fetch_one(
            'SELECT * FROM harness.pools WHERE name = %s', (name,)
        )

    async def create_pool(
        self,
        name: str,
        *,
        description: str | None,
        labels: list[str],
        organization_ids: list[str],
        service_account: str,
        service_account_id: str,
    ) -> Row:
        """Insert a pool.

        Raises:
            PoolExists: A pool has this name.

        """
        try:
            row = await self._fetch_one(
                'INSERT INTO harness.pools (name, description, labels,'
                ' organization_ids, service_account, service_account_id)'
                ' VALUES (%s, %s, %s, %s, %s, %s) RETURNING *',
                (
                    name,
                    description,
                    labels,
                    organization_ids,
                    service_account,
                    service_account_id,
                ),
            )
        except psycopg.errors.UniqueViolation as err:
            raise PoolExists(name) from err
        if row is None:  # pragma: no cover - RETURNING yields a row
            raise RuntimeError('pool insert returned no row')
        return row

    async def pool_names_of_service_account(self, slug: str) -> list[str]:
        """Return the pools whose pool credential is the service account
        ``slug``."""
        rows = await self._fetch_all(
            'SELECT name FROM harness.pools WHERE service_account = %s'
            ' ORDER BY name',
            (slug,),
        )
        return [str(row['name']) for row in rows]

    async def update_pool(self, name: str, changes: Row) -> Row | None:
        """Change columns of the pool ``name``; ``None`` when not found.

        A claim reads the labels and allowlist of the pool, so the change
        applies to runners that registered before it.
        """
        if not changes:
            return await self.pool(name)
        statement = sql.SQL(
            'UPDATE harness.pools SET {sets}, updated_at = NOW()'
            ' WHERE name = %s RETURNING *'
        ).format(
            sets=sql.SQL(', ').join(
                sql.SQL('{} = %s').format(sql.Identifier(column))
                for column in changes
            )
        )
        return await self._fetch_one(statement, (*changes.values(), name))

    async def delete_pool(self, name: str) -> bool:
        """Delete a pool and its offline runners.

        Raises:
            PoolInUse: The pool has a runner that is not offline.

        """
        async with self._pool.connection() as conn, conn.transaction():
            cursor = await conn.execute(
                'SELECT 1 FROM harness.runners'
                " WHERE pool = %s AND state <> 'offline' LIMIT 1",
                (name,),
            )
            if await cursor.fetchone() is not None:
                raise PoolInUse(name)
            cursor = await conn.execute(
                'DELETE FROM harness.pools WHERE name = %s', (name,)
            )
            return cursor.rowcount > 0

    async def runners(self, pools: list[str] | None = None) -> list[Row]:
        """Return the runners that are not offline, with their chain."""
        return await self._fetch_all(_RUNNERS_QUERY, {'pools': pools})

    # --- Runners -------------------------------------------------------

    async def register(
        self, pool: Row, *, instance: str | None, image_version: str | None
    ) -> tuple[Row, str, str]:
        """Register a runner of ``pool``.

        A runner has the labels and the allowlist of its pool as they
        are at each claim. Return the runner, its runner credential, and
        its executor credential.
        """
        runner_token, runner_hash = tokens.new_secret(tokens.RUNNER_PREFIX)
        executor_token, executor_hash = tokens.new_secret(
            tokens.EXECUTOR_PREFIX
        )
        row = await self._fetch_one(
            'INSERT INTO harness.runners (id, pool, instance, image_version,'
            ' runner_token_hash, executor_token_hash, lease_expires_at)'
            ' VALUES (%s, %s, %s, %s, %s, %s,'
            ' NOW() + make_interval(secs => %s)) RETURNING *',
            (
                uuid.uuid4(),
                pool['name'],
                instance,
                image_version,
                runner_hash,
                executor_hash,
                LEASE_SECONDS,
            ),
        )
        if row is None:  # pragma: no cover - RETURNING yields a row
            raise RuntimeError('runner insert returned no row')
        return row, runner_token, executor_token

    async def runner_by_credential(
        self, runner_id: uuid.UUID, token: str
    ) -> Row | None:
        """Return the live runner that ``token`` is the credential of."""
        return await self._fetch_one(
            'SELECT * FROM harness.runners WHERE id = %s'
            " AND runner_token_hash = %s AND state IN ('idle', 'busy')",
            (runner_id, tokens.hash_secret(token)),
        )

    async def runner_by_executor_credential(self, token: str) -> Row | None:
        """Return the live runner that ``token`` is the executor
        credential of. For the secret materialization routes."""
        return await self._fetch_one(
            'SELECT * FROM harness.runners WHERE executor_token_hash = %s'
            " AND state IN ('idle', 'busy')",
            (tokens.hash_secret(token),),
        )

    async def heartbeat(self, runner_id: uuid.UUID) -> Row | None:
        """Renew the lease of a live runner; ``None`` when it is not."""
        return await self._fetch_one(
            'UPDATE harness.runners SET last_heartbeat = NOW(),'
            ' lease_expires_at = NOW() + make_interval(secs => %s)'
            " WHERE id = %s AND state IN ('idle', 'busy') RETURNING *",
            (LEASE_SECONDS, runner_id),
        )

    async def chain(self, chain_id: uuid.UUID) -> Row | None:
        """Return a chain with the ``runner_state`` of its runner."""
        return await self._fetch_one(
            'SELECT c.*, r.state AS runner_state, p.labels AS runner_labels'
            ' FROM harness.chains AS c'
            ' LEFT JOIN harness.runners AS r ON r.id = c.runner_id'
            ' LEFT JOIN harness.pools AS p ON p.name = r.pool'
            ' WHERE c.root_task_id = %s',
            (chain_id,),
        )

    async def claim(
        self,
        runner: Row,
        agents: dict[str, list[str]],
        limits: dict[str, int],
    ) -> tuple[Row, Row] | None:
        """Pin the chain of the oldest task that ``runner`` may run.

        ``agents`` maps each enabled agent to its required labels.
        ``limits`` maps an agent id to its ``max_concurrent_tasks``.
        The labels and the organization allowlist come from the pool of
        the runner as it is now, in this transaction, so a change to the
        pool applies to runners that registered before it. Return the
        task and the chain, or ``None`` when no task waits.

        Raises:
            RunnerBusy: The runner is not idle.

        """
        async with self._pool.connection() as conn, conn.transaction():
            pool = await self._lock_idle(conn, runner['id'])
            labels = set(pool['labels'])
            await conn.execute(
                'SELECT pg_advisory_xact_lock(hashtext(%s))', (_CLAIM_LOCK,)
            )
            task = await _fetch_one(
                conn,
                _CLAIM_QUERY,
                {
                    'agents': [
                        agent_id
                        for agent_id, required in agents.items()
                        if set(required) <= labels
                    ],
                    'orgs': pool['organization_ids'],
                    'limits': pg_json.Jsonb(limits),
                    'pinned': list(PINNED),
                },
            )
            if task is None:
                return None
            chain_id = task['chain_id'] or task['id']
            chain = await _fetch_one(
                conn,
                'INSERT INTO harness.chains (root_task_id, organization_id,'
                ' runner_id) VALUES (%s, %s, %s)'
                ' ON CONFLICT (root_task_id) DO UPDATE SET'
                " runner_id = EXCLUDED.runner_id, state = 'running',"
                ' claimed_at = NOW(), fenced_at = NULL,'
                ' fencers_ok_at = NULL, fence_error = NULL,'
                " updated_at = NOW() WHERE chains.state = 'queued'"
                ' RETURNING *',
                (chain_id, task['organization_id'], runner['id']),
            )
            if chain is None:  # pragma: no cover - the claim lock holds
                return None
            await _record_claim(conn, task, chain, runner['id'])
            await conn.execute(
                "UPDATE harness.runners SET state = 'busy', chain_id = %s"
                ' WHERE id = %s',
                (chain_id, runner['id']),
            )
        return task, chain

    async def claim_child(self, runner: Row) -> tuple[Row, Row] | None:
        """Claim the oldest queued child task of the runner's chain.

        Return the task and the chain, or ``None`` when no child waits
        or the runner holds no running chain.
        """
        async with self._pool.connection() as conn, conn.transaction():
            chain = await _fetch_one(
                conn,
                'SELECT * FROM harness.chains WHERE root_task_id = %s'
                " AND runner_id = %s AND state = 'running' FOR UPDATE",
                (runner['chain_id'], runner['id']),
            )
            if chain is None:
                return None
            task = await _fetch_one(
                conn,
                _CHAIN_CLAIM_QUERY,
                {'chain': chain['root_task_id'], 'attempt': chain['attempt']},
            )
            if task is None:
                return None
            await _record_claim(conn, task, chain, runner['id'])
        return task, chain

    async def release_claim(
        self, runner_id: uuid.UUID, task: Row, chain: Row, *, pinned: bool
    ) -> None:
        """Undo a claim that the runner did not receive.

        The task can be claimed again in this attempt. With ``pinned``
        (the claim pinned the chain), the chain is unpinned: ``queued``
        when a task of it is open, else ``done``, and the runner is
        ``idle`` again.
        """
        async with self._pool.connection() as conn, conn.transaction():
            await conn.execute(
                'DELETE FROM harness.claims WHERE task_id = %s'
                ' AND attempt = %s',
                (task['id'], chain['attempt']),
            )
            if not pinned:
                return
            state: ChainState = (
                'queued'
                if await _chain_open(conn, chain['root_task_id'])
                else 'done'
            )
            await conn.execute(
                'UPDATE harness.chains SET state = %s, runner_id = NULL,'
                ' updated_at = NOW() WHERE root_task_id = %s'
                ' AND runner_id = %s',
                (state, chain['root_task_id'], runner_id),
            )
            await conn.execute(
                "UPDATE harness.runners SET state = 'idle', chain_id = NULL"
                " WHERE id = %s AND state = 'busy'",
                (runner_id,),
            )

    async def finish(self, runner: Row) -> Row | None:
        """End the work of a runner; return its chain, if it had one.

        A chain with no open task is ``done``. A chain with an open
        task goes to ``fencing``, as if the lease expired, so it goes
        back to the queue only after the fencers succeed.
        """
        async with self._pool.connection() as conn, conn.transaction():
            chain: Row | None = None
            state: RunnerState = 'offline'
            if runner['chain_id'] is not None:
                chain = await _fetch_one(
                    conn,
                    'SELECT * FROM harness.chains WHERE root_task_id = %s'
                    " AND runner_id = %s AND state = 'running' FOR UPDATE",
                    (runner['chain_id'], runner['id']),
                )
            if chain is not None:
                if await _chain_open(conn, chain['root_task_id']):
                    state = 'fenced'
                    chain = await _fetch_one(
                        conn,
                        "UPDATE harness.chains SET state = 'fencing',"
                        ' attempt = attempt + 1, fenced_at = NOW(),'
                        ' updated_at = NOW() WHERE root_task_id = %s'
                        ' RETURNING *',
                        (chain['root_task_id'],),
                    )
                else:
                    chain = await _fetch_one(
                        conn,
                        "UPDATE harness.chains SET state = 'done',"
                        ' updated_at = NOW() WHERE root_task_id = %s'
                        ' RETURNING *',
                        (chain['root_task_id'],),
                    )
            await conn.execute(
                'UPDATE harness.runners SET state = %s, offline_at = NOW()'
                ' WHERE id = %s',
                (state, runner['id']),
            )
        return chain

    async def runner_labels(self, chain_id: uuid.UUID) -> list[str] | None:
        """Return the pool labels of the runner of a running chain."""
        chain = await self.chain(chain_id)
        if chain is None or chain['state'] != 'running':
            return None
        labels: list[str] | None = chain['runner_labels']
        return labels

    # --- Rate limits ---------------------------------------------------

    async def count_tool_call(
        self,
        agent_id: str,
        tool_key: str,
        per: typing.Literal['minute', 'hour', 'day'],
        limit: int,
    ) -> tuple[bool, int, datetime.datetime]:
        """Count one call of a tool when the agent is under ``limit``.

        Return whether the call is allowed, the count in the window,
        and the start of the window. A refused call is not counted.
        """
        async with self._pool.connection() as conn, conn.transaction():
            cursor = await conn.execute(
                'INSERT INTO harness.tool_call_counts (agent_id, tool_key,'
                ' period, window_start, count)'
                ' VALUES (%s, %s, %s, date_trunc(%s, NOW()), 1)'
                ' ON CONFLICT (agent_id, tool_key, period, window_start)'
                ' DO UPDATE SET count = tool_call_counts.count + 1'
                ' WHERE tool_call_counts.count < %s'
                ' RETURNING count, window_start',
                (agent_id, tool_key, per, per, limit),
            )
            row = await cursor.fetchone()
            if row is not None:
                return True, int(row[0]), row[1]
            cursor = await conn.execute(
                'SELECT count, window_start FROM harness.tool_call_counts'
                ' WHERE agent_id = %s AND tool_key = %s AND period = %s'
                ' AND window_start = date_trunc(%s, NOW())',
                (agent_id, tool_key, per, per),
            )
            row = await cursor.fetchone()
            if row is None:  # pragma: no cover - the conflict found it
                raise RuntimeError('tool call counter row is missing')
            return False, int(row[0]), row[1]

    # --- Agent platform configuration ----------------------------------

    async def platform_config(
        self, organization_id: str, version: int | None = None
    ) -> Row | None:
        """Return version ``version`` of an organization's agent
        platform configuration, or the newest when it is ``None``."""
        return await self._fetch_one(
            'SELECT * FROM harness.platform_configs'
            ' WHERE organization_id = %s'
            ' AND (%s::int IS NULL OR version = %s)'
            ' ORDER BY version DESC LIMIT 1',
            (organization_id, version, version),
        )

    async def add_platform_config(
        self, organization_id: str, config: Row, created_by: str
    ) -> Row:
        """Write the next version of an organization's configuration.

        Raises:
            psycopg.errors.UniqueViolation: A concurrent write took the
                version.

        """
        row = await self._fetch_one(
            'INSERT INTO harness.platform_configs'
            ' (organization_id, version, config, created_by)'
            ' SELECT %s, COALESCE(max(version), 0) + 1, %s, %s'
            ' FROM harness.platform_configs WHERE organization_id = %s'
            ' RETURNING *',
            (
                organization_id,
                pg_json.Jsonb(config),
                created_by,
                organization_id,
            ),
        )
        if row is None:  # pragma: no cover - RETURNING yields a row
            raise RuntimeError('platform config insert returned no row')
        return row

    # --- Marketplaces --------------------------------------------------

    async def marketplaces(self, organization_id: str) -> list[Row]:
        """Return the marketplaces of an organization, by slug."""
        return await self._fetch_all(
            'SELECT * FROM harness.marketplaces WHERE organization_id = %s'
            ' ORDER BY slug',
            (organization_id,),
        )

    async def marketplace(self, organization_id: str, slug: str) -> Row | None:
        return await self._fetch_one(
            'SELECT * FROM harness.marketplaces'
            ' WHERE organization_id = %s AND slug = %s',
            (organization_id, slug),
        )

    async def create_marketplace(
        self, organization_id: str, slug: str, url: str, created_by: str
    ) -> Row:
        """Insert a marketplace.

        Raises:
            MarketplaceExists: The organization has one with this slug.

        """
        try:
            row = await self._fetch_one(
                'INSERT INTO harness.marketplaces'
                ' (id, organization_id, slug, url, created_by)'
                ' VALUES (%s, %s, %s, %s, %s) RETURNING *',
                (uuid.uuid4(), organization_id, slug, url, created_by),
            )
        except psycopg.errors.UniqueViolation as err:
            raise MarketplaceExists(slug) from err
        if row is None:  # pragma: no cover - RETURNING yields a row
            raise RuntimeError('marketplace insert returned no row')
        return row

    async def set_marketplace_sync(
        self, marketplace_id: uuid.UUID, changes: Row
    ) -> Row | None:
        """Record the result of a sync: the catalog, or ``sync_error``."""
        statement = sql.SQL(
            'UPDATE harness.marketplaces SET {sets}, updated_at = NOW()'
            ' WHERE id = %s RETURNING *'
        ).format(
            sets=sql.SQL(', ').join(
                sql.SQL('{} = %s').format(sql.Identifier(column))
                for column in changes
            )
        )
        values = [
            pg_json.Jsonb(value) if column == 'plugins' else value
            for column, value in changes.items()
        ]
        return await self._fetch_one(statement, (*values, marketplace_id))

    async def delete_marketplace(
        self, organization_id: str, slug: str
    ) -> bool:
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                'DELETE FROM harness.marketplaces'
                ' WHERE organization_id = %s AND slug = %s',
                (organization_id, slug),
            )
            return cursor.rowcount > 0

    async def binding_provider_type(
        self, organization_id: str, reference: str
    ) -> str | None:
        """Return the provider type of a secret binding, or ``None``
        when the organization has no binding with ``reference``."""
        row = await self._fetch_one(
            'SELECT p.type FROM secrets.bindings AS b'
            ' JOIN secrets.providers AS p ON p.id = b.provider_id'
            ' WHERE b.organization_id = %s AND b.reference = %s',
            (organization_id, reference),
        )
        return None if row is None else str(row['type'])

    # --- Lease sweep ---------------------------------------------------

    async def expire_leases(self) -> list[Row]:
        """Mark each live runner with an expired lease as lost.

        A runner with no chain goes ``offline``. A runner with a chain
        is ``fenced``, and its running chain goes to ``fencing`` with
        the next attempt, so its agent tokens stop working. Return the
        chains that went to ``fencing``.
        """
        async with self._pool.connection() as conn, conn.transaction():
            lost = await _fetch_all(
                conn,
                'UPDATE harness.runners SET state = CASE WHEN chain_id IS'
                " NULL THEN 'offline' ELSE 'fenced' END, offline_at = NOW()"
                " WHERE state IN ('idle', 'busy')"
                ' AND lease_expires_at < NOW() RETURNING id',
                (),
            )
            if not lost:
                return []
            return await _fetch_all(
                conn,
                "UPDATE harness.chains SET state = 'fencing',"
                ' attempt = attempt + 1, fenced_at = NOW(),'
                ' updated_at = NOW()'
                " WHERE state = 'running' AND runner_id = ANY(%s)"
                ' RETURNING *',
                ([row['id'] for row in lost],),
            )

    async def fencing_chains(self) -> list[Row]:
        """Return the chains that wait on fencers or the grace period."""
        return await self._fetch_all(
            'SELECT * FROM harness.chains'
            " WHERE state IN ('fencing', 'stuck') ORDER BY fenced_at",
            (),
        )

    async def set_fence_result(
        self, chain: Row, error: str | None
    ) -> Row | None:
        """Record the fencer result of a chain attempt.

        With no ``error`` the chain waits for the grace period; with
        one it is ``stuck``.
        """
        return await self._fetch_one(
            'UPDATE harness.chains SET state = %s, fence_error = %s,'
            ' fencers_ok_at = CASE WHEN %s THEN NOW() END,'
            ' updated_at = NOW() WHERE root_task_id = %s AND attempt = %s'
            " AND state IN ('fencing', 'stuck') RETURNING *",
            (
                'stuck' if error else 'fencing',
                error,
                error is None,
                chain['root_task_id'],
                chain['attempt'],
            ),
        )

    async def requeue(self, chain_id: uuid.UUID) -> bool:
        """Put a fenced chain back in the queue after the grace period.

        The fencers must have succeeded and :data:`GRACE_SECONDS` must
        have passed since the runner was lost. Each open task of the
        chain gets an ``attempt_marker`` event. Return ``False`` and
        change nothing when the chain is not ready.
        """
        async with self._pool.connection() as conn:
            async with conn.transaction():
                chain = await _fetch_one(
                    conn,
                    'SELECT * FROM harness.chains WHERE root_task_id = %s'
                    " AND state = 'fencing' AND fencers_ok_at IS NOT NULL"
                    ' AND fenced_at <= NOW() - make_interval(secs => %s)'
                    ' FOR UPDATE',
                    (chain_id, GRACE_SECONDS),
                )
                if chain is None:
                    return False
                published = await task_store.requeue_chain(
                    conn, chain_id, chain['attempt'], _SYSTEM
                )
                state: ChainState = (
                    'queued' if await _chain_open(conn, chain_id) else 'done'
                )
                await conn.execute(
                    'UPDATE harness.chains SET state = %s, runner_id = NULL,'
                    ' updated_at = NOW() WHERE root_task_id = %s',
                    (state, chain_id),
                )
                await conn.execute(
                    "UPDATE harness.runners SET state = 'offline'"
                    " WHERE id = %s AND state = 'fenced'",
                    (chain['runner_id'],),
                )
        for task, events in published:
            await log.publish(task, events)
        return True

    async def prune(self, days: int = 7) -> None:
        """Delete offline runners and tool call windows older than
        ``days``."""
        async with self._pool.connection() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM harness.runners WHERE state = 'offline'"
                ' AND last_heartbeat < NOW() - make_interval(days => %s)',
                (days,),
            )
            await conn.execute(
                'DELETE FROM harness.tool_call_counts'
                ' WHERE window_start < NOW() - make_interval(days => %s)',
                (days,),
            )

    # --- Helpers -------------------------------------------------------

    async def _lock_idle(self, conn: Conn, runner_id: uuid.UUID) -> Row:
        """Lock an idle runner; return the labels and allowlist of its
        pool as they are now."""
        row = await _fetch_one(
            conn,
            'SELECT r.state, p.labels, p.organization_ids'
            ' FROM harness.runners AS r'
            ' JOIN harness.pools AS p ON p.name = r.pool'
            ' WHERE r.id = %s FOR UPDATE OF r FOR SHARE OF p',
            (runner_id,),
        )
        if row is None or row['state'] != 'idle':
            raise RunnerBusy(str(runner_id))
        return row

    async def _fetch_one(
        self, query: _Query, params: typing.Any
    ) -> Row | None:
        async with self._pool.connection() as conn:
            return await _fetch_one(conn, query, params)

    async def _fetch_all(self, query: _Query, params: typing.Any) -> list[Row]:
        async with self._pool.connection() as conn:
            return await _fetch_all(conn, query, params)


async def _record_claim(
    conn: Conn, task: Row, chain: Row, runner_id: uuid.UUID
) -> None:
    await conn.execute(
        'INSERT INTO harness.claims (task_id, attempt, chain_id, runner_id)'
        ' VALUES (%s, %s, %s, %s)',
        (task['id'], chain['attempt'], chain['root_task_id'], runner_id),
    )


async def _chain_open(conn: Conn, chain_id: uuid.UUID) -> bool:
    """Return whether a task of the chain is not closed."""
    cursor = await conn.execute(
        'SELECT EXISTS (SELECT 1 FROM agent_runtime.tasks'
        ' WHERE (chain_id = %s OR (chain_id IS NULL AND id = %s))'
        " AND status <> 'closed')",
        (chain_id, chain_id),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def _fetch_one(
    conn: Conn, query: _Query, params: typing.Any
) -> Row | None:
    async with conn.cursor(row_factory=rows.dict_row) as cursor:
        await cursor.execute(query, params)
        return await cursor.fetchone()


async def _fetch_all(
    conn: Conn, query: _Query, params: typing.Any
) -> list[Row]:
    async with conn.cursor(row_factory=rows.dict_row) as cursor:
        await cursor.execute(query, params)
        return await cursor.fetchall()
