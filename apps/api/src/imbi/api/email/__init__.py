"""Email sending module for Imbi transactional emails.

This module provides email sending capabilities including:
- Password reset emails
- Welcome emails for new users
- Email verification
- Security alerts

The module uses SMTP for email delivery with retry logic and dead letter queue
for failed emails. All emails are rendered using Jinja2 templates with both
HTML and plain text versions.
"""

import logging
from urllib import parse

from imbi_common import clickhouse, neo4j

from . import client, models, templates

LOGGER = logging.getLogger(__name__)

__all__ = [
    'aclose',
    'initialize',
    'send_password_reset',
    'send_welcome_email',
]


async def initialize() -> None:
    """Initialize the email module.

    This should be called during application startup to:
    - Validate email settings
    - Initialize the email client singleton
    - Initialize the template manager singleton

    """
    LOGGER.info('Initializing email module')

    # Initialize singletons by getting instances
    email_client = client.EmailClient.get_instance()
    await email_client.initialize()
    templates.TemplateManager.get_instance()

    LOGGER.info('Email module initialized')


async def aclose() -> None:
    """Clean up email module resources.

    This should be called during application shutdown.

    """
    LOGGER.info('Closing email module')

    # Close and reset singletons
    if client.EmailClient._instance is not None:
        await client.EmailClient._instance.aclose()
    client.EmailClient._instance = None
    templates.TemplateManager._instance = None

    LOGGER.info('Email module closed')


async def send_welcome_email(
    username: str,
    email: str,
    display_name: str,
    login_url: str,
) -> models.EmailAudit:
    """Send a welcome email to a new user.

    Args:
        username: User's username
        email: User's email address
        display_name: User's display name for personalization
        login_url: URL for user to log in

    Returns:
        EmailAudit record with send status

    """
    LOGGER.info('Sending welcome email to %s', email)

    # Render template
    template_manager = templates.TemplateManager.get_instance()
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
    email_client = client.EmailClient.get_instance()
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
    username: str,
    email: str,
    display_name: str,
    reset_url_base: str,
) -> tuple[models.PasswordResetToken, models.EmailAudit]:
    """Send a password reset email with a secure token.

    Args:
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
    template_manager = templates.TemplateManager.get_instance()
    message = template_manager.render_email(
        'password_reset',
        {
            'to_email': email,
            'display_name': display_name,
            'reset_url': reset_url,
        },
    )

    # Send email
    email_client = client.EmailClient.get_instance()
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
