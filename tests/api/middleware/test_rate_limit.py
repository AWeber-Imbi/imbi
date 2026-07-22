"""Tests for middleware.rate_limit module."""

import unittest
from unittest import mock

from slowapi import errors as slowapi_errors

from imbi_api.middleware import rate_limit


class GetRateLimitKeyTestCase(unittest.TestCase):
    """Test cases for get_rate_limit_key function."""

    def test_returns_ip_key(self) -> None:
        """Test rate limit key uses the remote IP address."""
        mock_request = mock.MagicMock()

        with mock.patch(
            'imbi_api.middleware.rate_limit.slowapi_util.get_remote_address',
            return_value='192.168.1.100',
        ):
            key = rate_limit.get_rate_limit_key(mock_request)

        self.assertEqual(key, 'ip:192.168.1.100')

    def test_ipv6_address(self) -> None:
        """Test rate limit key with IPv6 address."""
        mock_request = mock.MagicMock()

        with mock.patch(
            'imbi_api.middleware.rate_limit.slowapi_util.get_remote_address',
            return_value='2001:db8::1',
        ):
            key = rate_limit.get_rate_limit_key(mock_request)

        self.assertEqual(key, 'ip:2001:db8::1')


class SetupRateLimitingTestCase(unittest.TestCase):
    """Test cases for setup_rate_limiting function."""

    def test_setup_rate_limiting(self) -> None:
        """Test rate limiting setup attaches limiter and handler."""
        # Create mock app
        mock_app = mock.MagicMock()

        # Call setup
        rate_limit.setup_rate_limiting(mock_app)

        # Verify limiter was attached to app state
        self.assertEqual(mock_app.state.limiter, rate_limit.limiter)

        # Verify exception handler was registered
        mock_app.add_exception_handler.assert_called_once()
        # Verify the exception type is RateLimitExceeded
        call_args = mock_app.add_exception_handler.call_args
        self.assertEqual(call_args[0][0], slowapi_errors.RateLimitExceeded)


class LimiterInitializationTestCase(unittest.TestCase):
    """Test cases for limiter initialization."""

    def test_limiter_is_singleton(self) -> None:
        """Test that limiter is a module-level singleton."""
        # Import in different ways should give same instance
        import imbi_api
        from imbi_api.middleware.rate_limit import limiter as limiter1

        limiter2 = imbi_api.middleware.rate_limit.limiter

        self.assertIs(limiter1, limiter2)
