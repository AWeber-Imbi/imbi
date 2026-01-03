import datetime
import unittest
from unittest import mock

import pydantic
from neo4j import exceptions

from imbi_common import blueprints, models, neo4j


class GetModelTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for blueprints.get_model function."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # Mock neo4j.fetch_nodes to return test blueprints
        self.fetch_nodes_patcher = mock.patch('imbi_common.neo4j.fetch_nodes')
        self.mock_fetch_nodes = self.fetch_nodes_patcher.start()
        self.addCleanup(self.fetch_nodes_patcher.stop)

    async def test_get_model_no_blueprints(self) -> None:
        """Test get_model with no blueprints returns base model."""

        # Mock empty blueprint list
        async def empty_iterator():
            return
            yield  # Make it a generator

        self.mock_fetch_nodes.return_value = empty_iterator()

        result_model = await blueprints.get_model(models.Environment)

        # Should have same name and base fields
        self.assertEqual(result_model.__name__, 'Environment')
        self.assertIn('name', result_model.model_fields)
        self.assertIn('slug', result_model.model_fields)
        self.assertIn('description', result_model.model_fields)

    async def test_get_model_with_string_fields(self) -> None:
        """Test get_model with basic string fields from blueprints."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'domain': {
                            'type': 'string',
                            'description': 'Base domain',
                        },
                        'region': {'type': 'string'},
                    },
                    'required': ['domain'],
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint

        self.mock_fetch_nodes.return_value = blueprint_iterator()

        result_model = await blueprints.get_model(models.Environment)

        # Check base fields exist
        self.assertIn('name', result_model.model_fields)
        self.assertIn('slug', result_model.model_fields)

        # Check blueprint fields
        self.assertIn('domain', result_model.model_fields)
        self.assertIn('region', result_model.model_fields)

        # Test instantiation with required field
        instance = result_model(
            name='Test Env', slug='test-env', domain='example.com'
        )
        self.assertEqual(instance.domain, 'example.com')
        self.assertIsNone(instance.region)  # Optional field

        # Test that missing required field raises error
        with self.assertRaises(pydantic.ValidationError):
            result_model(name='Test', slug='test')  # Missing domain

    async def test_get_model_with_integer_and_number_fields(self) -> None:
        """Test get_model with integer and number fields."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'max_instances': {'type': 'integer'},
                        'cpu_threshold': {'type': 'number'},
                    },
                    'required': ['max_instances'],
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint

        self.mock_fetch_nodes.return_value = blueprint_iterator()

        result_model = await blueprints.get_model(models.Environment)

        # Create instance and verify types
        instance = result_model(
            name='Test',
            slug='test',
            max_instances=10,
            cpu_threshold=0.75,
        )
        self.assertEqual(instance.max_instances, 10)
        self.assertEqual(instance.cpu_threshold, 0.75)

        # Test type validation
        with self.assertRaises(pydantic.ValidationError):
            result_model(name='Test', slug='test', max_instances='not-an-int')

    async def test_get_model_with_boolean_field(self) -> None:
        """Test get_model with boolean field."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {'is_production': {'type': 'boolean'}},
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint

        self.mock_fetch_nodes.return_value = blueprint_iterator()

        result_model = await blueprints.get_model(models.Environment)

        instance = result_model(name='Test', slug='test', is_production=True)
        self.assertTrue(instance.is_production)

    async def test_get_model_with_array_fields(self) -> None:
        """Test get_model with array fields."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'tags': {'type': 'array', 'items': {'type': 'string'}},
                        'ports': {
                            'type': 'array',
                            'items': {'type': 'integer'},
                        },
                        'generic_list': {'type': 'array'},
                    },
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint

        self.mock_fetch_nodes.return_value = blueprint_iterator()

        result_model = await blueprints.get_model(models.Environment)

        instance = result_model(
            name='Test',
            slug='test',
            tags=['prod', 'web'],
            ports=[80, 443],
            generic_list=[1, 'two', True],
        )
        self.assertEqual(instance.tags, ['prod', 'web'])
        self.assertEqual(instance.ports, [80, 443])
        self.assertEqual(instance.generic_list, [1, 'two', True])

    async def test_get_model_with_object_field(self) -> None:
        """Test get_model with object field."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {'metadata': {'type': 'object'}},
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint

        self.mock_fetch_nodes.return_value = blueprint_iterator()

        result_model = await blueprints.get_model(models.Environment)

        instance = result_model(
            name='Test', slug='test', metadata={'key': 'value'}
        )
        self.assertEqual(instance.metadata, {'key': 'value'})

    async def test_get_model_with_email_format(self) -> None:
        """Test get_model with email format string."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'contact': {'type': 'string', 'format': 'email'}
                    },
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint

        self.mock_fetch_nodes.return_value = blueprint_iterator()

        result_model = await blueprints.get_model(models.Environment)

        instance = result_model(
            name='Test', slug='test', contact='user@example.com'
        )
        self.assertEqual(str(instance.contact), 'user@example.com')

        # Test invalid email
        with self.assertRaises(pydantic.ValidationError):
            result_model(name='Test', slug='test', contact='not-an-email')

    async def test_get_model_with_uri_format(self) -> None:
        """Test get_model with uri/url format string."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'homepage': {'type': 'string', 'format': 'uri'}
                    },
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint

        self.mock_fetch_nodes.return_value = blueprint_iterator()

        result_model = await blueprints.get_model(models.Environment)

        instance = result_model(
            name='Test', slug='test', homepage='https://example.com'
        )
        self.assertEqual(str(instance.homepage), 'https://example.com/')

    async def test_get_model_with_datetime_formats(self) -> None:
        """Test get_model with date-time, date, and time formats."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'created_at': {
                            'type': 'string',
                            'format': 'date-time',
                        },
                        'launch_date': {'type': 'string', 'format': 'date'},
                        'maintenance_window': {
                            'type': 'string',
                            'format': 'time',
                        },
                    },
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint

        self.mock_fetch_nodes.return_value = blueprint_iterator()

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
        )
        self.assertEqual(instance.created_at, now)
        self.assertEqual(instance.launch_date, today)
        self.assertEqual(instance.maintenance_window, maintenance)

    async def test_get_model_with_enum(self) -> None:
        """Test get_model with enum constraint."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'tier': {
                            'type': 'string',
                            'enum': ['dev', 'staging', 'production'],
                        }
                    },
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint

        self.mock_fetch_nodes.return_value = blueprint_iterator()

        result_model = await blueprints.get_model(models.Environment)

        instance = result_model(name='Test', slug='test', tier='production')
        self.assertEqual(instance.tier, 'production')

        # Test invalid enum value
        with self.assertRaises(pydantic.ValidationError):
            result_model(name='Test', slug='test', tier='invalid')

    async def test_get_model_with_default_values(self) -> None:
        """Test get_model with default values from schema."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'region': {
                            'type': 'string',
                            'default': 'us-east-1',
                        },
                        'replicas': {'type': 'integer', 'default': 3},
                    },
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint

        self.mock_fetch_nodes.return_value = blueprint_iterator()

        result_model = await blueprints.get_model(models.Environment)

        # Create instance without providing optional fields
        instance = result_model(name='Test', slug='test')
        self.assertEqual(instance.region, 'us-east-1')
        self.assertEqual(instance.replicas, 3)

        # Override defaults
        instance2 = result_model(
            name='Test', slug='test', region='eu-west-1', replicas=5
        )
        self.assertEqual(instance2.region, 'eu-west-1')
        self.assertEqual(instance2.replicas, 5)

    async def test_get_model_with_descriptions(self) -> None:
        """Test get_model preserves field descriptions."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'domain': {
                            'type': 'string',
                            'description': 'Base domain name',
                        }
                    },
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint

        self.mock_fetch_nodes.return_value = blueprint_iterator()

        result_model = await blueprints.get_model(models.Environment)

        # Check that description is preserved in field info
        field_info = result_model.model_fields['domain']
        self.assertEqual(field_info.description, 'Base domain name')

    async def test_get_model_multiple_blueprints_priority(self) -> None:
        """Test get_model with multiple blueprints respects priority."""
        blueprint1 = models.Blueprint(
            name='base',
            type='Environment',
            priority=0,
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {'field1': {'type': 'string'}},
                }
            ),
        )
        blueprint2 = models.Blueprint(
            name='extended',
            type='Environment',
            priority=1,
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {'field2': {'type': 'integer'}},
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint1
            yield blueprint2

        self.mock_fetch_nodes.return_value = blueprint_iterator()

        result_model = await blueprints.get_model(models.Environment)

        # Both fields should be present
        self.assertIn('field1', result_model.model_fields)
        self.assertIn('field2', result_model.model_fields)

        instance = result_model(
            name='Test', slug='test', field1='test', field2=42
        )
        self.assertEqual(instance.field1, 'test')
        self.assertEqual(instance.field2, 42)

    async def test_get_model_json_schema_round_trip(self) -> None:
        """Test get_model creates valid Pydantic model with JSON schema."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'domain': {
                            'type': 'string',
                            'description': 'Base domain name',
                        },
                        'region': {
                            'type': 'string',
                            'description': 'AWS region',
                        },
                    },
                    'required': ['domain', 'region'],
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint

        self.mock_fetch_nodes.return_value = blueprint_iterator()

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
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'domain': {'type': 'string'},
                        'max_instances': {'type': 'integer'},
                    },
                    'required': ['domain'],
                }
            ),
        )

        async def blueprint_iterator():
            yield blueprint

        self.mock_fetch_nodes.return_value = blueprint_iterator()

        result_model = await blueprints.get_model(models.Environment)

        # Valid instance
        instance = result_model(
            name='Prod', slug='prod', domain='example.com', max_instances=10
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
        instance = dynamic_model(
            name='Production',
            slug='prod',
            domain='example.com',
            region='us-east-1',
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
        )
        self.assertEqual(instance2.max_instances, 5)

        # Test validation - missing required field should fail
        with self.assertRaises(pydantic.ValidationError):
            dynamic_model(
                name='Test', slug='test', domain='test.com'
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
