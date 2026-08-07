"""Tests for OpenAPI schema customization with blueprint models."""

import typing
import unittest
import unittest.mock

import fastapi
import pydantic

import imbi.common.blueprints
import imbi.common.models
from imbi.api import models as imbi_models
from imbi.api import openapi
from imbi.api.auth import permissions
from imbi.api.endpoints import graph_query
from imbi.common import graph


def _reset_openapi_module_state() -> None:
    """Wipe the openapi module's caches and singleton blueprint registries."""
    openapi._blueprint_models = {}
    openapi._response_models = {}
    openapi._edge_models = {}
    openapi._schema_cache = None


class GenerateBlueprintModelsTestCase(
    unittest.IsolatedAsyncioTestCase,
):
    """Test cases for generate_blueprint_models function."""

    async def asyncSetUp(self) -> None:
        """Reset module state before each test."""
        _reset_openapi_module_state()
        self.mock_db = unittest.mock.AsyncMock(spec=graph.Graph)
        self.mock_db.match.return_value = []

    async def asyncTearDown(self) -> None:
        """Restore module state so leakage cannot bleed across test files."""
        _reset_openapi_module_state()

    async def test_generate_blueprint_models_no_blueprints(
        self,
    ) -> None:
        """Test base models returned when no blueprints exist."""
        with unittest.mock.patch(
            'imbi.common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:
            mock_get_model.side_effect = lambda _db, m: m

            (
                write_models,
                response_models,
                _edge_models,
            ) = await openapi.generate_blueprint_models(self.mock_db)

            self.assertEqual(
                len(write_models),
                len(imbi_models.MODEL_TYPES),
            )
            self.assertEqual(
                len(response_models),
                len(imbi_models.MODEL_TYPES),
            )
            for model_name in imbi_models.MODEL_TYPES:
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
            'imbi.common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:
            enhanced_team = pydantic.create_model(
                'Team',
                __base__=imbi.common.models.Team,
                custom_field=(str, 'default_value'),
            )

            def mock_side_effect(_db: graph.Graph, model_class: type) -> type:
                if model_class is imbi.common.models.Team:
                    return enhanced_team
                return model_class

            mock_get_model.side_effect = mock_side_effect

            (
                write_models,
                response_models,
                _edge_models,
            ) = await openapi.generate_blueprint_models(self.mock_db)

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
            'imbi.common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:

            def mock_side_effect(_db: graph.Graph, model_class: type) -> type:
                if model_class is imbi.common.models.Team:
                    raise ValueError('Test error')
                return model_class

            mock_get_model.side_effect = mock_side_effect

            (
                write_models,
                response_models,
                _edge_models,
            ) = await openapi.generate_blueprint_models(self.mock_db)

            # Falls back to base model
            self.assertEqual(
                write_models['Team'],
                imbi_models.MODEL_TYPES['Team'],
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
        _reset_openapi_module_state()
        self.mock_db = unittest.mock.AsyncMock(spec=graph.Graph)
        self.mock_db.match.return_value = []

    async def asyncTearDown(self) -> None:
        _reset_openapi_module_state()

    async def test_refresh_updates_cache(self) -> None:
        """Test that refresh updates the cached models."""
        with unittest.mock.patch(
            'imbi.common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:
            mock_get_model.side_effect = lambda _db, m: m

            self.assertEqual(
                openapi._blueprint_models,
                {},
            )

            result = await openapi.refresh_blueprint_models(self.mock_db)

            self.assertEqual(
                len(result),
                len(imbi_models.MODEL_TYPES),
            )
            self.assertEqual(
                openapi._blueprint_models,
                result,
            )
            # Response models also populated
            self.assertEqual(
                len(openapi._response_models),
                len(imbi_models.MODEL_TYPES),
            )

    async def test_refresh_clears_schema_cache(self) -> None:
        """Test that refresh clears the OpenAPI schema cache."""
        openapi._schema_cache = {'fake': 'schema'}

        with unittest.mock.patch(
            'imbi.common.blueprints.get_model',
            new_callable=unittest.mock.AsyncMock,
        ) as mock_get_model:
            mock_get_model.side_effect = lambda _db, m: m

            await openapi.refresh_blueprint_models(self.mock_db)

            self.assertIsNone(openapi._schema_cache)


class CreateCustomOpenapiTestCase(unittest.TestCase):
    """Test cases for create_custom_openapi function."""

    def setUp(self) -> None:
        """Reset module state before each test."""
        _reset_openapi_module_state()

    def tearDown(self) -> None:
        _reset_openapi_module_state()

    def test_custom_openapi_includes_schemas(self) -> None:
        """Test OpenAPI schema includes request and response."""
        import fastapi

        enhanced_team = pydantic.create_model(
            'Team',
            __base__=imbi.common.models.Team,
            custom_field=(str, 'default_value'),
        )
        openapi._blueprint_models = {
            'Team': enhanced_team,
            'Project': imbi.common.models.Project,
        }
        openapi._response_models = {
            'Team': imbi.common.blueprints.make_response_model(
                enhanced_team,
            ),
            'Project': (
                imbi.common.blueprints.make_response_model(
                    imbi.common.models.Project,
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
        self.assertIn('TeamBlueprintRequest', schemas)
        self.assertIn(
            'custom_field',
            schemas['TeamBlueprintRequest']['properties'],
        )

        # Response schemas
        self.assertIn('TeamBlueprintResponse', schemas)
        self.assertIn(
            'custom_field',
            schemas['TeamBlueprintResponse']['properties'],
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

    def test_concurrent_cold_calls_build_once(self) -> None:
        """H16: two threads hitting a cold cache must build only once."""
        import threading

        openapi._blueprint_models = {}
        openapi._schema_cache = None

        app = fastapi.FastAPI(title='Test', version='1.0.0')
        custom_openapi_fn = openapi.create_custom_openapi(app)

        build_count = 0
        original_build = openapi._build_schema

        def counting_build(
            a: fastapi.FastAPI,
        ) -> tuple[dict, bool]:
            nonlocal build_count
            build_count += 1
            return original_build(a)

        results: list[dict] = []
        barrier = threading.Barrier(4)

        def worker() -> None:
            barrier.wait()
            results.append(custom_openapi_fn())

        with unittest.mock.patch.object(
            openapi, '_build_schema', side_effect=counting_build
        ):
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(build_count, 1)
        self.assertEqual(len(results), 4)
        # All callers observe the same cached schema instance.
        for r in results[1:]:
            self.assertIs(r, results[0])

    def test_partial_failure_does_not_pin_cache(self) -> None:
        """L14: a per-model failure must not pin a broken schema."""
        broken = unittest.mock.MagicMock(spec=pydantic.BaseModel)
        broken.model_json_schema.side_effect = ValueError('boom-for-test')
        # Stuff the registry with a broken write model so generation
        # raises on the first ``model_json_schema`` call.
        openapi._blueprint_models = {'Team': broken}
        openapi._response_models = {'Team': broken}
        openapi._edge_models = {}

        app = fastapi.FastAPI(title='Test', version='1.0.0')
        custom_openapi_fn = openapi.create_custom_openapi(app)

        schema = custom_openapi_fn()
        # Schema still returned (best-effort) so /openapi.json keeps
        # working for the unaffected paths...
        self.assertIsInstance(schema, dict)
        # ...but the cache stays empty so the next request retries.
        self.assertIsNone(openapi._schema_cache)

    def test_path_schema_rewriting(self) -> None:
        """Test list endpoints get array response schemas."""
        import fastapi

        openapi._blueprint_models = {
            'Team': imbi.common.models.Team,
        }
        openapi._response_models = {
            'Team': imbi.common.blueprints.make_response_model(
                imbi.common.models.Team,
            ),
        }

        app = fastapi.FastAPI(title='Test', version='1.0.0')

        # Must be a path in PATH_MODEL_MAPPING, or the rewriter skips it
        # and the assertions below only see FastAPI's own output.
        mapped = '/organizations/{org_slug}/teams/'

        @app.get(mapped)
        async def list_teams(  # pyright: ignore[reportUnusedFunction]
            org_slug: str,
        ) -> list[dict]:
            return []

        custom_openapi_fn = openapi.create_custom_openapi(app)
        schema = custom_openapi_fn()

        paths = schema.get('paths', {})
        self.assertIn(mapped, paths)
        get_op = paths[mapped].get('get', {})
        responses = get_op.get('responses', {})
        self.assertIn('200', responses)
        content = responses['200'].get('content', {})
        json_schema = content.get(
            'application/json',
            {},
        ).get('schema', {})
        self.assertEqual(json_schema.get('type'), 'array')
        self.assertIn('items', json_schema)
        # The rewritten $ref must name the blueprint schema that was
        # actually written, not the endpoint-derived `TeamResponse`.
        self.assertEqual(
            json_schema['items'].get('$ref'),
            '#/components/schemas/TeamBlueprintResponse',
        )


class BlueprintSchemaNamespaceTestCase(unittest.TestCase):
    """Blueprint schemas must not displace endpoint-derived ones.

    ``make_response_model`` names its output after the graph node, and
    several nodes share a name with a distinct endpoint response model.
    Writing those unnamespaced replaced the schema FastAPI derived from
    the endpoint, so ``IntegrationResponse`` and ``ProjectResponse`` were
    published describing a shape no endpoint returns.
    """

    def setUp(self) -> None:
        _reset_openapi_module_state()

    def tearDown(self) -> None:
        _reset_openapi_module_state()

    def test_blueprint_names_are_namespaced(self) -> None:
        self.assertEqual(
            'ProjectBlueprintResponse',
            openapi.blueprint_schema_name('Project', 'Response'),
        )
        self.assertEqual(
            'ProjectBlueprintRequest',
            openapi.blueprint_schema_name('Project', 'Request'),
        )

    def test_endpoint_schema_survives_a_same_named_node(self) -> None:
        """A node named like an endpoint model no longer clobbers it."""
        import fastapi

        openapi._blueprint_models = {
            'Project': imbi.common.models.Project,
        }
        openapi._response_models = {
            'Project': imbi.common.blueprints.make_response_model(
                imbi.common.models.Project,
            ),
        }

        class ProjectResponse(pydantic.BaseModel):
            """Stands in for an endpoint's own response model."""

            only_the_endpoint_has_this: str

        app = fastapi.FastAPI(title='Test', version='1.0.0')

        @app.get('/projects/')
        async def list_projects() -> (  # pyright: ignore[reportUnusedFunction]
            ProjectResponse
        ):
            return ProjectResponse(only_the_endpoint_has_this='x')

        schema = openapi.create_custom_openapi(app)()
        schemas = schema['components']['schemas']

        self.assertIn(
            'only_the_endpoint_has_this',
            schemas['ProjectResponse']['properties'],
        )
        self.assertIn('ProjectBlueprintResponse', schemas)
        self.assertNotIn(
            'only_the_endpoint_has_this',
            schemas['ProjectBlueprintResponse']['properties'],
        )

    def test_collision_is_refused_and_logged(self) -> None:
        """A converged namespace keeps the existing schema and logs."""
        schemas: dict[str, typing.Any] = {'TeamBlueprintResponse': {'x': 1}}
        with self.assertLogs(openapi.LOGGER, level='ERROR') as captured:
            allowed = openapi._claim_schema_name(
                schemas, 'TeamBlueprintResponse', 'Team'
            )
        self.assertFalse(allowed)
        self.assertIn('refusing to overwrite', captured.output[0])
        self.assertEqual({'x': 1}, schemas['TeamBlueprintResponse'])

    def test_free_name_is_claimable(self) -> None:
        self.assertTrue(
            openapi._claim_schema_name({}, 'TeamBlueprint', 'Team')
        )

    def test_refused_name_is_not_referenced_by_a_path(self) -> None:
        """A refused schema must not be pointed at by an operation.

        Refusing the write keeps the endpoint-derived component, so
        rewriting an operation to that name would resolve the ``$ref``
        to a shape the blueprint pass never produced. The build is a
        failure too, so the document must not be cached.
        """
        openapi._blueprint_models = {'Team': imbi.common.models.Team}
        openapi._response_models = {
            'Team': imbi.common.blueprints.make_response_model(
                imbi.common.models.Team,
            ),
        }

        class TeamBlueprintRequest(pydantic.BaseModel):
            """Occupies the name the blueprint write schema wants."""

            only_the_endpoint_has_this: str

        class TeamCreate(pydantic.BaseModel):
            """The body the mapped path actually accepts."""

            name: str

        app = fastapi.FastAPI(title='Test', version='1.0.0')
        mapped = '/organizations/{org_slug}/teams/'

        # An unmapped path is enough to make FastAPI publish the
        # colliding component before the blueprint pass runs.
        @app.post('/decoys/')
        async def create_decoy(  # pyright: ignore[reportUnusedFunction]
            body: TeamBlueprintRequest,
        ) -> dict:
            return {}

        @app.post(mapped)
        async def create_team(  # pyright: ignore[reportUnusedFunction]
            org_slug: str,
            body: TeamCreate,
        ) -> dict:
            return {}

        with self.assertLogs(openapi.LOGGER, level='ERROR') as captured:
            schema = openapi.create_custom_openapi(app)()

        self.assertIn('refusing to overwrite', captured.output[0])

        # The decoy keeps the component it was published under.
        schemas = schema['components']['schemas']
        self.assertIn(
            'only_the_endpoint_has_this',
            schemas['TeamBlueprintRequest']['properties'],
        )
        # The mapped operation is left alone rather than pointed at a
        # name the blueprint pass did not write.
        body_schema = schema['paths'][mapped]['post']['requestBody'][
            'content'
        ]['application/json']['schema']
        self.assertEqual(
            '#/components/schemas/TeamCreate',
            body_schema.get('$ref'),
        )
        # A refused name is a build failure, so nothing is cached.
        self.assertIsNone(openapi._schema_cache)


class MarkAiExcludedOperationsTestCase(unittest.TestCase):
    """Test cases for _mark_ai_excluded_operations."""

    def setUp(self) -> None:
        """Reset module state before each test."""
        _reset_openapi_module_state()

    def tearDown(self) -> None:
        _reset_openapi_module_state()

    def test_stamps_flag_on_excluded_tag(self) -> None:
        """Operations carrying an excluded tag get x-imbi-ai-tool."""
        excluded = next(iter(openapi.AI_TOOL_EXCLUDED_TAGS))
        schema = {
            'paths': {
                '/secret': {
                    'get': {'tags': [excluded]},
                    'delete': {'tags': [excluded]},
                },
                '/public': {'get': {'tags': ['Teams']}},
            }
        }

        openapi._mark_ai_excluded_operations(schema)

        secret = schema['paths']['/secret']
        self.assertIs(secret['get']['x-imbi-ai-tool'], False)
        self.assertIs(secret['delete']['x-imbi-ai-tool'], False)
        self.assertNotIn('x-imbi-ai-tool', schema['paths']['/public']['get'])

    def test_ignores_non_operation_values(self) -> None:
        """Path-item parameters and untagged ops are left untouched."""
        schema = {
            'paths': {
                '/items': {
                    'parameters': [{'name': 'id', 'in': 'query'}],
                    'get': {'tags': ['Items']},
                }
            }
        }

        openapi._mark_ai_excluded_operations(schema)

        self.assertNotIn('x-imbi-ai-tool', schema['paths']['/items']['get'])

    def test_excluded_tag_marks_endpoint_in_full_schema(self) -> None:
        """End-to-end: a tagged route is flagged in the built schema."""
        openapi._blueprint_models = {}
        excluded = next(iter(openapi.AI_TOOL_EXCLUDED_TAGS))

        app = fastapi.FastAPI(title='Test', version='1.0.0')

        @app.get('/configuration/', tags=[excluded])
        async def get_configuration() -> dict:
            return {}

        @app.get('/teams/', tags=['Teams'])
        async def list_teams() -> list[dict]:
            return []

        schema = openapi.create_custom_openapi(app)()

        self.assertIs(
            schema['paths']['/configuration/']['get']['x-imbi-ai-tool'],
            False,
        )
        self.assertNotIn('x-imbi-ai-tool', schema['paths']['/teams/']['get'])


class MarkRequiredPermissionsTestCase(unittest.TestCase):
    """Test cases for _mark_required_permissions."""

    def setUp(self) -> None:
        """Reset module state and build a fresh app for each test."""
        _reset_openapi_module_state()
        self.app = fastapi.FastAPI(title='Test', version='1.0.0')

    def tearDown(self) -> None:
        _reset_openapi_module_state()

    def test_stamps_operation_level_permission(self) -> None:
        """A route's require_permission dependency reaches the schema."""

        @self.app.get('/projects/')
        async def list_projects(
            _auth: typing.Annotated[
                permissions.AuthContext,
                fastapi.Depends(
                    permissions.require_permission('project:read')
                ),
            ],
        ) -> list[dict]:
            return []

        schema = openapi.create_custom_openapi(self.app)()

        self.assertEqual(
            ['project:read'],
            schema['paths']['/projects/']['get']['x-imbi-permission'],
        )

    def test_stamps_router_level_permission(self) -> None:
        """A permission declared on the router is found via nesting."""
        router = fastapi.APIRouter(
            dependencies=[
                fastapi.Depends(
                    permissions.require_permission('blueprint:write')
                )
            ]
        )

        @router.post('/blueprints/')
        async def create_blueprint() -> dict:
            return {}

        self.app.include_router(router)

        schema = openapi.create_custom_openapi(self.app)()

        self.assertEqual(
            ['blueprint:write'],
            schema['paths']['/blueprints/']['post']['x-imbi-permission'],
        )

    def test_stamps_route_with_path_converter(self) -> None:
        """A converter-typed path is still matched and stamped.

        FastAPI publishes ``/refs/{ref:path}`` as ``/refs/{ref}``, so
        matching on ``route.path`` rather than ``route.path_format``
        would skip the route and leave it looking unguarded.
        """

        @self.app.get('/refs/{ref:path}/commits')
        async def list_commits(
            ref: str,
            _auth: typing.Annotated[
                permissions.AuthContext,
                fastapi.Depends(
                    permissions.require_permission('project:deployment:read')
                ),
            ],
        ) -> list[dict]:
            return []

        schema = openapi.create_custom_openapi(self.app)()

        self.assertEqual(
            ['project:deployment:read'],
            schema['paths']['/refs/{ref}/commits']['get']['x-imbi-permission'],
        )

    def test_unguarded_operation_not_stamped(self) -> None:
        """A route with no permission dependency is left alone."""

        @self.app.get('/health')
        async def health() -> dict:
            return {}

        schema = openapi.create_custom_openapi(self.app)()

        self.assertNotIn(
            'x-imbi-permission', schema['paths']['/health']['get']
        )

    def test_admin_dependency_stamps_sentinel(self) -> None:
        """require_admin is reported as the ``admin`` sentinel."""

        @self.app.post('/graph/query')
        async def query(
            _auth: typing.Annotated[
                permissions.AuthContext,
                fastapi.Depends(graph_query.require_admin),
            ],
        ) -> dict:
            return {}

        schema = openapi.create_custom_openapi(self.app)()

        self.assertEqual(
            ['admin'],
            schema['paths']['/graph/query']['post']['x-imbi-permission'],
        )


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
        resp_model = imbi.common.blueprints.make_response_model(
            imbi.common.models.ProjectType,
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
        _reset_openapi_module_state()

    def tearDown(self) -> None:
        _reset_openapi_module_state()

    def test_clear_schema_cache(self) -> None:
        """Test that clear_schema_cache clears the cache."""
        openapi._schema_cache = {'some': 'schema'}

        openapi.clear_schema_cache()

        self.assertIsNone(openapi._schema_cache)


class StoplightsHtmlTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for stoplights_html."""

    async def test_injects_title_and_root_path(self) -> None:
        """Test templated title and root path are injected."""
        app = fastapi.FastAPI(
            title='Imbi API Docs',
            version='1.0.0',
            root_path='/imbi',
        )
        request = fastapi.Request(
            {
                'type': 'http',
                'app': app,
                'root_path': '/imbi/',
                'path': '/docs',
                'headers': [],
            }
        )

        response = await openapi.stoplights_html(request)
        content = response.body.decode()

        self.assertIn('<title>Imbi API Docs</title>', content)
        self.assertIn(
            'apiDescriptionUrl="/imbi/openapi.json"',
            content,
        )
