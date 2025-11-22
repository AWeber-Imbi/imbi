"""
Tests for namespace API endpoints.
"""
import pytest
from httpx import AsyncClient

from imbi.models import Namespace


@pytest.mark.asyncio
@pytest.mark.integration
class TestListNamespaces:
    """Tests for GET /api/namespaces"""

    async def test_list_empty(self, client: AsyncClient, clean_database):
        """Test listing namespaces when none exist."""
        response = await client.get("/api/namespaces")

        assert response.status_code == 200
        assert response.json() == []

    async def test_list_with_data(self, client: AsyncClient, sample_namespace):
        """Test listing namespaces with data."""
        response = await client.get("/api/namespaces")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Namespace"
        assert data[0]["slug"] == "test-namespace"
        assert data[0]["namespace_id"] == 1

    async def test_list_multiple(self, client: AsyncClient, clean_database, admin_user):
        """Test listing multiple namespaces."""
        # Create multiple namespaces
        namespaces = [
            Namespace(
                namespace_id=i,
                name=f"Namespace {i}",
                slug=f"namespace-{i}",
                created_by=admin_user["username"],
                last_modified_by=admin_user["username"],
            )
            for i in range(1, 4)
        ]
        for ns in namespaces:
            await ns.save()

        response = await client.get("/api/namespaces")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        # Should be ordered by name
        names = [ns["name"] for ns in data]
        assert names == sorted(names)

    async def test_list_no_auth_required(self, client: AsyncClient, clean_database):
        """Test that listing namespaces doesn't require authentication."""
        response = await client.get("/api/namespaces")
        assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
class TestGetNamespace:
    """Tests for GET /api/namespaces/{id}"""

    async def test_get_existing(self, client: AsyncClient, sample_namespace):
        """Test getting an existing namespace."""
        response = await client.get("/api/namespaces/1")

        assert response.status_code == 200
        data = response.json()
        assert data["namespace_id"] == 1
        assert data["name"] == "Test Namespace"
        assert data["slug"] == "test-namespace"
        assert "created_at" in data
        assert "created_by" in data
        assert "last_modified_at" in data
        assert "last_modified_by" in data

    async def test_get_nonexistent(self, client: AsyncClient, clean_database):
        """Test getting a nonexistent namespace returns 404."""
        response = await client.get("/api/namespaces/999")

        assert response.status_code == 404
        data = response.json()
        assert data["status"] == 404
        assert "not found" in data["detail"].lower()

    async def test_get_no_auth_required(self, client: AsyncClient, sample_namespace):
        """Test that getting a namespace doesn't require authentication."""
        response = await client.get("/api/namespaces/1")
        assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
