"""Tests for the pools and the RLS contexts of ``imbi.common.db``."""

import logging
import os
import typing
import unittest
from unittest import mock
from urllib import parse

import fastapi
from fastapi import testclient
from psycopg import errors as pg_errors
from psycopg import pq

from imbi.common import db, lifespan
from libraries.common.tests.db import support

_MEMBERSHIPS: typing.LiteralString = (
    'SELECT organization_id, principal_id FROM memberships'
    ' WHERE principal_id = %s ORDER BY organization_id'
)
_ORGANIZATIONS: typing.LiteralString = (
    'SELECT id FROM organizations WHERE id = ANY(%s) ORDER BY id'
)
_INTEGRATIONS: typing.LiteralString = (
    'SELECT id FROM integrations WHERE id = ANY(%s) ORDER BY id'
)
_SETTINGS: typing.LiteralString = (
    "SELECT current_setting('imbi.organization_id', true) AS organization,"
    " current_setting('imbi.principal_id', true) AS principal"
)


class ContextTestCase(support.DatabaseTestCase):
    """What ``memberships``, ``organizations``, and ``integrations`` show."""

    async def visible(
        self, tx: db.Transaction
    ) -> tuple[list[tuple[str, str]], list[str], list[str]]:
        conn = tx.connection
        cursor = await conn.execute(_MEMBERSHIPS, (self.seed.user,))
        memberships = [
            (row['organization_id'], row['principal_id'])
            for row in await cursor.fetchall()
        ]
        cursor = await conn.execute(_ORGANIZATIONS, (self.seed.organizations,))
        organizations = [row['id'] for row in await cursor.fetchall()]
        cursor = await conn.execute(_INTEGRATIONS, (self.seed.integrations,))
        integrations = [row['id'] for row in await cursor.fetchall()]
        return memberships, organizations, integrations

    async def test_organization_context(self) -> None:
        s = self.seed
        async with self.database.transaction(s.org_a, s.user) as tx:
            memberships, organizations, integrations = await self.visible(tx)
        self.assertEqual([(s.org_a, s.user)], memberships)
        self.assertEqual([s.org_a], organizations)
        self.assertEqual(
            sorted([s.integration_a, s.integration_instance]), integrations
        )

    async def test_organization_context_without_membership(self) -> None:
        # The context shows the organization's rows. The membership
        # check is the job of the request dependency, not of RLS.
        s = self.seed
        async with self.database.transaction(s.org_b, s.user) as tx:
            memberships, organizations, integrations = await self.visible(tx)
        self.assertEqual([], memberships)
        self.assertEqual([s.org_b], organizations)
        self.assertEqual(
            sorted([s.integration_b, s.integration_instance]), integrations
        )

    async def test_principal_only_context(self) -> None:
        s = self.seed
        async with self.database.transaction(principal_id=s.user) as tx:
            memberships, organizations, integrations = await self.visible(tx)
        self.assertEqual([(s.org_a, s.user)], memberships)
        self.assertEqual([s.org_a], organizations)
        self.assertEqual([s.integration_instance], integrations)

    async def test_no_context(self) -> None:
        async with self.database.transaction() as tx:
            memberships, organizations, integrations = await self.visible(tx)
        self.assertEqual([], memberships)
        self.assertEqual([], organizations)
        self.assertEqual([self.seed.integration_instance], integrations)

    async def test_admin_context(self) -> None:
        s = self.seed
        async with self.database.admin_transaction() as tx:
            cursor = await tx.connection.execute(
                _INTEGRATIONS, (s.integrations,)
            )
            integrations = [row['id'] for row in await cursor.fetchall()]
        self.assertEqual([s.integration_instance], integrations)
        for query, params in (
            (_MEMBERSHIPS, (s.user,)),
            (_ORGANIZATIONS, (s.organizations,)),
        ):
            with self.subTest(query=query):
                async with self.database.admin_transaction() as tx:
                    with self.assertRaises(pg_errors.InsufficientPrivilege):
                        await tx.connection.execute(query, params)

    async def test_admin_context_ignores_an_organization(self) -> None:
        # imbi_admin reaches only the instance sign-in providers,
        # whatever it sets.
        s = self.seed
        async with self.database.admin_transaction() as tx:
            await tx.connection.execute(
                "SELECT set_config('imbi.organization_id', %s, true)",
                (s.org_a,),
            )
            cursor = await tx.connection.execute(
                _INTEGRATIONS, (s.integrations,)
            )
            integrations = [row['id'] for row in await cursor.fetchall()]
        self.assertEqual([s.integration_instance], integrations)

    async def test_admin_transaction_clears_the_organization(self) -> None:
        async with self.database.admin_transaction() as tx:
            cursor = await tx.connection.execute(_SETTINGS)
            row = await cursor.fetchone()
        self.assertEqual({'organization': '', 'principal': ''}, row)


