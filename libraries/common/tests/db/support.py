"""Helpers for the tests of ``imbi.common.db``.

The tests use the relational database of the test process, which
:func:`imbi.common.testing.databases.isolated_database` copies from
``imbi_template``, and three logins:

- ``DATABASE_URL``: ``imbi_app``, the login under test.
- ``ADMIN_DATABASE_URL``: ``imbi_admin``, the login under test.
- ``MAINTENANCE_DATABASE_URL``: ``imbi_maintenance``. The tests use it
  only to add and remove their rows, because it bypasses row-level
  security.

"""

import dataclasses
import os
import unittest
import uuid

import psycopg
from psycopg import sql

from imbi.common import db
from imbi.common.testing import databases


def env_url(name: str) -> str:
    """Return the URL in *name*, for the database of this process."""
    databases.isolated_database()
    return os.environ[name]


def new_id(prefix: str) -> str:
    """Return a new id that is also a valid slug."""
    return f'{prefix}-{uuid.uuid4().hex[:12]}'


@dataclasses.dataclass(frozen=True)
class Seed:
    """The rows that :func:`seed` adds.

    Organization ``a`` has a membership for the user, organization ``b``
    has none. Each organization has an integration, and there is one
    instance sign-in provider (an integration with no organization).

    """

    tenant: str = dataclasses.field(default_factory=lambda: new_id('t'))
    org_a: str = dataclasses.field(default_factory=lambda: new_id('oa'))
    org_b: str = dataclasses.field(default_factory=lambda: new_id('ob'))
    role_a: str = dataclasses.field(default_factory=lambda: new_id('ra'))
    role_b: str = dataclasses.field(default_factory=lambda: new_id('rb'))
    user: str = dataclasses.field(default_factory=lambda: new_id('u'))
    plugin: str = dataclasses.field(default_factory=lambda: new_id('p'))
    integration_a: str = dataclasses.field(
        default_factory=lambda: new_id('ia')
    )
    integration_b: str = dataclasses.field(
        default_factory=lambda: new_id('ib')
    )
    integration_instance: str = dataclasses.field(
        default_factory=lambda: new_id('in')
    )

    @property
    def organizations(self) -> list[str]:
        return [self.org_a, self.org_b]

    @property
    def integrations(self) -> list[str]:
        return [
            self.integration_a,
            self.integration_b,
            self.integration_instance,
        ]


async def maintenance() -> psycopg.AsyncConnection[tuple[object, ...]]:
    """Connect as ``imbi_maintenance``, with autocommit."""
    return await psycopg.AsyncConnection.connect(
        env_url('MAINTENANCE_DATABASE_URL'), autocommit=True
    )


async def seed() -> Seed:
    """Add the rows of a new :class:`Seed`."""
    s = Seed()
    async with await maintenance() as conn:
        await conn.execute(
            'INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)',
            (s.tenant, 'Tenant', s.tenant),
        )
        for org in s.organizations:
            await conn.execute(
                'INSERT INTO organizations (id, tenant_id, name, slug)'
                ' VALUES (%s, %s, %s, %s)',
                (org, s.tenant, org, org),
            )
        for org, role in ((s.org_a, s.role_a), (s.org_b, s.role_b)):
            await conn.execute(
                'INSERT INTO roles (id, organization_id, name, slug)'
                ' VALUES (%s, %s, %s, %s)',
                (role, org, 'Member', 'member'),
            )
        await conn.execute(
            "INSERT INTO principals (id, principal_type) VALUES (%s, 'user')",
            (s.user,),
        )
        await conn.execute(
            'INSERT INTO users (id, email, display_name) VALUES (%s, %s, %s)',
            (s.user, f'{s.user}@example.com', 'User'),
        )
        await conn.execute(
            'INSERT INTO memberships (organization_id, principal_id, role_id)'
            ' VALUES (%s, %s, %s)',
            (s.org_a, s.user, s.role_a),
        )
        await conn.execute(
            'INSERT INTO plugin_registrations (slug) VALUES (%s)',
            (s.plugin,),
        )
        for org, integration in (
            (s.org_a, s.integration_a),
            (s.org_b, s.integration_b),
            (None, s.integration_instance),
        ):
            await conn.execute(
                'INSERT INTO integrations'
                ' (id, organization_id, plugin_slug, name, slug)'
                ' VALUES (%s, %s, %s, %s, %s)',
                (integration, org, s.plugin, integration, integration),
            )
    return s


async def unseed(s: Seed) -> None:
    """Remove the rows of *s*, and the rows that a test added to them."""
    async with await maintenance() as conn:
        for table in ('tags', 'integrations', 'memberships', 'roles'):
            await conn.execute(
                sql.SQL(
                    'DELETE FROM {} WHERE organization_id = ANY(%s)'
                ).format(sql.Identifier(table)),
                (s.organizations,),
            )
        await conn.execute(
            'DELETE FROM integrations WHERE plugin_slug = %s', (s.plugin,)
        )
        await conn.execute(
            'DELETE FROM organizations WHERE id = ANY(%s)', (s.organizations,)
        )
        await conn.execute('DELETE FROM tenants WHERE id = %s', (s.tenant,))
        await conn.execute('DELETE FROM users WHERE id = %s', (s.user,))
        await conn.execute(
            'DELETE FROM plugin_registrations WHERE slug = %s', (s.plugin,)
        )


class DatabaseTestCase(unittest.IsolatedAsyncioTestCase):
    """Seed the rows, and open a :class:`imbi.common.db.Database`."""

    seed: Seed
    database: db.Database

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        env_url('DATABASE_URL')
        env_url('ADMIN_DATABASE_URL')
        self.seed = await seed()
        self.addAsyncCleanup(unseed, self.seed)
        self.database = db.Database()
        await self.database.open()
        self.addAsyncCleanup(self.database.close)
