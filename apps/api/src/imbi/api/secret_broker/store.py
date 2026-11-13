"""Postgres repository for secret providers, bindings, and grants.

Every query is scoped to one organization. Deletion rules (plan 9.3):

- A provider that a binding uses cannot be deleted: the foreign key
  from ``bindings`` refuses it. A binding can only use a provider of
  its own organization.
- A binding that a grant, an active resolution, or a resolution with
  an unrevoked provider lease uses cannot be deleted. The delete locks
  the binding row ``FOR UPDATE``; a new resolution and a grant write
  lock it ``FOR SHARE``, so nothing starts to use the binding between
  the check and the delete.
"""

import typing
import uuid
from collections import abc

import psycopg
import psycopg.errors
from psycopg import rows, sql
from psycopg.types import json as pg_json

from imbi.api.secret_broker import audit, broker
from imbi.common import relational

SCHEMA = 'secrets'

Table = typing.Literal['providers', 'bindings', 'grants']
Row = broker.Row


class InUse(ValueError):
    """The row is in use. The message says by what."""


class RoleInUse(ValueError):
    """A provider in another organization uses the role."""


class UnknownProvider(ValueError):
    """A binding names a provider that is not in the organization."""


class UnknownBindings(ValueError):
    """A grant names a binding that is not in the organization."""


class ProviderKeyBinding(ValueError):
    """A grant names a provider key binding. The broker never gives
    such a binding to a task."""


def _value(value: typing.Any) -> typing.Any:
    return pg_json.Jsonb(value) if isinstance(value, dict) else value


#: Builds the audit event of a change from the changed row. A write
#: method adds it to the outbox in its own transaction, so a change and
#: its audit event commit together, or neither does.
type AuditEvent = abc.Callable[[Row], audit.Event]


