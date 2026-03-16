"""Tests for OpenAPI schema customization with blueprint models."""

import unittest
import unittest.mock

import imbi_common.blueprints
import imbi_common.models
import pydantic

from imbi_api import openapi


class GenerateBlueprintModelsTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for generate_blueprint_models function."""

    async def asyncSetUp(self) -> None:
        """Reset module state before each test."""
        openapi._blueprint_models = {}
        openapi._response_models = {}
        openapi._schema_cache = None

    async def test_generate_blueprint_models_no_blueprints(
        self,
    ) -> None:
        """Test base models returned when no blueprints exist."""
        with unittest.mock.patch(
            'imbi_common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:
            mock_get_model.side_effect = lambda m: m

            (
                write_models,
                response_models,
            ) = await openapi.generate_blueprint_models()

            self.assertEqual(
                len(write_models),
                len(imbi_common.models.MODEL_TYPES),
            )
            self.assertEqual(
                len(response_models),
                len(imbi_common.models.MODEL_TYPES),
            )
            for model_name in imbi_common.models.MODEL_TYPES:
                self.assertIn(model_name, write_models)
                self.assertIn(model_name, response_models)
                # Response model should have relationships
                self.assertIn(
                    'relationships',
                    response_models[model_name].model_fields,
                )

    async def test_generate_blueprint_models_with_blueprints(
        self,
    ) -> None:
        """Test enhanced models include blueprint fields."""
        with unittest.mock.patch(
            'imbi_common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:
            enhanced_team = pydantic.create_model(
                'Team',
                __base__=imbi_common.models.Team,
                custom_field=(str, 'default_value'),
            )

            def mock_side_effect(model_class: type) -> type:
                if model_class is imbi_common.models.Team:
                    return enhanced_team
                return model_class

            mock_get_model.side_effect = mock_side_effect

            (
                write_models,
                response_models,
            ) = await openapi.generate_blueprint_models()

            # Write model has custom_field
            self.assertIn('Team', write_models)
            self.assertIn(
                'custom_field',
                write_models['Team'].model_fields,
            )

            # Response model has both custom_field and
            # relationships
            self.assertIn('Team', response_models)
            self.assertIn(
                'custom_field',
                response_models['Team'].model_fields,
            )
            self.assertIn(
                'relationships',
                response_models['Team'].model_fields,
            )

    async def test_generate_blueprint_models_handles_errors(
        self,
    ) -> None:
        """Test errors are handled, falling back to base."""
        with unittest.mock.patch(
            'imbi_common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:

            def mock_side_effect(model_class: type) -> type:
                if model_class is imbi_common.models.Team:
                    raise ValueError('Test error')
                return model_class

            mock_get_model.side_effect = mock_side_effect

            (
                write_models,
                response_models,
            ) = await openapi.generate_blueprint_models()

            # Falls back to base model
            self.assertEqual(
                write_models['Team'],
                imbi_common.models.MODEL_TYPES['Team'],
            )
            # Response model still created
            self.assertIn(
                'relationships',
                response_models['Team'].model_fields,
            )


class RefreshBlueprintModelsTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for refresh_blueprint_models function."""

    async def asyncSetUp(self) -> None:
        """Reset module state before each test."""
        openapi._blueprint_models = {}
        openapi._response_models = {}
        openapi._schema_cache = None

    async def test_refresh_updates_cache(self) -> None:
        """Test that refresh updates the cached models."""
        with unittest.mock.patch(
            'imbi_common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:
            mock_get_model.side_effect = lambda m: m

            self.assertEqual(
                openapi._blueprint_models,
                {},
            )

            models = await openapi.refresh_blueprint_models()

            self.assertEqual(
                len(models),
                len(imbi_common.models.MODEL_TYPES),
            )
            self.assertEqual(
                openapi._blueprint_models,
                models,
            )
            # Response models also populated
            self.assertEqual(
                len(openapi._response_models),
                len(imbi_common.models.MODEL_TYPES),
            )

    async def test_refresh_clears_schema_cache(self) -> None:
        """Test that refresh clears the OpenAPI schema cache."""
        openapi._schema_cache = {'fake': 'schema'}

        with unittest.mock.patch(
            'imbi_common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:
            mock_get_model.side_effect = lambda m: m

            await openapi.refresh_blueprint_models()

            self.assertIsNone(openapi._schema_cache)


class CreateCustomOpenapiTestCase(unittest.TestCase):
    """Test cases for create_custom_openapi function."""

    def setUp(self) -> None:
        """Reset module state before each test."""
        openapi._blueprint_models = {}
        openapi._response_models = {}
        openapi._schema_cache = None

    def test_custom_openapi_includes_schemas(self) -> None:
        """Test OpenAPI schema includes request and response."""
        import fastapi

        enhanced_team = pydantic.create_model(
            'Team',
            __base__=imbi_common.models.Team,
            custom_field=(str, 'default_value'),
        )
        openapi._blueprint_models = {
            'Team': enhanced_team,
            'Project': imbi_common.models.Project,
        }
        openapi._response_models = {
            'Team': imbi_common.blueprints.make_response_model(
                enhanced_team,
            ),
            'Project': (
                imbi_common.blueprints.make_response_model(
                    imbi_common.models.Project,
                )
            ),
        }

        app = fastapi.FastAPI(title='Test', version='1.0.0')

        @app.get('/teams/')
        async def list_teams() -> list[dict]:
            return []

        custom_openapi_fn = openapi.create_custom_openapi(app)
        schema = custom_openapi_fn()

        self.assertIn('components', schema)
        schemas = schema['components']['schemas']

        # Request schemas
        self.assertIn('TeamRequest', schemas)
        self.assertIn(
            'custom_field',
            schemas['TeamRequest']['properties'],
        )

        # Response schemas
        self.assertIn('TeamResponse', schemas)
        self.assertIn(
            'custom_field',
            schemas['TeamResponse']['properties'],
        )

    def test_custom_openapi_caches_result(self) -> None:
        """Test that the schema is cached."""
        import fastapi

        openapi._blueprint_models = {}

        app = fastapi.FastAPI(title='Test', version='1.0.0')
        custom_openapi_fn = openapi.create_custom_openapi(app)

        schema1 = custom_openapi_fn()
        schema2 = custom_openapi_fn()

        self.assertIs(schema1, schema2)

    def test_path_schema_rewriting(self) -> None:
        """Test list endpoints get array response schemas."""
        import fastapi

        openapi._blueprint_models = {
            'Team': imbi_common.models.Team,
        }
        openapi._response_models = {
            'Team': imbi_common.blueprints.make_response_model(
                imbi_common.models.Team,
            ),
        }

        app = fastapi.FastAPI(title='Test', version='1.0.0')

        @app.get('/teams/')
        async def list_teams() -> list[dict]:
            return []

        custom_openapi_fn = openapi.create_custom_openapi(app)
        schema = custom_openapi_fn()

        paths = schema.get('paths', {})
        self.assertIn('/teams/', paths)
        get_op = paths['/teams/'].get('get', {})
        responses = get_op.get('responses', {})
        self.assertIn('200', responses)
        content = responses['200'].get('content', {})
        json_schema = content.get(
            'application/json',
            {},
        ).get('schema', {})
        self.assertEqual(json_schema.get('type'), 'array')
        self.assertIn('items', json_schema)


class HoistDefsToComponentsTestCase(unittest.TestCase):
    """Test cases for _hoist_defs_to_components."""

    def test_hoists_defs_to_top_level(self) -> None:
        """Test that $defs are moved to component schemas."""
        schemas: dict = {
            'ProjectTypeResponse': {
                'properties': {
                    'relationships': {
                        'additionalProperties': {
                            '$ref': ('#/components/schemas/RelationshipLink'),
                        },
                    },
                },
                '$defs': {
                    'Organization': {'type': 'object'},
                    'RelationshipLink': {'type': 'object'},
                },
            },
        }
        openapi._hoist_defs_to_components(schemas)

        self.assertIn('Organization', schemas)
        self.assertIn('RelationshipLink', schemas)
        self.assertNotIn(
            '$defs',
            schemas['ProjectTypeResponse'],
        )

    def test_does_not_overwrite_existing(self) -> None:
        """Test that existing schemas are not overwritten."""
        schemas: dict = {
            'Organization': {'type': 'object', 'existing': True},
            'MyResponse': {
                '$defs': {
                    'Organization': {
                        'type': 'object',
                        'existing': False,
                    },
                },
            },
        }
        openapi._hoist_defs_to_components(schemas)

        self.assertTrue(schemas['Organization']['existing'])

    def test_response_schemas_have_no_embedded_defs(
        self,
    ) -> None:
        """Test generated response schemas have $defs hoisted."""
        resp_model = imbi_common.blueprints.make_response_model(
            imbi_common.models.ProjectType,
        )
        schema = resp_model.model_json_schema(
            ref_template='#/components/schemas/{model}',
        )
        schemas = {'ProjectTypeResponse': schema}
        openapi._hoist_defs_to_components(schemas)

        self.assertNotIn(
            '$defs',
            schemas['ProjectTypeResponse'],
        )
        self.assertIn('RelationshipLink', schemas)
        self.assertIn('Organization', schemas)


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
