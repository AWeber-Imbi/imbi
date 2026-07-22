"""Tests for the shared API-key / client-credential helpers."""

import datetime
import unittest
from unittest import mock

import fastapi

from imbi_api.auth import password
from imbi_api.endpoints import _credentials


class ComputeExpiresAtTests(unittest.TestCase):
    def test_none_when_days_falsy(self) -> None:
        self.assertIsNone(_credentials.compute_expires_at(None, 365))
        self.assertIsNone(_credentials.compute_expires_at(0, 365))

    def test_computes_offset_from_now(self) -> None:
        before = datetime.datetime.now(datetime.UTC)
        result = _credentials.compute_expires_at(30, 365)
        after = datetime.datetime.now(datetime.UTC)
        assert result is not None
        self.assertGreaterEqual(result, before + datetime.timedelta(days=30))
        self.assertLessEqual(result, after + datetime.timedelta(days=30))

    def test_raises_400_when_over_max(self) -> None:
        with self.assertRaises(fastapi.HTTPException) as ctx:
            _credentials.compute_expires_at(400, 365)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn('365', ctx.exception.detail)

    def test_equal_to_max_is_allowed(self) -> None:
        self.assertIsNotNone(_credentials.compute_expires_at(365, 365))


class GenerateSecretTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_secret_and_verifiable_hash(self) -> None:
        secret, secret_hash = await _credentials.generate_secret()
        self.assertTrue(secret)
        self.assertNotEqual(secret, secret_hash)
        self.assertTrue(password.verify_password(secret, secret_hash))

    async def test_distinct_each_call(self) -> None:
        first, _ = await _credentials.generate_secret()
        second, _ = await _credentials.generate_secret()
        self.assertNotEqual(first, second)


class CreateOwnedNodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_true_when_row_created(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'n': {}}]
        result = await _credentials.create_service_account_owned_node(
            db, label='APIKey', props={'name': 'x'}, slug='bot'
        )
        self.assertTrue(result)

    async def test_false_when_no_row(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        result = await _credentials.create_service_account_owned_node(
            db, label='APIKey', props={'name': 'x'}, slug='bot'
        )
        self.assertFalse(result)

    async def test_query_and_params_shape(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'n': {}}]
        await _credentials.create_service_account_owned_node(
            db,
            label='ClientCredential',
            props={'name': 'x', 'revoked': False},
            slug='bot',
        )
        query, params = db.execute.call_args.args
        self.assertIn('CREATE (n:ClientCredential', query)
        self.assertIn('-[:OWNED_BY]->(s)', query)
        self.assertIn('name: {name}', query)
        self.assertIn('revoked: {revoked}', query)
        self.assertEqual(
            params, {'name': 'x', 'revoked': False, 'slug': 'bot'}
        )
