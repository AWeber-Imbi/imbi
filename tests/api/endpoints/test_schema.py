"""Tests for schema generation endpoints."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient

from imbi_api import app, models


class SchemaEndpointsTestCase(unittest.TestCase):
    """Test cases for schema generation endpoints."""

    def setUp(self) -> None:
        """
        Prepare the test fixture by creating a FastAPI app, an
        authenticated user context, and a TestClient.

        Sets the following attributes on self:
        - test_app: FastAPI application instance used by tests.
        - user: User model used for authentication.
        - auth_context: AuthContext returned by the overridden dependency.
        - client: TestClient bound to the test_app.

        Overrides the get_current_user dependency to return the auth
        context so tests run with authentication.
        """
        from imbi_api.auth import permissions

        self.test_app = app.create_app()

        # Create a regular user for authentication
        self.user = models.User(
            email='user@example.com',
            display_name='Test User',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        self.auth_context = permissions.AuthContext(
            user=self.user,
            session_id='test-session',
            auth_method='jwt',
            permissions={'schema:read'},
        )

        # Override the get_current_user dependency
        async def mock_get_current_user():
            """
            Provide the preconfigured authentication context for tests.

            Returns:
                The test's authentication context object used to simulate
                an authenticated user.
            """
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.client = testclient.TestClient(self.test_app)

    def test_get_model_schema_organization(self) -> None:
        """Test getting schema for Organization model type."""
        with mock.patch('imbi_api.blueprints.get_model') as mock_get_model:
            # Mock returns the base Organization model
            mock_get_model.return_value = models.Organization

            response = self.client.get('/schema/Organization')

            self.assertEqual(response.status_code, 200)
            schema = response.json()

            # Verify it's a valid JSON Schema
            self.assertEqual(schema.get('type'), 'object')
            self.assertIn('properties', schema)

            # Verify base Node fields are present
            properties = schema['properties']
            self.assertIn('name', properties)
            self.assertIn('slug', properties)
            self.assertIn('description', properties)

            # Verify get_model was called with Organization class
            mock_get_model.assert_called_once_with(models.Organization)

    def test_get_model_schema_project(self) -> None:
        """Test getting schema for Project model type."""
        with mock.patch('imbi_api.blueprints.get_model') as mock_get_model:
            # Mock returns the base Project model
            mock_get_model.return_value = models.Project

            response = self.client.get('/schema/Project')

            self.assertEqual(response.status_code, 200)
            schema = response.json()

            # Verify it's a valid JSON Schema
            self.assertEqual(schema.get('type'), 'object')
            self.assertIn('properties', schema)

            # Verify Project-specific fields are present
            properties = schema['properties']
            self.assertIn('links', properties)
            self.assertIn('urls', properties)
            self.assertIn('identifiers', properties)

            # Verify get_model was called with Project class
            mock_get_model.assert_called_once_with(models.Project)

    def test_get_model_schema_all_types(self) -> None:
        """Test getting schema for each supported model type."""
        model_types = [
            'Organization',
            'Team',
            'Environment',
            'ProjectType',
            'Project',
        ]

        for model_type in model_types:
            with (
                self.subTest(model_type=model_type),
                mock.patch('imbi_api.blueprints.get_model') as mock_get_model,
            ):
                # Mock returns the appropriate model class
                mock_get_model.return_value = models.MODEL_TYPES[model_type]

                response = self.client.get(f'/schema/{model_type}')

                self.assertEqual(response.status_code, 200)
                schema = response.json()
                self.assertEqual(schema.get('type'), 'object')
                self.assertIn('properties', schema)

    def test_get_model_schema_invalid_type(self) -> None:
        """Test getting schema with invalid model type returns 422."""
        response = self.client.get('/schema/InvalidType')

        # FastAPI path validation should reject invalid literals
        self.assertEqual(response.status_code, 422)

    def test_get_all_schemas(self) -> None:
        """Test getting schemas for all model types."""
        with mock.patch('imbi_api.blueprints.get_model') as mock_get_model:
            # Mock returns the appropriate model class for each call
            def mock_get_model_side_effect(model_class):
                return model_class

            mock_get_model.side_effect = mock_get_model_side_effect

            response = self.client.get('/schemata')

            self.assertEqual(response.status_code, 200)
            schemas = response.json()

            # Verify all model types are present
            expected_types = [
                'Organization',
                'Team',
                'Environment',
                'ProjectType',
                'Project',
            ]
            for model_type in expected_types:
                self.assertIn(model_type, schemas)
                schema = schemas[model_type]
                self.assertEqual(schema.get('type'), 'object')
                self.assertIn('properties', schema)

            # Verify get_model was called for each model type
            self.assertEqual(mock_get_model.call_count, len(expected_types))

    def test_get_all_schemas_returns_dict(self) -> None:
        """Test that /schemata returns a dict mapping types to schemas."""
        with mock.patch('imbi_api.blueprints.get_model') as mock_get_model:
            # Mock returns the appropriate model class for each call
            def mock_get_model_side_effect(model_class):
                return model_class

            mock_get_model.side_effect = mock_get_model_side_effect

            response = self.client.get('/schemata')

            self.assertEqual(response.status_code, 200)
            schemas = response.json()

            # Verify it's a dictionary
            self.assertIsInstance(schemas, dict)

            # Verify each value is a schema object
            for model_type, schema in schemas.items():
                self.assertIn(model_type, models.MODEL_TYPES)
                self.assertIsInstance(schema, dict)
                self.assertEqual(schema.get('type'), 'object')

    def test_authentication_required(self) -> None:
        """Test that schema endpoints require authentication."""
        # Create a new app without dependency overrides
        test_app = app.create_app()
        client = testclient.TestClient(test_app)

        # Try to access endpoint without authentication
        response = client.get('/schema/Organization')
        # Should return 401 or 403 depending on auth implementation
        self.assertIn(response.status_code, [401, 403])

        response = client.get('/schemata')
        self.assertIn(response.status_code, [401, 403])
