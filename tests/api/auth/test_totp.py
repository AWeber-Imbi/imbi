"""Tests for the shared TOTP/MFA verification helpers."""

import unittest
from unittest import mock

import fastapi
import pyotp

from imbi.api.auth import totp

PERIOD = 30
DIGITS = 6


class VerifyTotpCodeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.secret = pyotp.random_base32()
        self.totp = pyotp.TOTP(self.secret, interval=PERIOD, digits=DIGITS)
        self.patcher = mock.patch.object(
            totp, 'decrypt_totp_secret', return_value=self.secret
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_valid_totp_returns_true_no_hash(self) -> None:
        code = self.totp.now()
        result = await totp.verify_totp_code(
            {'secret': 'enc'}, code, period=PERIOD, digits=DIGITS
        )
        self.assertEqual(result, (True, None))

    async def test_backup_code_returns_matched_hash(self) -> None:
        wrong = '000000' if self.totp.now() != '000000' else '111111'
        with mock.patch.object(
            totp.password,
            'verify_password',
            side_effect=lambda code, h: h == 'good',
        ):
            result = await totp.verify_totp_code(
                {'secret': 'enc', 'backup_codes': ['bad', 'good']},
                wrong,
                period=PERIOD,
                digits=DIGITS,
            )
        self.assertEqual(result, (True, 'good'))

    async def test_no_match_returns_false(self) -> None:
        wrong = '000000' if self.totp.now() != '000000' else '111111'
        with mock.patch.object(
            totp.password, 'verify_password', return_value=False
        ):
            result = await totp.verify_totp_code(
                {'secret': 'enc', 'backup_codes': ['bad']},
                wrong,
                period=PERIOD,
                digits=DIGITS,
            )
        self.assertEqual(result, (False, None))

    async def test_missing_backup_codes_key(self) -> None:
        wrong = '000000' if self.totp.now() != '000000' else '111111'
        result = await totp.verify_totp_code(
            {'secret': 'enc'}, wrong, period=PERIOD, digits=DIGITS
        )
        self.assertEqual(result, (False, None))


class DecryptTotpSecretTests(unittest.TestCase):
    def test_success(self) -> None:
        encryptor = mock.MagicMock()
        encryptor.decrypt.return_value = 'plain'
        with mock.patch.object(
            totp.encryption.TokenEncryption,
            'get_instance',
            return_value=encryptor,
        ):
            self.assertEqual(totp.decrypt_totp_secret('enc'), 'plain')

    def test_none_raises_500(self) -> None:
        encryptor = mock.MagicMock()
        encryptor.decrypt.return_value = None
        with mock.patch.object(
            totp.encryption.TokenEncryption,
            'get_instance',
            return_value=encryptor,
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                totp.decrypt_totp_secret('enc')
        self.assertEqual(ctx.exception.status_code, 500)

    def test_decrypt_error_raises_500(self) -> None:
        encryptor = mock.MagicMock()
        encryptor.decrypt.side_effect = ValueError('bad')
        with mock.patch.object(
            totp.encryption.TokenEncryption,
            'get_instance',
            return_value=encryptor,
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                totp.decrypt_totp_secret('enc')
        self.assertEqual(ctx.exception.status_code, 500)


class FetchTotpSecretTests(unittest.IsolatedAsyncioTestCase):
    async def test_found(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'n': {'secret': 'enc'}}]
        with mock.patch.object(
            totp.graph, 'parse_agtype', side_effect=lambda x: x
        ):
            result = await totp.fetch_totp_secret(db, 'a@b.com')
        self.assertEqual(result, {'secret': 'enc'})

    async def test_missing_returns_none(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        result = await totp.fetch_totp_secret(db, 'a@b.com')
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
