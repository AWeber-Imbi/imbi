"""Data models for email sending and audit logging."""

import datetime
import hashlib
import secrets
import typing

import pydantic


class EmailMessage(pydantic.BaseModel):
    """Email message to be sent via SMTP."""

    model_config = pydantic.ConfigDict(extra='ignore')

    to_email: pydantic.EmailStr
    subject: str
    html_body: str
    text_body: str
    template_name: str
    context: dict[str, typing.Any] = {}


class EmailAudit(pydantic.BaseModel):
    """Audit log entry for sent emails (stored in ClickHouse).

    For GDPR compliance, the model computes privacy-preserving fields:
    - to_email_hash: SHA256 hash of email for privacy
    - to_email_domain: Domain only for analytics

    The to_email field is kept internally but excluded from serialization
    to ClickHouse.
    """

    model_config = pydantic.ConfigDict(extra='ignore')

    to_email: pydantic.EmailStr
    template_name: str
    subject: str
    status: typing.Literal['sent', 'failed', 'skipped', 'dry_run']
    error_message: str | None = None
    sent_at: datetime.datetime

    # Metadata for analytics
    user_id: str | None = None
    related_entity_type: str | None = None
    related_entity_id: str | None = None

    @pydantic.computed_field  # type: ignore[prop-decorator]
    @property
    def to_email_hash(self) -> str:
        """Compute SHA256 hash of email for privacy-preserving storage."""
        return hashlib.sha256(
            str(self.to_email).lower().encode('utf-8')
        ).hexdigest()

    @pydantic.computed_field  # type: ignore[prop-decorator]
    @property
    def to_email_domain(self) -> str:
        """Extract domain from email for analytics."""
        return str(self.to_email).split('@')[1]

    @pydantic.model_serializer(mode='wrap', when_used='always')
    def _serialize_without_email(
        self,
        serializer: pydantic.SerializerFunctionWrapHandler,
        info: pydantic.SerializationInfo,
    ) -> dict[str, typing.Any]:
        """Exclude to_email from serialization to ClickHouse."""
        data: dict[str, typing.Any] = serializer(self)
        # Remove PII field before storage
        data.pop('to_email', None)
        return data


class PasswordResetToken(pydantic.BaseModel):
    """Password reset token (stored in Neo4j).

    Tokens are cryptographically secure, single-use, and expire after 24 hours.
    """

    model_config = pydantic.ConfigDict(extra='ignore')

    token: str
    username: str
    email: pydantic.EmailStr
    created_at: datetime.datetime
    expires_at: datetime.datetime
    used: bool = False
    used_at: datetime.datetime | None = None

    @classmethod
    def create(
        cls,
        username: str,
        email: str,
        expiry_hours: int = 24,
    ) -> 'PasswordResetToken':
        """Create a new password reset token.

        Args:
            username: Username for the password reset
            email: Email address to send reset link to
            expiry_hours: Hours until token expires (default: 24)

        Returns:
            New PasswordResetToken instance

        """
        now = datetime.datetime.now(datetime.UTC)
        return cls(
            token=secrets.token_urlsafe(32),
            username=username,
            email=email,
            created_at=now,
            expires_at=now + datetime.timedelta(hours=expiry_hours),
            used=False,
        )

    def is_valid(self) -> bool:
        """Check if token is still valid (not expired and not used).

        Returns:
            True if token is valid, False otherwise

        """
        now = datetime.datetime.now(datetime.UTC)
        return not self.used and now < self.expires_at

    def mark_used(self) -> None:
        """Mark token as used."""
        self.used = True
        self.used_at = datetime.datetime.now(datetime.UTC)
