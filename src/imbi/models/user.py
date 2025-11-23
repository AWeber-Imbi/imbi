"""
User, Group, and authentication-related models.
"""

from __future__ import annotations

import datetime

from piccolo import columns, table

from imbi.models import base


class User(table.Table, tablename="users", schema="v1"):
    """User account model."""

    id = columns.Serial(primary_key=True)
    username = columns.Varchar(length=255, unique=True, null=False, index=True)
    user_type = columns.Text(null=False, default="internal")  # internal, ldap, google
    external_id = columns.Text(null=True, index=True)  # LDAP DN or Google ID
    email_address = columns.Text(null=True)
    display_name = columns.Text(null=True)
    password = columns.Text(null=True)  # Hashed password for internal users
    created_at = columns.Timestamptz(default=datetime.datetime.now, null=False)
    last_seen_at = columns.Timestamptz(null=True)

    @classmethod
    def ref(cls) -> columns.Varchar:
        """Readable reference for this model."""
        return cls.username


class Group(table.Table, tablename="groups", schema="v1"):
    """Group model for organizing users and permissions."""

    name = columns.Text(primary_key=True)
    permissions = columns.Array(columns.Text(), null=False, default=list)
    created_at = columns.Timestamptz(default=datetime.datetime.now, null=False)
    created_by = columns.Text(null=False)
    last_modified_at = columns.Timestamptz(
        default=datetime.datetime.now,
        auto_update=datetime.datetime.now,
        null=False,
    )
    last_modified_by = columns.Text(null=False)

    @classmethod
    def ref(cls) -> columns.Text:
        """Readable reference for this model."""
        return cls.name


class GroupMember(base.SimpleTable, tablename="group_members", schema="v1"):
    """Membership relationship between users and groups."""

    username = columns.Text(null=False, index=True)
    group = columns.Text(null=False, index=True)
    added_by = columns.Text(null=False)

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraint on username + group."""
        return [(cls.username, cls.group)]


class AuthenticationToken(table.Table, tablename="authentication_tokens", schema="v1"):
    """Personal access tokens for API authentication."""

    token = columns.UUID(primary_key=True)
    username = columns.Text(null=False, index=True)
    name = columns.Text(null=False)  # Token description/name
    created_at = columns.Timestamptz(default=datetime.datetime.now, null=False)
    expires_at = columns.Timestamptz(null=True)  # NULL = never expires
    last_used_at = columns.Timestamptz(null=True)

    @classmethod
    def ref(cls) -> columns.Text:
        """Readable reference for this model."""
        return cls.name


class UserOAuth2Token(table.Table, tablename="user_oauth2_tokens", schema="v1"):
    """OAuth2 tokens for external integrations (per user)."""

    username = columns.Text(null=False, index=True)
    integration = columns.Text(null=False, index=True)  # github, google, etc.
    external_id = columns.Text(null=False)  # External user ID
    access_token = columns.Text(null=False)
    refresh_token = columns.Text(null=True)
    expires_at = columns.Timestamptz(null=True)
    created_at = columns.Timestamptz(default=datetime.datetime.now, null=False)
    updated_at = columns.Timestamptz(
        default=datetime.datetime.now,
        auto_update=datetime.datetime.now,
        null=False,
    )

    @classmethod
    def get_unique_keys(cls):
        """Composite unique constraint on username + integration."""
        return [(cls.username, cls.integration)]
