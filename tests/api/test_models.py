import unittest

import pydantic

from imbi import models


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
            slug='test-blueprint',
            description='A test blueprint',
            json_schema=models.Schema.model_validate(schema),
        )
        self.assertEqual(blueprint.name, 'Test Blueprint')
        self.assertEqual(blueprint.slug, 'test-blueprint')
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
                name='Test', slug='test', description='test'
            )  # Missing json_schema


class NamespaceModelTestCase(unittest.TestCase):
    """Test cases for Namespace model."""

    def test_namespace_creation(self) -> None:
        """Test creating a Namespace model."""
        namespace = models.Namespace(
            name='Production',
            description='Production environment',
            icon_class='fa-server',
            slug='production',
        )
        self.assertEqual(namespace.name, 'Production')
        self.assertEqual(namespace.description, 'Production environment')
        self.assertEqual(namespace.icon_class, 'fa-server')
        self.assertEqual(namespace.slug, 'production')

    def test_namespace_validation(self) -> None:
        """Test Namespace model validation."""
        with self.assertRaises(pydantic.ValidationError):
            models.Namespace(
                name='Test', description='test'
            )  # Missing required fields


class ProjectTypeModelTestCase(unittest.TestCase):
    """Test cases for ProjectType model."""

    def test_project_type_creation(self) -> None:
        """Test creating a ProjectType model."""
        project_type = models.ProjectType(
            name='Web Service',
            plural_name='Web Services',
            description='HTTP-based services',
            icon_class='fa-cloud',
            environment_urls=True,
            slug='web-service',
        )
        self.assertEqual(project_type.name, 'Web Service')
        self.assertEqual(project_type.plural_name, 'Web Services')
        self.assertEqual(project_type.description, 'HTTP-based services')
        self.assertEqual(project_type.icon_class, 'fa-cloud')
        self.assertTrue(project_type.environment_urls)
        self.assertEqual(project_type.slug, 'web-service')

    def test_project_type_environment_urls_false(self) -> None:
        """Test ProjectType with environment_urls=False."""
        project_type = models.ProjectType(
            name='Library',
            plural_name='Libraries',
            description='Code libraries',
            icon_class='fa-book',
            environment_urls=False,
            slug='library',
        )
        self.assertFalse(project_type.environment_urls)

    def test_project_type_validation(self) -> None:
        """Test ProjectType model validation."""
        with self.assertRaises(pydantic.ValidationError):
            models.ProjectType(
                name='Test', plural_name='Tests'
            )  # Missing required fields


class ProjectModelTestCase(unittest.TestCase):
    """Test cases for Project model."""

    def test_project_creation(self) -> None:
        """Test creating a Project model."""
        project = models.Project(
            id=1,
            name='My Service',
            slug='my-service',
            description='A test service',
            environments=['dev', 'staging', 'prod'],
            links={
                'repo': pydantic.HttpUrl(
                    'https://github.com/example/my-service'
                )
            },
            urls={'staging': pydantic.HttpUrl('https://staging.example.com')},
            identifiers={'jira': 'PROJ-123', 'pagerduty_id': 12345},
        )
        self.assertEqual(project.id, 1)
        self.assertEqual(project.name, 'My Service')
        self.assertEqual(project.slug, 'my-service')
        self.assertEqual(project.description, 'A test service')
        self.assertEqual(project.environments, ['dev', 'staging', 'prod'])
        self.assertIn('repo', project.links)
        self.assertIn('staging', project.urls)
        self.assertEqual(project.identifiers['jira'], 'PROJ-123')
        self.assertEqual(project.identifiers['pagerduty_id'], 12345)

    def test_project_empty_collections(self) -> None:
        """Test Project with empty collections."""
        project = models.Project(
            id=2,
            name='Minimal Project',
            slug='minimal',
            description='Minimal project',
            environments=[],
            links={},
            urls={},
            identifiers={},
        )
        self.assertEqual(project.environments, [])
        self.assertEqual(project.links, {})
        self.assertEqual(project.urls, {})
        self.assertEqual(project.identifiers, {})

    def test_project_url_validation(self) -> None:
        """Test Project URL validation."""
        with self.assertRaises(pydantic.ValidationError):
            models.Project(
                id=3,
                name='Test',
                slug='test',
                description='test',
                environments=[],
                links={'repo': 'not-a-url'},  # Invalid URL
                urls={},
                identifiers={},
            )

    def test_project_validation(self) -> None:
        """Test Project model validation."""
        with self.assertRaises(pydantic.ValidationError):
            models.Project(
                id='not-an-int',  # Invalid type
                name='Test',
                slug='test',
                description='test',
                environments=[],
                links={},
                urls={},
                identifiers={},
            )
