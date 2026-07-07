"""Unit tests for :mod:`imbi_api.plugins.credentials`."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest import mock

import fastapi

from imbi_api.plugins import credentials


class _Encryptor:
    """Deterministic stand-in for ``TokenEncryption``."""

    def encrypt(self, value: str) -> str:
        return f'enc:{value}'


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _blob(data: dict[str, str]) -> str:
    """Mimic how AGE stores a dict prop: a JSON string, itself returned
    by ``parse_agtype`` (which JSON-decodes once). Double-encode so the
    decoded value is the inner JSON blob string the code expects."""
    return json.dumps(json.dumps(data))


class ReadCredentialsTestCase(unittest.TestCase):
    def test_not_found_returns_false(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        found, raw, creds = _run(
            credentials._read_encrypted_credentials(db, 'gh', 'org')
        )
        self.assertFalse(found)
        self.assertEqual(raw, '')
        self.assertEqual(creds, {})

    def test_absent_blob_returns_empty(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'creds': None}]
        found, raw, creds = _run(
            credentials._read_encrypted_credentials(db, 'gh', 'org')
        )
        self.assertTrue(found)
        self.assertEqual(raw, '')
        self.assertEqual(creds, {})

    def test_parses_json_blob_and_drops_empty_values(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {'creds': _blob({'token': 'x', 'blank': ''})}
        ]
        found, raw, creds = _run(
            credentials._read_encrypted_credentials(db, 'gh', 'org')
        )
        self.assertTrue(found)
        self.assertEqual(creds, {'token': 'x'})
        self.assertIn('token', raw)

    def test_invalid_json_blob_returns_raw_and_empty(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'creds': 'not-json'}]
        found, raw, creds = _run(
            credentials._read_encrypted_credentials(db, 'gh', 'org')
        )
        self.assertTrue(found)
        self.assertEqual(raw, 'not-json')
        self.assertEqual(creds, {})

    def test_non_dict_json_returns_empty(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'creds': json.dumps([1, 2])}]
        found, _raw, creds = _run(
            credentials._read_encrypted_credentials(db, 'gh', 'org')
        )
        self.assertTrue(found)
        self.assertEqual(creds, {})


class GetCredentialFieldsTestCase(unittest.TestCase):
    def test_returns_sorted_field_names(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'creds': _blob({'b': '1', 'a': '2'})}]
        fields = _run(
            credentials.get_integration_credential_fields(db, 'gh', 'org')
        )
        self.assertEqual(fields, ['a', 'b'])


class PatchCredentialsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(
            credentials.TokenEncryption,
            'get_instance',
            return_value=_Encryptor(),
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_missing_integration_raises_404(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        with self.assertRaises(fastapi.HTTPException) as ctx:
            _run(
                credentials.patch_integration_credentials(
                    db, 'gh', 'org', {'token': 'x'}
                )
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_adds_and_removes_fields(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = [
            [{'creds': _blob({'keep': 'old', 'drop': 'gone'})}],
            [{'i': {'id': '1'}}],  # successful CAS write
        ]
        fields = _run(
            credentials.patch_integration_credentials(
                db,
                'gh',
                'org',
                {'token': 'new', 'drop': None},
            )
        )
        self.assertEqual(fields, ['keep', 'token'])
        write_params = db.execute.await_args_list[1].args[1]
        stored = json.loads(write_params['blob'])
        self.assertEqual(stored['token'], 'enc:new')
        self.assertNotIn('drop', stored)

    def test_concurrent_modification_retries_then_409(self) -> None:
        db = mock.AsyncMock()
        # Every read succeeds, every CAS write returns no rows -> retry
        # exhaustion -> 409.
        db.execute.side_effect = [
            [{'creds': _blob({'a': '1'})}],
            [],
            [{'creds': _blob({'a': '1'})}],
            [],
            [{'creds': _blob({'a': '1'})}],
            [],
        ]
        with self.assertRaises(fastapi.HTTPException) as ctx:
            _run(
                credentials.patch_integration_credentials(
                    db, 'gh', 'org', {'a': '2'}
                )
            )
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == '__main__':
    unittest.main()
