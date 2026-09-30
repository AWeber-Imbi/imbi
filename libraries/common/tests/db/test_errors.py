"""Tests for ``imbi.common.db.errors``."""

import typing
import unittest

import fastapi
import psycopg
from fastapi import testclient
from psycopg import errors as pg_errors

from imbi.common.db import errors
from libraries.common.tests.db import support


def _client(exc: Exception) -> testclient.TestClient:
    """A client for an app whose one route raises *exc*."""
    app = fastapi.FastAPI()
    errors.add_exception_handlers(app)

    @app.get('/')
    async def fail() -> None:  # pyright: ignore[reportUnusedFunction]
        raise exc

    return testclient.TestClient(app, raise_server_exceptions=False)


class DatabaseViolationTestCase(support.DatabaseTestCase):
    """Real violations, raised for ``imbi_app``, map to the status."""

    _INSERT_TAG: typing.LiteralString = (
        'INSERT INTO tags (id, organization_id, name, slug)'
        ' VALUES (%s, %s, %s, %s)'
    )

    async def violation(
        self, statements: list[tuple[typing.LiteralString, tuple[str, ...]]]
    ) -> psycopg.Error:
        async with self.database.transaction(
            self.seed.org_a, self.seed.user
        ) as tx:
            try:
                for query, params in statements:
                    await tx.connection.execute(query, params)
            except psycopg.Error as exc:
                return exc
        self.fail('No violation')

    async def test_violations(self) -> None:
        s = self.seed
        tag = support.new_id('tag')
        cases: list[
            tuple[
                str,
                type[psycopg.Error],
                list[tuple[typing.LiteralString, tuple[str, ...]]],
                int,
            ]
        ] = [
            (
                'restrict',
                pg_errors.RestrictViolation,
                [('DELETE FROM roles WHERE id = %s', (s.role_a,))],
                409,
            ),
            (
                'foreign key',
                pg_errors.ForeignKeyViolation,
                [
                    (
                        'INSERT INTO memberships'
                        ' (organization_id, principal_id, role_id)'
                        ' VALUES (%s, %s, %s)',
                        (s.org_a, 'no-such-principal', s.role_a),
                    )
                ],
                409,
            ),
            (
                'unique',
                pg_errors.UniqueViolation,
                [
                    (self._INSERT_TAG, (tag, s.org_a, tag, tag)),
                    (self._INSERT_TAG, (tag + 'x', s.org_a, tag, tag)),
                ],
                409,
            ),
            (
                'check',
                pg_errors.CheckViolation,
                [(self._INSERT_TAG, (tag, s.org_a, tag, 'Not A Slug'))],
                422,
            ),
        ]
        for name, cls, statements, status in cases:
            with self.subTest(name):
                exc = await self.violation(statements)
                self.assertIsInstance(exc, cls)
                response = _client(exc).get('/')
                self.assertEqual(status, response.status_code)
                self.assertEqual(['detail'], list(response.json()))
                self.assertIsInstance(response.json()['detail'], str)


class ViolationDetailsTestCase(unittest.TestCase):
    def test_uses_the_endpoint_message(self) -> None:
        with self.assertRaises(fastapi.HTTPException) as ctx:
            with errors.violation_details(unique='Tag exists'):
                raise pg_errors.UniqueViolation('duplicate key')
        self.assertEqual(409, ctx.exception.status_code)
        self.assertEqual('Tag exists', ctx.exception.detail)

    def test_each_argument(self) -> None:
        for kwarg, exc, status in (
            ('restrict', pg_errors.RestrictViolation(), 409),
            ('foreign_key', pg_errors.ForeignKeyViolation(), 409),
            ('unique', pg_errors.UniqueViolation(), 409),
            ('check', pg_errors.CheckViolation(), 422),
        ):
            with self.subTest(kwarg):
                with self.assertRaises(fastapi.HTTPException) as ctx:
                    with errors.violation_details(**{kwarg: 'Message'}):
                        raise exc
                self.assertEqual(status, ctx.exception.status_code)

    def test_without_a_message_the_error_passes(self) -> None:
        with self.assertRaises(pg_errors.CheckViolation):
            with errors.violation_details(unique='Tag exists'):
                raise pg_errors.CheckViolation('bad slug')

    def test_other_integrity_errors_pass(self) -> None:
        with self.assertRaises(pg_errors.NotNullViolation):
            with errors.violation_details(unique='Tag exists'):
                raise pg_errors.NotNullViolation('null')

    def test_fallback_body(self) -> None:
        response = _client(pg_errors.UniqueViolation('dup')).get('/')
        self.assertEqual(409, response.status_code)
        self.assertEqual(
            {'detail': 'The resource already exists'}, response.json()
        )

    def test_unmapped_error_is_a_server_error(self) -> None:
        response = _client(pg_errors.NotNullViolation('null')).get('/')
        self.assertEqual(500, response.status_code)


class ModuleTestCase(unittest.TestCase):
    def test_status_mapping(self) -> None:
        self.assertEqual(
            {'23001': 409, '23503': 409, '23505': 409, '23514': 422},
            errors.STATUS,
        )
