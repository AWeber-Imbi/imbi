import datetime
import typing
import unittest
from unittest import mock

import pydantic
from neo4j import exceptions

from imbi_common import blueprints, models, neo4j


class GetModelTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for blueprints.get_model function."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.org = models.Organization(name='Org', slug='org')
        # Mock neo4j.fetch_nodes to return test blueprints
        self.fetch_nodes_patcher = mock.patch('imbi_common.neo4j.fetch_nodes')
        self.mock_fetch_nodes = self.fetch_nodes_patcher.start()
        self.addCleanup(self.fetch_nodes_patcher.stop)

    def _make_blueprint(
        self,
        *,
        properties: dict[str, typing.Any],
        required: list[str] | None = None,
        name: str = 'test',
        priority: int = 0,
    ) -> models.Blueprint:
        schema: dict[str, typing.Any] = {
            'type': 'object',
            'properties': properties,
        }
        if required:
            schema['required'] = required
        return models.Blueprint(
            name=name,
            type='Environment',
            priority=priority,
            json_schema=models.Schema.model_validate(schema),
        )

    def _set_blueprints(self, *bps: models.Blueprint) -> None:
        async def iterator():
            for bp in bps:
                yield bp

        self.mock_fetch_nodes.return_value = iterator()

    async def test_model_is_subclass_of_input(self) -> None:
        """Verify the returned model is a true subclass, not just cast."""
        self._set_blueprints(
            self._make_blueprint(
                properties={'domain': {'type': 'string'}},
            )
        )

        result_model = await blueprints.get_model(models.Environment)

        self.assertTrue(issubclass(result_model, models.Environment))

    async def test_get_model_no_blueprints(self) -> None:
        """Test get_model with no blueprints returns base model."""
        self._set_blueprints()

        result_model = await blueprints.get_model(models.Environment)

        # Should have same name and base fields
        self.assertEqual(result_model.__name__, 'Environment')
        self.assertIn('name', result_model.model_fields)
        self.assertIn('slug', result_model.model_fields)
        self.assertIn('description', result_model.model_fields)

    async def test_get_model_with_string_fields(self) -> None:
        """Test get_model with basic string fields from blueprints."""
        self._set_blueprints(
            self._make_blueprint(
                properties={
                    'domain': {
                        'type': 'string',
                        'description': 'Base domain',
                    },
                    'region': {'type': 'string'},
                },
                required=['domain'],
            )
        )

        result_model = await blueprints.get_model(models.Environment)

        # Check base fields exist
        self.assertIn('name', result_model.model_fields)
        self.assertIn('slug', result_model.model_fields)

        # Check blueprint fields
        self.assertIn('domain', result_model.model_fields)
        self.assertIn('region', result_model.model_fields)

        # Test instantiation with required field
        instance = result_model(
            name='Test Env',
            slug='test-env',
            domain='example.com',
            organization=self.org,
        )
        self.assertEqual(instance.domain, 'example.com')
        self.assertIsNone(instance.region)  # Optional field

        # Test that missing required field raises error
        with self.assertRaises(pydantic.ValidationError):
            result_model(
                name='Test', slug='test', organization=self.org
            )  # Missing domain

    async def test_get_model_with_integer_and_number_fields(self) -> None:
        """Test get_model with integer and number fields."""
        self._set_blueprints(
            self._make_blueprint(
                properties={
                    'max_instances': {'type': 'integer'},
                    'cpu_threshold': {'type': 'number'},
                },
                required=['max_instances'],
            )
        )

        result_model = await blueprints.get_model(models.Environment)

        # Create instance and verify types
        instance = result_model(
            name='Test',
            slug='test',
            max_instances=10,
            cpu_threshold=0.75,
            organization=self.org,
        )
        self.assertEqual(instance.max_instances, 10)
        self.assertEqual(instance.cpu_threshold, 0.75)

        # Test type validation
        with self.assertRaises(pydantic.ValidationError):
            result_model(
                name='Test',
                slug='test',
                max_instances='not-an-int',
                organization=self.org,
            )

    async def test_get_model_with_boolean_field(self) -> None:
        """Test get_model with boolean field."""
        self._set_blueprints(
            self._make_blueprint(
                properties={'is_production': {'type': 'boolean'}}
            )
        )

        result_model = await blueprints.get_model(models.Environment)

        instance = result_model(
            name='Test',
            slug='test',
            is_production=True,
            organization=self.org,
        )
        self.assertTrue(instance.is_production)

    async def test_get_model_with_array_fields(self) -> None:
        """Test get_model with array fields."""
        self._set_blueprints(
            self._make_blueprint(
                properties={
                    'tags': {'type': 'array', 'items': {'type': 'string'}},
                    'ports': {'type': 'array', 'items': {'type': 'integer'}},
                    'generic_list': {'type': 'array'},
                }
            )
        )

        result_model = await blueprints.get_model(models.Environment)

        instance = result_model(
            name='Test',
            slug='test',
            tags=['prod', 'web'],
            ports=[80, 443],
            generic_list=[1, 'two', True],
            organization=self.org,
        )
        self.assertEqual(instance.tags, ['prod', 'web'])
        self.assertEqual(instance.ports, [80, 443])
        self.assertEqual(instance.generic_list, [1, 'two', True])

    async def test_get_model_with_object_field(self) -> None:
        """Test get_model with object field."""
        self._set_blueprints(
            self._make_blueprint(properties={'metadata': {'type': 'object'}})
        )

        result_model = await blueprints.get_model(models.Environment)

        instance = result_model(
            name='Test',
            slug='test',
            metadata={'key': 'value'},
            organization=self.org,
        )
        self.assertEqual(instance.metadata, {'key': 'value'})

    async def test_get_model_with_email_format(self) -> None:
        """Test get_model with email format string."""
        self._set_blueprints(
            self._make_blueprint(
                properties={'contact': {'type': 'string', 'format': 'email'}}
            )
        )

        result_model = await blueprints.get_model(models.Environment)

        instance = result_model(
            name='Test',
            slug='test',
            contact='user@example.com',
            organization=self.org,
        )
        self.assertEqual(str(instance.contact), 'user@example.com')

        # Test invalid email
        with self.assertRaises(pydantic.ValidationError):
            result_model(
                name='Test',
                slug='test',
                contact='not-an-email',
                organization=self.org,
            )

    async def test_get_model_with_uri_format(self) -> None:
        """Test get_model with uri/url format string."""
        self._set_blueprints(
            self._make_blueprint(
                properties={'homepage': {'type': 'string', 'format': 'uri'}}
            )
        )

        result_model = await blueprints.get_model(models.Environment)

        instance = result_model(
            name='Test',
            slug='test',
            homepage='https://example.com',
            organization=self.org,
        )
        self.assertEqual(str(instance.homepage), 'https://example.com/')

    async def test_get_model_with_datetime_formats(self) -> None:
        """Test get_model with date-time, date, and time formats."""
        self._set_blueprints(
            self._make_blueprint(
                properties={
                    'created_at': {'type': 'string', 'format': 'date-time'},
                    'launch_date': {'type': 'string', 'format': 'date'},
                    'maintenance_window': {'type': 'string', 'format': 'time'},
                }
            )
        )

        result_model = await blueprints.get_model(models.Environment)

        now = datetime.datetime.now(datetime.UTC)
        today = datetime.datetime.now(datetime.UTC).date()
        maintenance = datetime.time(2, 0, 0)

        instance = result_model(
            name='Test',
            slug='test',
            created_at=now,
            launch_date=today,
            maintenance_window=maintenance,
            organization=self.org,
        )
        self.assertEqual(instance.created_at, now)
        self.assertEqual(instance.launch_date, today)
        self.assertEqual(instance.maintenance_window, maintenance)

    async def test_get_model_with_enum(self) -> None:
        """Test get_model with enum constraint."""
        self._set_blueprints(
            self._make_blueprint(
                properties={
                    'tier': {
                        'type': 'string',
                        'enum': ['dev', 'staging', 'production'],
                    }
                }
            )
        )

        result_model = await blueprints.get_model(models.Environment)

        instance = result_model(
            name='Test',
            slug='test',
            tier='production',
            organization=self.org,
        )
        self.assertEqual(instance.tier, 'production')

        # Test invalid enum value
        with self.assertRaises(pydantic.ValidationError):
            result_model(
                name='Test',
                slug='test',
                tier='invalid',
                organization=self.org,
            )

    async def test_get_model_with_default_values(self) -> None:
        """Test get_model with default values from schema."""
        self._set_blueprints(
            self._make_blueprint(
                properties={
                    'region': {'type': 'string', 'default': 'us-east-1'},
                    'replicas': {'type': 'integer', 'default': 3},
                }
            )
        )

        result_model = await blueprints.get_model(models.Environment)

        # Create instance without providing optional fields
        instance = result_model(
            name='Test', slug='test', organization=self.org
        )
        self.assertEqual(instance.region, 'us-east-1')
        self.assertEqual(instance.replicas, 3)

        # Override defaults
        instance2 = result_model(
            name='Test',
            slug='test',
            region='eu-west-1',
            replicas=5,
            organization=self.org,
        )
        self.assertEqual(instance2.region, 'eu-west-1')
        self.assertEqual(instance2.replicas, 5)

    async def test_get_model_with_descriptions(self) -> None:
        """Test get_model preserves field descriptions."""
        self._set_blueprints(
            self._make_blueprint(
                properties={
                    'domain': {
                        'type': 'string',
                        'description': 'Base domain name',
                    }
                }
            )
        )

        result_model = await blueprints.get_model(models.Environment)

        # Check that description is preserved in field info
        field_info = result_model.model_fields['domain']
        self.assertEqual(field_info.description, 'Base domain name')

    async def test_get_model_multiple_blueprints_priority(self) -> None:
        """Test get_model with multiple blueprints respects priority."""
        self._set_blueprints(
            self._make_blueprint(
                properties={'field1': {'type': 'string'}},
                name='base',
                priority=0,
            ),
            self._make_blueprint(
                properties={'field2': {'type': 'integer'}},
                name='extended',
                priority=1,
            ),
        )

        result_model = await blueprints.get_model(models.Environment)

        # Both fields should be present
        self.assertIn('field1', result_model.model_fields)
        self.assertIn('field2', result_model.model_fields)

        instance = result_model(
            name='Test',
            slug='test',
            field1='test',
            field2=42,
            organization=self.org,
        )
        self.assertEqual(instance.field1, 'test')
        self.assertEqual(instance.field2, 42)

    async def test_get_model_json_schema_round_trip(self) -> None:
        """Test get_model creates valid Pydantic model with JSON schema."""
        self._set_blueprints(
            self._make_blueprint(
                properties={
                    'domain': {
                        'type': 'string',
                        'description': 'Base domain name',
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region',
                    },
                },
                required=['domain', 'region'],
            )
        )

        result_model = await blueprints.get_model(models.Environment)

        # Should be able to get JSON schema from result
        json_schema = result_model.model_json_schema()

        # Verify the schema contains our fields
        self.assertIn('properties', json_schema)
        self.assertIn('domain', json_schema['properties'])
        self.assertIn('region', json_schema['properties'])
        self.assertIn('required', json_schema)
        self.assertIn('domain', json_schema['required'])
        self.assertIn('region', json_schema['required'])

    async def test_get_model_validates_instances(self) -> None:
        """Test that instances of returned model validate correctly."""
        self._set_blueprints(
            self._make_blueprint(
                properties={
                    'domain': {'type': 'string'},
                    'max_instances': {'type': 'integer'},
                },
                required=['domain'],
            )
        )

        result_model = await blueprints.get_model(models.Environment)

        # Valid instance
        instance = result_model(
            name='Prod',
            slug='prod',
            domain='example.com',
            max_instances=10,
            organization=self.org,
        )
        self.assertEqual(instance.name, 'Prod')
        self.assertEqual(instance.domain, 'example.com')
        self.assertEqual(instance.max_instances, 10)

        # Can serialize to dict
        data = instance.model_dump()
        self.assertEqual(data['name'], 'Prod')
        self.assertEqual(data['domain'], 'example.com')

        # Can serialize to JSON
        json_str = instance.model_dump_json()
        self.assertIn('Prod', json_str)
        self.assertIn('example.com', json_str)


