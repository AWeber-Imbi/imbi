"""
User, Group, and authentication-related models.
"""
from __future__ import annotations

from datetime import datetime

from piccolo.columns import (
    Array,
    Boolean,
    Serial,
    Text,
    Timestamptz,
    UUID,
    Varchar,
)
from piccolo.table import Table

from imbi.models.base import SimpleTable


class User(Table, tablename="users", schema="v1"):
    """User account model."""

    id = Serial(primary_key=True)
    username = Varchar(length=255, unique=True, null=False, index=True)
    user_type = Text(null=False, default="internal")  # internal, ldap, google
    external_id = Text(null=True, index=True)  # LDAP DN or Google ID
    email_address = Text(null=True)
    display_name = Text(null=True)
    password = Text(null=True)  # Hashed password for internal users
    created_at = Timestamptz(default=datetime.now, null=False)
    last_seen_at = Timestamptz(null=True)

    @classmethod
    def ref(cls) -> Varchar:
        """Readable reference for this model."""
        return cls.username


class Group(Table, tablename="groups", schema="v1"):
    """Group model for organizing users and permissions."""

    name = Text(primary_key=True)
    permissions = Array(Text(), null=False, default=list)
    created_at = Timestamptz(default=datetime.now, null=False)
    created_by = Text(null=False)
    last_modified_at = Timestamptz(
        default=datetime.now,
        auto_update=datetime.now,
        null=False,
    )
    last_modified_by = Text(null=False)

    @classmethod
    def ref(cls) -> Text:
        """Readable reference for this model."""
        return cls.name


class GroupMember(SimpleTable, tablename="group_members", schema="v1"):
    """Membership relationship between users and groups."""

    username = Text(null=False, index=True)
    group = Text(null=False, index=True)
    added_by = Text(null=False)

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraint on username + group."""
        return [(cls.username, cls.group)]


class AuthenticationToken(Table, tablename="authentication_tokens", schema="v1"):
    """Personal access tokens for API authentication."""

    token = UUID(primary_key=True)
    username = Text(null=False, index=True)
    name = Text(null=False)  # Token description/name
    created_at = Timestamptz(default=datetime.now, null=False)
    expires_at = Timestamptz(null=True)  # NULL = never expires
    last_used_at = Timestamptz(null=True)

    @classmethod
    def ref(cls) -> Text:
        """Readable reference for this model."""
        return cls.name


class UserOAuth2Token(Table, tablename="user_oauth2_tokens", schema="v1"):
    """OAuth2 tokens for external integrations (per user)."""

    username = Text(null=False, index=True)
    integration = Text(null=False, index=True)  # github, google, etc.
    external_id = Text(null=False)  # External user ID
    access_token = Text(null=False)
    refresh_token = Text(null=True)
    expires_at = Timestamptz(null=True)
    created_at = Timestamptz(default=datetime.now, null=False)
    updated_at = Timestamptz(
        default=datetime.now,
        auto_update=datetime.now,
        null=False,
    )

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraint on username + integration."""
        return [(cls.username, cls.integration)]
