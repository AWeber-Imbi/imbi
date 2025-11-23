"""
Tests for project note endpoints.
"""

import pytest
from httpx import AsyncClient

from imbi.models import ProjectNote


@pytest.mark.asyncio
@pytest.mark.integration
class TestListProjectNotes:
    """Tests for GET /api/projects/{id}/notes"""

    async def test_list_empty(self, client: AsyncClient, sample_project: dict):
        """Test listing notes when project has none."""
        response = await client.get(f"/api/projects/{sample_project['id']}/notes")

        assert response.status_code == 200
        assert response.json() == []

    async def test_list_with_notes(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test listing notes when project has some."""
        # Add notes
        await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/notes",
            json={"note": "First note"},
        )
        await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/notes",
            json={"note": "Second note"},
        )

        # List notes
        response = await authenticated_client.get(
            f"/api/projects/{sample_project['id']}/notes"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # Should be ordered by creation date (newest first)
        assert data[0]["note"] == "Second note"
        assert data[1]["note"] == "First note"

    async def test_list_nonexistent_project(self, client: AsyncClient):
        """Test listing notes for nonexistent project returns 404."""
        response = await client.get("/api/projects/999/notes")

        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
class TestAddProjectNote:
    """Tests for POST /api/projects/{id}/notes"""

    async def test_add_success(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test successfully adding a note."""
        response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/notes",
            json={"note": "This is a test note"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["project_id"] == sample_project["id"]
        assert data["note"] == "This is a test note"
        assert "note_id" in data
        assert "created_by" in data
        assert "created_at" in data

    async def test_add_long_note(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test adding a long note."""
        long_note = "A" * 1000  # 1000 character note

        response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/notes",
            json={"note": long_note},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["note"] == long_note

    async def test_add_empty_note_fails(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test adding empty note returns 422."""
        response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/notes",
            json={"note": ""},
        )

        assert response.status_code == 422

    async def test_add_nonexistent_project(self, authenticated_client: AsyncClient):
        """Test adding note to nonexistent project returns 404."""
        response = await authenticated_client.post(
            "/api/projects/999/notes",
            json={"note": "Test note"},
        )

        assert response.status_code == 404

    async def test_add_requires_auth(self, client: AsyncClient, sample_project: dict):
        """Test adding note requires authentication."""
        response = await client.post(
            f"/api/projects/{sample_project['id']}/notes",
            json={"note": "Test note"},
        )

        assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
class TestUpdateProjectNote:
    """Tests for PATCH /api/projects/{id}/notes/{note_id}"""

    async def test_update_success(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test successfully updating a note."""
        # Add note first
        add_response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/notes",
            json={"note": "Original note"},
        )
        assert add_response.status_code == 201
        note_id = add_response.json()["note_id"]

        # Update it
        response = await authenticated_client.patch(
            f"/api/projects/{sample_project['id']}/notes/{note_id}",
            json={"note": "Updated note"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["note"] == "Updated note"
        assert data["note_id"] == note_id

    async def test_update_nonexistent(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test updating nonexistent note returns 404."""
        response = await authenticated_client.patch(
            f"/api/projects/{sample_project['id']}/notes/999",
            json={"note": "Updated"},
        )

        assert response.status_code == 404

    async def test_update_empty_note_fails(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test updating to empty note returns 422."""
        # Add note first
        add_response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/notes",
            json={"note": "Original"},
        )
        note_id = add_response.json()["note_id"]

        # Try to update to empty
        response = await authenticated_client.patch(
            f"/api/projects/{sample_project['id']}/notes/{note_id}",
            json={"note": ""},
        )

        assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
class TestRemoveProjectNote:
    """Tests for DELETE /api/projects/{id}/notes/{note_id}"""

    async def test_remove_success(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test successfully removing a note."""
        # Add note first
        add_response = await authenticated_client.post(
            f"/api/projects/{sample_project['id']}/notes",
            json={"note": "Test note"},
        )
        assert add_response.status_code == 201
        note_id = add_response.json()["note_id"]

        # Remove it
        response = await authenticated_client.delete(
            f"/api/projects/{sample_project['id']}/notes/{note_id}"
        )

        assert response.status_code == 204

        # Verify it's gone
        note = await ProjectNote.select().where(ProjectNote.note_id == note_id).first()
        assert note is None

    async def test_remove_nonexistent(
        self, authenticated_client: AsyncClient, sample_project: dict
    ):
        """Test removing nonexistent note returns 404."""
        response = await authenticated_client.delete(
            f"/api/projects/{sample_project['id']}/notes/999"
        )

        assert response.status_code == 404

    async def test_remove_requires_auth(
        self, client: AsyncClient, sample_project: dict
    ):
        """Test removing note requires authentication."""
        response = await client.delete(f"/api/projects/{sample_project['id']}/notes/1")

        assert response.status_code == 401
