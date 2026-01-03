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


class NodeModelTestCase(unittest.TestCase):
    """Test cases for Node-based models."""

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
        env = models.Environment(
            name='Production',
            slug='prod',
            description='Production environment',
        )
        self.assertEqual(env.name, 'Production')
        self.assertEqual(env.slug, 'prod')
        self.assertEqual(env.description, 'Production environment')

    def test_project_type_creation(self) -> None:
        """Test creating a ProjectType model."""
        project_type = models.ProjectType(
            name='Web Service',
            slug='web-service',
            description='HTTP-based services',
        )
        self.assertEqual(project_type.name, 'Web Service')
        self.assertEqual(project_type.slug, 'web-service')
        self.assertEqual(project_type.description, 'HTTP-based services')

    def test_node_validation(self) -> None:
        """Test Node model validation."""
        with self.assertRaises(pydantic.ValidationError):
            models.Environment(name='Test')  # Missing slug


class ProjectModelTestCase(unittest.TestCase):
    """Test cases for Project model."""

    def test_project_url_validation(self) -> None:
        """Test Project URL validation."""
        # Create minimal valid related objects
        org = models.Organization(name='Org', slug='org')
        team = models.Team(name='Team', slug='team', member_of=org)
        project_type = models.ProjectType(name='Type', slug='type')

        with self.assertRaises(pydantic.ValidationError):
            models.Project(
                name='Test',
                slug='test',
                team=team,
                project_type=project_type,
                links={'repo': 'not-a-url'},  # Invalid URL
                urls={},
                identifiers={},
            )
