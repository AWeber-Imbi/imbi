import datetime
import json
import typing
import unittest

import pydantic

from imbi_common import models


class BlueprintModelTestCase(unittest.TestCase):
    """Test cases for Blueprint model."""

    def test_blueprint_creation(self) -> None:
        """Test creating a Blueprint model."""
        import jsonschema_models

        schema = {
            'type': 'object',
            'properties': {'foo': {'type': 'string'}},
        }
        blueprint = models.Blueprint(
            name='Test Blueprint',
            type='Environment',
            description='A test blueprint',
            json_schema=models.Schema.model_validate(schema),
        )
        self.assertEqual(blueprint.name, 'Test Blueprint')
        self.assertEqual(blueprint.type, 'Environment')
        self.assertEqual(blueprint.description, 'A test blueprint')
        # json_schema gets converted to Schema object
        self.assertIsInstance(blueprint.json_schema, jsonschema_models.Schema)
        # Verify the schema properties are preserved
        self.assertEqual(blueprint.json_schema.type, 'object')
        self.assertIn('foo', blueprint.json_schema.properties)

    def test_blueprint_validation(self) -> None:
        """Test Blueprint model validation."""
        with self.assertRaises(pydantic.ValidationError):
            models.Blueprint(
                name='Test', description='test'
            )  # Missing type and json_schema

    def test_blueprint_slug_auto_generation(self) -> None:
        """Test that slug is auto-generated from name."""
        schema = {'type': 'object', 'properties': {}}
        blueprint = models.Blueprint(
            name='My Test Blueprint',
            type='Project',
            json_schema=models.Schema.model_validate(schema),
        )
        self.assertEqual(blueprint.slug, 'my-test-blueprint')

    def test_blueprint_slug_explicit(self) -> None:
        """Test setting slug explicitly."""
        schema = {'type': 'object', 'properties': {}}
        blueprint = models.Blueprint(
            name='Test Blueprint',
            slug='custom-slug',
            type='Project',
            json_schema=models.Schema.model_validate(schema),
        )
        self.assertEqual(blueprint.slug, 'custom-slug')

    def test_blueprint_slug_special_characters(self) -> None:
        """Test slug generation with special characters."""
        schema = {'type': 'object', 'properties': {}}
        blueprint = models.Blueprint(
            name='Test & Blueprint #1',
            type='Project',
            json_schema=models.Schema.model_validate(schema),
        )
        self.assertEqual(blueprint.slug, 'test-blueprint-1')

    def test_blueprint_slug_unicode(self) -> None:
        """Test slug generation with Unicode characters."""
        schema = {'type': 'object', 'properties': {}}
        blueprint = models.Blueprint(
            name='Café Blueprint',
            type='Project',
            json_schema=models.Schema.model_validate(schema),
        )
        self.assertEqual(blueprint.slug, 'cafe-blueprint')

    def test_blueprint_slug_invalid_characters(self) -> None:
        """Test that invalid characters in explicit slug raise error."""
        schema = {'type': 'object', 'properties': {}}
        with self.assertRaises(pydantic.ValidationError) as ctx:
            models.Blueprint(
                name='Test',
                slug='invalid slug!',
                type='Project',
                json_schema=models.Schema.model_validate(schema),
            )
        self.assertIn('Slug must contain only', str(ctx.exception))

    def test_blueprint_slug_empty(self) -> None:
        """Test that empty slug raises error."""
        schema = {'type': 'object', 'properties': {}}
        with self.assertRaises(pydantic.ValidationError) as ctx:
            models.Blueprint(
                name='Test',
                slug='',
                type='Project',
                json_schema=models.Schema.model_validate(schema),
            )
        self.assertIn('Slug cannot be empty', str(ctx.exception))