class InstanceSignInProviderTestCase(support.DatabaseTestCase):
    """Only the admin pool can write an integration with no organization."""

    _INSERT: typing.LiteralString = (
        'INSERT INTO integrations (id, organization_id, plugin_slug, name,'
        ' slug) VALUES (%s, NULL, %s, %s, %s)'
    )

    async def test_admin_pool_can_write(self) -> None:
        integration = support.new_id('ix')
        async with self.database.admin_transaction() as tx:
            await tx.connection.execute(
                self._INSERT,
                (integration, self.seed.plugin, integration, integration),
            )
            await tx.commit()
        async with self.database.transaction() as tx:
            cursor = await tx.connection.execute(
                _INTEGRATIONS, ([integration],)
            )
            self.assertEqual([{'id': integration}], await cursor.fetchall())

    async def test_application_pool_cannot_write(self) -> None:
        integration = support.new_id('ix')
        for organization_id in (None, self.seed.org_a):
            with self.subTest(organization_id=organization_id):
                async with self.database.transaction(organization_id) as tx:
                    with self.assertRaises(pg_errors.InsufficientPrivilege):
                        await tx.connection.execute(
                            self._INSERT,
                            (
                                integration,
                                self.seed.plugin,
                                integration,
                                integration,
                            ),
                        )


class TransactionTestCase(support.DatabaseTestCase):
    """Commit, rollback, and the life of the settings."""

    _INSERT_TAG: typing.LiteralString = (
        'INSERT INTO tags (id, organization_id, name, slug)'
        ' VALUES (%s, %s, %s, %s)'
    )
    _TAG: typing.LiteralString = 'SELECT id FROM tags WHERE id = %s'

    async def asyncSetUp(self) -> None:
        # One connection, so that each transaction reuses the
        # connection of the one before it.
        with mock.patch.dict(
            os.environ,
            {'DATABASE_MIN_POOL_SIZE': '1', 'DATABASE_MAX_POOL_SIZE': '1'},
        ):
            await super().asyncSetUp()

    async def tag_exists(self, tag: str) -> bool:
        async with self.database.transaction(self.seed.org_a) as tx:
            cursor = await tx.connection.execute(self._TAG, (tag,))
            return await cursor.fetchone() is not None

    async def test_commit(self) -> None:
        tag = support.new_id('tag')
        async with self.database.transaction(self.seed.org_a) as tx:
            await tx.connection.execute(
                self._INSERT_TAG, (tag, self.seed.org_a, tag, tag)
            )
            await tx.commit()
        self.assertTrue(await self.tag_exists(tag))

    async def test_rollback_unless_committed(self) -> None:
        tag = support.new_id('tag')
        async with self.database.transaction(self.seed.org_a) as tx:
            await tx.connection.execute(
                self._INSERT_TAG, (tag, self.seed.org_a, tag, tag)
            )
        self.assertFalse(await self.tag_exists(tag))

    async def test_rollback_on_error(self) -> None:
        tag = support.new_id('tag')
        with self.assertRaises(ValueError):
            async with self.database.transaction(self.seed.org_a) as tx:
                await tx.connection.execute(
                    self._INSERT_TAG, (tag, self.seed.org_a, tag, tag)
                )
                raise ValueError('stop')
        self.assertFalse(await self.tag_exists(tag))

    async def test_settings_are_local_to_the_transaction(self) -> None:
        s = self.seed
        for commit in (False, True):
            with self.subTest(commit=commit):
                async with self.database.transaction(s.org_a, s.user) as tx:
                    cursor = await tx.connection.execute(_SETTINGS)
                    self.assertEqual(
                        {'organization': s.org_a, 'principal': s.user},
                        await cursor.fetchone(),
                    )
                    if commit:
                        await tx.commit()
                # The same connection, outside of transaction().
                pool = self.database._pool  # pyright: ignore[reportPrivateUsage]
                async with pool.connection() as conn:
                    cursor = await conn.execute(_SETTINGS)
                    row = await cursor.fetchone()
                self.assertEqual({'organization': '', 'principal': ''}, row)

    async def test_connection_finished_after_commit(self) -> None:
        async with self.database.transaction() as tx:
            await tx.commit()
            with self.assertRaises(RuntimeError):
                _ = tx.connection
        with self.assertRaises(RuntimeError):
            _ = tx.connection

    async def test_connection_returned_mid_transaction(self) -> None:
        pool = self.database._pool  # pyright: ignore[reportPrivateUsage]
        conn = await pool.getconn()
        await conn.execute(
            "SELECT set_config('imbi.organization_id', %s, true)",
            (self.seed.org_a,),
        )
        self.assertEqual(
            pq.TransactionStatus.INTRANS, conn.info.transaction_status
        )
        with self.assertLogs('psycopg.pool', logging.WARNING) as logs:
            await pool.putconn(conn)
        self.assertIn('rolling back returned connection', logs.output[0])
        async with self.database.transaction() as tx:
            self.assertIs(conn, tx.connection)
            cursor = await tx.connection.execute(_SETTINGS)
            self.assertEqual(
                {'organization': '', 'principal': ''}, await cursor.fetchone()
            )


