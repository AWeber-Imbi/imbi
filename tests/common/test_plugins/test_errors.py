import unittest

from imbi_common.plugins.errors import (
    CursorExpiredError,
    PluginAuthenticationFailed,
    PluginCredentialsMissing,
    PluginNotFoundError,
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
