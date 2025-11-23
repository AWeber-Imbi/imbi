"""
Tests for login/logout authentication endpoints.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.integration
class TestLogin:
    """Tests for POST /api/login"""

    async def test_login_success(self, client: AsyncClient, test_user: dict):
        """Test successful login with valid credentials."""
        response = await client.post(
            "/api/login",
            json={"username": "testuser", "password": "password"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["user_type"] == "internal"
        assert data["email_address"] == "test@example.com"
        assert data["message"] == "Login successful"

        # Verify session cookie is set (cookie name from test config)
        assert "test_session" in response.cookies or "test_session" in client.cookies

    async def test_login_wrong_password(self, client: AsyncClient, test_user: dict):
        """Test login with wrong password returns 401."""
        response = await client.post(
            "/api/login",
            json={"username": "testuser", "password": "wrongpassword"},
        )

        assert response.status_code == 401
        data = response.json()
        assert data["status"] == 401
        assert "invalid" in data["detail"].lower()

    async def test_login_nonexistent_user(self, client: AsyncClient, clean_database):
        """Test login with nonexistent user returns 401."""
        response = await client.post(
            "/api/login",
            json={"username": "nonexistent", "password": "password"},
        )

        assert response.status_code == 401

    async def test_login_validation_error(self, client: AsyncClient):
        """Test login with invalid data returns 422."""
        response = await client.post(
            "/api/login",
            json={"username": ""},  # Empty username
        )

        assert response.status_code == 422

    async def test_login_empty_password(self, client: AsyncClient):
        """Test login with empty password returns 422."""
        response = await client.post(
            "/api/login",
            json={"username": "testuser", "password": ""},
        )

        assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
class TestLogout:
    """Tests for POST /api/logout"""

    async def test_logout_success(self, client: AsyncClient, test_user: dict):
        """Test successful logout."""
        # First login
        login_response = await client.post(
            "/api/login",
            json={"username": "testuser", "password": "password"},
        )
        assert login_response.status_code == 200

        # Then logout
        logout_response = await client.post("/api/logout")

        assert logout_response.status_code == 200
        data = logout_response.json()
        assert data["message"] == "Logout successful"

    async def test_logout_when_not_logged_in(self, client: AsyncClient):
        """Test logout when not logged in (should still succeed)."""
        response = await client.post("/api/logout")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Logout successful"


@pytest.mark.asyncio
@pytest.mark.integration
class TestWhoAmI:
    """Tests for GET /api/whoami"""

    async def test_whoami_authenticated(self, client: AsyncClient, test_user: dict):
        """Test /whoami when authenticated."""
        # First login
        login_response = await client.post(
            "/api/login",
            json={"username": "testuser", "password": "password"},
        )
        assert login_response.status_code == 200

        # Then check whoami
        whoami_response = await client.get("/api/whoami")

        assert whoami_response.status_code == 200
        data = whoami_response.json()
        assert data["username"] == "testuser"
        assert data["authenticated"] is True
        assert data["user_type"] == "internal"

    async def test_whoami_not_authenticated(self, client: AsyncClient):
        """Test /whoami when not authenticated returns 401."""
        response = await client.get("/api/whoami")

        assert response.status_code == 401
        data = response.json()
        assert data["status"] == 401


@pytest.mark.asyncio
@pytest.mark.integration
class TestAuthenticationFlow:
    """Tests for complete authentication flow."""

    async def test_login_logout_flow(self, client: AsyncClient, test_user: dict):
        """Test complete login -> authenticated request -> logout flow."""
        # 1. Login
        login_response = await client.post(
            "/api/login",
            json={"username": "testuser", "password": "password"},
        )
        assert login_response.status_code == 200

        # 2. Make authenticated request
        whoami_response = await client.get("/api/whoami")
        assert whoami_response.status_code == 200
        assert whoami_response.json()["username"] == "testuser"

        # 3. Logout
        logout_response = await client.post("/api/logout")
        assert logout_response.status_code == 200

        # 4. Verify session is gone
        whoami_after_logout = await client.get("/api/whoami")
        assert whoami_after_logout.status_code == 401

    async def test_admin_login_has_permissions(
        self, client: AsyncClient, admin_user: dict
    ):
        """Test admin user login includes permissions."""
        # Login as admin
        response = await client.post(
            "/api/login",
            json={"username": "admin", "password": "password"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "admin"
        assert "admin" in data["permissions"]
        assert "reader" in data["permissions"]
        assert "writer" in data["permissions"]
        assert "admin" in data["groups"]
