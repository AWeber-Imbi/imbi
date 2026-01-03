"""Unit tests for auth.core module."""

import datetime
import unittest

from imbi_common.auth import core


class TestPasswordHashing(unittest.TestCase):
    """Test password hashing and verification."""

    def test_hash_password_returns_string(self):
        """Test that hash_password returns a string."""
        hashed = core.hash_password('test_password')
        self.assertIsInstance(hashed, str)

    def test_hash_password_not_plaintext(self):
        """Test that hash is not the plaintext password."""
        password = 'test_password'
        hashed = core.hash_password(password)
        self.assertNotEqual(hashed, password)

    def test_verify_password_correct(self):
        """Test verifying correct password."""
        password = 'secure_password_123'
        hashed = core.hash_password(password)
        self.assertTrue(core.verify_password(password, hashed))

    def test_verify_password_incorrect(self):
        """Test verifying incorrect password."""
        password = 'secure_password_123'
        hashed = core.hash_password(password)
        self.assertFalse(core.verify_password('wrong_password', hashed))

    def test_verify_password_empty(self):
        """Test verifying empty password."""
        hashed = core.hash_password('test')
        self.assertFalse(core.verify_password('', hashed))

    def test_different_hashes_for_same_password(self):
        """Test that same password produces different hashes (salt)."""
        password = 'test_password'
        hash1 = core.hash_password(password)
        hash2 = core.hash_password(password)
        self.assertNotEqual(hash1, hash2)

    def test_needs_rehash(self):
        """Test needs_rehash function."""
        password = 'test_password'
        hashed = core.hash_password(password)
        # Should not need rehash immediately after creation
        self.assertFalse(core.needs_rehash(hashed))


class TestJWTTokens(unittest.TestCase):
    """Test JWT token creation and verification."""

    def test_create_access_token_returns_string(self):
        """Test that create_access_token returns a string."""
        token = core.create_access_token(subject='user@example.com')
        self.assertIsInstance(token, str)

    def test_verify_token_returns_dict(self):
        """Test that verify_token returns a dict with payload."""
        token = core.create_access_token(subject='user@example.com')
        payload = core.verify_token(token)
        self.assertIsInstance(payload, dict)

    def test_token_contains_subject(self):
        """Test that token contains subject claim."""
        subject = 'user@example.com'
        token = core.create_access_token(subject=subject)
        payload = core.verify_token(token)
        self.assertEqual(payload['sub'], subject)

    def test_token_contains_extra_claims(self):
        """Test that token contains extra claims."""
        token = core.create_access_token(
            subject='user@example.com',
            extra_claims={'role': 'admin', 'org': 'test-org'},
        )
        payload = core.verify_token(token)
        self.assertEqual(payload['role'], 'admin')
        self.assertEqual(payload['org'], 'test-org')

    def test_token_contains_expiration(self):
        """Test that token contains expiration claim."""
        token = core.create_access_token(subject='user@example.com')
        payload = core.verify_token(token)
        self.assertIn('exp', payload)

    def test_token_contains_issued_at(self):
        """Test that token contains issued-at claim."""
        token = core.create_access_token(subject='user@example.com')
        payload = core.verify_token(token)
        self.assertIn('iat', payload)

    def test_create_refresh_token(self):
        """Test creating refresh token."""
        token = core.create_refresh_token(subject='user@example.com')
        payload = core.verify_token(token)
        self.assertEqual(payload['sub'], 'user@example.com')

    def test_invalid_token_raises_exception(self):
        """Test that invalid token raises exception."""
        with self.assertRaises(Exception):
            core.verify_token('invalid.token.here')

    def test_tampered_token_raises_exception(self):
        """Test that tampered token raises exception."""
        token = core.create_access_token(subject='user@example.com')
        tampered = token[:-10] + 'tampered12'
        with self.assertRaises(Exception):
            core.verify_token(tampered)


class TestTokenExpiration(unittest.TestCase):
    """Test token expiration handling."""

    def test_token_has_future_expiration(self):
        """Test that newly created token has future expiration."""
        token = core.create_access_token(subject='user@example.com')
        payload = core.verify_token(token)

        exp = datetime.datetime.fromtimestamp(
            payload['exp'], tz=datetime.timezone.utc
        )
        now = datetime.datetime.now(datetime.timezone.utc)

        self.assertGreater(exp, now)

    def test_token_expiration_in_expected_range(self):
        """Test that token expiration is in expected range."""
        token = core.create_access_token(subject='user@example.com')
        payload = core.verify_token(token)

        exp = datetime.datetime.fromtimestamp(
            payload['exp'], tz=datetime.timezone.utc
        )
        now = datetime.datetime.now(datetime.timezone.utc)
        expected_exp = now + datetime.timedelta(hours=1)

        # Allow 5 second variance
        time_diff = abs((exp - expected_exp).total_seconds())
        self.assertLess(time_diff, 5)


if __name__ == '__main__':
    unittest.main()
