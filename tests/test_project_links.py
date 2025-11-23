"""
Tests for project link endpoints.
"""

import pytest
from httpx import AsyncClient

from imbi.models import ProjectLink


@pytest.mark.asyncio
@pytest.mark.integration
class TestProjectLinkTypes:
    """Tests for project link type management"""

    async def test_list_link_types_empty(self, client: AsyncClient, clean_database):
        """Test listing link types when none exist."""
        response = await client.get("/api/project-link-types")

        assert response.status_code == 200
        assert response.json() == []

    async def test_list_link_types(self, client: AsyncClient, sample_link_type: dict):
        """Test listing link types."""
        response = await client.get("/api/project-link-types")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["link_type"] == "GitHub"

    async def test_create_link_type(self, admin_client: AsyncClient, clean_database):
        """Test creating a link type."""
        response = await admin_client.post(
            "/api/project-link-types",
            json={"link_type": "Documentation", "icon_class": "fas fa-book"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["link_type"] == "Documentation"
        assert data["icon_class"] == "fas fa-book"

    async def test_create_duplicate_link_type(
        self, admin_client: AsyncClient, sample_link_type: dict
    ):
        """Test creating duplicate link type returns 409."""
        response = await admin_client.post(
            "/api/project-link-types",
            json={"link_type": "GitHub"},  # Already exists
        )

        assert response.status_code == 409


@pytest.mark.asyncio
@pytest.mark.integration
class TestListProjectLinks:
    """Tests for GET /api/projects/{id}/links"""

    async def test_list_empty(self, client: AsyncClient, sample_project: dict):
        """Test listing links when project has none."""
        response = await client.get(f"/api/projects/{sample_project['id']}/links")

        assert response.status_code == 200
        assert response.json() == []

    async def test_list_with_links(
        self,
        authenticated_client: AsyncClient,
        sample_project: dict,
        sample_link_type: dict,
    ):
        """Test listing links when project has some."""
        # Add a link
        add_response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/links",
            json={
                "link_type_id": sample_link_type["id"],
                "url": "https://github.com/org/repo",
            },
        )
        assert add_response.status_code == 201

        # List links
        response = await authenticated_client.get(
            f"/api/projects/{sample_project['id']}/links"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["link_type"] == "GitHub"
        assert data[0]["url"] == "https://github.com/org/repo"

    async def test_list_nonexistent_project(self, client: AsyncClient):
        """Test listing links for nonexistent project returns 404."""
        response = await client.get("/api/projects/999/links")

        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
class TestAddProjectLink:
    """Tests for POST /api/projects/{id}/links"""

    async def test_add_success(
        self,
        authenticated_client: AsyncClient,
        sample_project: dict,
        sample_link_type: dict,
    ):
        """Test successfully adding a link."""
        response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/links",
            json={
                "link_type_id": sample_link_type["id"],
                "url": "https://github.com/org/repo",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["project_id"] == sample_project["id"]
        assert data["link_type_id"] == sample_link_type["id"]
        assert data["link_type"] == "GitHub"
        assert data["url"] == "https://github.com/org/repo"

    async def test_add_duplicate_link_type(
        self,
        authenticated_client: AsyncClient,
        sample_project: dict,
        sample_link_type: dict,
    ):
        """Test adding duplicate link type returns 409."""
        # Add first time
        response1 = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/links",
            json={
                "link_type_id": sample_link_type["id"],
                "url": "https://github.com/org/repo1",
            },
        )
        assert response1.status_code == 201

        # Add again with same type
        response2 = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/links",
            json={
                "link_type_id": sample_link_type["id"],
                "url": "https://github.com/org/repo2",
            },
        )

        assert response2.status_code == 409

    async def test_add_nonexistent_link_type(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test adding link with nonexistent type returns 404."""
        response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/links",
            json={"link_type_id": 999, "url": "https://example.com"},
        )

        assert response.status_code == 404

    async def test_add_requires_auth(
        self, client: AsyncClient, sample_project: dict, sample_link_type: dict
    ):
        """Test adding link requires authentication."""
        response = await client.post(
            f"/api/projects/{sample_project['id']}/links",
            json={
                "link_type_id": sample_link_type["id"],
                "url": "https://example.com",
            },
        )

        assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
class TestUpdateProjectLink:
    """Tests for PATCH /api/projects/{id}/links/{link_type_id}"""

    async def test_update_success(
        self,
        authenticated_client: AsyncClient,
        sample_project: dict,
        sample_link_type: dict,
    ):
        """Test successfully updating a link."""
        # Add link first
        add_response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/links",
            json={
                "link_type_id": sample_link_type["id"],
                "url": "https://github.com/org/old",
            },
        )
        assert add_response.status_code == 201

        # Update it
        response = await authenticated_client.patch(
            f"/api/projects/{sample_project['id']}/links/{sample_link_type['id']}",
            json={"url": "https://github.com/org/new"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "https://github.com/org/new"
        assert data["link_type"] == "GitHub"

    async def test_update_nonexistent(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test updating nonexistent link returns 404."""
        response = await authenticated_client.patch(
            f"/api/projects/{sample_project['id']}/links/999",
            json={"url": "https://example.com"},
        )

        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
class TestRemoveProjectLink:
    """Tests for DELETE /api/projects/{id}/links/{link_type_id}"""

    async def test_remove_success(
        self,
        authenticated_client: AsyncClient,
        sample_project: dict,
        sample_link_type: dict,
    ):
        """Test successfully removing a link."""
        # Add link first
        add_response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/links",
            json={
                "link_type_id": sample_link_type["id"],
                "url": "https://github.com/org/repo",
            },
        )
        assert add_response.status_code == 201

        # Remove it
        response = await authenticated_client.delete(
            f"/api/projects/{sample_project['id']}/links/{sample_link_type['id']}"
        )

        assert response.status_code == 204

        # Verify it's gone
        link = (
            await ProjectLink.select()
            .where(
                (ProjectLink.project_id == sample_project["id"])
                & (ProjectLink.link_type_id == sample_link_type["id"])
            )
            .first()
        )
        assert link is None

    async def test_remove_nonexistent(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test removing nonexistent link returns 404."""
        response = await authenticated_client.delete(
            f"/api/projects/{sample_project['id']}/links/999"
        )

        assert response.status_code == 404
