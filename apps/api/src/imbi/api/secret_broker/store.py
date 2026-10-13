"""Postgres repository for secret providers, bindings, and grants.

Every query is scoped to one organization. Deletion rules (plan 9.3):

- A provider that a binding uses cannot be deleted: the foreign key
  from ``bindings`` refuses it.
- A binding that a grant or an active resolution uses cannot be
  deleted. The delete locks the binding row ``FOR UPDATE``; a new
  resolution and a grant write lock it ``FOR SHARE``, so nothing starts
  to use the binding between the check and the delete.
"""

import typing
import uuid

import psycopg
import psycopg.errors
from psycopg import rows, sql
from psycopg.types import json as pg_json

from imbi.api.secret_broker import broker

SCHEMA = 'secrets'

Table = typing.Literal['providers', 'bindings', 'grants']
Row = broker.Row


class InUse(ValueError):
    """The row is in use. The message says by what."""


class RoleInUse(ValueError):
    """A provider in another organization uses the role."""


class UnknownBindings(ValueError):
    """A grant names a binding that is not in the organization."""


def _value(value: typing.Any) -> typing.Any:
    return pg_json.Jsonb(value) if isinstance(value, dict) else value


class SecretStore:
    def __init__(self, pool: broker.Pool) -> None:
        self._pool = pool

    async def _all(
        self, query: sql.Composed | str, params: typing.Any
    ) -> list[Row]:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(query, params)  # pyright: ignore[reportArgumentType]
            return await cur.fetchall()

    async def list_all(self, table: Table, organization_id: str) -> list[Row]:
        order = 'reference' if table == 'bindings' else 'created_at'
        return await self._all(
            sql.SQL(
                'SELECT * FROM {table} WHERE organization_id = %s'
                ' ORDER BY {order}'
            ).format(
                table=sql.Identifier(SCHEMA, table),
                order=sql.Identifier(order),
            ),
            (organization_id,),
        )

    async def get(
        self, table: Table, organization_id: str, row_id: uuid.UUID
    ) -> Row | None:
        found = await self._all(
            sql.SQL(
                'SELECT * FROM {table} WHERE organization_id = %s AND id = %s'
            ).format(table=sql.Identifier(SCHEMA, table)),
            (organization_id, row_id),
        )
        return found[0] if found else None

    async def create(
        self, table: Table, organization_id: str, values: Row
    ) -> Row:
        """Insert a row and return it.

        Raises:
            psycopg.errors.UniqueViolation: A name or reference is in use.
            UnknownBindings: A grant names a binding not in the org.

        """
        values = {
            'id': uuid.uuid4(),
            'organization_id': organization_id,
            **values,
        }
        query = sql.SQL(
            'INSERT INTO {table} ({cols}) VALUES ({vals}) RETURNING *'
        ).format(
            table=sql.Identifier(SCHEMA, table),
            cols=sql.SQL(', ').join(map(sql.Identifier, values)),
            vals=sql.SQL(', ').join(sql.Placeholder() * len(values)),
        )
        async with (
            self._pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            if table == 'grants':
                await _lock_bindings(
                    cur, organization_id, values['binding_ids']
                )
            if table == 'providers':
                await _check_role(cur, organization_id, values.get('config'))
            await cur.execute(query, [_value(v) for v in values.values()])
            return typing.cast(Row, await cur.fetchone())

    async def update(
        self,
        table: Table,
        organization_id: str,
        row_id: uuid.UUID,
        changes: Row,
    ) -> Row | None:
        """Change a row; return it, or ``None`` when it is not there.

        Raises:
            psycopg.errors.UniqueViolation: A name is in use.
            UnknownBindings: A grant names a binding not in the org.

        """
        query = sql.SQL(
            'UPDATE {table} SET {sets}updated_at = NOW()'
            ' WHERE organization_id = %s AND id = %s RETURNING *'
        ).format(
            table=sql.Identifier(SCHEMA, table),
            sets=sql.SQL('').join(
                sql.SQL('{} = %s, ').format(sql.Identifier(name))
                for name in changes
            ),
        )
        async with (
            self._pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            if table == 'grants' and 'binding_ids' in changes:
                await _lock_bindings(
                    cur, organization_id, changes['binding_ids']
                )
            if table == 'providers':
                await _check_role(cur, organization_id, changes.get('config'))
            await cur.execute(
                query,
                [
                    *(_value(v) for v in changes.values()),
                    organization_id,
                    row_id,
                ],
            )
            return await cur.fetchone()

    async def set_health(
        self,
        organization_id: str,
        provider_id: uuid.UUID,
        status: str,
        reason: str | None,
    ) -> Row | None:
        found = await self._all(
            'UPDATE secrets.providers SET health_status = %s,'
            ' health_reason = %s, health_checked_at = NOW()'
            ' WHERE organization_id = %s AND id = %s RETURNING *',
            (status, reason, organization_id, provider_id),
        )
        return found[0] if found else None

    async def delete(
        self, table: Table, organization_id: str, row_id: uuid.UUID
    ) -> bool:
        """Delete a row; return ``False`` when it is not there.

        Raises:
            InUse: A binding uses the provider, or a grant or an active
                resolution uses the binding.

        """
        async with self._pool.connection() as conn, conn.transaction():
            if table == 'bindings':
                await _check_binding_unused(conn, organization_id, row_id)
            try:
                cur = await conn.execute(
                    sql.SQL(
                        'DELETE FROM {table}'
                        ' WHERE organization_id = %s AND id = %s'
                    ).format(table=sql.Identifier(SCHEMA, table)),
                    (organization_id, row_id),
                )
            except (
                psycopg.errors.ForeignKeyViolation,
                psycopg.errors.RestrictViolation,
            ):
                raise InUse('A binding uses the provider') from None
            return cur.rowcount > 0

    async def evaluate(
        self,
        organization_id: str,
        agent_id: str,
        project_id: str | None,
        reference: broker.Reference,
        purpose: str,
        delivery_mode: str,
        ttl_seconds: int,
        delivery_target: str | None = None,
    ) -> broker.Decision:
        """The grant decision for a request. No provider call.

        Raises:
            BrokerError: The request is denied.

        """
        async with self._pool.connection() as conn:
            return await broker.evaluate(
                conn,
                organization_id,
                agent_id,
                project_id,
                reference,
                purpose,
                delivery_mode,
                ttl_seconds,
                delivery_target,
            )

    async def resolutions(
        self,
        organization_id: str,
        *,
        state: str | None,
        task_id: uuid.UUID | None,
        limit: int,
    ) -> list[Row]:
        """Return resolutions, newest first."""
        return await self._all(
            'SELECT * FROM secrets.resolutions WHERE organization_id = %s'
            ' AND (%s::TEXT IS NULL OR state = %s)'
            ' AND (%s::UUID IS NULL OR task_id = %s)'
            ' ORDER BY created_at DESC LIMIT %s',
            (organization_id, state, state, task_id, task_id, limit),
        )

    async def resolution(
        self, organization_id: str, resolution_id: uuid.UUID
    ) -> Row | None:
        found = await self._all(
            'SELECT * FROM secrets.resolutions'
            ' WHERE organization_id = %s AND id = %s',
            (organization_id, resolution_id),
        )
        return found[0] if found else None


async def _check_binding_unused(
    conn: broker.Conn, organization_id: str, binding_id: uuid.UUID
) -> None:
    await conn.execute(
        'SELECT id FROM secrets.bindings'
        ' WHERE organization_id = %s AND id = %s FOR UPDATE',
        (organization_id, binding_id),
    )
    cur = await conn.execute(
        'SELECT 1 FROM secrets.grants WHERE %s = ANY(binding_ids) LIMIT 1',
        (binding_id,),
    )
    if await cur.fetchone() is not None:
        raise InUse('A grant uses the binding')
    cur = await conn.execute(
        'SELECT 1 FROM secrets.resolutions WHERE binding_id = %s'
        " AND state IN ('pending', 'active') LIMIT 1",
        (binding_id,),
    )
    if await cur.fetchone() is not None:
        raise InUse('An active resolution uses the binding')


async def _check_role(
    cur: psycopg.AsyncCursor[Row],
    organization_id: str,
    config: dict[str, typing.Any] | None,
) -> None:
    """One AWS role belongs to one organization.

    A transaction lock on the role name serializes two organizations
    that write the same role at the same time.
    """
    role = (config or {}).get('role_arn')
    if not role:
        return
    await cur.execute(
        'SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
        (f'secrets.role_arn:{role}',),
    )
    await cur.execute(
        "SELECT 1 FROM secrets.providers WHERE config->>'role_arn' = %s"
        ' AND organization_id <> %s LIMIT 1',
        (role, organization_id),
    )
    if await cur.fetchone() is not None:
        # Generic: the message must not say that another tenant has it.
        raise RoleInUse('This role cannot be used')


async def _lock_bindings(
    cur: psycopg.AsyncCursor[Row],
    organization_id: str,
    binding_ids: list[uuid.UUID],
) -> None:
    """Lock the bindings of a grant; each must be in the organization."""
    await cur.execute(
        'SELECT id FROM secrets.bindings'
        ' WHERE organization_id = %s AND id = ANY(%s) FOR SHARE',
        (organization_id, binding_ids),
    )
    if len(await cur.fetchall()) != len(set(binding_ids)):
        raise UnknownBindings('A binding is not in the organization')