async def _audit(
    conn: broker.Conn, event: AuditEvent | None, row: Row | None
) -> None:
    if event is not None and row is not None:
        await audit.write(conn, [event(row)])


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

    async def binding_by_reference(
        self, organization_id: str, reference: str
    ) -> Row | None:
        """The binding of ``reference`` (without a field), or ``None``."""
        found = await self._all(
            'SELECT * FROM secrets.bindings'
            ' WHERE organization_id = %s AND reference = %s',
            (organization_id, reference),
        )
        return found[0] if found else None

    async def binding_granted(self, binding_id: uuid.UUID) -> bool:
        """Whether a grant names the binding."""
        return bool(await self._all(_GRANTED, (binding_id,)))

    async def _write_one(
        self, query: str, params: typing.Any, event: AuditEvent | None
    ) -> Row | None:
        async with (
            self._pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(query, params)  # pyright: ignore[reportArgumentType]
            row = await cur.fetchone()
            await _audit(conn, event, row)
            return row

    async def mark_provider_key(
        self,
        organization_id: str,
        binding_id: uuid.UUID,
        usage: Row,
        *,
        event: AuditEvent | None = None,
    ) -> Row | None:
        """Set ``provider_key_usage`` of a key binding that has none and
        that no grant names. One statement does the check and the
        write, so of two concurrent marks only the first applies.
        Return the row, or ``None`` when the mark was not written.

        A grant write holds the binding ``FOR SHARE`` until it commits.
        A separate ``FOR UPDATE`` lock first waits for that grant, so
        the grant check of the ``UPDATE`` gets a new snapshot that
        includes it.
        """
        async with (
            self._pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(
                'SELECT 1 FROM secrets.bindings'
                ' WHERE organization_id = %s AND id = %s FOR UPDATE',
                (organization_id, binding_id),
            )
            await cur.execute(
                'UPDATE secrets.bindings SET provider_key_usage = %s,'
                ' updated_at = NOW()'
                ' WHERE organization_id = %s AND id = %s'
                ' AND provider_key_usage IS NULL'
                ' AND NOT EXISTS (SELECT 1 FROM secrets.grants'
                ' WHERE bindings.id = ANY(binding_ids)) RETURNING *',
                (pg_json.Jsonb(usage), organization_id, binding_id),
            )
            row = await cur.fetchone()
            await _audit(conn, event, row)
            return row

    async def add_provider_key_consumer(
        self,
        organization_id: str,
        binding_id: uuid.UUID,
        consumer: uuid.UUID,
        *,
        host: str,
        app_id: str,
        event: AuditEvent | None = None,
    ) -> Row | None:
        """Append ``consumer`` to the consumers of a key binding marked
        for ``host`` and ``app_id``. The append is one statement on the
        stored value, so concurrent appends do not lose a consumer.
        Return the row, or ``None`` when nothing changed.
        """
        return await self._write_one(
            'UPDATE secrets.bindings SET provider_key_usage ='
            " jsonb_set(provider_key_usage, '{consumers}',"
            " COALESCE(provider_key_usage->'consumers', '[]')"
            ' || to_jsonb(%s::text)), updated_at = NOW()'
            ' WHERE organization_id = %s AND id = %s'
            " AND provider_key_usage->>'host' = %s"
            " AND provider_key_usage->>'app_id' = %s"
            " AND NOT COALESCE(provider_key_usage->'consumers', '[]') ? %s"
            ' RETURNING *',
            (
                str(consumer),
                organization_id,
                binding_id,
                host,
                app_id,
                str(consumer),
            ),
            event,
        )

    async def create(
        self,
        table: Table,
        organization_id: str,
        values: Row,
        *,
        event: AuditEvent | None = None,
    ) -> Row:
        """Insert a row and return it, with its audit ``event``.

        Raises:
            psycopg.errors.UniqueViolation: A name or reference is in use.
            UnknownBindings: A grant names a binding not in the org.
            ProviderKeyBinding: A grant names a provider key binding.

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
            await relational.lock_organization_shared(conn, organization_id)
            if table == 'grants':
                await _lock_bindings(
                    cur, organization_id, values['binding_ids']
                )
            if table == 'providers':
                await _check_role(cur, organization_id, values.get('config'))
            if table == 'bindings':
                await _check_provider(
                    cur, organization_id, values['provider_id']
                )
            await cur.execute(query, [_value(v) for v in values.values()])
            row = typing.cast(Row, await cur.fetchone())
            await _audit(conn, event, row)
            return row

    async def update(
        self,
        table: Table,
        organization_id: str,
        row_id: uuid.UUID,
        changes: Row,
        *,
        event: AuditEvent | None = None,
    ) -> Row | None:
        """Change a row; return it, or ``None`` when it is not there.

        The audit ``event`` commits with the change.

        Raises:
            psycopg.errors.UniqueViolation: A name is in use.
            UnknownBindings: A grant names a binding not in the org.
            ProviderKeyBinding: A grant names a provider key binding.
            InUse: The change sets or clears the provider key mark of a
                binding that a grant names.

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
            if table == 'bindings' and 'provider_id' in changes:
                await _check_provider(
                    cur, organization_id, changes['provider_id']
                )
            if table == 'bindings' and 'provider_key_usage' in changes:
                await _check_mark_change(
                    cur, organization_id, row_id, changes['provider_key_usage']
                )
            await cur.execute(
                query,
                [
                    *(_value(v) for v in changes.values()),
                    organization_id,
                    row_id,
                ],
            )
            row = await cur.fetchone()
            await _audit(conn, event, row)
            return row

    async def set_health(
        self,
        organization_id: str,
        provider_id: uuid.UUID,
        status: str,
        reason: str | None,
        *,
        event: AuditEvent | None = None,
    ) -> Row | None:
        async with (
            self._pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(
                'UPDATE secrets.providers SET health_status = %s,'
                ' health_reason = %s, health_checked_at = NOW()'
                ' WHERE organization_id = %s AND id = %s RETURNING *',
                (status, reason, organization_id, provider_id),
            )
            row = await cur.fetchone()
            await _audit(conn, event, row)
            return row

    async def delete(
        self,
        table: Table,
        organization_id: str,
        row_id: uuid.UUID,
        *,
        event: AuditEvent | None = None,
    ) -> bool:
        """Delete a row; return ``False`` when it is not there.

        The audit ``event`` commits with the delete.

        Raises:
            InUse: A binding uses the provider, or a grant or an active
                resolution uses the binding.

        """
        async with self._pool.connection() as conn, conn.transaction():
            if table == 'bindings':
                await _check_binding_unused(conn, organization_id, row_id)
            try:
                async with conn.cursor(row_factory=rows.dict_row) as cur:
                    await cur.execute(
                        sql.SQL(
                            'DELETE FROM {table} WHERE organization_id = %s'
                            ' AND id = %s RETURNING *'
                        ).format(table=sql.Identifier(SCHEMA, table)),
                        (organization_id, row_id),
                    )
                    row = await cur.fetchone()
            except (
                psycopg.errors.ForeignKeyViolation,
                psycopg.errors.RestrictViolation,
            ):
                raise InUse('A binding uses the provider') from None
            await _audit(conn, event, row)
            return row is not None

    async def remove_agent(
        self, organization_id: str, agent_id: str, actor: str
    ) -> None:
        """Remove a deleted agent from every grant of the organization.

        A grant left with no agent matches nothing, so it is deleted.
        """
        await self._remove_from_grants(
            organization_id, 'agent', agent_id, actor
        )

    async def remove_project(
        self, organization_id: str, project_id: str, actor: str
    ) -> None:
        """Remove a deleted project from every grant of the organization.

        A grant left with no project is deleted: an empty
        ``project_ids`` allows every project, so keeping it would widen
        the grant.
        """
        await self._remove_from_grants(
            organization_id, 'project', project_id, actor
        )

    async def _remove_from_grants(
        self,
        organization_id: str,
        kind: typing.Literal['agent', 'project'],
        value: str,
        actor: str,
    ) -> None:
        """Remove ``value`` from ``<kind>_ids`` of every grant of the
        organization, and delete each grant that it leaves empty. The
        audit events commit with the change."""
        async with (
            self._pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(
                sql.SQL(
                    'UPDATE secrets.grants'
                    ' SET {col} = array_remove({col}, %(value)s),'
                    ' updated_at = NOW()'
                    ' WHERE organization_id = %(org)s'
                    ' AND %(value)s = ANY({col})'
                    ' RETURNING id, {col} AS remaining'
                ).format(col=sql.Identifier(f'{kind}_ids')),
                {'value': value, 'org': organization_id},
            )
            changed = await cur.fetchall()
            empty = [r['id'] for r in changed if not r['remaining']]
            if empty:
                await cur.execute(
                    'DELETE FROM secrets.grants WHERE id = ANY(%s)', (empty,)
                )
            await audit.write(
                conn,
                [
                    audit.Event.model_validate(
                        {
                            'organization_id': organization_id,
                            'type': 'secret_grant_deleted'
                            if r['id'] in empty
                            else 'secret_grant_updated',
                            'actor': actor,
                            'grant_id': str(r['id']),
                            f'{kind}_id': value,
                        }
                    )
                    for r in changed
                ],
            )

    async def agent_references(
        self,
        organization_id: str,
        agent_id: str,
        project_ids: abc.Sequence[str] = (),
    ) -> list[Row]:
        """The references that an agent can request for a command in a
        task of ``project_ids``: an enabled grant for the agent and all
        the projects, with ``environment`` delivery, on an enabled binding
        that allows it. The same rules as :func:`broker.evaluate`.

        Each row has the ``reference``, and the ``description`` and
        ``allowed_fields`` of its binding, as hints for the model.
        """
        return await self._all(
            'SELECT DISTINCT b.reference, b.description, b.allowed_fields'  # noqa: S608
            ' FROM secrets.grants g'
            ' JOIN secrets.bindings b ON b.id = ANY(g.binding_ids)'
            ' WHERE g.organization_id = %(org)s AND g.enabled AND b.enabled'
            ' AND b.organization_id = g.organization_id'
            ' AND %(agent)s = ANY(g.agent_ids)'
            " AND 'environment' = ANY(g.delivery_modes)"
            " AND 'environment' = ANY(b.allowed_delivery_modes)"
            ' AND ' + broker.PROJECTS_ALLOWED + ' ORDER BY b.reference',
            {
                'org': organization_id,
                'agent': agent_id,
                'projects': list(project_ids),
            },
        )

    async def evaluate(
        self,
        organization_id: str,
        agent_id: str,
        project_ids: abc.Sequence[str],
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
                project_ids,
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

    async def identity_source(self, organization_id: str) -> Row | None:
        """Return the ``workload_identity`` setting, or ``None``."""
        found = await self._all(
            'SELECT * FROM secrets.identity_sources'
            ' WHERE organization_id = %s',
            (organization_id,),
        )
        return found[0] if found else None

    async def put_identity_source(
        self,
        organization_id: str,
        source_type: str,
        config: Row,
        updated_by: str,
        *,
        event: AuditEvent | None = None,
    ) -> Row:
        """Create or replace the ``workload_identity`` setting."""
        async with (
            self._pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await relational.lock_organization_shared(conn, organization_id)
            await cur.execute(
                'INSERT INTO secrets.identity_sources'
                ' (organization_id, type, config, updated_by)'
                ' VALUES (%s, %s, %s, %s)'
                ' ON CONFLICT (organization_id) DO UPDATE'
                ' SET type = EXCLUDED.type, config = EXCLUDED.config,'
                ' updated_by = EXCLUDED.updated_by, updated_at = NOW()'
                ' RETURNING *',
                (
                    organization_id,
                    source_type,
                    pg_json.Jsonb(config),
                    updated_by,
                ),
            )
            row = typing.cast(Row, await cur.fetchone())
            await _audit(conn, event, row)
            return row

    async def delete_identity_source(
        self, organization_id: str, *, event: AuditEvent | None = None
    ) -> bool:
        """Delete the setting; return ``False`` when it is not there."""
        async with (
            self._pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(
                'DELETE FROM secrets.identity_sources'
                ' WHERE organization_id = %s RETURNING *',
                (organization_id,),
            )
            row = await cur.fetchone()
            await _audit(conn, event, row)
            return row is not None


_GRANTED = 'SELECT 1 FROM secrets.grants WHERE %s = ANY(binding_ids) LIMIT 1'

#: A resolution that is active, or whose provider lease is not revoked.
#: The rows it needs (its binding, provider, and organization) must stay
#: until it settles.
UNSETTLED_RESOLUTION: typing.LiteralString = (
    "(state IN ('pending', 'active')"
    " OR revocation_state IN ('pending', 'failed'))"
)


async def _check_binding_unused(
    conn: broker.Conn, organization_id: str, binding_id: uuid.UUID
) -> None:
    await conn.execute(
        'SELECT id FROM secrets.bindings'
        ' WHERE organization_id = %s AND id = %s FOR UPDATE',
        (organization_id, binding_id),
    )
    cur = await conn.execute(_GRANTED, (binding_id,))
    if await cur.fetchone() is not None:
        raise InUse('A grant uses the binding')
    cur = await conn.execute(
        sql.SQL(
            'SELECT 1 FROM secrets.resolutions WHERE binding_id = %s'
            ' AND {} LIMIT 1'
        ).format(sql.SQL(UNSETTLED_RESOLUTION)),
        (binding_id,),
    )
    if await cur.fetchone() is not None:
        # A lease that is not revoked yet needs the binding, and through
        # it the provider, until the revocation succeeds.
        raise InUse(
            'An active resolution or an unrevoked provider lease uses '
            'the binding'
        )


async def _check_provider(
    cur: psycopg.AsyncCursor[Row],
    organization_id: str,
    provider_id: uuid.UUID,
) -> None:
    """A binding uses a provider of its own organization only."""
    await cur.execute(
        'SELECT 1 FROM secrets.providers'
        ' WHERE organization_id = %s AND id = %s FOR SHARE',
        (organization_id, provider_id),
    )
    if await cur.fetchone() is None:
        raise UnknownProvider('The provider is not in the organization')


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
    """Lock the bindings of a grant; each must be in the organization
    and must not be a provider key binding."""
    await cur.execute(
        'SELECT provider_key_usage FROM secrets.bindings'
        ' WHERE organization_id = %s AND id = ANY(%s) FOR SHARE',
        (organization_id, binding_ids),
    )
    found = await cur.fetchall()
    if len(found) != len(set(binding_ids)):
        raise UnknownBindings('A binding is not in the organization')
    if any(row['provider_key_usage'] for row in found):
        raise ProviderKeyBinding(
            'A provider key binding cannot be granted to a task'
        )


async def _check_mark_change(
    cur: psycopg.AsyncCursor[Row],
    organization_id: str,
    binding_id: uuid.UUID,
    usage: Row | None,
) -> None:
    """The provider key mark of a granted binding does not change. A
    cleared mark gives the private key to the tasks of the grant, and a
    new mark makes the grant useless. A null that stays null is no
    change. The row lock waits for a grant write that holds the binding.
    """
    await cur.execute(
        'SELECT provider_key_usage FROM secrets.bindings'
        ' WHERE organization_id = %s AND id = %s FOR UPDATE',
        (organization_id, binding_id),
    )
    row = await cur.fetchone()
    if not row or not (row['provider_key_usage'] or usage):
        return
    await cur.execute(_GRANTED, (binding_id,))
    if await cur.fetchone() is not None:
        raise InUse(
            'A grant uses the binding; remove it from the grant before '
            'changing the provider key mark'
        )
