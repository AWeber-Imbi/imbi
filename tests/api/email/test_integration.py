"""Integration tests for email module with Mailpit.

These tests verify end-to-end email sending with a real SMTP server (Mailpit).
"""

import os
import unittest
from unittest import mock

import httpx

from imbi_api.email import client, templates


class MailpitIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for Mailpit integration."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Reset singletons for test isolation
        client.EmailClient._instance = None
        templates.TemplateManager._instance = None

        # Get Mailpit configuration from environment
        self.mailpit_smtp_host = os.getenv('MAILPIT_SMTP_HOST', '127.0.0.1')
        self.mailpit_smtp_port = int(os.getenv('MAILPIT_SMTP_PORT', '1025'))
        self.mailpit_api_url = os.getenv(
            'MAILPIT_API_URL',
            'http://127.0.0.1:8025',
        )

        # Check if Mailpit is available
        self.mailpit_available = self._is_mailpit_available()

    def _is_mailpit_available(self) -> bool:
        """Check if Mailpit is running and accessible.

        Returns:
            True if Mailpit API is reachable, False otherwise.

        """
        try:
            import socket

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(
                (self.mailpit_smtp_host, self.mailpit_smtp_port)
            )
            sock.close()
            return result == 0
        except OSError:
            return False

    async def test_send_welcome_email_with_mailpit(self) -> None:
        """Test sending welcome email through Mailpit."""
        if not self.mailpit_available:
            self.skipTest('Mailpit not available')

        # Import here to avoid circular dependency
        from imbi_api import email

        # Mock settings to use Mailpit
        with mock.patch(
            'imbi_api.email.client.settings.Email'
        ) as mock_settings:
            email_settings = mock_settings.return_value
            email_settings.enabled = True
            email_settings.dry_run = False
            email_settings.smtp_host = self.mailpit_smtp_host
            email_settings.smtp_port = self.mailpit_smtp_port
            email_settings.smtp_use_tls = False
            email_settings.smtp_use_ssl = False
            email_settings.smtp_username = None
            email_settings.smtp_password = None
            email_settings.smtp_timeout = 10
            email_settings.from_email = 'noreply@imbi.example'
            email_settings.from_name = 'Imbi Test'
            email_settings.reply_to = None

            # Mock ClickHouse to avoid database dependency
            with mock.patch('imbi_api.clickhouse.insert') as mock_insert:
                mock_insert.return_value = None

                # Send email
                audit = await email.send_welcome_email(
                    username='testuser',
                    email='test@example.com',
                    display_name='Test User',
                    login_url='https://imbi.example.com/login',
                )

                # Verify audit record
                self.assertEqual(audit.to_email, 'test@example.com')
                self.assertEqual(audit.template_name, 'welcome')
                self.assertEqual(audit.status, 'sent')
                self.assertIsNone(audit.error_message)

                # Verify ClickHouse insert was called
                mock_insert.assert_called_once()

        # Verify email in Mailpit via API
        await self._verify_email_in_mailpit(
            to_email='test@example.com',
            expected_subject='Welcome to Imbi, Test User!',
            expected_content_html='Test User',
            expected_content_text='Test User',
        )

    async def _verify_email_in_mailpit(
        self,
        to_email: str,
        expected_subject: str,
        expected_content_html: str,
        expected_content_text: str,
    ) -> None:
        """Verify email was received by Mailpit.

        Args:
            to_email: Expected recipient email
            expected_subject: Expected email subject
            expected_content_html: Expected string in HTML body
            expected_content_text: Expected string in text body

        """
        # Query Mailpit API for messages
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(
                f'{self.mailpit_api_url}/api/v1/messages',
                timeout=5.0,
            )
            self.assertEqual(response.status_code, 200)

            data = response.json()
            messages = data.get('messages', [])

            # Find message to our recipient
            message = None
            for msg in messages:
                if any(
                    rcpt['Address'] == to_email for rcpt in msg.get('To', [])
                ):
                    message = msg
                    break

            self.assertIsNotNone(
                message,
                f'No message found to {to_email} in Mailpit',
            )

            # Verify subject
            self.assertEqual(message['Subject'], expected_subject)

            # Get full message details
            message_id = message['ID']
            response = await http_client.get(
                f'{self.mailpit_api_url}/api/v1/message/{message_id}',
                timeout=5.0,
            )
            self.assertEqual(response.status_code, 200)

            full_message = response.json()

            # Verify HTML content
            html_body = full_message.get('HTML', '')
            self.assertIn(
                expected_content_html,
                html_body,
                'Expected content not found in HTML body',
            )

            # Verify text content
            text_body = full_message.get('Text', '')
            self.assertIn(
                expected_content_text,
                text_body,
                'Expected content not found in text body',
            )

            # Verify both HTML and text parts exist
            self.assertTrue(html_body, 'HTML body is empty')
            self.assertTrue(text_body, 'Text body is empty')

    async def test_email_disabled(self) -> None:
        """Test that emails are skipped when disabled."""
        from imbi_api import email

        with mock.patch(
            'imbi_api.email.client.settings.Email'
        ) as mock_settings:
            email_settings = mock_settings.return_value
            email_settings.enabled = False

            with mock.patch('imbi_api.clickhouse.insert'):
                audit = await email.send_welcome_email(
                    username='testuser',
                    email='test@example.com',
                    display_name='Test User',
                    login_url='https://imbi.example.com/login',
                )

                # Verify email was skipped
                self.assertEqual(audit.status, 'skipped')
                self.assertEqual(audit.error_message, 'Email disabled')

    async def test_email_dry_run(self) -> None:
        """Test that emails are logged but not sent in dry-run mode."""
        from imbi_api import email

        with mock.patch(
            'imbi_api.email.client.settings.Email'
        ) as mock_settings:
            email_settings = mock_settings.return_value
            email_settings.enabled = True
            email_settings.dry_run = True

            with mock.patch('imbi_api.clickhouse.insert'):
                audit = await email.send_welcome_email(
                    username='testuser',
                    email='test@example.com',
                    display_name='Test User',
                    login_url='https://imbi.example.com/login',
                )

                # Verify email was marked as dry-run
                self.assertEqual(audit.status, 'dry_run')
                self.assertEqual(audit.error_message, 'Dry run mode')

    async def test_send_password_reset_email(self) -> None:
        """Test sending password reset email."""
        from imbi_api import email

        with mock.patch(
            'imbi_api.email.client.settings.Email'
        ) as mock_settings:
            email_settings = mock_settings.return_value
            email_settings.enabled = True
            email_settings.dry_run = True

            with mock.patch('imbi_api.clickhouse.insert'):
                with mock.patch('imbi_api.neo4j.create_node') as mock_create:
                    mock_create.return_value = None

                    token, audit = await email.send_password_reset(
                        username='testuser',
                        email='test@example.com',
                        display_name='Test User',
                        reset_url_base='https://imbi.example.com/reset',
                    )

                    # Verify token was created
                    self.assertEqual(token.email, 'test@example.com')
                    self.assertIsNotNone(token.token)
                    self.assertIsNotNone(token.expires_at)

                    # Verify Neo4j create_node was called
                    mock_create.assert_called_once()

                    # Verify audit record
                    self.assertEqual(audit.to_email, 'test@example.com')
                    self.assertEqual(audit.template_name, 'password_reset')
                    self.assertEqual(audit.status, 'dry_run')

    async def test_clickhouse_audit_error_handling(self) -> None:
        """Test that ClickHouse errors don't fail email sends."""
        from imbi_api import clickhouse, email

        with mock.patch(
            'imbi_api.email.client.settings.Email'
        ) as mock_settings:
            email_settings = mock_settings.return_value
            email_settings.enabled = True
            email_settings.dry_run = True

            # Mock ClickHouse to raise an error
            with mock.patch('imbi_api.clickhouse.insert') as mock_insert:
                mock_insert.side_effect = clickhouse.client.DatabaseError(
                    'Connection failed'
                )

                # Email send should still succeed despite audit failure
                audit = await email.send_welcome_email(
                    username='testuser',
                    email='test@example.com',
                    display_name='Test User',
                    login_url='https://imbi.example.com/login',
                )

                # Verify email was still sent
                self.assertEqual(audit.status, 'dry_run')
                self.assertEqual(audit.to_email, 'test@example.com')

    async def test_password_reset_url_with_existing_params(self) -> None:
        """Test password reset URL handles existing query parameters."""
        from imbi_api import email

        with mock.patch(
            'imbi_api.email.client.settings.Email'
        ) as mock_settings:
            email_settings = mock_settings.return_value
            email_settings.enabled = True
            email_settings.dry_run = True

            with mock.patch('imbi_api.clickhouse.insert'):
                with mock.patch('imbi_api.neo4j.create_node') as mock_create:
                    mock_create.return_value = None

                    # Mock template manager to capture reset URL
                    with mock.patch(
                        'imbi_api.email.templates.TemplateManager.render_email'
                    ) as mock_render:
                        # Mock message with required attributes
                        mock_message = mock.MagicMock()
                        mock_message.to_email = 'test@example.com'
                        mock_message.template_name = 'password_reset'
                        mock_message.subject = 'Password Reset'
                        mock_render.return_value = mock_message

                        # Test with URL that already has query params
                        base_url = (
                            'https://imbi.example.com/reset'
                            '?mode=secure&lang=en'
                        )
                        _token, _audit = await email.send_password_reset(
                            username='testuser',
                            email='test@example.com',
                            display_name='Test User',
                            reset_url_base=base_url,
                        )

                        # Verify template was called
                        mock_render.assert_called_once()
                        call_args = mock_render.call_args[0]
                        context = call_args[1]

                        # Verify reset URL contains token and preserves
                        # existing params
                        reset_url = context['reset_url']
                        self.assertIn('token=', reset_url)
                        self.assertIn('mode=secure', reset_url)
                        self.assertIn('lang=en', reset_url)
