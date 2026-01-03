"""Unit tests for logging module."""

import logging as stdlib_logging
import unittest

from imbi_common import logging


class TestGetLogConfig(unittest.TestCase):
    """Test get_log_config function."""

    def test_returns_dict(self):
        """Test that get_log_config returns a dictionary."""
        config = logging.get_log_config()
        self.assertIsInstance(config, dict)

    def test_has_version_key(self):
        """Test that config has version key."""
        config = logging.get_log_config()
        self.assertIn('version', config)
        self.assertEqual(config['version'], 1)

    def test_has_formatters(self):
        """Test that config has formatters section."""
        config = logging.get_log_config()
        self.assertIn('formatters', config)
        self.assertIsInstance(config['formatters'], dict)

    def test_has_handlers(self):
        """Test that config has handlers section."""
        config = logging.get_log_config()
        self.assertIn('handlers', config)
        self.assertIsInstance(config['handlers'], dict)

    def test_has_loggers(self):
        """Test that config has loggers section."""
        config = logging.get_log_config()
        self.assertIn('loggers', config)
        self.assertIsInstance(config['loggers'], dict)


class TestConfigureLogging(unittest.TestCase):
    """Test configure_logging function."""

    def test_configure_logging_no_errors(self):
        """Test that configure_logging runs without errors."""
        logging.configure_logging()

    def test_configure_logging_with_dev_mode(self):
        """Test configure_logging with dev mode enabled."""
        logging.configure_logging(dev=True)

        # Verify imbi logger is at DEBUG level
        logger = stdlib_logging.getLogger('imbi')
        self.assertEqual(logger.level, stdlib_logging.DEBUG)

    def test_configure_logging_with_custom_config(self):
        """Test configure_logging with custom config dict."""
        custom_config = {
            'version': 1,
            'disable_existing_loggers': False,
            'formatters': {'simple': {'format': '%(levelname)s: %(message)s'}},
            'handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'simple',
                }
            },
            'loggers': {
                'test_logger': {'level': 'INFO', 'handlers': ['console']}
            },
        }

        logging.configure_logging(log_config=custom_config)

        # Verify custom logger is configured
        logger = stdlib_logging.getLogger('test_logger')
        self.assertEqual(logger.level, stdlib_logging.INFO)


if __name__ == '__main__':
    unittest.main()