class BlueprintFilterValidatorTestCase(unittest.TestCase):
    """Test Blueprint filter and json_schema validators/serializers."""

    def _schema(self) -> models.Schema:
        return models.Schema.model_validate(
            {'type': 'object', 'properties': {}}
        )

    def test_filter_from_json_string(self) -> None:
        """Test filter field accepts a JSON string."""
        filter_json = json.dumps({'project_type': ['apis'], 'environment': []})
        bp = models.Blueprint(
            name='test',
            type='Project',
            json_schema=self._schema(),
            filter=filter_json,
        )
        self.assertIsInstance(bp.filter, models.BlueprintFilter)
        self.assertEqual(bp.filter.project_type, ['apis'])

    def test_filter_from_blueprint_filter_instance(self) -> None:
        """Test filter field accepts a BlueprintFilter instance."""
        bf = models.BlueprintFilter(project_type=['apis'])
        bp = models.Blueprint(
            name='test',
            type='Project',
            json_schema=self._schema(),
            filter=bf,
        )
        self.assertEqual(bp.filter, bf)

    def test_filter_invalid_type_raises(self) -> None:
        """Test filter rejects invalid types."""
        with self.assertRaises(pydantic.ValidationError):
            models.Blueprint(
                name='test',
                type='Project',
                json_schema=self._schema(),
                filter=42,
            )

    def test_filter_serialization(self) -> None:
        """Test filter serializes to JSON string."""
        bf = models.BlueprintFilter(project_type=['apis'])
        bp = models.Blueprint(
            name='test',
            type='Project',
            json_schema=self._schema(),
            filter=bf,
        )
        dumped = bp.model_dump()
        # serialize_filter should produce a JSON string
        self.assertIsInstance(dumped['filter'], str)
        parsed = json.loads(dumped['filter'])
        self.assertEqual(parsed['project_type'], ['apis'])

    def test_filter_none_serialization(self) -> None:
        """Test None filter serializes to None."""
        bp = models.Blueprint(
            name='test',
            type='Project',
            json_schema=self._schema(),
        )
        dumped = bp.model_dump()
        self.assertIsNone(dumped['filter'])

    def test_json_schema_from_schema_instance(self) -> None:
        """Test json_schema field accepts a Schema instance."""
        schema = self._schema()
        bp = models.Blueprint(
            name='test',
            type='Project',
            json_schema=schema,
        )
        self.assertEqual(bp.json_schema, schema)

    def test_json_schema_invalid_type_raises(self) -> None:
        """Test json_schema rejects invalid types."""
        with self.assertRaises(pydantic.ValidationError):
            models.Blueprint(
                name='test',
                type='Project',
                json_schema=42,
            )


class NodeModelTestCase(unittest.TestCase):
    """Test cases for Node-based models."""

    def test_node_id_auto_generated(self) -> None:
        """Test that id is auto-generated via nanoid."""
        org = models.Organization(
            name='ACME Corp',
            slug='acme',
        )
        self.assertIsInstance(org.id, str)
        self.assertTrue(len(org.id) > 0)

    def test_node_id_explicit(self) -> None:
        """Test that id can be set explicitly."""
        org = models.Organization(
            name='ACME Corp',
            slug='acme',
            id='custom-id',
        )
        self.assertEqual(org.id, 'custom-id')

    def test_node_ids_are_unique(self) -> None:
        """Test that auto-generated ids differ."""
        a = models.Organization(name='A', slug='a')
        b = models.Organization(name='B', slug='b')
        self.assertNotEqual(a.id, b.id)

    def test_organization_creation(self) -> None:
        """Test creating an Organization model."""
        org = models.Organization(
            name='ACME Corp',
            slug='acme',
            description='Test organization',
        )
        self.assertEqual(org.name, 'ACME Corp')
        self.assertEqual(org.slug, 'acme')
        self.assertEqual(org.description, 'Test organization')

    def test_environment_creation(self) -> None:
        """Test creating an Environment model."""
        org = models.Organization(name='Org', slug='org')
        env = models.Environment(
            name='Production',
            slug='prod',
            description='Production environment',
            organization=org,
        )
        self.assertEqual(env.name, 'Production')
        self.assertEqual(env.slug, 'prod')
        self.assertEqual(env.description, 'Production environment')
        self.assertEqual(env.organization, org)

    def test_project_type_creation(self) -> None:
        """Test creating a ProjectType model."""
        org = models.Organization(name='Org', slug='org')
        project_type = models.ProjectType(
            name='Web Service',
            slug='web-service',
            description='HTTP-based services',
            organization=org,
        )
        self.assertEqual(project_type.name, 'Web Service')
        self.assertEqual(project_type.slug, 'web-service')
        self.assertEqual(project_type.description, 'HTTP-based services')
        self.assertEqual(project_type.organization, org)

    def test_node_timestamps_defaults(self) -> None:
        """Test that created_at defaults to now, updated_at to None."""
        org = models.Organization(
            name='ACME Corp',
            slug='acme',
        )
        self.assertIsNotNone(org.created_at)
        self.assertEqual(org.created_at.tzinfo, datetime.UTC)
        self.assertIsNone(org.updated_at)

    def test_node_timestamps_explicit(self) -> None:
        """Test that Node timestamps can be set explicitly."""
        now = datetime.datetime.now(datetime.UTC)
        org = models.Organization(
            name='ACME Corp',
            slug='acme',
            created_at=now,
            updated_at=now,
        )
        self.assertEqual(org.created_at, now)
        self.assertEqual(org.updated_at, now)

    def test_node_validation(self) -> None:
        """Test Node model validation."""
        org = models.Organization(name='Org', slug='org')
        with self.assertRaises(pydantic.ValidationError):
            models.Environment(name='Test', organization=org)  # Missing slug


