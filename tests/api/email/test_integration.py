"""Integration tests for email module with Mailpit.

These tests verify end-to-end email sending with a real SMTP server
(Mailpit).
"""

import os
import unittest
from unittest import mock

import httpx
from imbi_common import graph

from imbi_api.email import client, templates


class MailpitIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for Mailpit integration."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Get Mailpit configuration from environment
        self.mailpit_smtp_host = os.getenv('MAILPIT_SMTP_HOST', '127.0.0.1')
        self.mailpit_smtp_port = int(os.getenv('MAILPIT_SMTP_PORT', '1025'))
        self.mailpit_api_url = os.getenv(
            'MAILPIT_API_URL',
            'http://127.0.0.1:8025',
        )

        # Check if Mailpit is available
        self.mailpit_available = self._is_mailpit_available()

        # Create a mock graph.Graph for tests that need it
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.mock_db.merge = mock.AsyncMock(return_value=None)

    def _is_mailpit_available(self) -> bool:
        """Check if Mailpit is running and accessible."""
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

        from imbi_api import email

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

            email_client = client.EmailClient()
            await email_client.initialize()
            template_manager = templates.TemplateManager()

            with mock.patch('imbi_common.clickhouse.insert') as mock_insert:
                mock_insert.return_value = None

                audit = await email.send_welcome_email(
                    email_client,
                    template_manager,
                    username='testuser',
                    email='test@example.com',
                    display_name='Test User',
                    login_url='https://imbi.example.com/login',
                )

                self.assertEqual(audit.to_email, 'test@example.com')
                self.assertEqual(audit.template_name, 'welcome')
                self.assertEqual(audit.status, 'sent')
                self.assertIsNone(audit.error_message)

                mock_insert.assert_called_once()

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
        """Verify email was received by Mailpit."""
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(
                f'{self.mailpit_api_url}/api/v1/messages',
                timeout=5.0,
            )
            self.assertEqual(response.status_code, 200)

            data = response.json()
            messages = data.get('messages', [])

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

            self.assertEqual(message['Subject'], expected_subject)

            message_id = message['ID']
            response = await http_client.get(
                f'{self.mailpit_api_url}/api/v1/message/{message_id}',
                timeout=5.0,
            )
            self.assertEqual(response.status_code, 200)

            full_message = response.json()

            html_body = full_message.get('HTML', '')
            self.assertIn(
                expected_content_html,
                html_body,
                'Expected content not found in HTML body',
            )

            text_body = full_message.get('Text', '')
            self.assertIn(
                expected_content_text,
                text_body,
                'Expected content not found in text body',
            )

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

            email_client = client.EmailClient()
            template_manager = templates.TemplateManager()

            with mock.patch('imbi_common.clickhouse.insert'):
                audit = await email.send_welcome_email(
                    email_client,
                    template_manager,
                    username='testuser',
                    email='test@example.com',
                    display_name='Test User',
                    login_url='https://imbi.example.com/login',
                )

                self.assertEqual(audit.status, 'skipped')
                self.assertEqual(audit.error_message, 'Email disabled')

    async def test_email_dry_run(self) -> None:
        """Test that emails are logged but not sent in dry-run."""
        from imbi_api import email

        with mock.patch(
            'imbi_api.email.client.settings.Email'
        ) as mock_settings:
            email_settings = mock_settings.return_value
            email_settings.enabled = True
            email_settings.dry_run = True

            email_client = client.EmailClient()
            template_manager = templates.TemplateManager()

            with mock.patch('imbi_common.clickhouse.insert'):
                audit = await email.send_welcome_email(
                    email_client,
                    template_manager,
                    username='testuser',
                    email='test@example.com',
                    display_name='Test User',
                    login_url='https://imbi.example.com/login',
                )

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

            email_client = client.EmailClient()
            template_manager = templates.TemplateManager()

            with mock.patch('imbi_common.clickhouse.insert'):
                token, audit = await email.send_password_reset(
                    email_client,
                    template_manager,
                    self.mock_db,
                    username='testuser',
                    email='test@example.com',
                    display_name='Test User',
                    reset_url_base=('https://imbi.example.com/reset'),
                )

                self.assertEqual(token.email, 'test@example.com')
                self.assertIsNotNone(token.token)
                self.assertIsNotNone(token.expires_at)

                self.mock_db.merge.assert_called_once()

                self.assertEqual(audit.to_email, 'test@example.com')
                self.assertEqual(audit.template_name, 'password_reset')
                self.assertEqual(audit.status, 'dry_run')

    async def test_clickhouse_audit_error_handling(self) -> None:
        """Test that ClickHouse errors don't fail email sends."""
        from imbi_common import clickhouse

        from imbi_api import email

        with mock.patch(
            'imbi_api.email.client.settings.Email'
        ) as mock_settings:
            email_settings = mock_settings.return_value
            email_settings.enabled = True
            email_settings.dry_run = True

            email_client = client.EmailClient()
            template_manager = templates.TemplateManager()

            with mock.patch('imbi_common.clickhouse.insert') as mock_insert:
                mock_insert.side_effect = clickhouse.client.DatabaseError(
                    'Connection failed'
                )

                audit = await email.send_welcome_email(
                    email_client,
                    template_manager,
                    username='testuser',
                    email='test@example.com',
                    display_name='Test User',
                    login_url='https://imbi.example.com/login',
                )

                self.assertEqual(audit.status, 'dry_run')
                self.assertEqual(audit.to_email, 'test@example.com')

    async def test_password_reset_url_with_existing_params(
        self,
    ) -> None:
        """Test password reset URL handles existing query params."""
        from imbi_api import email

        with mock.patch(
            'imbi_api.email.client.settings.Email'
        ) as mock_settings:
            email_settings = mock_settings.return_value
            email_settings.enabled = True
            email_settings.dry_run = True

            email_client = client.EmailClient()
            template_manager = templates.TemplateManager()

            with mock.patch('imbi_common.clickhouse.insert'):
                with mock.patch.object(
                    template_manager,
                    'render_email',
                ) as mock_render:
                    mock_message = mock.MagicMock()
                    mock_message.to_email = 'test@example.com'
                    mock_message.template_name = 'password_reset'
                    mock_message.subject = 'Password Reset'
                    mock_render.return_value = mock_message

                    base_url = (
                        'https://imbi.example.com/reset?mode=secure&lang=en'
                    )
                    _token, _audit = await email.send_password_reset(
                        email_client,
                        template_manager,
                        self.mock_db,
                        username='testuser',
                        email='test@example.com',
                        display_name='Test User',
                        reset_url_base=base_url,
                    )

                    mock_render.assert_called_once()
                    call_args = mock_render.call_args[0]
                    context = call_args[1]

                    reset_url = context['reset_url']
                    self.assertIn('token=', reset_url)
                    self.assertIn('mode=secure', reset_url)
                    self.assertIn('lang=en', reset_url)
