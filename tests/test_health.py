"""
Tests for health check endpoint.
"""
import pytest
from httpx import AsyncClient

from imbi import __version__


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test the /api/status health check endpoint."""
    response = await client.get("/api/status")

    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == __version__
    assert "ready" in data


@pytest.mark.asyncio
async def test_health_check_no_auth_required(client: AsyncClient):
    """Test that health check doesn't require authentication."""
    response = await client.get("/api/status")
    assert response.status_code == 200
    # Should not get 401 Unauthorized