class MatchesFilterTestCase(unittest.TestCase):
    """Test cases for blueprints._matches_filter."""

    def _make_blueprint(
        self,
        *,
        bp_filter: dict[str, typing.Any] | None = None,
    ) -> models.Blueprint:
        return models.Blueprint(
            name='test',
            type='Project',
            json_schema=models.Schema.model_validate(
                {'type': 'object', 'properties': {}}
            ),
            filter=bp_filter,
        )

    def test_no_filter_matches_everything(self) -> None:
        bp = self._make_blueprint()
        self.assertTrue(blueprints._matches_filter(bp, None))
        self.assertTrue(
            blueprints._matches_filter(bp, {'project_type': 'apis'})
        )

    def test_filter_with_no_context_rejects(self) -> None:
        bp = self._make_blueprint(bp_filter={'project_type': ['apis']})
        self.assertFalse(blueprints._matches_filter(bp, None))

    def test_filter_matches_context(self) -> None:
        bp = self._make_blueprint(bp_filter={'project_type': ['apis']})
        self.assertTrue(
            blueprints._matches_filter(bp, {'project_type': 'apis'})
        )
        self.assertFalse(
            blueprints._matches_filter(bp, {'project_type': 'consumers'})
        )

    def test_list_filter_matches_any(self) -> None:
        bp = self._make_blueprint(
            bp_filter={
                'project_type': [
                    'apis',
                    'consumers',
                    'daemons',
                ]
            }
        )
        self.assertTrue(
            blueprints._matches_filter(bp, {'project_type': 'apis'})
        )
        self.assertTrue(
            blueprints._matches_filter(bp, {'project_type': 'daemons'})
        )
        self.assertFalse(
            blueprints._matches_filter(bp, {'project_type': 'database'})
        )

    def test_multiple_filter_fields_and(self) -> None:
        bp = self._make_blueprint(
            bp_filter={
                'project_type': ['apis'],
                'environment': ['production'],
            }
        )
        self.assertTrue(
            blueprints._matches_filter(
                bp,
                {
                    'project_type': 'apis',
                    'environment': 'production',
                },
            )
        )
        self.assertFalse(
            blueprints._matches_filter(
                bp,
                {
                    'project_type': 'apis',
                    'environment': 'staging',
                },
            )
        )
        # Missing key
        self.assertFalse(
            blueprints._matches_filter(bp, {'project_type': 'apis'})
        )

    def test_empty_filter_lists_match_everything(self) -> None:
        bp = self._make_blueprint(
            bp_filter={
                'project_type': [],
                'environment': [],
            }
        )
        self.assertTrue(blueprints._matches_filter(bp, None))
        self.assertTrue(
            blueprints._matches_filter(bp, {'project_type': 'apis'})
        )


