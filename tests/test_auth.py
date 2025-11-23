"""
Tests for authentication and authorization.
"""

import pytest

from imbi.config import Config
from imbi.services.user import User


@pytest.mark.asyncio
class TestUserService:
    """Tests for User service."""

    def test_hash_password(self, test_config: Config):
        """Test password hashing is consistent."""
        user = User(config=test_config)

        hash1 = user.hash_password("password123")
        hash2 = user.hash_password("password123")

        assert hash1 == hash2
        assert len(hash1) == 128  # HMAC-SHA512 produces 128 hex chars
        assert hash1 != "password123"

    def test_hash_password_different_inputs(self, test_config: Config):
        """Test different passwords produce different hashes."""
        user = User(config=test_config)

        hash1 = user.hash_password("password1")
        hash2 = user.hash_password("password2")

        assert hash1 != hash2

    @pytest.mark.skip(reason="Database authentication not yet fully implemented")
    async def test_authenticate_database_success(self, test_config: Config, test_user):
        """Test successful database authentication."""
        user = User(
            config=test_config,
            username="testuser",
            password="password",
        )

        result = await user.authenticate()

        assert result is True
        assert user.username == "testuser"
        assert user.email_address == "test@example.com"

    @pytest.mark.skip(reason="Database authentication not yet fully implemented")
    async def test_authenticate_database_wrong_password(
        self, test_config: Config, test_user
    ):
        """Test failed database authentication with wrong password."""
        user = User(
            config=test_config,
            username="testuser",
            password="wrongpassword",
        )

        result = await user.authenticate()

        assert result is False

    @pytest.mark.skip(reason="Database authentication not yet fully implemented")
    async def test_authenticate_database_nonexistent_user(
        self, test_config: Config, clean_database
    ):
        """Test failed database authentication with nonexistent user."""
        user = User(
            config=test_config,
            username="nonexistent",
            password="password",
        )

        result = await user.authenticate()

        assert result is False

    def test_has_permission(self, test_config: Config):
        """Test permission checking."""
        user = User(config=test_config)
        user.permissions = ["admin", "reader", "writer"]

        assert user.has_permission("admin") is True
        assert user.has_permission("reader") is True
        assert user.has_permission("nonexistent") is False

    def test_to_dict(self, test_config: Config):
        """Test user serialization."""
        user = User(config=test_config, username="testuser")
        user.user_type = "internal"
        user.email_address = "test@example.com"
        user.display_name = "Test User"
        user.groups = ["developers"]
        user.permissions = ["reader", "writer"]

        data = user.to_dict()

        assert data["username"] == "testuser"
        assert data["user_type"] == "internal"
        assert data["email_address"] == "test@example.com"
        assert data["display_name"] == "Test User"
        assert data["groups"] == ["developers"]
        assert data["permissions"] == ["reader", "writer"]

    def test_from_dict(self, test_config: Config):
        """Test user deserialization."""
        data = {
            "username": "testuser",
            "user_type": "internal",
            "email_address": "test@example.com",
            "display_name": "Test User",
            "groups": ["developers"],
            "permissions": ["reader", "writer"],
        }

        user = User.from_dict(test_config, data)

        assert user.username == "testuser"
        assert user.user_type == "internal"
        assert user.email_address == "test@example.com"
        assert user.display_name == "Test User"
        assert user.groups == ["developers"]
        assert user.permissions == ["reader", "writer"]


@pytest.mark.asyncio
class TestAuthenticationDependencies:
    """Tests for FastAPI authentication dependencies."""

    @pytest.mark.skip(reason="Authentication flow not yet complete")
    async def test_get_current_user_from_session(self, client, test_user):
        """Test getting current user from session."""
        # TODO: Implement once login endpoint exists
        pass

    @pytest.mark.skip(reason="Authentication flow not yet complete")
    async def test_get_current_user_from_token(self, client, test_user):
        """Test getting current user from API token."""
        # TODO: Implement once token authentication is complete
        pass

    @pytest.mark.skip(reason="Authentication flow not yet complete")
    async def test_require_authentication_success(self, authenticated_client):
        """Test accessing protected endpoint with authentication."""
        # TODO: Implement once we have protected endpoints
        pass

    @pytest.mark.skip(reason="Authentication flow not yet complete")
    async def test_require_authentication_failure(self, client):
        """Test accessing protected endpoint without authentication."""
        # TODO: Implement once we have protected endpoints
        pass

    @pytest.mark.skip(reason="Authentication flow not yet complete")
    async def test_require_permission_success(self, admin_client):
        """Test accessing admin endpoint with admin permission."""
        # TODO: Test admin-only endpoints
        pass

    @pytest.mark.skip(reason="Authentication flow not yet complete")
    async def test_require_permission_failure(self, authenticated_client):
        """Test accessing admin endpoint without admin permission."""
        # TODO: Test admin-only endpoints with non-admin user
        pass
