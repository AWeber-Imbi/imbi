"""SMTP client for sending emails with retry logic and error handling."""

import asyncio
import datetime
import logging
import smtplib
import ssl
import typing
from email.mime import multipart, text

from imbi_common import settings

from . import models

LOGGER = logging.getLogger(__name__)


class EmailClient:
    """Singleton SMTP client for sending emails.

    The client uses Python's smtplib to send emails via SMTP. Operations
    run in an executor to avoid blocking the event loop. The client supports
    TLS/SSL connections and can be configured via Email settings.

    """

    _instance: typing.ClassVar[typing.Optional['EmailClient']] = None
    _lock: typing.ClassVar[asyncio.Lock] = asyncio.Lock()

    def __init__(self) -> None:
        self._settings = settings.Email()
        self._initialized = False

    @classmethod
    def get_instance(cls) -> 'EmailClient':
        """Get the singleton EmailClient instance.

        Returns:
            The singleton EmailClient instance.

        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def initialize(self) -> None:
        """Initialize the email client and verify SMTP connection.

        This tests the SMTP connection during application startup to
        catch configuration issues early.

        Raises:
            Exception: If SMTP connection test fails.

        """
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            if not self._settings.enabled:
                LOGGER.info('Email sending is disabled via configuration')
                self._initialized = True
                return

            # Test SMTP connection
            try:
                await self._test_connection()
                LOGGER.info(
                    'Email client initialized successfully (SMTP: %s:%d)',
                    self._settings.smtp_host,
                    self._settings.smtp_port,
                )
            except Exception:
                LOGGER.exception('Failed to initialize email client')
                raise

            self._initialized = True

    async def aclose(self) -> None:
        """Clean up email client resources."""
        async with self._lock:
            self._initialized = False
            LOGGER.debug('Email client closed')

    async def send_email(
        self,
        message: models.EmailMessage,
    ) -> models.EmailAudit:
        """Send an email via SMTP with retry logic.

        Implements exponential backoff for transient failures:
        - Initial delay: configured initial_retry_delay (default: 1.0s)
        - Backoff multiplier: configured retry_backoff_factor (default: 2.0)
        - Max retries: configured max_retries (default: 3)

        Args:
            message: EmailMessage to send

        Returns:
            EmailAudit record with send status

        """
        if not self._settings.enabled:
            return self._create_audit(message, 'skipped', 'Email disabled')

        if self._settings.dry_run:
            LOGGER.info(
                'DRY RUN: Would send email to %s with subject "%s"',
                message.to_email,
                message.subject,
            )
            return self._create_audit(message, 'dry_run', 'Dry run mode')

        # Retry logic with exponential backoff
        last_error = None
        delay = self._settings.initial_retry_delay

        for attempt in range(self._settings.max_retries + 1):
            try:
                await self._send_smtp(message)
                if attempt > 0:
                    LOGGER.info(
                        'Email sent to %s after %d retries',
                        message.to_email,
                        attempt,
                    )
                return self._create_audit(message, 'sent', None)

            except (smtplib.SMTPException, OSError, TimeoutError) as err:
                last_error = err
                is_final_attempt = attempt >= self._settings.max_retries

                if is_final_attempt:
                    LOGGER.exception(
                        'Failed to send email to %s after %d attempts',
                        message.to_email,
                        attempt + 1,
                    )
                else:
                    LOGGER.warning(
                        'Email send attempt %d/%d failed for %s: %s. '
                        'Retrying in %.2fs...',
                        attempt + 1,
                        self._settings.max_retries + 1,
                        message.to_email,
                        err,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    delay *= self._settings.retry_backoff_factor

        # All retries exhausted
        error_msg = (
            f'SMTP error after {self._settings.max_retries + 1} attempts: '
            f'{last_error}'
        )
        return self._create_audit(message, 'failed', error_msg)

    async def _send_smtp(self, message: models.EmailMessage) -> None:
        """Send email via SMTP (runs in executor to avoid blocking).

        Args:
            message: EmailMessage to send

        Raises:
            Exception: If SMTP send fails

        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send_smtp_sync, message)

    def _send_smtp_sync(self, message: models.EmailMessage) -> None:
        """Synchronous SMTP send operation.

        Args:
            message: EmailMessage to send

        Raises:
            Exception: If SMTP send fails

        """
        # Create MIME message
        msg = multipart.MIMEMultipart('alternative')
        msg['Subject'] = message.subject
        msg['From'] = (
            f'{self._settings.from_name} <{self._settings.from_email}>'
        )
        msg['To'] = message.to_email

        if self._settings.reply_to:
            msg['Reply-To'] = str(self._settings.reply_to)

        # Attach text and HTML parts (text first, HTML second for fallback)
        if message.text_body:
            msg.attach(text.MIMEText(message.text_body, 'plain', 'utf-8'))
        if message.html_body:
            msg.attach(text.MIMEText(message.html_body, 'html', 'utf-8'))

        # Send via SMTP
        smtp_class = (
            smtplib.SMTP_SSL if self._settings.smtp_use_ssl else smtplib.SMTP
        )

        with smtp_class(
            self._settings.smtp_host,
            self._settings.smtp_port,
            timeout=self._settings.smtp_timeout,
        ) as server:
            if self._settings.smtp_use_tls and not self._settings.smtp_use_ssl:
                context = ssl.create_default_context()
                server.starttls(context=context)

            if self._settings.smtp_username and self._settings.smtp_password:
                server.login(
                    self._settings.smtp_username,
                    self._settings.smtp_password,
                )

            server.send_message(msg)

    async def _test_connection(self) -> None:
        """Test SMTP connection during initialization.

        Raises:
            Exception: If SMTP connection test fails

        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._test_connection_sync)

    def _test_connection_sync(self) -> None:
        """Synchronous SMTP connection test.

        Raises:
            Exception: If SMTP connection test fails

        """
        smtp_class = (
            smtplib.SMTP_SSL if self._settings.smtp_use_ssl else smtplib.SMTP
        )

        with smtp_class(
            self._settings.smtp_host,
            self._settings.smtp_port,
            timeout=self._settings.smtp_timeout,
        ) as server:
            if self._settings.smtp_use_tls and not self._settings.smtp_use_ssl:
                context = ssl.create_default_context()
                server.starttls(context=context)

            if self._settings.smtp_username and self._settings.smtp_password:
                server.login(
                    self._settings.smtp_username,
                    self._settings.smtp_password,
                )

            server.noop()  # Test command

    def _create_audit(
        self,
        message: models.EmailMessage,
        status: typing.Literal['sent', 'failed', 'skipped', 'dry_run'],
        error: str | None,
    ) -> models.EmailAudit:
        """Create an audit record for an email send attempt.

        Args:
            message: EmailMessage that was sent or attempted
            status: Send status
            error: Error message if failed

        Returns:
            EmailAudit record

        """
        return models.EmailAudit(
            to_email=message.to_email,
            template_name=message.template_name,
            subject=message.subject,
            status=status,
            error_message=error,
            sent_at=datetime.datetime.now(datetime.UTC),
        )
