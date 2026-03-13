"""Email sending module for Imbi transactional emails.

This module provides email sending capabilities including:
- Password reset emails
- Welcome emails for new users
- Email verification
- Security alerts

The module uses SMTP for email delivery with retry logic. All emails are
rendered using Jinja2 templates with both HTML and plain text versions.
"""

import logging
from urllib import parse

from imbi_common import clickhouse, neo4j

from .client import EmailClient
from .dependencies import InjectEmailClient, InjectTemplateManager
from .templates import TemplateManager

from . import models  # isort: skip

LOGGER = logging.getLogger(__name__)

__all__ = [
    'EmailClient',
    'InjectEmailClient',
    'InjectTemplateManager',
    'TemplateManager',
    'send_password_reset',
    'send_welcome_email',
]


async def send_welcome_email(
    email_client: EmailClient,
    template_manager: TemplateManager,
    *,
    username: str,
    email: str,
    display_name: str,
    login_url: str,
) -> models.EmailAudit:
    """Send a welcome email to a new user.

    Args:
        email_client: SMTP client for sending emails.
        template_manager: Jinja2 template renderer.
        username: User's username
        email: User's email address
        display_name: User's display name for personalization
        login_url: URL for user to log in

    Returns:
        EmailAudit record with send status

    """
    LOGGER.info('Sending welcome email to %s', email)

    # Render template
    message = template_manager.render_email(
        'welcome',
        {
            'to_email': email,
            'username': username,
            'display_name': display_name,
            'login_url': login_url,
        },
    )

    # Send email
    audit = await email_client.send_email(message)

    # Save audit to ClickHouse
    await _save_audit(audit)

    LOGGER.info(
        'Welcome email to %s: status=%s',
        email,
        audit.status,
    )

    return audit


async def send_password_reset(
    email_client: EmailClient,
    template_manager: TemplateManager,
    *,
    username: str,
    email: str,
    display_name: str,
    reset_url_base: str,
) -> tuple[models.PasswordResetToken, models.EmailAudit]:
    """Send a password reset email with a secure token.

    Args:
        email_client: SMTP client for sending emails.
        template_manager: Jinja2 template renderer.
        username: User's username
        email: User's email address
        display_name: User's display name for personalization
        reset_url_base: Base URL for password reset page (token appended)

    Returns:
        Tuple of (PasswordResetToken, EmailAudit)

    """
    LOGGER.info('Sending password reset email to %s', email)

    # Create password reset token
    token_model = models.PasswordResetToken.create(
        username=username,
        email=email,
    )

    # Store token in Neo4j
    await neo4j.create_node(token_model)
    LOGGER.debug('Password reset token stored in Neo4j for %s', username)

    # Build reset URL with token (handle existing query params)
    parsed = parse.urlparse(reset_url_base)
    query_params = parse.parse_qs(parsed.query)
    query_params['token'] = [token_model.token]
    new_query = parse.urlencode(query_params, doseq=True)
    reset_url = parse.urlunparse(parsed._replace(query=new_query))

    # Render template
    message = template_manager.render_email(
        'password_reset',
        {
            'to_email': email,
            'display_name': display_name,
            'reset_url': reset_url,
        },
    )

    # Send email
    audit = await email_client.send_email(message)

    # Save audit to ClickHouse
    await _save_audit(audit)

    LOGGER.info(
        'Password reset email to %s: status=%s',
        email,
        audit.status,
    )

    return token_model, audit


async def _save_audit(audit: models.EmailAudit) -> None:
    """Save email audit record to ClickHouse.

    Args:
        audit: Email audit record to save

    """
    try:
        await clickhouse.insert('email_audit', [audit])
        LOGGER.debug('Email audit saved to ClickHouse: %s', audit.to_email)
    except clickhouse.client.DatabaseError as err:
        # Log error but don't fail the email send
        LOGGER.warning(
            'Failed to save email audit to ClickHouse: %s',
            err,
        )
