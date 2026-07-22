"""Tests for the identity repository module."""

import datetime
import unittest
from unittest import mock

from imbi_common.plugins.base import IdentityCredentials, IdentityProfile

from imbi_api.identity import repository


class FakeEncryptor:
    """No-op TokenEncryption stand-in: returns input unchanged."""

    def encrypt(self, value: str | None) -> str | None:
        return value

    def decrypt(self, value: str | None) -> str | None:
        return value


class NowIsoTestCase(unittest.TestCase):
    """Verify the timestamp helper returns an ISO-8601 UTC string."""

    def test_returns_isoformat_with_tz(self) -> None:
        result = repository._now_iso()
        # Must be parseable as an aware datetime.
        parsed = datetime.datetime.fromisoformat(result)
        self.assertIsNotNone(parsed.tzinfo)


class DecryptHelperTestCase(unittest.TestCase):
    """Verify _decrypt's None / empty / agtype-parsing branches."""

    def test_none_input_returns_none(self) -> None:
        self.assertIsNone(repository._decrypt(None))

    def test_empty_string_returns_none(self) -> None:
        with mock.patch.object(
            repository.TokenEncryption,
            'get_instance',
            return_value=FakeEncryptor(),
        ):
            self.assertIsNone(repository._decrypt(''))

    def test_string_input_decrypts_directly(self) -> None:
        with mock.patch.object(
            repository.TokenEncryption,
            'get_instance',
            return_value=FakeEncryptor(),
        ):
            self.assertEqual(repository._decrypt('cipher-text'), 'cipher-text')

    def test_non_string_parses_agtype(self) -> None:
        with (
            mock.patch.object(
                repository.graph,
                'parse_agtype',
                return_value='cipher',
            ),
            mock.patch.object(
                repository.TokenEncryption,
                'get_instance',
                return_value=FakeEncryptor(),
            ),
        ):
            self.assertEqual(repository._decrypt({'wrapped': True}), 'cipher')


class MarkStatusTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify mark_status emits the expected query + params."""

    async def test_executes_with_status_param(self) -> None:
        db = mock.AsyncMock()
        await repository.mark_status(db, 'conn-1', 'expired')
        db.execute.assert_awaited_once()
        _query, params, _columns = db.execute.await_args.args
        self.assertEqual(params['id'], 'conn-1')
        self.assertEqual(params['status'], 'expired')
        self.assertIn('now', params)


class RevokeTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify revoke clears tokens and flips status."""

    async def test_executes_with_integration_and_user(self) -> None:
        db = mock.AsyncMock()
        await repository.revoke(db, 'integration-1', 'user-1')
        db.execute.assert_awaited_once()
        query, params, _columns = db.execute.await_args.args
        self.assertEqual(params['integration_id'], 'integration-1')
        self.assertEqual(params['user_id'], 'user-1')
        self.assertIn("status = 'revoked'", query)
        self.assertIn('access_token_encrypted = null', query)


class UpsertConnectionTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify upsert_connection encrypts and returns the connection id."""

    async def test_returns_connection_id(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'id': '"conn-abc"'}]
        profile = IdentityProfile(subject='sub-1')
        credentials = IdentityCredentials(
            access_token='access',
            refresh_token='refresh',
        )
        with (
            mock.patch.object(
                repository.TokenEncryption,
                'get_instance',
                return_value=FakeEncryptor(),
            ),
            mock.patch.object(
                repository.graph,
                'parse_agtype',
                return_value='conn-abc',
            ),
        ):
            connection_id = await repository.upsert_connection(
                db, 'integration-1', 'user-1', profile, credentials
            )
        self.assertEqual(connection_id, 'conn-abc')

    async def test_raises_when_query_returns_no_rows(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        profile = IdentityProfile(subject='sub-1')
        credentials = IdentityCredentials(access_token='access')
        with mock.patch.object(
            repository.TokenEncryption,
            'get_instance',
            return_value=FakeEncryptor(),
        ):
            with self.assertRaises(RuntimeError):
                await repository.upsert_connection(
                    db, 'plugin-1', 'user-1', profile, credentials
                )

    async def test_logs_and_reraises_on_execute_failure(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = RuntimeError('graph down')
        profile = IdentityProfile(subject='sub-1')
        credentials = IdentityCredentials(access_token='access')
        with mock.patch.object(
            repository.TokenEncryption,
            'get_instance',
            return_value=FakeEncryptor(),
        ):
            with self.assertRaises(RuntimeError):
                await repository.upsert_connection(
                    db, 'plugin-1', 'user-1', profile, credentials
                )


class LoadConnectionTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify load_connection's None / missing-token / happy paths."""

    async def test_returns_none_when_no_rows(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        result = await repository.load_connection(db, 'p', 'u')
        self.assertIsNone(result)

    async def test_returns_none_when_access_token_missing(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {
                'id': '"c"',
                'subject': '"s"',
                'access': None,
                'refresh': None,
                'expires_at': None,
                'scopes': None,
                'status': '"active"',
                'metadata': None,
            }
        ]
        with mock.patch.object(
            repository.TokenEncryption,
            'get_instance',
            return_value=FakeEncryptor(),
        ):
            result = await repository.load_connection(db, 'p', 'u')
        self.assertIsNone(result)

    async def test_happy_path_returns_credentials_internal(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {
                'id': '"conn-1"',
                'subject': '"sub-1"',
                'access': 'access-cipher',
                'refresh': 'refresh-cipher',
                'expires_at': None,
                'scopes': None,
                'status': '"active"',
                'metadata': None,
            }
        ]

        def parse(value: object) -> object:
            # Strip the quoting our test fixtures use to mimic agtype.
            if isinstance(value, str) and value.startswith('"'):
                return value.strip('"')
            return value

        with (
            mock.patch.object(
                repository.TokenEncryption,
                'get_instance',
                return_value=FakeEncryptor(),
            ),
            mock.patch.object(
                repository.graph,
                'parse_agtype',
                side_effect=parse,
            ),
        ):
            result = await repository.load_connection(db, 'p', 'u')
        assert result is not None
        self.assertEqual(result.connection_id, 'conn-1')
        self.assertEqual(result.subject, 'sub-1')
        self.assertEqual(result.access_token, 'access-cipher')
        self.assertEqual(result.refresh_token, 'refresh-cipher')
        self.assertEqual(result.status, 'active')


class ListForUserTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify list_for_user returns parsed rows for the actor."""

    async def test_returns_parsed_rows(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {
                'id': '"conn-1"',
                'integration_id': '"integration-1"',
                'integration_slug': '"oidc"',
                'integration_name': '"OIDC"',
                'subject': '"sub"',
                'status': '"active"',
                'expires_at': None,
                'scopes': None,
                'last_used_at': None,
                'metadata': None,
                'claims_enc': None,
            }
        ]

        def parse(value: object) -> object:
            if isinstance(value, str) and value.startswith('"'):
                return value.strip('"')
            return value

        with mock.patch.object(
            repository.graph,
            'parse_agtype',
            side_effect=parse,
        ):
            rows = await repository.list_for_user(db, 'user-1')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], 'conn-1')
        self.assertEqual(rows[0]['integration_slug'], 'oidc')
        self.assertNotIn('claims_enc', rows[0])

    async def test_returns_empty_list_when_no_rows(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        result = await repository.list_for_user(db, 'user-1')
        self.assertEqual(result, [])


class FindUserBySubjectTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify find_user_by_subject returns a user_id or None."""

    async def test_returns_user_id_when_exactly_one_match(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'user_ids': '["user-42"]'}]
        with mock.patch.object(
            repository.graph,
            'parse_agtype',
            return_value=['user-42'],
        ):
            result = await repository.find_user_by_subject(
                db, 'github', '12345'
            )
        self.assertEqual(result, 'user-42')
        _query, params, _cols = db.execute.await_args.args
        self.assertEqual(params['integration_id'], 'github')
        self.assertEqual(params['subject'], '12345')

    async def test_returns_none_when_no_rows(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        result = await repository.find_user_by_subject(db, 'github', '99999')
        self.assertIsNone(result)

    async def test_returns_none_when_no_users_in_collection(self) -> None:
        # collect() over an empty match yields a row with an empty list.
        db = mock.AsyncMock()
        db.execute.return_value = [{'user_ids': '[]'}]
        with mock.patch.object(
            repository.graph,
            'parse_agtype',
            return_value=[],
        ):
            result = await repository.find_user_by_subject(
                db, 'github', '12345'
            )
        self.assertIsNone(result)

    async def test_returns_none_when_multiple_distinct_users_match(
        self,
    ) -> None:
        # Two Imbi users link the same GitHub subject — fail closed
        # rather than silently picking one. Suggested-by: coderabbitai
        db = mock.AsyncMock()
        db.execute.return_value = [{'user_ids': '["user-1","user-2"]'}]
        with (
            mock.patch.object(
                repository.graph,
                'parse_agtype',
                return_value=['user-1', 'user-2'],
            ),
            self.assertLogs(
                'imbi_api.identity.repository', level='ERROR'
            ) as cm,
        ):
            result = await repository.find_user_by_subject(
                db, 'github', '12345'
            )
        self.assertIsNone(result)
        self.assertTrue(
            any('multiple Imbi users' in line for line in cm.output)
        )

    async def test_query_filters_by_active_status(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        await repository.find_user_by_subject(db, 'github', '1')
        query, _params, _cols = db.execute.await_args.args
        self.assertIn("status = 'active'", query)

    async def test_returns_none_when_parse_agtype_yields_non_list(
        self,
    ) -> None:
        # Defensive guard: if AGE somehow returns a non-list payload,
        # don't crash the comprehension. Suggested-by: coderabbitai
        db = mock.AsyncMock()
        db.execute.return_value = [{'user_ids': '"oops"'}]
        with mock.patch.object(
            repository.graph,
            'parse_agtype',
            return_value='oops',
        ):
            result = await repository.find_user_by_subject(
                db, 'github', '12345'
            )
        self.assertIsNone(result)


class StaleConnectionsTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify stale_connections returns parsed rows."""

    async def test_returns_rows_with_parsed_values(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [
            {'id': '"c"', 'integration_id': '"p"', 'user_id': '"u"'}
        ]
        horizon = datetime.datetime.now(datetime.UTC)

        def parse(value: object) -> object:
            if isinstance(value, str) and value.startswith('"'):
                return value.strip('"')
            return value

        with mock.patch.object(
            repository.graph,
            'parse_agtype',
            side_effect=parse,
        ):
            rows = await repository.stale_connections(db, horizon)
        self.assertEqual(
            rows, [{'id': 'c', 'integration_id': 'p', 'user_id': 'u'}]
        )
