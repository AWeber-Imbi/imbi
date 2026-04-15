"""Tests for blueprint CRUD endpoints"""

import datetime
import unittest
from unittest import mock

import psycopg.errors
from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models


class BlueprintEndpointsTestCase(unittest.TestCase):
    """Test cases for blueprint CRUD endpoints."""

    def setUp(self) -> None:
        """Prepare the test fixture.

        Creates a FastAPI app, an authenticated admin context,
        a mock Graph instance, a TestClient, and a sample
        Blueprint model.
        """
        from imbi_api.auth import permissions

        self.test_app = app.create_app()

        # Create an admin user for authentication
        self.admin_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_context = permissions.AuthContext(
            user=self.admin_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)
        self.test_blueprint = models.Blueprint(
            name='Test Blueprint',
            slug='test-blueprint',
            type='Project',
            description='A test blueprint',
            json_schema=models.Schema.model_validate(
                {'type': 'object', 'properties': {}}
            ),
        )

    def test_create_blueprint_success(self) -> None:
        """Test successful blueprint creation."""
        created = models.Blueprint(
            name='New Blueprint',
            slug='new-blueprint',
            type='Environment',
            description=None,
            enabled=True,
            priority=0,
            json_schema=models.Schema.model_validate(
                {'type': 'object', 'properties': {}}
            ),
            version=0,
        )
        self.mock_db.merge.return_value = created

        response = self.client.post(
            '/blueprints/',
            json={
                'name': 'New Blueprint',
                'type': 'Environment',
                'json_schema': {
                    'type': 'object',
                    'properties': {},
                },
            },
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['name'], 'New Blueprint')
        self.assertEqual(data['type'], 'Environment')
        self.assertEqual(data['slug'], 'new-blueprint')
        self.mock_db.merge.assert_called_once()

    def test_create_blueprint_duplicate(self) -> None:
        """Test creating duplicate blueprint returns 409."""
        self.mock_db.merge.side_effect = psycopg.errors.UniqueViolation(
            'Constraint violation'
        )

        response = self.client.post(
            '/blueprints/',
            json={
                'name': 'Duplicate',
                'type': 'Project',
                'json_schema': {
                    'type': 'object',
                    'properties': {},
                },
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_create_blueprint_invalid_data(self) -> None:
        """Test creating blueprint with invalid data returns 422."""
        response = self.client.post(
            '/blueprints/',
            json={
                'name': 'Invalid',
                # Missing required fields
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_list_blueprints_empty(self) -> None:
        """Test listing blueprints when none exist."""
        self.mock_db.match.return_value = []

        response = self.client.get('/blueprints/')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data, [])

    def test_list_blueprints_with_data(self) -> None:
        """Test listing blueprints returns data."""
        self.mock_db.match.return_value = [
            self.test_blueprint,
        ]

        response = self.client.get('/blueprints/')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['name'], 'Test Blueprint')
        self.assertEqual(data[0]['slug'], 'test-blueprint')

    def test_list_blueprints_with_enabled_filter(self) -> None:
        """Test listing blueprints with enabled filter."""
        self.mock_db.match.return_value = [
            self.test_blueprint,
        ]

        response = self.client.get(
            '/blueprints/?enabled=true',
        )

        self.assertEqual(response.status_code, 200)
        # Verify filter was passed to db.match
        call_args = self.mock_db.match.call_args
        self.assertIn('enabled', call_args[0][1])
        self.assertTrue(call_args[0][1]['enabled'])

    def test_list_blueprints_by_type(self) -> None:
        """Test listing blueprints filtered by type."""
        self.mock_db.match.return_value = [
            self.test_blueprint,
        ]

        response = self.client.get('/blueprints/Project')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['type'], 'Project')

        # Verify type filter was passed
        call_args = self.mock_db.match.call_args
        self.assertEqual(call_args[0][1]['type'], 'Project')

    def test_list_blueprints_by_type_with_enabled_filter(
        self,
    ) -> None:
        """Test listing blueprints by type with enabled filter."""
        self.mock_db.match.return_value = [
            self.test_blueprint,
        ]

        response = self.client.get(
            '/blueprints/Project?enabled=false',
        )

        self.assertEqual(response.status_code, 200)
        # Verify both filters were passed
        call_args = self.mock_db.match.call_args
        parameters = call_args[0][1]
        self.assertEqual(parameters['type'], 'Project')
        self.assertFalse(parameters['enabled'])

    def test_get_blueprint_success(self) -> None:
        """Test getting a specific blueprint."""
        self.mock_db.match.return_value = [
            self.test_blueprint,
        ]

        response = self.client.get(
            '/blueprints/Project/test-blueprint',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'Test Blueprint')
        self.assertEqual(data['slug'], 'test-blueprint')
        self.assertEqual(data['type'], 'Project')

    def test_get_blueprint_not_found(self) -> None:
        """Test getting non-existent blueprint returns 404."""
        self.mock_db.match.return_value = []

        response = self.client.get(
            '/blueprints/Project/nonexistent-slug',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_update_blueprint_success(self) -> None:
        """Test updating a blueprint."""
        updated = models.Blueprint(
            name='Updated Blueprint',
            slug='test-blueprint',
            type='Project',
            description='Updated description',
            json_schema=models.Schema.model_validate(
                {'type': 'object', 'properties': {}}
            ),
        )
        self.mock_db.merge.return_value = updated

        response = self.client.put(
            '/blueprints/Project/test-blueprint',
            json={
                'name': 'Updated Blueprint',
                'slug': 'test-blueprint',
                'type': 'Project',
                'description': 'Updated description',
                'json_schema': {
                    'type': 'object',
                    'properties': {},
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'Updated Blueprint')
        self.assertEqual(data['description'], 'Updated description')
        self.mock_db.merge.assert_called_once()

    def test_update_blueprint_slug_mismatch_rejected(
        self,
    ) -> None:
        """Mismatched slug in body vs URL returns 400."""
        response = self.client.put(
            '/blueprints/Project/test-blueprint',
            json={
                'name': 'Test',
                'slug': 'new-slug',
                'type': 'Project',
                'json_schema': {
                    'type': 'object',
                    'properties': {},
                },
            },
        )

        self.assertEqual(response.status_code, 400)
        self.mock_db.merge.assert_not_called()

    def test_update_blueprint_type_mismatch_rejected(
        self,
    ) -> None:
        """Mismatched type in body vs URL returns 400."""
        response = self.client.put(
            '/blueprints/Project/test-blueprint',
            json={
                'name': 'Test',
                'slug': 'test-blueprint',
                'type': 'Team',
                'json_schema': {
                    'type': 'object',
                    'properties': {},
                },
            },
        )

        self.assertEqual(response.status_code, 400)
        self.mock_db.merge.assert_not_called()

    def test_delete_blueprint_success(self) -> None:
        """Test deleting a blueprint."""
        self.mock_db.execute.return_value = [{'n': 'true'}]

        response = self.client.delete(
            '/blueprints/Project/test-blueprint',
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')

    def test_delete_blueprint_not_found(self) -> None:
        """Test deleting non-existent blueprint returns 404."""
        self.mock_db.execute.return_value = []

        response = self.client.delete(
            '/blueprints/Project/nonexistent-slug',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_patch_blueprint_enabled(self) -> None:
        """Test patching a blueprint's enabled flag."""
        from imbi_common import models as common_models

        existing = common_models.Blueprint(
            name='Extra Field',
            slug='extra-field',
            type='Project',
            json_schema=common_models.Schema.model_validate(
                {'type': 'object', 'properties': {'extra': {'type': 'string'}}}
            ),
            enabled=True,
        )
        self.mock_db.match.side_effect = [
            [existing],  # fetch
        ]
        self.mock_db.merge.return_value = None

        with mock.patch(
            'imbi_api.endpoints.blueprints.openapi.refresh_blueprint_models',
        ) as mock_refresh:
            mock_refresh.return_value = None
            response = self.client.patch(
                '/blueprints/Project/extra-field',
                json=[{'op': 'replace', 'path': '/enabled', 'value': False}],
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['enabled'])
        self.mock_db.merge.assert_called_once()

    def test_patch_blueprint_not_found(self) -> None:
        """Test patching a non-existent blueprint returns 404."""
        self.mock_db.match.return_value = []

        response = self.client.patch(
            '/blueprints/Project/nonexistent',
            json=[{'op': 'replace', 'path': '/enabled', 'value': False}],
        )

        self.assertEqual(response.status_code, 404)

    def test_patch_blueprint_slug_mismatch_raises_400(self) -> None:
        """Test that patching slug to a different value raises 400."""
        from imbi_common import models as common_models

        existing = common_models.Blueprint(
            name='Extra Field',
            slug='extra-field',
            type='Project',
            json_schema=common_models.Schema.model_validate(
                {'type': 'object'}
            ),
            enabled=True,
        )
        self.mock_db.match.return_value = [existing]

        response = self.client.patch(
            '/blueprints/Project/extra-field',
            json=[
                {'op': 'replace', 'path': '/slug', 'value': 'different-slug'}
            ],
        )

        self.assertEqual(response.status_code, 400)

    def test_blueprint_requires_authentication(self) -> None:
        """Verify blueprint endpoints reject unauthenticated."""
        from imbi_api.auth import permissions

        # Remove auth override only; keep graph DI override
        del self.test_app.dependency_overrides[permissions.get_current_user]

        client_no_auth = testclient.TestClient(self.test_app)

        response = client_no_auth.get('/blueprints/')
        self.assertEqual(response.status_code, 401)

        response = client_no_auth.post(
            '/blueprints/',
            json={
                'name': 'Test',
                'type': 'Project',
                'json_schema': {'type': 'object'},
            },
        )
        self.assertEqual(response.status_code, 401)

        # Restore the overrides for other tests
        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )
