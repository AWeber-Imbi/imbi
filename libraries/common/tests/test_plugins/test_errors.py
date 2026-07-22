import unittest

from imbi.common.plugins.errors import (
    CursorExpiredError,
    PluginAuthenticationFailed,
    PluginCredentialsMissing,
    PluginNotFoundError,
    PluginRateLimited,
    PluginTimeoutError,
    PluginUnavailableError,
)


class ErrorsTestCase(unittest.TestCase):
    def test_plugin_not_found_error_is_exception(self) -> None:
        self.assertTrue(issubclass(PluginNotFoundError, Exception))

    def test_plugin_unavailable_error_is_exception(self) -> None:
        self.assertTrue(issubclass(PluginUnavailableError, Exception))

    def test_cursor_expired_error_is_exception(self) -> None:
        self.assertTrue(issubclass(CursorExpiredError, Exception))

    def test_plugin_timeout_error_is_exception(self) -> None:
        self.assertTrue(issubclass(PluginTimeoutError, Exception))

    def test_plugin_credentials_missing_is_exception(self) -> None:
        self.assertTrue(issubclass(PluginCredentialsMissing, Exception))

    def test_plugin_not_found_error_can_be_raised(self) -> None:
        with self.assertRaises(PluginNotFoundError):
            raise PluginNotFoundError('test-slug')

    def test_plugin_unavailable_error_can_be_raised(self) -> None:
        with self.assertRaises(PluginUnavailableError):
            raise PluginUnavailableError('test-slug')

    def test_cursor_expired_error_can_be_raised(self) -> None:
        with self.assertRaises(CursorExpiredError):
            raise CursorExpiredError('cursor-123')

    def test_plugin_timeout_error_can_be_raised(self) -> None:
        with self.assertRaises(PluginTimeoutError):
            raise PluginTimeoutError('timed out after 30s')

    def test_plugin_credentials_missing_can_be_raised(self) -> None:
        with self.assertRaises(PluginCredentialsMissing):
            raise PluginCredentialsMissing('api_key')

    def test_plugin_authentication_failed_is_exception(self) -> None:
        self.assertTrue(issubclass(PluginAuthenticationFailed, Exception))

    def test_plugin_authentication_failed_can_be_raised(self) -> None:
        with self.assertRaises(PluginAuthenticationFailed):
            raise PluginAuthenticationFailed('401 from upstream')

    def test_plugin_rate_limited_is_exception(self) -> None:
        self.assertTrue(issubclass(PluginRateLimited, Exception))

    def test_plugin_rate_limited_carries_retry_at(self) -> None:
        exc = PluginRateLimited(retry_at=1234.0)
        self.assertEqual(1234.0, exc.retry_at)

    def test_plugin_rate_limited_default_message(self) -> None:
        exc = PluginRateLimited(retry_at=1234.5)
        self.assertEqual('Rate limited until epoch 1234', str(exc))

    def test_plugin_rate_limited_custom_message(self) -> None:
        exc = PluginRateLimited(retry_at=1234.0, message='primary limit')
        self.assertEqual('primary limit', str(exc))

    def test_plugin_rate_limited_can_be_raised(self) -> None:
        with self.assertRaises(PluginRateLimited):
            raise PluginRateLimited(retry_at=1234.0)
