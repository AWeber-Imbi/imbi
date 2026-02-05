"""Tests for OpenAPI schema customization with blueprint models."""

import unittest
import unittest.mock

import imbi_common.models
import pydantic

from imbi_api import openapi


class GenerateBlueprintModelsTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for generate_blueprint_models function."""

    async def asyncSetUp(self) -> None:
        """Reset module state before each test."""
        openapi._blueprint_models = {}
        openapi._schema_cache = None

    async def test_generate_blueprint_models_no_blueprints(self) -> None:
        """Test that base models are returned when no blueprints exist."""
        with unittest.mock.patch(
            'imbi_common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:
            # Mock returns the base model for each type
            mock_get_model.side_effect = lambda m: m

            models = await openapi.generate_blueprint_models()

            self.assertEqual(len(models), len(imbi_common.models.MODEL_TYPES))
            for model_name in imbi_common.models.MODEL_TYPES:
                self.assertIn(model_name, models)
                self.assertEqual(
                    models[model_name],
                    imbi_common.models.MODEL_TYPES[model_name],
                )

    async def test_generate_blueprint_models_with_blueprints(self) -> None:
        """Test that enhanced models include blueprint fields."""
        with unittest.mock.patch(
            'imbi_common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:
            # Create an enhanced model with an extra field
            enhanced_org = pydantic.create_model(
                'Organization',
                __base__=imbi_common.models.Organization,
                custom_field=(str, 'default_value'),
            )

            def mock_side_effect(model_class: type) -> type:
                if model_class is imbi_common.models.Organization:
                    return enhanced_org
                return model_class

            mock_get_model.side_effect = mock_side_effect

            models = await openapi.generate_blueprint_models()

            # Verify Organization has the custom field
            self.assertIn('Organization', models)
            self.assertIn('custom_field', models['Organization'].model_fields)

            # Verify other models are base models
            self.assertEqual(
                models['Team'], imbi_common.models.MODEL_TYPES['Team']
            )

    async def test_generate_blueprint_models_handles_errors(self) -> None:
        """Test that errors are handled gracefully, falling back to base."""
        with unittest.mock.patch(
            'imbi_common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:

            def mock_side_effect(model_class: type) -> type:
                if model_class is imbi_common.models.Organization:
                    raise ValueError('Test error')
                return model_class

            mock_get_model.side_effect = mock_side_effect

            models = await openapi.generate_blueprint_models()

            # Organization should fall back to base model
            self.assertEqual(
                models['Organization'],
                imbi_common.models.MODEL_TYPES['Organization'],
            )
            # Other models should work normally
            self.assertEqual(
                models['Team'], imbi_common.models.MODEL_TYPES['Team']
            )


class RefreshBlueprintModelsTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for refresh_blueprint_models function."""

    async def asyncSetUp(self) -> None:
        """Reset module state before each test."""
        openapi._blueprint_models = {}
        openapi._schema_cache = None

    async def test_refresh_updates_cache(self) -> None:
        """Test that refresh updates the cached models."""
        with unittest.mock.patch(
            'imbi_common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:
            mock_get_model.side_effect = lambda m: m

            # Initially empty
            self.assertEqual(openapi._blueprint_models, {})

            # After refresh, should have models
            models = await openapi.refresh_blueprint_models()

            self.assertEqual(len(models), len(imbi_common.models.MODEL_TYPES))
            self.assertEqual(openapi._blueprint_models, models)

    async def test_refresh_clears_schema_cache(self) -> None:
        """Test that refresh clears the OpenAPI schema cache."""
        # Set up a fake schema cache
        openapi._schema_cache = {'fake': 'schema'}

        with unittest.mock.patch(
            'imbi_common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:
            mock_get_model.side_effect = lambda m: m

            await openapi.refresh_blueprint_models()

            # Schema cache should be cleared
            self.assertIsNone(openapi._schema_cache)


class CreateCustomOpenapiTestCase(unittest.TestCase):
    """Test cases for create_custom_openapi function."""

    def setUp(self) -> None:
        """Reset module state before each test."""
        openapi._blueprint_models = {}
        openapi._schema_cache = None

    def test_custom_openapi_includes_blueprint_schemas(self) -> None:
        """Test that OpenAPI schema includes blueprint-enhanced schemas."""
        import fastapi

        # Set up blueprint models
        enhanced_org = pydantic.create_model(
            'Organization',
            __base__=imbi_common.models.Organization,
            custom_field=(str, 'default_value'),
        )
        openapi._blueprint_models = {
            'Organization': enhanced_org,
            'Team': imbi_common.models.Team,
        }

        # Create a minimal FastAPI app
        app = fastapi.FastAPI(title='Test', version='1.0.0')

        @app.get('/organizations/')
        async def list_orgs() -> list[dict]:
            return []

        # Get the custom openapi function
        custom_openapi_fn = openapi.create_custom_openapi(app)
        schema = custom_openapi_fn()

        # Verify blueprint schemas are in components
        self.assertIn('components', schema)
        self.assertIn('schemas', schema['components'])
        self.assertIn(
            'OrganizationWithBlueprints', schema['components']['schemas']
        )
        self.assertIn('TeamWithBlueprints', schema['components']['schemas'])

        # Verify OrganizationWithBlueprints has custom_field
        org_schema = schema['components']['schemas'][
            'OrganizationWithBlueprints'
        ]
        self.assertIn('properties', org_schema)
        self.assertIn('custom_field', org_schema['properties'])

    def test_custom_openapi_caches_result(self) -> None:
        """Test that the schema is cached after first generation."""
        import fastapi

        openapi._blueprint_models = {}

        app = fastapi.FastAPI(title='Test', version='1.0.0')
        custom_openapi_fn = openapi.create_custom_openapi(app)

        # First call generates schema
        schema1 = custom_openapi_fn()

        # Second call should return cached schema
        schema2 = custom_openapi_fn()

        self.assertIs(schema1, schema2)

    def test_path_schema_rewriting_for_list_endpoints(self) -> None:
        """Test that list endpoints get array schemas."""
        import fastapi

        openapi._blueprint_models = {
            'Organization': imbi_common.models.Organization,
        }

        app = fastapi.FastAPI(title='Test', version='1.0.0')

        @app.get('/organizations/')
        async def list_orgs() -> list[dict]:
            return []

        custom_openapi_fn = openapi.create_custom_openapi(app)
        schema = custom_openapi_fn()

        # Check that GET /organizations/ has array response
        paths = schema.get('paths', {})
        self.assertIn('/organizations/', paths)
        get_op = paths['/organizations/'].get('get', {})
        responses = get_op.get('responses', {})
        self.assertIn('200', responses)
        content = responses['200'].get('content', {})
        json_schema = content.get('application/json', {}).get('schema', {})
        self.assertEqual(json_schema.get('type'), 'array')
        self.assertIn('items', json_schema)


class ClearSchemaCacheTestCase(unittest.TestCase):
    """Test cases for clear_schema_cache function."""

    def setUp(self) -> None:
        """Reset module state before each test."""
        openapi._schema_cache = None

    def test_clear_schema_cache(self) -> None:
        """Test that clear_schema_cache clears the cache."""
        openapi._schema_cache = {'some': 'schema'}

        openapi.clear_schema_cache()

        self.assertIsNone(openapi._schema_cache)
