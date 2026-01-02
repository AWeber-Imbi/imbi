"""Tests for email module initialization and cleanup."""

import unittest
from unittest import mock

from imbi import email
from imbi.email import client, templates


class EmailModuleTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for email module-level functions."""

    async def asyncSetUp(self) -> None:
        """Set up test fixtures."""
        # Reset singletons for test isolation
        client.EmailClient._instance = None
        templates.TemplateManager._instance = None

    async def test_initialize_success(self) -> None:
        """Test successful email module initialization."""
        with mock.patch('imbi.email.client.settings.Email') as mock_settings:
            email_settings = mock_settings.return_value
            email_settings.enabled = False

            await email.initialize()

            # Verify singletons were created
            self.assertIsNotNone(client.EmailClient._instance)
            self.assertIsNotNone(templates.TemplateManager._instance)
            self.assertTrue(client.EmailClient._instance._initialized)

    async def test_initialize_with_smtp_connection(self) -> None:
        """Test email module initialization with SMTP connection."""
        with mock.patch('imbi.email.client.settings.Email') as mock_settings:
            email_settings = mock_settings.return_value
            email_settings.enabled = True
            email_settings.smtp_host = 'localhost'
            email_settings.smtp_port = 1025
            email_settings.smtp_timeout = 30
            email_settings.smtp_use_tls = False
            email_settings.smtp_use_ssl = False

            with mock.patch('smtplib.SMTP') as mock_smtp_class:
                mock_smtp = mock.MagicMock()
                mock_smtp_class.return_value.__enter__.return_value = mock_smtp

                await email.initialize()

                # Verify SMTP connection was tested
                mock_smtp_class.assert_called_once_with(
                    'localhost',
                    1025,
                    timeout=30,
                )
                mock_smtp.noop.assert_called_once()

    async def test_aclose_with_initialized_instance(self) -> None:
        """Test email module cleanup with initialized instance."""
        with mock.patch('imbi.email.client.settings.Email') as mock_settings:
            email_settings = mock_settings.return_value
            email_settings.enabled = False

            # Initialize first
            await email.initialize()
            self.assertIsNotNone(client.EmailClient._instance)
            self.assertIsNotNone(templates.TemplateManager._instance)

            # Clean up
            await email.aclose()

            # Verify singletons were reset
            self.assertIsNone(client.EmailClient._instance)
            self.assertIsNone(templates.TemplateManager._instance)

    async def test_aclose_without_initialized_instance(self) -> None:
        """Test email module cleanup without initialized instance."""
        # Ensure singletons are None
        client.EmailClient._instance = None
        templates.TemplateManager._instance = None

        # Should not raise an error
        await email.aclose()

        # Verify singletons remain None
        self.assertIsNone(client.EmailClient._instance)
        self.assertIsNone(templates.TemplateManager._instance)
