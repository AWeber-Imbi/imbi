"""Tests for email.client module."""

import datetime
import smtplib
import unittest
from unittest import mock

from imbi_api.email import client, models


class EmailClientTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for EmailClient."""

    async def asyncSetUp(self) -> None:
        """Set up test fixtures."""
        # Reset singleton for test isolation
        client.EmailClient._instance = None

        # Mock settings
        self.mock_settings_patcher = mock.patch(
            'imbi_api.email.client.settings.Email'
        )
        self.mock_settings_class = self.mock_settings_patcher.start()
        self.mock_settings = mock.MagicMock()
        self.mock_settings_class.return_value = self.mock_settings

        # Configure default settings
        self.mock_settings.enabled = True
        self.mock_settings.dry_run = False
        self.mock_settings.smtp_host = 'localhost'
        self.mock_settings.smtp_port = 1025
        self.mock_settings.smtp_use_tls = False
        self.mock_settings.smtp_use_ssl = False
        self.mock_settings.smtp_username = None
        self.mock_settings.smtp_password = None
        self.mock_settings.smtp_timeout = 30
        self.mock_settings.from_email = 'noreply@imbi.local'
        self.mock_settings.from_name = 'Imbi Test'
        self.mock_settings.reply_to = None
        self.mock_settings.max_retries = 3
        self.mock_settings.initial_retry_delay = 1.0
        self.mock_settings.retry_backoff_factor = 2.0

        # Mock SMTP
        self.mock_smtp = mock.MagicMock()
        self.smtp_patcher = mock.patch('smtplib.SMTP')
        self.mock_smtp_class = self.smtp_patcher.start()
        self.mock_smtp_class.return_value.__enter__.return_value = (
            self.mock_smtp
        )

        self.addCleanup(self.mock_settings_patcher.stop)
        self.addCleanup(self.smtp_patcher.stop)

    async def test_singleton_pattern(self) -> None:
        """Test EmailClient uses singleton pattern."""
        instance1 = client.EmailClient.get_instance()
        instance2 = client.EmailClient.get_instance()
        self.assertIs(instance1, instance2)

    async def test_initialize_success(self) -> None:
        """Test successful email client initialization."""
        email_client = client.EmailClient.get_instance()
        await email_client.initialize()

        self.assertTrue(email_client._initialized)
        self.mock_smtp_class.assert_called_once_with(
            'localhost', 1025, timeout=30
        )
        self.mock_smtp.noop.assert_called_once()

    async def test_initialize_disabled(self) -> None:
        """Test initialization when email sending is disabled."""
        self.mock_settings.enabled = False

        email_client = client.EmailClient.get_instance()
        await email_client.initialize()

        self.assertTrue(email_client._initialized)
        self.mock_smtp_class.assert_not_called()

    async def test_initialize_idempotent(self) -> None:
        """Test initialize is idempotent (can be called multiple times)."""
        email_client = client.EmailClient.get_instance()
        await email_client.initialize()
        await email_client.initialize()

        # Should only initialize once
        self.assertEqual(self.mock_smtp_class.call_count, 1)

    async def test_send_email_success(self) -> None:
        """Test successful email sending."""
        email_client = client.EmailClient.get_instance()
        await email_client.initialize()

        message = models.EmailMessage(
            to_email='user@example.com',
            subject='Test Email',
            html_body='<p>Test HTML</p>',
            text_body='Test text',
            template_name='test',
            context={},
        )

        audit = await email_client.send_email(message)

        self.assertEqual(audit.status, 'sent')
        self.assertEqual(audit.to_email, 'user@example.com')
        self.assertEqual(audit.subject, 'Test Email')
        self.assertEqual(audit.template_name, 'test')
        self.assertIsNone(audit.error_message)
        self.mock_smtp.send_message.assert_called_once()

    async def test_send_email_disabled(self) -> None:
        """Test email sending when disabled."""
        self.mock_settings.enabled = False

        email_client = client.EmailClient.get_instance()
        message = models.EmailMessage(
            to_email='user@example.com',
            subject='Test',
            html_body='<p>Test</p>',
            text_body='Test',
            template_name='test',
            context={},
        )

        audit = await email_client.send_email(message)

        self.assertEqual(audit.status, 'skipped')
        self.assertEqual(audit.error_message, 'Email disabled')
        self.mock_smtp.send_message.assert_not_called()

    async def test_send_email_dry_run(self) -> None:
        """Test email sending in dry run mode."""
        self.mock_settings.dry_run = True

        email_client = client.EmailClient.get_instance()
        message = models.EmailMessage(
            to_email='user@example.com',
            subject='Test',
            html_body='<p>Test</p>',
            text_body='Test',
            template_name='test',
            context={},
        )

        audit = await email_client.send_email(message)

        self.assertEqual(audit.status, 'dry_run')
        self.assertEqual(audit.error_message, 'Dry run mode')
        self.mock_smtp.send_message.assert_not_called()

    async def test_send_email_failure(self) -> None:
        """Test email sending failure."""
        import smtplib

        self.mock_smtp.send_message.side_effect = smtplib.SMTPException(
            'SMTP error'
        )

        email_client = client.EmailClient.get_instance()
        await email_client.initialize()

        message = models.EmailMessage(
            to_email='user@example.com',
            subject='Test',
            html_body='<p>Test</p>',
            text_body='Test',
            template_name='test',
            context={},
        )

        audit = await email_client.send_email(message)

        self.assertEqual(audit.status, 'failed')
        self.assertIn('SMTP error', audit.error_message)
        # Should retry 3 times (max_retries=3) plus initial attempt = 4 total
        self.assertEqual(self.mock_smtp.send_message.call_count, 4)

    async def test_send_email_with_tls(self) -> None:
        """Test email sending with TLS."""
        self.mock_settings.smtp_use_tls = True

        email_client = client.EmailClient.get_instance()
        await email_client.initialize()

        # Reset mock after initialization
        self.mock_smtp.reset_mock()

        message = models.EmailMessage(
            to_email='user@example.com',
            subject='Test',
            html_body='<p>Test</p>',
            text_body='Test',
            template_name='test',
            context={},
        )

        await email_client.send_email(message)

        self.mock_smtp.starttls.assert_called_once()
        self.mock_smtp.send_message.assert_called_once()

    async def test_send_email_with_authentication(self) -> None:
        """Test email sending with SMTP authentication."""
        self.mock_settings.smtp_username = 'testuser'
        self.mock_settings.smtp_password = 'testpass'

        email_client = client.EmailClient.get_instance()
        await email_client.initialize()

        message = models.EmailMessage(
            to_email='user@example.com',
            subject='Test',
            html_body='<p>Test</p>',
            text_body='Test',
            template_name='test',
            context={},
        )

        await email_client.send_email(message)

        self.mock_smtp.login.assert_called_with('testuser', 'testpass')
        self.mock_smtp.send_message.assert_called_once()

    async def test_send_email_with_ssl(self) -> None:
        """Test email sending with SSL."""
        self.mock_settings.smtp_use_ssl = True
        self.mock_settings.smtp_use_tls = False
        self.mock_settings.smtp_port = 465

        # Mock SMTP_SSL
        mock_smtp_ssl = mock.MagicMock()
        with mock.patch('smtplib.SMTP_SSL') as mock_smtp_ssl_class:
            mock_smtp_ssl_class.return_value.__enter__.return_value = (
                mock_smtp_ssl
            )

            email_client = client.EmailClient.get_instance()
            await email_client.initialize()

            message = models.EmailMessage(
                to_email='user@example.com',
                subject='Test',
                html_body='<p>Test</p>',
                text_body='Test',
                template_name='test',
                context={},
            )

            await email_client.send_email(message)

            mock_smtp_ssl_class.assert_called()
            mock_smtp_ssl.send_message.assert_called_once()

    async def test_aclose(self) -> None:
        """Test email client cleanup."""
        email_client = client.EmailClient.get_instance()
        await email_client.initialize()

        self.assertTrue(email_client._initialized)

        await email_client.aclose()

        self.assertFalse(email_client._initialized)

    async def test_create_audit(self) -> None:
        """Test audit record creation."""
        email_client = client.EmailClient.get_instance()

        message = models.EmailMessage(
            to_email='user@example.com',
            subject='Test Email',
            html_body='<p>Test</p>',
            text_body='Test',
            template_name='test',
            context={'key': 'value'},
        )

        audit = email_client._create_audit(message, 'sent', None)

        self.assertEqual(audit.to_email, 'user@example.com')
        self.assertEqual(audit.subject, 'Test Email')
        self.assertEqual(audit.template_name, 'test')
        self.assertEqual(audit.status, 'sent')
        self.assertIsNone(audit.error_message)
        self.assertIsInstance(audit.sent_at, datetime.datetime)

    async def test_retry_success_on_second_attempt(self) -> None:
        """Test retry succeeds on second attempt."""
        self.mock_settings.max_retries = 3
        self.mock_settings.initial_retry_delay = 0.01
        self.mock_settings.retry_backoff_factor = 2.0

        email_client = client.EmailClient.get_instance()
        await email_client.initialize()

        message = models.EmailMessage(
            to_email='user@example.com',
            subject='Test',
            html_body='<p>Test</p>',
            text_body='Test',
            template_name='test',
            context={},
        )

        # Fail first attempt, succeed second
        self.mock_smtp.send_message.side_effect = [
            smtplib.SMTPException('Transient error'),
            None,
        ]

        audit = await email_client.send_email(message)

        self.assertEqual(audit.status, 'sent')
        self.assertIsNone(audit.error_message)
        self.assertEqual(self.mock_smtp.send_message.call_count, 2)

    async def test_retry_exhausted_all_attempts(self) -> None:
        """Test all retry attempts exhausted."""
        self.mock_settings.max_retries = 2
        self.mock_settings.initial_retry_delay = 0.01

        email_client = client.EmailClient.get_instance()
        await email_client.initialize()

        message = models.EmailMessage(
            to_email='user@example.com',
            subject='Test',
            html_body='<p>Test</p>',
            text_body='Test',
            template_name='test',
            context={},
        )

        # Fail all attempts
        self.mock_smtp.send_message.side_effect = smtplib.SMTPException(
            'Persistent error'
        )

        audit = await email_client.send_email(message)

        self.assertEqual(audit.status, 'failed')
        self.assertIn('after 3 attempts', audit.error_message)
        self.assertIn('Persistent error', audit.error_message)
        self.assertEqual(self.mock_smtp.send_message.call_count, 3)

    async def test_retry_exponential_backoff(self) -> None:
        """Test exponential backoff delays."""
        self.mock_settings.max_retries = 3
        self.mock_settings.initial_retry_delay = 0.1
        self.mock_settings.retry_backoff_factor = 2.0

        email_client = client.EmailClient.get_instance()
        await email_client.initialize()

        message = models.EmailMessage(
            to_email='user@example.com',
            subject='Test',
            html_body='<p>Test</p>',
            text_body='Test',
            template_name='test',
            context={},
        )

        # Track sleep calls to verify exponential backoff
        sleep_times = []

        async def mock_sleep(delay: float) -> None:
            sleep_times.append(delay)

        with mock.patch('asyncio.sleep', side_effect=mock_sleep):
            # Fail first 2 attempts, succeed third
            self.mock_smtp.send_message.side_effect = [
                smtplib.SMTPException('Error 1'),
                smtplib.SMTPException('Error 2'),
                None,
            ]

            audit = await email_client.send_email(message)

            self.assertEqual(audit.status, 'sent')
            self.assertEqual(len(sleep_times), 2)
            # Verify exponential backoff: 0.1, 0.2
            self.assertAlmostEqual(sleep_times[0], 0.1, places=2)
            self.assertAlmostEqual(sleep_times[1], 0.2, places=2)

    async def test_retry_different_error_types(self) -> None:
        """Test retry handles different error types."""
        self.mock_settings.max_retries = 2
        self.mock_settings.initial_retry_delay = 0.01

        email_client = client.EmailClient.get_instance()
        await email_client.initialize()

        message = models.EmailMessage(
            to_email='user@example.com',
            subject='Test',
            html_body='<p>Test</p>',
            text_body='Test',
            template_name='test',
            context={},
        )

        # Test OSError retry
        self.mock_smtp.send_message.side_effect = [
            OSError('Connection refused'),
            None,
        ]

        audit = await email_client.send_email(message)
        self.assertEqual(audit.status, 'sent')

        # Reset and test TimeoutError retry
        self.mock_smtp.send_message.reset_mock()
        self.mock_smtp.send_message.side_effect = [
            TimeoutError('Timeout'),
            None,
        ]

        audit = await email_client.send_email(message)
        self.assertEqual(audit.status, 'sent')
