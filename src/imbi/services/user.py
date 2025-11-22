"""
User authentication and authorization service.

Supports multiple authentication methods:
- Internal (database-stored password)
- LDAP
- Google OAuth2
- API tokens
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta
from typing import Optional

from imbi.config import Config
from imbi.database import get_db
from imbi.models import User as UserModel

logger = logging.getLogger(__name__)


class User:
    """User service for authentication and authorization."""

    def __init__(
        self,
        config: Config,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
    ):
        self.config = config
        self.username = username
        self.password = password
        self.token = token

        # User attributes
        self.user_type: str = "internal"
        self.external_id: Optional[str] = None
        self.email_address: Optional[str] = None
        self.display_name: Optional[str] = None
        self.groups: list[str] = []
        self.permissions: list[str] = []
        self.last_seen_at: Optional[datetime] = None
        self.created_at: Optional[datetime] = None

    def hash_password(self, password: str) -> str:
        """
        Hash a password using HMAC-SHA512.

        Args:
            password: Plain text password

        Returns:
            Hex-encoded hash
        """
        key = self.config.encryption_key.encode("utf-8")
        return hmac.new(key, password.encode("utf-8"), hashlib.sha512).hexdigest()

    async def authenticate(self) -> bool:
        """
        Authenticate the user using available credentials.

        Returns:
            True if authentication successful, False otherwise
        """
        if self.token:
            return await self._authenticate_token()

        if self.username and self.password:
            # Try database authentication first
            if await self._authenticate_database():
                return True

            # Try LDAP if enabled
            if self.config.ldap.enabled:
                return await self._authenticate_ldap()

        return False

    async def _authenticate_database(self) -> bool:
        """Authenticate against database."""
        logger.debug(f"Authenticating {self.username} via database")

        db = get_db()
        password_hash = self.hash_password(self.password)

        # Update last_seen_at and verify credentials
        result = await (
            UserModel.update({UserModel.last_seen_at: datetime.utcnow()})
            .where(
                (UserModel.username == self.username)
                & (UserModel.password == password_hash)
                & (UserModel.user_type == "internal")
            )
            .returning(UserModel.username)
        )

        if result:
            await self._load_user_data()
            return True

        logger.debug(f"Database authentication failed for {self.username}")
        return False

    async def _authenticate_token(self) -> bool:
        """Authenticate via API token."""
        logger.debug("Authenticating via API token")

        # TODO: Implement token authentication
        # Query authentication_tokens table
        # Update last_used_at
        # Load user data

        logger.warning("Token authentication not yet implemented")
        return False

    async def _authenticate_ldap(self) -> bool:
        """Authenticate via LDAP."""
        logger.debug(f"Authenticating {self.username} via LDAP")

        # TODO: Implement LDAP authentication
        # Connect to LDAP
        # Verify credentials
        # Sync groups from LDAP
        # Upsert user in database

        logger.warning("LDAP authentication not yet implemented")
        return False

    async def _load_user_data(self) -> None:
        """Load user data from database."""
        user = await UserModel.select().where(UserModel.username == self.username).first()

        if not user:
            logger.error(f"User {self.username} not found after authentication")
            return

        self.user_type = user["user_type"]
        self.external_id = user["external_id"]
        self.email_address = user["email_address"]
        self.display_name = user["display_name"]
        self.last_seen_at = user["last_seen_at"]
        self.created_at = user["created_at"]

        # Load groups and permissions
        await self._load_groups_and_permissions()

    async def _load_groups_and_permissions(self) -> None:
        """Load user's groups and aggregate permissions."""
        # TODO: Implement group/permission loading
        # Query group_members table
        # Query groups table for permissions
        # Aggregate all permissions

        logger.warning("Group/permission loading not yet implemented")
        self.groups = []
        self.permissions = []

    def has_permission(self, permission: str) -> bool:
        """
        Check if user has a specific permission.

        Args:
            permission: Permission string to check

        Returns:
            True if user has permission
        """
        return permission in self.permissions

    def to_dict(self) -> dict:
        """
        Serialize user data for session storage.

        Returns:
            Dictionary of user attributes
        """
        return {
            "username": self.username,
            "user_type": self.user_type,
            "external_id": self.external_id,
            "email_address": self.email_address,
            "display_name": self.display_name,
            "groups": self.groups,
            "permissions": self.permissions,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, config: Config, data: dict) -> User:
        """
        Deserialize user data from session.

        Args:
            config: Application configuration
            data: User data dictionary

        Returns:
            User instance
        """
        user = cls(config)
        user.username = data.get("username")
        user.user_type = data.get("user_type", "internal")
        user.external_id = data.get("external_id")
        user.email_address = data.get("email_address")
        user.display_name = data.get("display_name")
        user.groups = data.get("groups", [])
        user.permissions = data.get("permissions", [])

        if data.get("last_seen_at"):
            user.last_seen_at = datetime.fromisoformat(data["last_seen_at"])
        if data.get("created_at"):
            user.created_at = datetime.fromisoformat(data["created_at"])

        return user
