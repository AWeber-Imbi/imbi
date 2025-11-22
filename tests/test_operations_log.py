"""
Tests for operations log endpoints.
"""
import datetime

import pytest
from httpx import AsyncClient

from imbi.models import OperationsLog


@pytest.mark.asyncio
@pytest.mark.integration
class TestListOperationsLog:
    """Tests for GET /api/operations-log"""

    async def test_list_empty(self, client: AsyncClient, clean_database):
        """Test listing operations log when empty."""
        response = await client.get("/api/operations-log")

        assert response.status_code == 200
        data = response.json()
        assert data["entries"] == []
        assert data["total"] == 0

    async def test_list_with_entries(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test listing operations log with entries."""
        # Add entries
        await authenticated_client.post(
            "/api/operations-log",
            json={
                "project_id": sample_project["id"],
                "change_type": "deployment",
                "description": "Deployed v1.0.0",
                "occurred_at": "2025-11-22T10:00:00Z",
                "version": "1.0.0",
            },
        )
        await authenticated_client.post(
            "/api/operations-log",
            json={
                "project_id": sample_project["id"],
                "change_type": "incident",
                "description": "Database connection timeout",
                "occurred_at": "2025-11-22T11:00:00Z",
            },
        )

        # List entries
        response = await authenticated_client.get("/api/operations-log")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["entries"]) == 2
        # Should be ordered by occurred_at (newest first)
        assert data["entries"][0]["description"] == "Database connection timeout"
        assert data["entries"][1]["description"] == "Deployed v1.0.0"

    async def test_list_with_limit(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test listing with limit parameter."""
        # Add multiple entries
        for i in range(5):
            await authenticated_client.post(
                "/api/operations-log",
                json={
                    "project_id": sample_project["id"],
                    "change_type": "deployment",
                    "description": f"Deploy {i}",
                    "occurred_at": f"2025-11-22T{10+i:02d}:00:00Z",
                },
            )

        # List with limit
        response = await authenticated_client.get("/api/operations-log?limit=3")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["entries"]) == 3
        assert data["limit"] == 3

    async def test_list_filter_by_project(
        self, authenticated_client: AsyncClient, sample_project: dict, second_project: dict
    ):
        """Test filtering by project_id."""
        # Add entries for different projects
        await authenticated_client.post(
            "/api/operations-log",
            json={
                "project_id": sample_project["id"],
                "change_type": "deployment",
                "description": "Project 1 deploy",
                "occurred_at": "2025-11-22T10:00:00Z",
            },
        )
        await authenticated_client.post(
            "/api/operations-log",
            json={
                "project_id": second_project["id"],
                "change_type": "deployment",
                "description": "Project 2 deploy",
                "occurred_at": "2025-11-22T11:00:00Z",
            },
        )

        # Filter by project
        response = await authenticated_client.get(
            f"/api/operations-log?project_id={sample_project['id']}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["entries"][0]["description"] == "Project 1 deploy"

    async def test_list_filter_by_date_range(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test filtering by date range."""
        # Add entries at different times
        await authenticated_client.post(
            "/api/operations-log",
            json={
                "project_id": sample_project["id"],
                "change_type": "deployment",
                "description": "Old deploy",
                "occurred_at": "2025-11-20T10:00:00Z",
            },
        )
        await authenticated_client.post(
            "/api/operations-log",
            json={
                "project_id": sample_project["id"],
                "change_type": "deployment",
                "description": "Recent deploy",
                "occurred_at": "2025-11-22T10:00:00Z",
            },
        )

        # Filter by date
        response = await authenticated_client.get(
            "/api/operations-log?from=2025-11-22T00:00:00Z"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["entries"][0]["description"] == "Recent deploy"


@pytest.mark.asyncio
@pytest.mark.integration
class TestGetOperationsLogEntry:
    """Tests for GET /api/operations-log/{id}"""

    async def test_get_existing(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test getting an existing entry."""
        # Create entry
        create_response = await authenticated_client.post(
            "/api/operations-log",
            json={
                "project_id": sample_project["id"],
                "change_type": "deployment",
                "description": "Test deployment",
                "occurred_at": "2025-11-22T10:00:00Z",
                "version": "1.0.0",
                "environment": "production",
            },
        )
        entry_id = create_response.json()["id"]

        # Get entry
        response = await authenticated_client.get(f"/api/operations-log/{entry_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == entry_id
        assert data["description"] == "Test deployment"
        assert data["version"] == "1.0.0"
        assert data["project_name"] == "Test Project"

    async def test_get_nonexistent(self, client: AsyncClient):
        """Test getting nonexistent entry returns 404."""
        response = await client.get("/api/operations-log/999")

        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
class TestCreateOperationsLogEntry:
    """Tests for POST /api/operations-log"""

    async def test_create_success(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test successfully creating an entry."""
        response = await authenticated_client.post(
            "/api/operations-log",
            json={
                "project_id": sample_project["id"],
                "change_type": "deployment",
                "description": "Deployed version 2.0.0",
                "occurred_at": "2025-11-22T15:30:00Z",
                "version": "2.0.0",
                "environment": "production",
                "performed_by": "admin",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["project_id"] == sample_project["id"]
        assert data["change_type"] == "deployment"
        assert data["description"] == "Deployed version 2.0.0"
        assert data["version"] == "2.0.0"
        assert data["recorded_by"] == "admin"  # From authenticated user

    async def test_create_minimal(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test creating entry with only required fields."""
        response = await authenticated_client.post(
            "/api/operations-log",
            json={
                "project_id": sample_project["id"],
                "change_type": "change",
                "description": "Configuration update",
                "occurred_at": "2025-11-22T10:00:00Z",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["version"] is None
        assert data["environment"] is None
        assert data["link"] is None

    async def test_create_nonexistent_project(
        self, authenticated_client: AsyncClient
    ):
        """Test creating entry for nonexistent project returns 404."""
        response = await authenticated_client.post(
            "/api/operations-log",
            json={
                "project_id": 999,
                "change_type": "deployment",
                "description": "Test",
                "occurred_at": "2025-11-22T10:00:00Z",
            },
        )

        assert response.status_code == 404

    async def test_create_requires_auth(
        self, client: AsyncClient, sample_project: dict
    ):
        """Test creating entry requires authentication."""
        response = await client.post(
            "/api/operations-log",
            json={
                "project_id": sample_project["id"],
                "change_type": "deployment",
                "description": "Test",
                "occurred_at": "2025-11-22T10:00:00Z",
            },
        )

        assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
class TestUpdateOperationsLogEntry:
    """Tests for PATCH /api/operations-log/{id}"""

    async def test_update_success(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test successfully updating an entry."""
        # Create entry
        create_response = await authenticated_client.post(
            "/api/operations-log",
            json={
                "project_id": sample_project["id"],
                "change_type": "deployment",
                "description": "Original description",
                "occurred_at": "2025-11-22T10:00:00Z",
            },
        )
        entry_id = create_response.json()["id"]

        # Update it
        response = await authenticated_client.patch(
            f"/api/operations-log/{entry_id}",
            json={
                "description": "Updated description",
                "version": "1.0.1",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "Updated description"
        assert data["version"] == "1.0.1"

    async def test_update_nonexistent(self, authenticated_client: AsyncClient):
        """Test updating nonexistent entry returns 404."""
        response = await authenticated_client.patch(
            "/api/operations-log/999",
            json={"description": "Updated"},
        )

        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
class TestDeleteOperationsLogEntry:
    """Tests for DELETE /api/operations-log/{id}"""

    async def test_delete_success(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test successfully deleting an entry."""
        # Create entry
        create_response = await authenticated_client.post(
            "/api/operations-log",
            json={
                "project_id": sample_project["id"],
                "change_type": "deployment",
                "description": "Test",
                "occurred_at": "2025-11-22T10:00:00Z",
            },
        )
        entry_id = create_response.json()["id"]

        # Delete it
        response = await authenticated_client.delete(
            f"/api/operations-log/{entry_id}"
        )

        assert response.status_code == 204

        # Verify it's gone
        entry = await OperationsLog.select().where(
            OperationsLog.id == entry_id
        ).first()
        assert entry is None

    async def test_delete_nonexistent(self, authenticated_client: AsyncClient):
        """Test deleting nonexistent entry returns 404."""
        response = await authenticated_client.delete("/api/operations-log/999")

        assert response.status_code == 404

    async def test_delete_requires_auth(self, client: AsyncClient):
        """Test deleting entry requires authentication."""
        response = await client.delete("/api/operations-log/1")

        assert response.status_code == 401