class GetModelFilterTestCase(unittest.IsolatedAsyncioTestCase):
    """Test get_model with filter context."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.org = models.Organization(name='Org', slug='org')
        self.fetch_nodes_patcher = mock.patch('imbi_common.neo4j.fetch_nodes')
        self.mock_fetch_nodes = self.fetch_nodes_patcher.start()
        self.addCleanup(self.fetch_nodes_patcher.stop)

    def _make_blueprint(
        self,
        *,
        properties: dict[str, typing.Any],
        name: str = 'test',
        bp_filter: dict[str, typing.Any] | None = None,
        priority: int = 0,
    ) -> models.Blueprint:
        schema: dict[str, typing.Any] = {
            'type': 'object',
            'properties': properties,
        }
        return models.Blueprint(
            name=name,
            type='Project',
            priority=priority,
            json_schema=models.Schema.model_validate(schema),
            filter=bp_filter,
        )

    def _set_blueprints(self, *bps: models.Blueprint) -> None:
        async def iterator():
            for bp in bps:
                yield bp

        self.mock_fetch_nodes.return_value = iterator()

    async def test_context_filters_blueprints(self) -> None:
        self._set_blueprints(
            self._make_blueprint(
                name='common',
                properties={'has_ci': {'type': 'boolean'}},
            ),
            self._make_blueprint(
                name='api-facts',
                properties={
                    'framework': {
                        'type': 'string',
                        'enum': ['FastAPI', 'Tornado'],
                    }
                },
                bp_filter={'project_type': ['apis']},
            ),
            self._make_blueprint(
                name='db-facts',
                properties={
                    'database_type': {
                        'type': 'string',
                        'enum': ['PostgreSQL', 'MySQL'],
                    }
                },
                bp_filter={'project_type': ['database']},
            ),
        )

        model = await blueprints.get_model(
            models.Project,
            context={'project_type': 'apis'},
        )

        self.assertIn('has_ci', model.model_fields)
        self.assertIn('framework', model.model_fields)
        self.assertNotIn('database_type', model.model_fields)

    async def test_no_context_returns_unfiltered_only(
        self,
    ) -> None:
        self._set_blueprints(
            self._make_blueprint(
                name='common',
                properties={'has_ci': {'type': 'boolean'}},
            ),
            self._make_blueprint(
                name='api-facts',
                properties={'framework': {'type': 'string'}},
                bp_filter={'project_type': ['apis']},
            ),
        )

        model = await blueprints.get_model(models.Project)

        self.assertIn('has_ci', model.model_fields)
        self.assertNotIn('framework', model.model_fields)


class GetModelIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    """Integration tests for blueprints.get_model with real Neo4j."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # Initialize Neo4j connection
        await neo4j.initialize()
        # Clean up any existing test blueprint before starting
        async with neo4j.session() as session:
            await session.run(
                "MATCH (b:Blueprint {name: 'test-rtt'}) DETACH DELETE b"
            )

    async def asyncTearDown(self) -> None:
        # Clean up test blueprints
        async with neo4j.session() as session:
            await session.run(
                "MATCH (b:Blueprint {name: 'test-rtt'}) DETACH DELETE b"
            )
        # Close Neo4j connection
        await neo4j.aclose()
        await super().asyncTearDown()

    async def test_round_trip_with_neo4j(self) -> None:
        """Test round-trip: create blueprint in Neo4j and build model."""
        # Create a test blueprint
        blueprint = models.Blueprint(
            name='test-rtt',
            type='Environment',
            description='Round-trip test blueprint',
            json_schema=models.Schema.model_validate(
                {
                    '$schema': 'http://json-schema.org/draft-07/schema#',
                    'title': 'Environment Extensions',
                    'description': 'Additional environment properties',
                    'type': 'object',
                    'properties': {
                        'domain': {
                            'title': 'Domain',
                            'type': 'string',
                            'description': 'Base domain for services.',
                        },
                        'region': {
                            'title': 'AWS Region',
                            'type': 'string',
                            'description': 'AWS region for environment.',
                        },
                        'max_instances': {
                            'title': 'Max Instances',
                            'type': 'integer',
                            'default': 10,
                            'description': 'Maximum number of instances.',
                        },
                    },
                    'required': ['domain', 'region'],
                }
            ),
        )

        # Store blueprint in Neo4j (handle constraint errors if already exists)
        try:
            await neo4j.create_node(blueprint)
        except exceptions.ConstraintError:
            pass  # Blueprint already exists from previous run

        # Use get_model to fetch blueprints and build dynamic model
        dynamic_model = await blueprints.get_model(models.Environment)

        # Verify the dynamic model has base fields
        self.assertIn('name', dynamic_model.model_fields)
        self.assertIn('slug', dynamic_model.model_fields)
        self.assertIn('description', dynamic_model.model_fields)

        # Verify blueprint-defined fields are present
        self.assertIn('domain', dynamic_model.model_fields)
        self.assertIn('region', dynamic_model.model_fields)
        self.assertIn('max_instances', dynamic_model.model_fields)

        # Verify field metadata is preserved
        domain_field = dynamic_model.model_fields['domain']
        self.assertEqual(domain_field.description, 'Base domain for services.')

        region_field = dynamic_model.model_fields['region']
        self.assertEqual(
            region_field.description, 'AWS region for environment.'
        )

        max_instances_field = dynamic_model.model_fields['max_instances']
        self.assertEqual(
            max_instances_field.description, 'Maximum number of instances.'
        )

        # Create an instance with required fields
        org = models.Organization(name='Org', slug='org')
        instance = dynamic_model(
            name='Production',
            slug='prod',
            domain='example.com',
            region='us-east-1',
            organization=org,
        )

        self.assertEqual(instance.name, 'Production')
        self.assertEqual(instance.slug, 'prod')
        self.assertEqual(instance.domain, 'example.com')
        self.assertEqual(instance.region, 'us-east-1')
        self.assertEqual(
            instance.max_instances, 10
        )  # Should use default value

        # Override default value
        instance2 = dynamic_model(
            name='Staging',
            slug='staging',
            domain='staging.example.com',
            region='us-west-2',
            max_instances=5,
            organization=org,
        )
        self.assertEqual(instance2.max_instances, 5)

        # Test validation - missing required field should fail
        with self.assertRaises(pydantic.ValidationError):
            dynamic_model(
                name='Test',
                slug='test',
                domain='test.com',
                organization=org,
            )  # Missing region

        # Test JSON schema generation
        json_schema = dynamic_model.model_json_schema()
        self.assertIn('properties', json_schema)
        self.assertIn('domain', json_schema['properties'])
        self.assertIn('region', json_schema['properties'])
        self.assertIn('max_instances', json_schema['properties'])
        self.assertIn('required', json_schema)
        self.assertIn('domain', json_schema['required'])
        self.assertIn('region', json_schema['required'])

        # Test serialization
        data = instance.model_dump()
        self.assertEqual(data['name'], 'Production')
        self.assertEqual(data['domain'], 'example.com')
        self.assertEqual(data['region'], 'us-east-1')
        self.assertEqual(data['max_instances'], 10)

        json_str = instance.model_dump_json()
        self.assertIn('Production', json_str)
        self.assertIn('example.com', json_str)
        self.assertIn('us-east-1', json_str)
