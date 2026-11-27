"""Per-user UI preferences (Slack App Home PRD, section 6.1).

The ``preferences`` schema holds one row for each user and namespace.
It is a plain Postgres schema next to the graph: the declarative
``schemata.toml`` is applied on every start. The queries use the
connection of the graph pool, under :func:`lock_key`.
"""

import contextlib
import datetime
import enum
import pathlib
import typing
from collections import abc

import psycopg
import pydantic
from psycopg import rows
from psycopg.types import json as pg_json

from imbi.common import relational

SCHEMA = 'preferences'
SCHEMATA_PATH = pathlib.Path(__file__).parent / 'schemata.toml'

type Connection = psycopg.AsyncConnection[typing.Any]


class Namespace(enum.StrEnum):
    """The preference namespaces. Each has a model of its value."""

    slack_home = 'slack_home'


SectionKey = typing.Literal[
    'needs_attention',
    'my_tickets',
    'pull_requests',
    'merged_not_deployed',
    'release_drift',
    'my_projects',
    'agent_activity',
    'document_comments',
]

#: The default order of the Slack App Home sections.
DEFAULT_ORDER: tuple[SectionKey, ...] = typing.get_args(SectionKey)


class SlackHomeSection(pydantic.BaseModel):
    display: typing.Literal['expanded', 'collapsed', 'hidden'] = 'expanded'


class SlackHomePreferences(pydantic.BaseModel):
    """The layout of the Slack App Home tab of one user."""

    order: list[SectionKey] = pydantic.Field(
        default_factory=lambda: list(DEFAULT_ORDER)
    )
    sections: dict[SectionKey, SlackHomeSection] = pydantic.Field(
        default_factory=dict
    )
    hide_empty: bool = True
    max_items: typing.Literal[5, 10] = 5
    count_expanded_only: bool = False

    @pydantic.model_validator(mode='after')
    def _check_and_normalize(self) -> typing.Self:
        """Refuse a hidden ``needs_attention`` and a repeated order key.

        Add the keys that are not in ``order`` at the end, in the
        default order. A stored value is validated again on read, so a
        section added in a later release also gets its place.
        """
        section = self.sections.get('needs_attention')
        if section is not None and section.display == 'hidden':
            raise ValueError('needs_attention cannot be hidden')
        if len(set(self.order)) != len(self.order):
            raise ValueError('order must hold each section key once')
        missing: list[SectionKey] = [
            key for key in DEFAULT_ORDER if key not in self.order
        ]
        self.order.extend(missing)
        return self


class SlackHomePreferencesWrite(pydantic.BaseModel):
    value: SlackHomePreferences
    #: The stored version, or 0 when no value is stored yet.
    version: int = pydantic.Field(ge=0)


class SlackHomePreferencesResponse(pydantic.BaseModel):
    value: SlackHomePreferences
    version: int
    updated_at: datetime.datetime


def lock_key(email: str) -> str:
    """Return the advisory lock key for the preferences of ``email``."""
    return f'imbi.api.preferences.{email}'


async def get(
    conn: Connection, email: str, namespace: Namespace
) -> dict[str, typing.Any] | None:
    """Return the stored row, or ``None``."""
    async with conn.cursor(row_factory=rows.dict_row) as cur:
        await cur.execute(
            'SELECT value, version, updated_at'
            ' FROM preferences.user_preferences'
            ' WHERE email = %s AND namespace = %s',
            (email, namespace.value),
        )
        return await cur.fetchone()


async def put(
    conn: Connection,
    email: str,
    namespace: Namespace,
    value: dict[str, typing.Any],
    version: int,
) -> dict[str, typing.Any] | None:
    """Write ``value`` if ``version`` is the stored version.

    Version 0 creates the row with version 1. Return the new row, or
    ``None`` when ``version`` is not the stored version.
    """
    async with conn.cursor(row_factory=rows.dict_row) as cur:
        if version == 0:
            await cur.execute(
                'INSERT INTO preferences.user_preferences'
                ' (email, namespace, value) VALUES (%s, %s, %s)'
                ' ON CONFLICT DO NOTHING'
                ' RETURNING value, version, updated_at',
                (email, namespace.value, pg_json.Jsonb(value)),
            )
        else:
            await cur.execute(
                'UPDATE preferences.user_preferences'
                ' SET value = %s, version = version + 1, updated_at = NOW()'
                ' WHERE email = %s AND namespace = %s AND version = %s'
                ' RETURNING value, version, updated_at',
                (pg_json.Jsonb(value), email, namespace.value, version),
            )
        return await cur.fetchone()


async def delete_user(conn: Connection, email: str) -> None:
    """Delete every row of ``email``."""
    await conn.execute(
        'DELETE FROM preferences.user_preferences WHERE email = %s',
        (email,),
    )


async def initialize() -> None:
    """Create the ``preferences`` schema and its table."""
    await relational.initialize(
        SCHEMA,
        relational.load_schemata(SCHEMATA_PATH),
        f'imbi.api.initialize.{SCHEMA}',
    )


@contextlib.asynccontextmanager
async def schema_lifespan() -> abc.AsyncGenerator[None]:
    """Apply the schema on startup."""
    await initialize()
    yield
