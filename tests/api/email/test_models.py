"""Tests for email.models module."""

import datetime
import unittest

from imbi.email import models


class PasswordResetTokenTestCase(unittest.TestCase):
    """Test cases for PasswordResetToken."""

    def test_create_token(self) -> None:
        """Test creating a new password reset token."""
        token = models.PasswordResetToken.create(
            username='testuser',
            email='test@example.com',
        )

        self.assertIsInstance(token.token, str)
        self.assertEqual(len(token.token), 43)  # URL-safe base64 32 bytes
        self.assertEqual(token.email, 'test@example.com')
        self.assertFalse(token.used)
        self.assertIsNone(token.used_at)

    def test_token_expiry_default(self) -> None:
        """Test token expires after 24 hours by default."""
        token = models.PasswordResetToken.create(
            username='testuser',
            email='test@example.com',
        )

        # Token should expire in ~24 hours
        expected_expiry = token.created_at + datetime.timedelta(hours=24)
        delta = abs((token.expires_at - expected_expiry).total_seconds())
        self.assertLess(delta, 1)  # Within 1 second

    def test_token_expiry_custom(self) -> None:
        """Test custom token expiry."""
        token = models.PasswordResetToken.create(
            username='testuser',
            email='test@example.com',
            expiry_hours=1,
        )

        # Token should expire in ~1 hour
        expected_expiry = token.created_at + datetime.timedelta(hours=1)
        delta = abs((token.expires_at - expected_expiry).total_seconds())
        self.assertLess(delta, 1)  # Within 1 second

    def test_is_valid_fresh_token(self) -> None:
        """Test that a fresh token is valid."""
        token = models.PasswordResetToken.create(
            username='testuser',
            email='test@example.com',
        )

        self.assertTrue(token.is_valid())

    def test_is_valid_expired_token(self) -> None:
        """Test that an expired token is invalid."""
        token = models.PasswordResetToken.create(
            username='testuser',
            email='test@example.com',
            expiry_hours=-1,  # Already expired
        )

        self.assertFalse(token.is_valid())

    def test_is_valid_used_token(self) -> None:
        """Test that a used token is invalid."""
        token = models.PasswordResetToken.create(
            username='testuser',
            email='test@example.com',
        )

        token.mark_used()

        self.assertFalse(token.is_valid())
        self.assertTrue(token.used)
        self.assertIsNotNone(token.used_at)

    def test_mark_used_sets_timestamp(self) -> None:
        """Test that marking a token as used sets timestamp."""
        token = models.PasswordResetToken.create(
            username='testuser',
            email='test@example.com',
        )

        before = datetime.datetime.now(datetime.UTC)
        token.mark_used()
        after = datetime.datetime.now(datetime.UTC)

        self.assertTrue(token.used)
        self.assertIsNotNone(token.used_at)
        self.assertGreaterEqual(token.used_at, before)
        self.assertLessEqual(token.used_at, after)

    def test_token_uniqueness(self) -> None:
        """Test that each token is unique."""
        token1 = models.PasswordResetToken.create(
            username='testuser',
            email='test@example.com',
        )
        token2 = models.PasswordResetToken.create(
            username='testuser',
            email='test@example.com',
        )

        self.assertNotEqual(token1.token, token2.token)
