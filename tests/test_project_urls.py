"""
Tests for project URL endpoints.
"""

import pytest
from httpx import AsyncClient

from imbi.models import ProjectURL


@pytest.mark.asyncio
@pytest.mark.integration
class TestListProjectURLs:
    """Tests for GET /api/projects/{id}/urls"""

    async def test_list_empty(self, client: AsyncClient, sample_project: dict):
        """Test listing URLs when project has none."""
        response = await client.get(f"/api/projects/{sample_project['id']}/urls")

        assert response.status_code == 200
        assert response.json() == []

    async def test_list_with_urls(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test listing URLs when project has some."""
        # Add URLs
        await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/urls",
            json={"environment": "production", "url": "https://prod.example.com"},
        )
        await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/urls",
            json={"environment": "staging", "url": "https://staging.example.com"},
        )

        # List URLs
        response = await authenticated_client.get(
            f"/api/projects/{sample_project['id']}/urls"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # Should be ordered by environment
        envs = [url["environment"] for url in data]
        assert sorted(envs) == envs

    async def test_list_nonexistent_project(self, client: AsyncClient):
        """Test listing URLs for nonexistent project returns 404."""
        response = await client.get("/api/projects/999/urls")

        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
class TestAddProjectURL:
    """Tests for POST /api/projects/{id}/urls"""

    async def test_add_success(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test successfully adding a URL."""
        response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/urls",
            json={"environment": "production", "url": "https://api.example.com"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["project_id"] == sample_project["id"]
        assert data["environment"] == "production"
        assert data["url"] == "https://api.example.com"
        assert "created_by" in data

    async def test_add_duplicate_environment(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test adding duplicate environment returns 409."""
        # Add first time
        response1 = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/urls",
            json={"environment": "production", "url": "https://url1.example.com"},
        )
        assert response1.status_code == 201

        # Add again for same environment
        response2 = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/urls",
            json={"environment": "production", "url": "https://url2.example.com"},
        )

        assert response2.status_code == 409

    async def test_add_nonexistent_project(self, authenticated_client: AsyncClient):
        """Test adding URL to nonexistent project returns 404."""
        response = await authenticated_client.post(
            "/api/projects/999/urls",
            json={"environment": "production", "url": "https://example.com"},
        )

        assert response.status_code == 404

    async def test_add_requires_auth(self, client: AsyncClient, sample_project: dict):
        """Test adding URL requires authentication."""
        response = await client.post(
            f"/api/projects/{sample_project['id']}/urls",
            json={"environment": "production", "url": "https://example.com"},
        )

        assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
class TestUpdateProjectURL:
    """Tests for PATCH /api/projects/{id}/urls/{environment}"""

    async def test_update_success(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test successfully updating a URL."""
        # Add URL first
        add_response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/urls",
            json={"environment": "production", "url": "https://old.example.com"},
        )
        assert add_response.status_code == 201

        # Update it
        response = await authenticated_client.patch(
            f"/api/projects/{sample_project['id']}/urls/production",
            json={"url": "https://new.example.com"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "https://new.example.com"
        assert data["environment"] == "production"

    async def test_update_nonexistent(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test updating nonexistent URL returns 404."""
        response = await authenticated_client.patch(
            f"/api/projects/{sample_project['id']}/urls/nonexistent",
            json={"url": "https://example.com"},
        )

        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
class TestRemoveProjectURL:
    """Tests for DELETE /api/projects/{id}/urls/{environment}"""

    async def test_remove_success(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test successfully removing a URL."""
        # Add URL first
        add_response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/urls",
            json={"environment": "production", "url": "https://example.com"},
        )
        assert add_response.status_code == 201

        # Remove it
        response = await authenticated_client.delete(
            f"/api/projects/{sample_project['id']}/urls/production"
        )

        assert response.status_code == 204

        # Verify it's gone
        url = (
            await ProjectURL.select()
            .where(
                (ProjectURL.project_id == sample_project["id"])
                & (ProjectURL.environment == "production")
            )
            .first()
        )
        assert url is None

    async def test_remove_nonexistent(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test removing nonexistent URL returns 404."""
        response = await authenticated_client.delete(
            f"/api/projects/{sample_project['id']}/urls/nonexistent"
        )

        assert response.status_code == 404