class TestCreateNamespace:
    """Tests for POST /api/namespaces"""

    async def test_create_success(self, admin_client: AsyncClient, clean_database):
        """Test successfully creating a namespace."""
        payload = {
            "namespace_id": 10,
            "name": "New Namespace",
            "slug": "new-namespace",
            "icon_class": "fas fa-rocket",
            "maintained_by": "Platform Team",
        }

        response = await admin_client.post("/api/namespaces", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["namespace_id"] == 10
        assert data["name"] == "New Namespace"
        assert data["slug"] == "new-namespace"
        assert data["icon_class"] == "fas fa-rocket"
        assert "created_at" in data
        assert "created_by" in data

        # Verify it's in the database
        ns = await Namespace.select().where(Namespace.namespace_id == 10).first()
        assert ns is not None
        assert ns["name"] == "New Namespace"

    async def test_create_minimal(self, admin_client: AsyncClient, clean_database):
        """Test creating a namespace with only required fields."""
        payload = {
            "namespace_id": 20,
            "name": "Minimal Namespace",
            "slug": "minimal-namespace",
        }

        response = await admin_client.post("/api/namespaces", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["namespace_id"] == 20
        assert data["icon_class"] is None
        assert data["maintained_by"] is None

    async def test_create_duplicate_id(
        self, admin_client: AsyncClient, sample_namespace
    ):
        """Test creating a namespace with duplicate namespace_id returns 409."""
        payload = {
            "namespace_id": 1,  # Already exists
            "name": "Different Name",
            "slug": "different-slug",
        }

        response = await admin_client.post("/api/namespaces", json=payload)

        assert response.status_code == 409
        data = response.json()
        assert data["status"] == 409
        assert "conflict" in data["detail"].lower()

    async def test_create_duplicate_name(
        self, admin_client: AsyncClient, sample_namespace
    ):
        """Test creating a namespace with duplicate name returns 409."""
        payload = {
            "namespace_id": 99,
            "name": "Test Namespace",  # Already exists
            "slug": "different-slug",
        }

        response = await admin_client.post("/api/namespaces", json=payload)

        assert response.status_code == 409

    async def test_create_duplicate_slug(
        self, admin_client: AsyncClient, sample_namespace
    ):
        """Test creating a namespace with duplicate slug returns 409."""
        payload = {
            "namespace_id": 99,
            "name": "Different Name",
            "slug": "test-namespace",  # Already exists
        }

        response = await admin_client.post("/api/namespaces", json=payload)

        assert response.status_code == 409

    @pytest.mark.skip(reason="Authentication not yet fully implemented")
    async def test_create_requires_admin(
        self, authenticated_client: AsyncClient, clean_database
    ):
        """Test that creating a namespace requires admin permission."""
        payload = {
            "namespace_id": 30,
            "name": "Should Fail",
            "slug": "should-fail",
        }

        response = await authenticated_client.post("/api/namespaces", json=payload)

        assert response.status_code == 403
        data = response.json()
        assert data["status"] == 403

    @pytest.mark.skip(reason="Authentication not yet fully implemented")
    async def test_create_requires_auth(self, client: AsyncClient, clean_database):
        """Test that creating a namespace requires authentication."""
        payload = {
            "namespace_id": 40,
            "name": "Should Fail",
            "slug": "should-fail",
        }

        response = await client.post("/api/namespaces", json=payload)

        assert response.status_code == 401

    async def test_create_validation_error(
        self, admin_client: AsyncClient, clean_database
    ):
        """Test that invalid data returns 422."""
        payload = {
            "namespace_id": "not-an-int",  # Should be int
            "name": "Test",
            "slug": "test",
        }

        response = await admin_client.post("/api/namespaces", json=payload)

        assert response.status_code == 422
        data = response.json()
        assert "errors" in data or "detail" in data


@pytest.mark.asyncio
@pytest.mark.integration
class TestUpdateNamespace:
    """Tests for PATCH /api/namespaces/{id}"""

    async def test_update_success(self, admin_client: AsyncClient, sample_namespace):
        """Test successfully updating a namespace."""
        payload = {
            "name": "Updated Namespace",
            "maintained_by": "New Team",
        }

        response = await admin_client.patch("/api/namespaces/1", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Namespace"
        assert data["maintained_by"] == "New Team"
        assert data["slug"] == "test-namespace"  # Unchanged

        # Verify in database
        ns = await Namespace.select().where(Namespace.namespace_id == 1).first()
        assert ns["name"] == "Updated Namespace"

    async def test_update_partial(self, admin_client: AsyncClient, sample_namespace):
        """Test updating only some fields."""
        payload = {"icon_class": "fas fa-updated"}

        response = await admin_client.patch("/api/namespaces/1", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["icon_class"] == "fas fa-updated"
        assert data["name"] == "Test Namespace"  # Unchanged

    async def test_update_nonexistent(self, admin_client: AsyncClient, clean_database):
        """Test updating a nonexistent namespace returns 404."""
        payload = {"name": "Should Fail"}

        response = await admin_client.patch("/api/namespaces/999", json=payload)

        assert response.status_code == 404

    async def test_update_conflict(self, admin_client: AsyncClient, clean_database, admin_user):
        """Test updating to a conflicting name returns 409."""
        # Create two namespaces
        ns1 = Namespace(
            namespace_id=1,
            name="Namespace One",
            slug="namespace-one",
            created_by=admin_user["username"],
            last_modified_by=admin_user["username"],
        )
        await ns1.save()

        ns2 = Namespace(
            namespace_id=2,
            name="Namespace Two",
            slug="namespace-two",
            created_by=admin_user["username"],
            last_modified_by=admin_user["username"],
        )
        await ns2.save()

        # Try to update ns2's name to conflict with ns1
        payload = {"name": "Namespace One"}

        response = await admin_client.patch("/api/namespaces/2", json=payload)

        assert response.status_code == 409

    @pytest.mark.skip(reason="Authentication not yet fully implemented")
    async def test_update_requires_admin(
        self, authenticated_client: AsyncClient, sample_namespace
    ):
        """Test that updating a namespace requires admin permission."""
        payload = {"name": "Should Fail"}

        response = await authenticated_client.patch("/api/namespaces/1", json=payload)

        assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
class TestDeleteNamespace:
    """Tests for DELETE /api/namespaces/{id}"""

    async def test_delete_success(self, admin_client: AsyncClient, sample_namespace):
        """Test successfully deleting a namespace."""
        response = await admin_client.delete("/api/namespaces/1")

        assert response.status_code == 204
        assert response.content == b""

        # Verify it's deleted
        ns = await Namespace.select().where(Namespace.namespace_id == 1).first()
        assert ns is None

    async def test_delete_nonexistent(self, admin_client: AsyncClient, clean_database):
        """Test deleting a nonexistent namespace returns 404."""
        response = await admin_client.delete("/api/namespaces/999")

        assert response.status_code == 404

    @pytest.mark.skip(reason="Authentication not yet fully implemented")
    async def test_delete_requires_admin(
        self, authenticated_client: AsyncClient, sample_namespace
    ):
        """Test that deleting a namespace requires admin permission."""
        response = await authenticated_client.delete("/api/namespaces/1")

        assert response.status_code == 403

    @pytest.mark.skip(reason="Authentication not yet fully implemented")
    async def test_delete_requires_auth(self, client: AsyncClient, sample_namespace):
        """Test that deleting a namespace requires authentication."""
        response = await client.delete("/api/namespaces/1")

        assert response.status_code == 401
