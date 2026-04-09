import datetime
import unittest
from unittest import mock

import pydantic
from imbi_common import blueprints, graph

from imbi_api import models


class GetModelTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for blueprints.get_model function."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # Create a mock graph.Graph instance
        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        # Default: return empty list from match()
        self.mock_db.match = mock.AsyncMock(return_value=[])
        # Create a shared organization for model instantiation
        self.org = models.Organization(name='Test Org', slug='test-org')

    async def test_get_model_no_blueprints(self) -> None:
        """Test get_model with no blueprints returns base model."""
        self.mock_db.match.return_value = []

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

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
        self.mock_db.match.return_value = [blueprint]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

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
            organization=self.org,
            domain='example.com',
        )
        self.assertEqual(instance.domain, 'example.com')
        self.assertIsNone(instance.region)  # Optional field

        # Test that missing required field raises error
        with self.assertRaises(pydantic.ValidationError):
            result_model(
                name='Test',
                slug='test',
                organization=self.org,
            )  # Missing domain

    async def test_get_model_with_integer_and_number_fields(
        self,
    ) -> None:
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
        self.mock_db.match.return_value = [blueprint]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

        # Create instance and verify types
        instance = result_model(
            name='Test',
            slug='test',
            organization=self.org,
            max_instances=10,
            cpu_threshold=0.75,
        )
        self.assertEqual(instance.max_instances, 10)
        self.assertEqual(instance.cpu_threshold, 0.75)

        # Test type validation
        with self.assertRaises(pydantic.ValidationError):
            result_model(
                name='Test',
                slug='test',
                organization=self.org,
                max_instances='not-an-int',
            )

    async def test_get_model_with_boolean_field(self) -> None:
        """Test get_model with boolean field."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'is_production': {'type': 'boolean'},
                    },
                }
            ),
        )
        self.mock_db.match.return_value = [blueprint]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

        instance = result_model(
            name='Test',
            slug='test',
            organization=self.org,
            is_production=True,
        )
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
                        'tags': {
                            'type': 'array',
                            'items': {'type': 'string'},
                        },
                        'ports': {
                            'type': 'array',
                            'items': {'type': 'integer'},
                        },
                        'generic_list': {'type': 'array'},
                    },
                }
            ),
        )
        self.mock_db.match.return_value = [blueprint]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

        instance = result_model(
            name='Test',
            slug='test',
            organization=self.org,
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
                    'properties': {
                        'metadata': {'type': 'object'},
                    },
                }
            ),
        )
        self.mock_db.match.return_value = [blueprint]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

        instance = result_model(
            name='Test',
            slug='test',
            organization=self.org,
            metadata={'key': 'value'},
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
                        'contact': {
                            'type': 'string',
                            'format': 'email',
                        },
                    },
                }
            ),
        )
        self.mock_db.match.return_value = [blueprint]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

        instance = result_model(
            name='Test',
            slug='test',
            organization=self.org,
            contact='user@example.com',
        )
        self.assertEqual(str(instance.contact), 'user@example.com')

        # Test invalid email
        with self.assertRaises(pydantic.ValidationError):
            result_model(
                name='Test',
                slug='test',
                organization=self.org,
                contact='not-an-email',
            )

    async def test_get_model_with_uri_format(self) -> None:
        """Test get_model with uri/url format string."""
        blueprint = models.Blueprint(
            name='test',
            type='Environment',
            json_schema=models.Schema.model_validate(
                {
                    'type': 'object',
                    'properties': {
                        'homepage': {
                            'type': 'string',
                            'format': 'uri',
                        },
                    },
                }
            ),
        )
        self.mock_db.match.return_value = [blueprint]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

        instance = result_model(
            name='Test',
            slug='test',
            organization=self.org,
            homepage='https://example.com',
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
                        'launch_date': {
                            'type': 'string',
                            'format': 'date',
                        },
                        'maintenance_window': {
                            'type': 'string',
                            'format': 'time',
                        },
                    },
                }
            ),
        )
        self.mock_db.match.return_value = [blueprint]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

        now = datetime.datetime.now(datetime.UTC)
        today = datetime.datetime.now(datetime.UTC).date()
        maintenance = datetime.time(2, 0, 0)

        instance = result_model(
            name='Test',
            slug='test',
            organization=self.org,
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
                            'enum': [
                                'dev',
                                'staging',
                                'production',
                            ],
                        },
                    },
                }
            ),
        )
        self.mock_db.match.return_value = [blueprint]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

        instance = result_model(
            name='Test',
            slug='test',
            organization=self.org,
            tier='production',
        )
        self.assertEqual(instance.tier, 'production')

        # Test invalid enum value
        with self.assertRaises(pydantic.ValidationError):
            result_model(
                name='Test',
                slug='test',
                organization=self.org,
                tier='invalid',
            )

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
                        'replicas': {
                            'type': 'integer',
                            'default': 3,
                        },
                    },
                }
            ),
        )
        self.mock_db.match.return_value = [blueprint]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

        # Create instance without providing optional fields
        instance = result_model(
            name='Test',
            slug='test',
            organization=self.org,
        )
        self.assertEqual(instance.region, 'us-east-1')
        self.assertEqual(instance.replicas, 3)

        # Override defaults
        instance2 = result_model(
            name='Test',
            slug='test',
            organization=self.org,
            region='eu-west-1',
            replicas=5,
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
                        },
                    },
                }
            ),
        )
        self.mock_db.match.return_value = [blueprint]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

        # Check that description is preserved in field info
        field_info = result_model.model_fields['domain']
        self.assertEqual(field_info.description, 'Base domain name')

    async def test_get_model_multiple_blueprints_priority(
        self,
    ) -> None:
        """Test get_model with multiple blueprints."""
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
        self.mock_db.match.return_value = [blueprint1, blueprint2]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

        # Both fields should be present
        self.assertIn('field1', result_model.model_fields)
        self.assertIn('field2', result_model.model_fields)

        instance = result_model(
            name='Test',
            slug='test',
            organization=self.org,
            field1='test',
            field2=42,
        )
        self.assertEqual(instance.field1, 'test')
        self.assertEqual(instance.field2, 42)

    async def test_get_model_json_schema_round_trip(self) -> None:
        """Test get_model creates valid Pydantic model."""
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
        self.mock_db.match.return_value = [blueprint]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

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
        """Test that instances of returned model validate."""
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
        self.mock_db.match.return_value = [blueprint]

        result_model = await blueprints.get_model(
            self.mock_db, models.Environment
        )

        # Valid instance
        instance = result_model(
            name='Prod',
            slug='prod',
            organization=self.org,
            domain='example.com',
            max_instances=10,
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