class LifecycleTestCase(unittest.IsolatedAsyncioTestCase):
    """Open, close, the startup check, and the singleton."""

    def setUp(self) -> None:
        support.env_url('DATABASE_URL')
        support.env_url('ADMIN_DATABASE_URL')

    async def test_startup_check_fails_on_an_empty_database(self) -> None:
        # The maintenance database of the server has no Imbi tables.
        url = parse.urlsplit(os.environ['DATABASE_URL'])
        with mock.patch.dict(
            os.environ,
            {'DATABASE_URL': url._replace(path='/postgres').geturl()},
        ):
            database = db.Database()
        with self.assertRaises(db.SchemaMissingError) as error:
            await database.open()
        self.assertFalse(database.opened)
        self.assertIn('organizations, tenants', str(error.exception))
        self.assertIn('moon run root:schema-apply', str(error.exception))

    async def test_transaction_requires_open(self) -> None:
        database = db.Database()
        with self.assertRaises(RuntimeError):
            async with database.transaction():
                pass
        with self.assertRaises(RuntimeError):
            async with database.admin_transaction():
                pass

    def isolate_the_instance(self) -> None:
        # Another app of this test process can hold the instance open.
        patcher = mock.patch.object(db.Database, '_instance', None)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_module_functions_use_the_instance(self) -> None:
        self.isolate_the_instance()
        async with db.database_lifespan() as database:
            self.assertIs(database, db.Database.get_instance())
            self.assertTrue(database.opened)
            async with db.transaction(principal_id='p-1') as tx:
                cursor = await tx.connection.execute(_SETTINGS)
                self.assertEqual(
                    {'organization': '', 'principal': 'p-1'},
                    await cursor.fetchone(),
                )
            async with db.admin_transaction() as tx:
                await tx.connection.execute('SELECT 1')
        self.assertFalse(database.opened)
        self.assertIsNot(database, db.Database.get_instance())

    async def test_second_open_lifespan_gets_its_own_instance(self) -> None:
        self.isolate_the_instance()
        async with db.database_lifespan() as first:
            async with db.database_lifespan() as second:
                self.assertIsNot(first, second)
                self.assertTrue(second.opened)
            self.assertFalse(second.opened)
            # Closing the second one leaves the process instance open.
            self.assertTrue(first.opened)
            self.assertIs(first, db.Database.get_instance())
        self.assertFalse(first.opened)


class DependencyTestCase(unittest.TestCase):
    """``db.Pool`` gives an endpoint the instance that the lifespan opened."""

    def test_pool_dependency(self) -> None:
        support.env_url('DATABASE_URL')
        support.env_url('ADMIN_DATABASE_URL')
        app = fastapi.FastAPI(lifespan=lifespan.Lifespan(db.database_lifespan))

        @app.get('/setting')
        async def setting(  # pyright: ignore[reportUnusedFunction]
            database: db.Pool,
        ) -> dict[str, typing.Any]:
            async with database.transaction('org-1') as tx:
                cursor = await tx.connection.execute(_SETTINGS)
                row = await cursor.fetchone()
            return dict(row or {})

        with testclient.TestClient(app) as client:
            response = client.get('/setting')
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {'organization': 'org-1', 'principal': ''}, response.json()
        )
