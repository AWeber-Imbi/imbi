"""Postgres repository for workflow definitions (ADR 0021).

A workflow row and its versions change in one transaction. The
``UPDATE`` of a save locks the workflow row, so concurrent saves get
consecutive version numbers.
"""

import dataclasses
import typing
import uuid

import psycopg
import psycopg_pool
from psycopg import rows
from psycopg.types import json as pg_json

type Pool = psycopg_pool.AsyncConnectionPool[
    psycopg.AsyncConnection[typing.Any]
]
type Row = dict[str, typing.Any]

SCHEMA = 'workflows'

#: A workflow with its latest version.
_SELECT = (
    'SELECT w.*, v.graph, v.settings, v.validation,'
    ' v.created_by AS version_created_by,'
    ' v.created_at AS version_created_at'
    ' FROM workflows.workflows AS w'
    ' JOIN workflows.workflow_versions AS v'
    ' ON v.workflow_id = w.id AND v.version = w.latest_version'
    ' WHERE w.organization_id = %s'
)

_INSERT_VERSION = (
    'INSERT INTO workflows.workflow_versions'
    ' (workflow_id, version, graph, settings, validation, created_by)'
    ' VALUES (%s, %s, %s, %s, %s, %s)'
)


@dataclasses.dataclass(frozen=True)
class Definition:
    """The values that a create or a save writes."""

    name: str
    description: str
    owner_team_id: str
    graph: dict[str, typing.Any]
    settings: dict[str, typing.Any]
    validation: dict[str, typing.Any]
    author: str


class WorkflowStore:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def _one(
        self, query: str, params: tuple[typing.Any, ...]
    ) -> Row | None:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(query, params)  # pyright: ignore[reportArgumentType]
            return await cur.fetchone()

    async def _all(
        self, query: str, params: tuple[typing.Any, ...]
    ) -> list[Row]:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cur,
        ):
            await cur.execute(query, params)  # pyright: ignore[reportArgumentType]
            return await cur.fetchall()

    async def list_all(self, organization_id: str) -> list[Row]:
        """Return the workflows of the organization, by name."""
        return await self._all(
            _SELECT + ' ORDER BY w.name, w.slug', (organization_id,)
        )

    async def get(self, organization_id: str, slug: str) -> Row | None:
        return await self._one(
            _SELECT + ' AND w.slug = %s', (organization_id, slug)
        )

    async def create(
        self, organization_id: str, slug: str, definition: Definition
    ) -> None:
        """Write a workflow and its version 1.

        Raises:
            psycopg.errors.UniqueViolation: The slug is in use.

        """
        workflow_id = uuid.uuid4()
        async with self._pool.connection() as conn, conn.transaction():
            await conn.execute(
                'INSERT INTO workflows.workflows (id, organization_id,'
                ' slug, name, description, owner_team_id, created_by)'
                ' VALUES (%s, %s, %s, %s, %s, %s, %s)',
                (
                    workflow_id,
                    organization_id,
                    slug,
                    definition.name,
                    definition.description,
                    definition.owner_team_id,
                    definition.author,
                ),
            )
            await conn.execute(
                _INSERT_VERSION, _version_values(workflow_id, 1, definition)
            )

    async def save(
        self,
        organization_id: str,
        slug: str,
        definition: Definition,
        owner_team_id: str,
    ) -> bool:
        """Write a new version.

        ``owner_team_id`` is the owner team that the caller checked. The
        save changes nothing and returns ``False`` when there is no
        workflow, or when its owner team is no longer that team.
        """
        async with self._pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                'UPDATE workflows.workflows SET name = %s,'
                ' description = %s, owner_team_id = %s,'
                ' latest_version = latest_version + 1, updated_at = NOW()'
                ' WHERE organization_id = %s AND slug = %s'
                ' AND owner_team_id = %s'
                ' RETURNING id, latest_version',
                (
                    definition.name,
                    definition.description,
                    definition.owner_team_id,
                    organization_id,
                    slug,
                    owner_team_id,
                ),
            )
            row = await cur.fetchone()
            if row is None:
                return False
            await conn.execute(
                _INSERT_VERSION, _version_values(row[0], row[1], definition)
            )
        return True

    async def delete(self, organization_id: str, slug: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                'DELETE FROM workflows.workflows'
                ' WHERE organization_id = %s AND slug = %s',
                (organization_id, slug),
            )
            return cur.rowcount > 0

    async def versions(self, organization_id: str, slug: str) -> list[Row]:
        """Return the versions of a workflow, newest first."""
        return await self._all(
            'SELECT v.* FROM workflows.workflow_versions AS v'
            ' JOIN workflows.workflows AS w ON w.id = v.workflow_id'
            ' WHERE w.organization_id = %s AND w.slug = %s'
            ' ORDER BY v.version DESC',
            (organization_id, slug),
        )

    async def version(
        self, organization_id: str, slug: str, version: int
    ) -> Row | None:
        return await self._one(
            'SELECT v.* FROM workflows.workflow_versions AS v'
            ' JOIN workflows.workflows AS w ON w.id = v.workflow_id'
            ' WHERE w.organization_id = %s AND w.slug = %s'
            ' AND v.version = %s',
            (organization_id, slug, version),
        )

    async def activate(
        self, organization_id: str, slug: str, version: int, email: str
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE workflows.workflows SET status = 'active',"
                ' active_version = %s, activated_by = %s,'
                ' activated_at = NOW(), updated_at = NOW()'
                ' WHERE organization_id = %s AND slug = %s',
                (version, email, organization_id, slug),
            )

    async def pause(self, organization_id: str, slug: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE workflows.workflows SET status = 'paused',"
                ' updated_at = NOW()'
                ' WHERE organization_id = %s AND slug = %s',
                (organization_id, slug),
            )


def _version_values(
    workflow_id: uuid.UUID, version: int, definition: Definition
) -> tuple[typing.Any, ...]:
    return (
        workflow_id,
        version,
        pg_json.Jsonb(definition.graph),
        pg_json.Jsonb(definition.settings),
        pg_json.Jsonb(definition.validation),
        definition.author,
    )
