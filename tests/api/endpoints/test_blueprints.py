"""Tests for blueprint CRUD endpoints"""

import datetime
import unittest
from unittest import mock

from fastapi import testclient

from imbi import app, models


class BlueprintEndpointsTestCase(unittest.TestCase):
    """Test cases for blueprint CRUD endpoints."""

    def setUp(self) -> None:
        """
        Prepare the test fixture by creating a FastAPI app, an
        authenticated admin context, a TestClient, and a sample
        Blueprint model.

        Sets the following attributes on self:
        - test_app: FastAPI application instance used by tests.
        - admin_user: admin User model used for authentication.
        - auth_context: AuthContext returned by the overridden
            dependency.
        - client: TestClient bound to the test_app.
        - test_blueprint: Blueprint model instance used in endpoint
            tests.

        Overrides the get_current_user dependency to return the admin
        auth context so tests run with elevated permissions.
        """
        from imbi.auth import permissions

        self.test_app = app.create_app()

        # Create an admin user for authentication
        self.admin_user = models.User(
            username='admin',
            email='admin@example.com',
            display_name='Admin User',
            is_active=True,
            is_admin=True,  # Admin has all permissions
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_context = permissions.AuthContext(
            user=self.admin_user,
            session_id='test-session',
            auth_method='jwt',
            permissions=set(),  # Admin bypasses permission checks
        )

        # Override the get_current_user dependency
        async def mock_get_current_user():
            """
            Provide the preconfigured authentication context for tests.

            Returns:
                The test's authentication context object used to
                    simulate an authenticated user.
            """
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
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
        with mock.patch('imbi.neo4j.create_node') as mock_create:
            # Mock node that can be converted to dict
            mock_node = {
                'name': 'New Blueprint',
                'slug': 'new-blueprint',
                'type': 'Environment',
                'description': None,
                'enabled': True,
                'priority': 0,
                'filter': None,
                'json_schema': '{"type": "object", "properties": {}}',
                'version': 0,
            }
            mock_create.return_value = mock_node

            response = self.client.post(
                '/blueprints/',
                json={
                    'name': 'New Blueprint',
                    'type': 'Environment',
                    'json_schema': {'type': 'object', 'properties': {}},
                },
            )

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertEqual(data['name'], 'New Blueprint')
            self.assertEqual(data['type'], 'Environment')
            self.assertEqual(data['slug'], 'new-blueprint')
            mock_create.assert_called_once()

    def test_create_blueprint_duplicate(self) -> None:
        """Test creating duplicate blueprint returns 409."""
        import neo4j

        with (
            mock.patch('imbi.neo4j.create_node') as mock_create,
        ):
            mock_create.side_effect = neo4j.exceptions.ConstraintError(
                'Constraint violation'
            )

            response = self.client.post(
                '/blueprints/',
                json={
                    'name': 'Duplicate',
                    'type': 'Project',
                    'json_schema': {'type': 'object', 'properties': {}},
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

        async def empty_generator():
            """
            Async generator that yields no items.

            Returns:
                Async iterator: An asynchronous iterator that yields no values.
            """
            return
            yield  # Make this a generator

        with (
            mock.patch(
                'imbi.neo4j.fetch_nodes', return_value=empty_generator()
            ),
        ):
            response = self.client.get('/blueprints/')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data, [])

    def test_list_blueprints_with_data(self) -> None:
        """Test listing blueprints returns data."""

        async def blueprint_generator():
            """
            Yield the test blueprint model instance used by the test
            case.

            Returns:
                An asynchronous generator that yields the single
                    blueprint model `self.test_blueprint`.
            """
            yield self.test_blueprint

        with (
            mock.patch(
                'imbi.neo4j.fetch_nodes', return_value=blueprint_generator()
            ),
        ):
            response = self.client.get('/blueprints/')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['name'], 'Test Blueprint')
            self.assertEqual(data[0]['slug'], 'test-blueprint')

    def test_list_blueprints_with_enabled_filter(self) -> None:
        """Test listing blueprints with enabled filter."""

        async def blueprint_generator():
            """
            Yield the test blueprint model instance used by the test
            case.

            Returns:
                An asynchronous generator that yields the single
                    blueprint model `self.test_blueprint`.
            """
            yield self.test_blueprint

        with (
            mock.patch(
                'imbi.neo4j.fetch_nodes', return_value=blueprint_generator()
            ) as mock_fetch,
        ):
            response = self.client.get('/blueprints/?enabled=true')

            self.assertEqual(response.status_code, 200)
            # Verify filter was passed to fetch_nodes
            call_args = mock_fetch.call_args
            self.assertIn('enabled', call_args[0][1])
            self.assertTrue(call_args[0][1]['enabled'])

    def test_list_blueprints_by_type(self) -> None:
        """Test listing blueprints filtered by type."""

        async def blueprint_generator():
            """
            Yield the test blueprint model instance used by the test
            case.

            Returns:
                An asynchronous generator that yields the single
                    blueprint model `self.test_blueprint`.
            """
            yield self.test_blueprint

        with (
            mock.patch(
                'imbi.neo4j.fetch_nodes', return_value=blueprint_generator()
            ) as mock_fetch,
        ):
            response = self.client.get('/blueprints/Project')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['type'], 'Project')

            # Verify type filter was passed
            call_args = mock_fetch.call_args
            self.assertEqual(call_args[0][1]['type'], 'Project')

    def test_list_blueprints_by_type_with_enabled_filter(self) -> None:
        """Test listing blueprints by type with enabled filter."""

        async def blueprint_generator():
            """
            Yield the test blueprint model instance used by the test
            case.

            Returns:
                An asynchronous generator that yields the single
                    blueprint model `self.test_blueprint`.
            """
            yield self.test_blueprint

        with (
            mock.patch(
                'imbi.neo4j.fetch_nodes', return_value=blueprint_generator()
            ) as mock_fetch,
        ):
            response = self.client.get('/blueprints/Project?enabled=false')

            self.assertEqual(response.status_code, 200)
            # Verify both filters were passed
            call_args = mock_fetch.call_args
            parameters = call_args[0][1]
            self.assertEqual(parameters['type'], 'Project')
            self.assertFalse(parameters['enabled'])

    def test_get_blueprint_success(self) -> None:
        """Test getting a specific blueprint."""
        with (
            mock.patch(
                'imbi.neo4j.fetch_node', return_value=self.test_blueprint
            ),
        ):
            response = self.client.get('/blueprints/Project/test-blueprint')

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['name'], 'Test Blueprint')
            self.assertEqual(data['slug'], 'test-blueprint')
            self.assertEqual(data['type'], 'Project')

    def test_get_blueprint_not_found(self) -> None:
        """Test getting non-existent blueprint returns 404."""
        with (
            mock.patch('imbi.neo4j.fetch_node', return_value=None),
        ):
            response = self.client.get('/blueprints/Project/nonexistent-slug')

            self.assertEqual(response.status_code, 404)
            self.assertIn('not found', response.json()['detail'])

    def test_update_blueprint_success(self) -> None:
        """Test updating a blueprint."""
        with (
            mock.patch('imbi.neo4j.upsert') as mock_upsert,
        ):
            mock_upsert.return_value = 'element123'

            response = self.client.put(
                '/blueprints/Project/test-blueprint',
                json={
                    'name': 'Updated Blueprint',
                    'slug': 'test-blueprint',
                    'type': 'Project',
                    'description': 'Updated description',
                    'json_schema': {'type': 'object', 'properties': {}},
                },
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['name'], 'Updated Blueprint')
            self.assertEqual(data['description'], 'Updated description')
            mock_upsert.assert_called_once()

    def test_update_blueprint_slug_mismatch(self) -> None:
        """Test updating blueprint with mismatched slug returns 400."""
        response = self.client.put(
            '/blueprints/Project/test-blueprint',
            json={
                'name': 'Test',
                'slug': 'wrong-slug',  # Doesn't match URL
                'type': 'Project',
                'json_schema': {'type': 'object', 'properties': {}},
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('must match', response.json()['detail'])

    def test_update_blueprint_type_mismatch(self) -> None:
        """Test updating blueprint with mismatched type returns 400."""
        response = self.client.put(
            '/blueprints/Project/test-blueprint',
            json={
                'name': 'Test',
                'slug': 'test-blueprint',
                'type': 'Environment',  # Doesn't match URL
                'json_schema': {'type': 'object', 'properties': {}},
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('must match', response.json()['detail'])

    def test_delete_blueprint_success(self) -> None:
        """Test deleting a blueprint."""
        with (
            mock.patch('imbi.neo4j.delete_node', return_value=True),
        ):
            response = self.client.delete('/blueprints/Project/test-blueprint')

            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.content, b'')

    def test_delete_blueprint_not_found(self) -> None:
        """Test deleting non-existent blueprint returns 404."""
        with (
            mock.patch('imbi.neo4j.delete_node', return_value=False),
        ):
            response = self.client.delete(
                '/blueprints/Project/nonexistent-slug'
            )

            self.assertEqual(response.status_code, 404)
            self.assertIn('not found', response.json()['detail'])

    def test_blueprint_requires_authentication(self) -> None:
        """
        Verify that blueprint endpoints reject unauthenticated requests.

        Sends unauthenticated GET and POST requests to the blueprints
        endpoints and asserts each responds with HTTP 401. Restores the
        test's authentication dependency override after the checks to
        avoid affecting other tests.
        """
        from imbi.auth import permissions

        # Clear dependency overrides to test actual authentication
        self.test_app.dependency_overrides.clear()

        # Create a new client without auth override
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

        # Restore the override for other tests
        async def mock_get_current_user():
            """
            Provide the preconfigured authentication context for tests.

            Returns:
                The test's authentication context object used to
                    simulate an authenticated user.
            """
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )
