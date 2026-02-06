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

    def test_node_validation(self) -> None:
        """Test Node model validation."""
        org = models.Organization(name='Org', slug='org')
        with self.assertRaises(pydantic.ValidationError):
            models.Environment(name='Test', organization=org)  # Missing slug


class UploadModelTestCase(unittest.TestCase):
    """Test cases for Upload model."""

    def _make_upload(self, **overrides: object) -> models.Upload:
        defaults = {
            'id': 'upload-1',
            'filename': 'test.png',
            'content_type': 'image/png',
            'size': 1024,
            's3_key': 'uploads/test.png',
            'uploaded_by': 'user@example.com',
            'created_at': '2024-01-01T00:00:00Z',
        }
        defaults.update(overrides)
        return models.Upload(**defaults)

    def test_upload_creation(self) -> None:
        """Test creating a valid Upload model."""
        upload = self._make_upload()
        self.assertEqual(upload.id, 'upload-1')
        self.assertEqual(upload.size, 1024)
        self.assertFalse(upload.has_thumbnail)
        self.assertIsNone(upload.thumbnail_s3_key)

    def test_upload_with_thumbnail(self) -> None:
        """Test Upload with valid thumbnail fields."""
        upload = self._make_upload(
            has_thumbnail=True,
            thumbnail_s3_key='uploads/test_thumb.png',
        )
        self.assertTrue(upload.has_thumbnail)
        self.assertEqual(upload.thumbnail_s3_key, 'uploads/test_thumb.png')

    def test_upload_negative_size(self) -> None:
        """Test that negative size raises validation error."""
        with self.assertRaises(pydantic.ValidationError) as ctx:
            self._make_upload(size=-1)
        self.assertIn('non-negative', str(ctx.exception))

    def test_upload_zero_size(self) -> None:
        """Test that zero size is valid."""
        upload = self._make_upload(size=0)
        self.assertEqual(upload.size, 0)

    def test_upload_thumbnail_true_without_key(self) -> None:
        """Test has_thumbnail=True without thumbnail_s3_key."""
        with self.assertRaises(pydantic.ValidationError) as ctx:
            self._make_upload(has_thumbnail=True)
        self.assertIn('thumbnail_s3_key is required', str(ctx.exception))

    def test_upload_thumbnail_false_with_key(self) -> None:
        """Test has_thumbnail=False with thumbnail_s3_key set."""
        with self.assertRaises(pydantic.ValidationError) as ctx:
            self._make_upload(
                has_thumbnail=False,
                thumbnail_s3_key='uploads/thumb.png',
            )
        self.assertIn('thumbnail_s3_key must be empty', str(ctx.exception))


class PasswordChangeRequestTestCase(unittest.TestCase):
    """Test cases for PasswordChangeRequest model."""

    def test_valid_password(self) -> None:
        """Test a valid password passes validation."""
        req = models.PasswordChangeRequest(new_password='Str0ng!Pass12')
        self.assertEqual(req.new_password, 'Str0ng!Pass12')

    def test_password_too_short(self) -> None:
        """Test password shorter than 12 characters."""
        with self.assertRaises(pydantic.ValidationError) as ctx:
            models.PasswordChangeRequest(new_password='Sh0rt!')
        self.assertIn('at least 12', str(ctx.exception))

    def test_password_no_uppercase(self) -> None:
        """Test password without uppercase letter."""
        with self.assertRaises(pydantic.ValidationError) as ctx:
            models.PasswordChangeRequest(new_password='nouppercase1!')
        self.assertIn('uppercase', str(ctx.exception))

    def test_password_no_lowercase(self) -> None:
        """Test password without lowercase letter."""
        with self.assertRaises(pydantic.ValidationError) as ctx:
            models.PasswordChangeRequest(new_password='NOLOWERCASE1!')
        self.assertIn('lowercase', str(ctx.exception))

    def test_password_no_digit(self) -> None:
        """Test password without a digit."""
        with self.assertRaises(pydantic.ValidationError) as ctx:
            models.PasswordChangeRequest(new_password='NoDigitHere!!')
        self.assertIn('digit', str(ctx.exception))

    def test_password_no_special(self) -> None:
        """Test password without a special character."""
        with self.assertRaises(pydantic.ValidationError) as ctx:
            models.PasswordChangeRequest(new_password='NoSpecialChar1')
        self.assertIn('special', str(ctx.exception))


class ProjectModelTestCase(unittest.TestCase):
    """Test cases for Project model."""

    def test_project_url_validation(self) -> None:
        """Test Project URL validation."""
        # Create minimal valid related objects
        org = models.Organization(name='Org', slug='org')
        team = models.Team(name='Team', slug='team', organization=org)
        project_type = models.ProjectType(
            name='Type', slug='type', organization=org
        )

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