class GraphModelTestCase(unittest.TestCase):
    """Test cases for GraphModel base class."""

    def test_graph_model_id_auto_generated(self) -> None:
        gm = models.GraphModel()
        self.assertIsInstance(gm.id, str)
        self.assertTrue(len(gm.id) > 0)

    def test_graph_model_id_explicit(self) -> None:
        gm = models.GraphModel(id='custom-id')
        self.assertEqual(gm.id, 'custom-id')

    def test_graph_model_timestamps(self) -> None:
        gm = models.GraphModel()
        self.assertIsNotNone(gm.created_at)
        self.assertEqual(gm.created_at.tzinfo, datetime.UTC)
        self.assertIsNone(gm.updated_at)

    def test_graph_model_extra_ignored(self) -> None:
        gm = models.GraphModel(
            id='x',
            extra_field='should be ignored',
        )
        self.assertFalse(hasattr(gm, 'extra_field'))

    def test_node_is_graph_model(self) -> None:
        org = models.Organization(name='Org', slug='org')
        self.assertIsInstance(org, models.GraphModel)

    def test_graph_model_ids_unique(self) -> None:
        a = models.GraphModel()
        b = models.GraphModel()
        self.assertNotEqual(a.id, b.id)


class EmbeddableTestCase(unittest.TestCase):
    """Test cases for the Embeddable dataclass."""

    def test_embeddable_defaults(self) -> None:
        e = models.Embeddable()
        self.assertEqual(e.model_name, 'text')
        self.assertFalse(e.chunk)

    def test_embeddable_custom(self) -> None:
        e = models.Embeddable(model_name='code', chunk=True)
        self.assertEqual(e.model_name, 'code')
        self.assertTrue(e.chunk)

    def test_embeddable_frozen(self) -> None:
        e = models.Embeddable()
        with self.assertRaises(AttributeError):
            e.model_name = 'other'  # type: ignore[misc]


class BlueprintAsNodeTestCase(unittest.TestCase):
    """Test Blueprint inherits from Node."""

    def test_blueprint_is_node(self) -> None:
        schema = {'type': 'object', 'properties': {}}
        bp = models.Blueprint(
            name='Test',
            type='Project',
            json_schema=models.Schema.model_validate(schema),
        )
        self.assertIsInstance(bp, models.Node)

    def test_blueprint_has_id(self) -> None:
        schema = {'type': 'object', 'properties': {}}
        bp = models.Blueprint(
            name='Test',
            type='Project',
            json_schema=models.Schema.model_validate(schema),
        )
        self.assertIsInstance(bp.id, str)
        self.assertTrue(len(bp.id) > 0)

    def test_blueprint_has_timestamps(self) -> None:
        schema = {'type': 'object', 'properties': {}}
        bp = models.Blueprint(
            name='Test',
            type='Project',
            json_schema=models.Schema.model_validate(schema),
        )
        self.assertIsNotNone(bp.created_at)
        self.assertIsNone(bp.updated_at)


class ProjectModelTestCase(unittest.TestCase):
    """Test cases for Project model."""

    def test_project_url_validation(self) -> None:
        """Test Project URL validation."""
        # Create minimal valid related objects
        org = models.Organization(name='Org', slug='org')
        team = models.Team(
            name='Team',
            slug='team',
            organization=org,
        )
        project_type = models.ProjectType(
            name='Type',
            slug='type',
            organization=org,
        )

        with self.assertRaises(pydantic.ValidationError):
            models.Project(
                name='Test',
                slug='test',
                team=team,
                project_types=[project_type],
                links={'repo': 'not-a-url'},  # Invalid URL
                urls={},
                identifiers={},
            )


