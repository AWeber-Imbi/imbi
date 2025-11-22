"""
Tests for project dependency endpoints.
"""
import pytest
from httpx import AsyncClient

from imbi.models import ProjectDependency


@pytest.mark.asyncio
@pytest.mark.integration
class TestListProjectDependencies:
    """Tests for GET /api/projects/{id}/dependencies"""

    async def test_list_empty(
        self, client: AsyncClient, sample_project: dict
    ):
        """Test listing dependencies when project has none."""
        response = await client.get(f"/api/projects/{sample_project['id']}/dependencies")

        assert response.status_code == 200
        assert response.json() == []

    async def test_list_with_dependencies(
        self, authenticated_client: AsyncClient, sample_project: dict, second_project: dict
    ):
        """Test listing dependencies when project has some."""
        # Add a dependency
        add_response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/dependencies",
            json={"dependency_id": second_project["id"]},
        )
        assert add_response.status_code == 201

        # List dependencies
        response = await authenticated_client.get(
            f"/api/projects/{sample_project['id']}/dependencies"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["dependency_id"] == second_project["id"]
        assert data[0]["dependency_name"] == "Database API"

    async def test_list_nonexistent_project(self, client: AsyncClient):
        """Test listing dependencies for nonexistent project returns 404."""
        response = await client.get("/api/projects/999/dependencies")

        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
class TestAddProjectDependency:
    """Tests for POST /api/projects/{id}/dependencies"""

    async def test_add_success(
        self, authenticated_client: AsyncClient, sample_project: dict, second_project: dict
    ):
        """Test successfully adding a dependency."""
        response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/dependencies",
            json={"dependency_id": second_project["id"]},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["project_id"] == sample_project["id"]
        assert data["dependency_id"] == second_project["id"]
        assert data["dependency_name"] == "Database API"
        assert "created_at" in data
        assert "added_by" in data

        # Verify in database
        dep = await ProjectDependency.select().where(
            (ProjectDependency.project_id == sample_project["id"])
            & (ProjectDependency.dependency_id == second_project["id"])
        ).first()
        assert dep is not None

    async def test_add_duplicate(
        self, authenticated_client: AsyncClient, sample_project: dict, second_project: dict
    ):
        """Test adding duplicate dependency returns 409."""
        # Add first time
        response1 = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/dependencies",
            json={"dependency_id": second_project["id"]},
        )
        assert response1.status_code == 201

        # Add again
        response2 = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/dependencies",
            json={"dependency_id": second_project["id"]},
        )

        assert response2.status_code == 409

    async def test_add_nonexistent_project(
        self, authenticated_client: AsyncClient, second_project: dict
    ):
        """Test adding dependency to nonexistent project returns 404."""
        response = await authenticated_client.post(
            "/api/projects/999/dependencies",
            json={"dependency_id": second_project["id"]},
        )

        assert response.status_code == 404

    async def test_add_nonexistent_dependency(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test adding nonexistent dependency returns 404."""
        response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/dependencies",
            json={"dependency_id": 999},
        )

        assert response.status_code == 404

    async def test_add_requires_auth(
        self, client: AsyncClient, sample_project: dict, second_project: dict
    ):
        """Test adding dependency requires authentication."""
        response = await client.post(
            f"/api/projects/{sample_project['id']}/dependencies",
            json={"dependency_id": second_project["id"]},
        )

        assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
class TestRemoveProjectDependency:
    """Tests for DELETE /api/projects/{id}/dependencies/{dep_id}"""

    async def test_remove_success(
        self, authenticated_client: AsyncClient, sample_project: dict, second_project: dict
    ):
        """Test successfully removing a dependency."""
        # Add dependency first
        add_response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/dependencies",
            json={"dependency_id": second_project["id"]},
        )
        assert add_response.status_code == 201

        # Remove it
        response = await authenticated_client.delete(
            f"/api/projects/{sample_project['id']}/dependencies/{second_project['id']}"
        )

        assert response.status_code == 204

        # Verify it's gone
        dep = await ProjectDependency.select().where(
            (ProjectDependency.project_id == sample_project["id"])
            & (ProjectDependency.dependency_id == second_project["id"])
        ).first()
        assert dep is None

    async def test_remove_nonexistent(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test removing nonexistent dependency returns 404."""
        response = await authenticated_client.delete(
            f"/api/projects/{sample_project['id']}/dependencies/999"
        )

        assert response.status_code == 404

    async def test_remove_requires_auth(
        self, client: AsyncClient, sample_project: dict, second_project: dict
    ):
        """Test removing dependency requires authentication."""
        response = await client.delete(
            f"/api/projects/{sample_project['id']}/dependencies/{second_project['id']}"
        )

        assert response.status_code == 401
