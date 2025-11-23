"""
Test that AsyncClient maintains cookies between requests.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_sets_cookie(client: AsyncClient, test_user: dict):
    """Test that login sets a cookie."""
    response = await client.post(
        "/api/login",
        json={"username": "testuser", "password": "password"},
    )

    assert response.status_code == 200
    print(f"Response cookies: {response.cookies}")
    print(f"Client cookies: {client.cookies}")

    # Check that client has the cookie
    assert len(client.cookies) > 0, "Client should have cookies after login"


@pytest.mark.asyncio
async def test_cookie_persists_across_requests(client: AsyncClient, test_user: dict):
    """Test that cookies persist across multiple requests."""
    # First request - login
    login_response = await client.post(
        "/api/login",
        json={"username": "testuser", "password": "password"},
    )
    assert login_response.status_code == 200

    # Second request - whoami
    whoami_response = await client.get("/api/whoami")
    print(f"Whoami status: {whoami_response.status_code}")
    print(f"Whoami body: {whoami_response.json()}")

    # This should be 200, not 401
    # If it's 401, cookies aren't being maintained
    assert whoami_response.status_code == 200, (
        f"Session not persisting. Cookies: {client.cookies}"
    )