class OperationLogTestCase(unittest.TestCase):
    """Tests for the OperationLog model."""

    def _make(self, **overrides) -> models.OperationLog:
        defaults = {
            'recorded_by': 'github',
            'project_id': 'abc123',
            'project_slug': 'my-service',
            'environment_slug': 'production',
            'entry_type': 'Deployed',
            'description': 'Deploy v1.2.3',
        }
        defaults.update(overrides)
        return models.OperationLog(**defaults)

    def test_id_auto_generated(self) -> None:
        entry = self._make()
        self.assertIsInstance(entry.id, str)
        self.assertTrue(len(entry.id) > 0)

    def test_ids_are_unique(self) -> None:
        a = self._make()
        b = self._make()
        self.assertNotEqual(a.id, b.id)

    def test_occurred_at_defaults_to_utc_now(self) -> None:
        entry = self._make()
        self.assertIsNotNone(entry.occurred_at)
        self.assertEqual(entry.occurred_at.tzinfo, datetime.UTC)

    def test_recorded_at_defaults_to_utc_now(self) -> None:
        entry = self._make()
        self.assertIsNotNone(entry.recorded_at)
        self.assertEqual(entry.recorded_at.tzinfo, datetime.UTC)

    def test_nullable_fields_default_to_none(self) -> None:
        entry = self._make()
        self.assertIsNone(entry.performed_by)
        self.assertIsNone(entry.completed_at)
        self.assertIsNone(entry.link)
        self.assertIsNone(entry.notes)
        self.assertIsNone(entry.ticket_slug)
        self.assertIsNone(entry.version)

    def test_optional_fields_can_be_set(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        entry = self._make(
            performed_by='user@example.com',
            completed_at=now,
            link='https://github.com/org/repo/actions/runs/123',
            notes='Some notes',
            ticket_slug='PROJ-42',
            version='v1.2.3',
        )
        self.assertEqual(entry.performed_by, 'user@example.com')
        self.assertEqual(entry.completed_at, now)
        self.assertEqual(
            entry.link, 'https://github.com/org/repo/actions/runs/123'
        )
        self.assertEqual(entry.notes, 'Some notes')
        self.assertEqual(entry.ticket_slug, 'PROJ-42')
        self.assertEqual(entry.version, 'v1.2.3')

    def test_invalid_entry_type_raises(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            self._make(entry_type='NotAType')

    def test_all_valid_entry_types(self) -> None:
        for entry_type in typing.get_args(models._OPSLOG_ENTRY_TYPES):
            with self.subTest(entry_type=entry_type):
                entry = self._make(entry_type=entry_type)
                self.assertEqual(entry.entry_type, entry_type)

    def test_model_dump_column_order_matches_ddl(self) -> None:
        """key order from model_dump(by_alias=True) must mirror DDL."""
        entry = self._make()
        keys = list(entry.model_dump(by_alias=True).keys())
        expected = [
            'id',
            'occurred_at',
            'recorded_at',
            'recorded_by',
            'performed_by',
            'completed_at',
            'project_id',
            'project_slug',
            'environment_slug',
            'entry_type',
            'description',
            'link',
            'notes',
            'ticket_slug',
            'version',
            '_row_version',
            'is_deleted',
        ]
        self.assertEqual(keys, expected)

    def test_operation_log_in_all(self) -> None:
        self.assertIn('OperationLog', models.__all__)


class OperationLogFieldsTests(unittest.TestCase):
    """Tests for OperationLog schema/API fields."""

    def _minimum_kwargs(self) -> dict:
        return {
            'recorded_by': 'alice@example.com',
            'project_id': 'abc123',
            'project_slug': 'imbi-api',
            'environment_slug': 'production',
            'entry_type': 'Deployed',
            'description': 'Rolled out v1',
        }

    def test_defaults_row_version_to_one(self) -> None:
        entry = models.OperationLog(**self._minimum_kwargs())
        self.assertEqual(entry.row_version, 1)

    def test_defaults_is_deleted_to_false(self) -> None:
        entry = models.OperationLog(**self._minimum_kwargs())
        self.assertFalse(entry.is_deleted)

    def test_row_version_accepts_alias(self) -> None:
        entry = models.OperationLog(
            **self._minimum_kwargs(),
            _row_version=7,
        )
        self.assertEqual(entry.row_version, 7)

    def test_row_version_accepts_field_name(self) -> None:
        entry = models.OperationLog(
            **self._minimum_kwargs(),
            row_version=7,
        )
        self.assertEqual(entry.row_version, 7)

    def test_is_deleted_can_be_set(self) -> None:
        entry = models.OperationLog(
            **self._minimum_kwargs(),
            is_deleted=True,
        )
        self.assertTrue(entry.is_deleted)

    def test_model_dump_by_alias_emits_underscore_name(self) -> None:
        entry = models.OperationLog(**self._minimum_kwargs())
        dumped = entry.model_dump(by_alias=True)
        self.assertIn('_row_version', dumped)
        self.assertNotIn('row_version', dumped)
        self.assertEqual(dumped['_row_version'], 1)
        self.assertFalse(dumped['is_deleted'])
