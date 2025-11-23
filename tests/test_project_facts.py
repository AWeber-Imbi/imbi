"""
Tests for project fact endpoints.
"""

import pytest
from httpx import AsyncClient

from imbi.models import ProjectFact


@pytest.mark.asyncio
@pytest.mark.integration
class TestFactTypes:
    """Tests for fact type management"""

    async def test_list_fact_types_empty(self, client: AsyncClient, clean_database):
        """Test listing fact types when none exist."""
        response = await client.get("/api/fact-types")

        assert response.status_code == 200
        assert response.json() == []

    async def test_list_fact_types(self, client: AsyncClient, sample_fact_type: dict):
        """Test listing fact types."""
        response = await client.get("/api/fact-types")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Language"
        assert data[0]["fact_type"] == "string"

    async def test_create_fact_type(self, admin_client: AsyncClient, clean_database):
        """Test creating a fact type."""
        response = await admin_client.post(
            "/api/fact-types",
            json={
                "name": "Version",
                "fact_type": "string",
                "description": "Software version",
                "weight": 20,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Version"
        assert data["fact_type"] == "string"
        assert data["weight"] == 20

    async def test_create_duplicate_fact_type(
        self, admin_client: AsyncClient, sample_fact_type: dict
    ):
        """Test creating duplicate fact type returns 409."""
        response = await admin_client.post(
            "/api/fact-types",
            json={"name": "Language", "fact_type": "string"},
        )

        assert response.status_code == 409


@pytest.mark.asyncio
@pytest.mark.integration
class TestListProjectFacts:
    """Tests for GET /api/projects/{id}/facts"""

    async def test_list_empty(self, client: AsyncClient, sample_project: dict):
        """Test listing facts when project has none."""
        response = await client.get(f"/api/projects/{sample_project['id']}/facts")

        assert response.status_code == 200
        assert response.json() == []

    async def test_list_with_facts(
        self,
        authenticated_client: AsyncClient,
        sample_project: dict,
        sample_fact_type: dict,
    ):
        """Test listing facts when project has some."""
        # Add a fact
        add_response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/facts",
            json={
                "fact_type_id": sample_fact_type["id"],
                "value": "Python",
                "score": 100.0,
            },
        )
        assert add_response.status_code == 201

        # List facts
        response = await authenticated_client.get(
            f"/api/projects/{sample_project['id']}/facts"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["fact_type_name"] == "Language"
        assert data[0]["value"] == "Python"
        assert data[0]["score"] == 100.0

    async def test_list_nonexistent_project(self, client: AsyncClient):
        """Test listing facts for nonexistent project returns 404."""
        response = await client.get("/api/projects/999/facts")

        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
class TestAddProjectFact:
    """Tests for POST /api/projects/{id}/facts"""

    async def test_add_success(
        self,
        authenticated_client: AsyncClient,
        sample_project: dict,
        sample_fact_type: dict,
    ):
        """Test successfully adding a fact."""
        response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/facts",
            json={
                "fact_type_id": sample_fact_type["id"],
                "value": "Python",
                "score": 95.5,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["project_id"] == sample_project["id"]
        assert data["fact_type_id"] == sample_fact_type["id"]
        assert data["fact_type_name"] == "Language"
        assert data["value"] == "Python"
        assert data["score"] == 95.5

    async def test_add_without_score(
        self,
        authenticated_client: AsyncClient,
        sample_project: dict,
        sample_fact_type: dict,
    ):
        """Test adding a fact without score."""
        response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/facts",
            json={"fact_type_id": sample_fact_type["id"], "value": "Python"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["value"] == "Python"
        assert data["score"] is None

    async def test_add_duplicate_fact_type(
        self,
        authenticated_client: AsyncClient,
        sample_project: dict,
        sample_fact_type: dict,
    ):
        """Test adding duplicate fact type returns 409."""
        # Add first time
        response1 = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/facts",
            json={"fact_type_id": sample_fact_type["id"], "value": "Python"},
        )
        assert response1.status_code == 201

        # Add again with same fact type
        response2 = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/facts",
            json={"fact_type_id": sample_fact_type["id"], "value": "Go"},
        )

        assert response2.status_code == 409

    async def test_add_nonexistent_fact_type(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test adding fact with nonexistent type returns 404."""
        response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/facts",
            json={"fact_type_id": 999, "value": "test"},
        )

        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
class TestUpdateProjectFact:
    """Tests for PATCH /api/projects/{id}/facts/{fact_type_id}"""

    async def test_update_success(
        self,
        authenticated_client: AsyncClient,
        sample_project: dict,
        sample_fact_type: dict,
    ):
        """Test successfully updating a fact."""
        # Add fact first
        add_response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/facts",
            json={
                "fact_type_id": sample_fact_type["id"],
                "value": "Python",
                "score": 80.0,
            },
        )
        assert add_response.status_code == 201

        # Update it
        response = await authenticated_client.patch(
            f"/api/projects/{sample_project['id']}/facts/{sample_fact_type['id']}",
            json={"value": "Go", "score": 90.0},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["value"] == "Go"
        assert data["score"] == 90.0

    async def test_update_nonexistent(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test updating nonexistent fact returns 404."""
        response = await authenticated_client.patch(
            f"/api/projects/{sample_project['id']}/facts/999",
            json={"value": "test"},
        )

        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
class TestRemoveProjectFact:
    """Tests for DELETE /api/projects/{id}/facts/{fact_type_id}"""

    async def test_remove_success(
        self,
        authenticated_client: AsyncClient,
        sample_project: dict,
        sample_fact_type: dict,
    ):
        """Test successfully removing a fact."""
        # Add fact first
        add_response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/facts",
            json={"fact_type_id": sample_fact_type["id"], "value": "Python"},
        )
        assert add_response.status_code == 201

        # Remove it
        response = await authenticated_client.delete(
            f"/api/projects/{sample_project['id']}/facts/{sample_fact_type['id']}"
        )

        assert response.status_code == 204

        # Verify it's gone
        fact = (
            await ProjectFact.select()
            .where(
                (ProjectFact.project_id == sample_project["id"])
                & (ProjectFact.fact_type_id == sample_fact_type["id"])
            )
            .first()
        )
        assert fact is None

    async def test_remove_nonexistent(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test removing nonexistent fact returns 404."""
        response = await authenticated_client.delete(
            f"/api/projects/{sample_project['id']}/facts/999"
        )

        assert response.status_code == 404
