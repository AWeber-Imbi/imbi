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
        # Release-train defaults: deployable by default, opt-in promote.
        self.assertTrue(env.can_deploy)
        self.assertFalse(env.can_promote)

    def test_environment_release_train_flags(self) -> None:
        """Explicit overrides for release-train flags round-trip."""
        org = models.Organization(name='Org', slug='org')
        env = models.Environment(
            name='Production',
            slug='prod',
            organization=org,
            can_deploy=False,
            can_promote=True,
        )
        self.assertFalse(env.can_deploy)
        self.assertTrue(env.can_promote)

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
        self.assertFalse(project_type.deployable)

    def test_project_type_deployable(self) -> None:
        """Explicit override for the deployable flag round-trips."""
        org = models.Organization(name='Org', slug='org')
        project_type = models.ProjectType(
            name='Web Service',
            slug='web-service',
            organization=org,
            deployable=True,
        )
        self.assertTrue(project_type.deployable)

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

    def test_project_links_parsed_from_json_string(self) -> None:
        """AGE stores dict properties as JSON strings; verify the
        before-validator decodes them back so consumers (e.g. the
        link-presence scoring policy) see a real dict."""
        org = models.Organization(name='Org', slug='org')
        team = models.Team(name='Team', slug='team', organization=org)
        project = models.Project.model_validate(
            {
                'name': 'Test',
                'slug': 'test',
                'team': team,
                'links': (
                    '{"grafana-dashboard": "https://grafana.example/d/foo"}'
                ),
                'identifiers': '{"github": "12345"}',
            }
        )
        self.assertIsInstance(project.links, dict)
        self.assertIn('grafana-dashboard', project.links)
        self.assertIsInstance(project.identifiers, dict)
        self.assertEqual('12345', project.identifiers['github'])


class DocumentTemplateModelTestCase(unittest.TestCase):
    """Test cases for DocumentTemplate model."""

    def _org(self) -> models.Organization:
        return models.Organization(name='Org', slug='org')

    def test_document_template_creation(self) -> None:
        org = self._org()
        adr = models.Tag(name='ADR', slug='adr', organization=org)
        template = models.DocumentTemplate(
            name='ADR',
            slug='adr',
            description='Context · Decision · Trade-offs',
            organization=org,
            content='# Context\n',
            tags=[adr],
            project_type_slugs=['http-api'],
            sort_order=10,
        )
        self.assertEqual(template.name, 'ADR')
        self.assertEqual(template.slug, 'adr')
        self.assertEqual(template.content, '# Context\n')
        self.assertEqual(template.tags, [adr])
        self.assertEqual(template.organization, org)
        self.assertEqual(template.project_type_slugs, ['http-api'])
        self.assertEqual(template.sort_order, 10)

    def test_document_template_defaults(self) -> None:
        template = models.DocumentTemplate(
            name='Runbook',
            slug='runbook',
            organization=self._org(),
        )
        self.assertEqual(template.content, '')
        self.assertEqual(template.tags, [])
        self.assertEqual(template.project_type_slugs, [])
        self.assertEqual(template.sort_order, 0)
        self.assertIsNone(template.title)

    def test_document_template_requires_organization(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.DocumentTemplate(name='ADR', slug='adr')


def _make_document() -> models.Document:
    return models.Document.model_construct(
        id='doc-id',
        project=_make_project(),
        title='Runbook',
        content='# Runbook\n',
        created_by='alice@example.com',
    )


class CommentThreadModelTestCase(unittest.TestCase):
    """Test cases for the CommentThread model."""

    def _edges(
        self, model_cls: type[pydantic.BaseModel]
    ) -> dict[str, models.Edge]:
        result: dict[str, models.Edge] = {}
        for name, field in model_cls.model_fields.items():
            for meta in field.metadata:
                if isinstance(meta, models.Edge):
                    result[name] = meta
        return result

    def _make(self, **overrides: typing.Any) -> models.CommentThread:
        defaults: dict[str, typing.Any] = {
            'document': _make_document(),
            'created_by': 'alice@example.com',
        }
        defaults.update(overrides)
        return models.CommentThread(**defaults)

    def test_minimal(self) -> None:
        thread = self._make()
        self.assertEqual(thread.created_by, 'alice@example.com')

    def test_kind_defaults_to_page(self) -> None:
        self.assertEqual(self._make().kind, 'page')

    def test_kind_inline_accepted(self) -> None:
        thread = self._make(kind='inline')
        self.assertEqual(thread.kind, 'inline')

    def test_invalid_kind_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            self._make(kind='gibberish')

    def test_resolution_defaults(self) -> None:
        thread = self._make()
        self.assertFalse(thread.resolved)
        self.assertIsNone(thread.resolved_by)
        self.assertIsNone(thread.resolved_at)

    def test_resolution_round_trip(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        thread = self._make(
            resolved=True,
            resolved_by='bob@example.com',
            resolved_at=now,
        )
        self.assertTrue(thread.resolved)
        self.assertEqual(thread.resolved_by, 'bob@example.com')
        self.assertEqual(thread.resolved_at, now)

    def test_anchor_defaults(self) -> None:
        thread = self._make()
        self.assertEqual(thread.anchor_quote, '')
        self.assertEqual(thread.anchor_prefix, '')
        self.assertEqual(thread.anchor_suffix, '')
        self.assertEqual(thread.anchor_start, 0)

    def test_anchor_fields_round_trip(self) -> None:
        thread = self._make(
            kind='inline',
            anchor_quote='the quick brown fox',
            anchor_prefix='see ',
            anchor_suffix=' jumped',
            anchor_start=42,
        )
        self.assertEqual(thread.anchor_quote, 'the quick brown fox')
        self.assertEqual(thread.anchor_prefix, 'see ')
        self.assertEqual(thread.anchor_suffix, ' jumped')
        self.assertEqual(thread.anchor_start, 42)

    def test_requires_created_by(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.CommentThread(document=_make_document())

    def test_requires_document(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.CommentThread(created_by='alice@example.com')

    def test_on_document_edge(self) -> None:
        edges = self._edges(models.CommentThread)
        self.assertIn('document', edges)
        edge = edges['document']
        self.assertEqual(edge.rel_type, 'ON_DOCUMENT')
        self.assertEqual(edge.direction, 'OUTGOING')

    def test_is_graph_model_not_node(self) -> None:
        self.assertIsInstance(self._make(), models.GraphModel)
        self.assertFalse(issubclass(models.CommentThread, models.Node))

    def test_identity_fields(self) -> None:
        thread = self._make()
        self.assertIsInstance(thread.id, str)
        self.assertTrue(len(thread.id) > 0)
        self.assertEqual(thread.created_at.tzinfo, datetime.UTC)
        self.assertIsNone(thread.updated_at)

    def test_in_all(self) -> None:
        self.assertIn('CommentThread', models.__all__)


class CommentModelTestCase(unittest.TestCase):
    """Test cases for the Comment model."""

    def _edges(
        self, model_cls: type[pydantic.BaseModel]
    ) -> dict[str, models.Edge]:
        result: dict[str, models.Edge] = {}
        for name, field in model_cls.model_fields.items():
            for meta in field.metadata:
                if isinstance(meta, models.Edge):
                    result[name] = meta
        return result

    def _thread(self) -> models.CommentThread:
        return models.CommentThread.model_construct(
            id='thread-id',
            document=_make_document(),
            created_by='alice@example.com',
        )

    def _make(self, **overrides: typing.Any) -> models.Comment:
        defaults: dict[str, typing.Any] = {
            'thread': self._thread(),
            'author': 'alice@example.com',
            'body': 'Looks good to me.',
        }
        defaults.update(overrides)
        return models.Comment(**defaults)

    def test_minimal(self) -> None:
        comment = self._make()
        self.assertEqual(comment.author, 'alice@example.com')
        self.assertEqual(comment.body, 'Looks good to me.')

    def test_list_defaults_empty(self) -> None:
        comment = self._make()
        self.assertEqual(comment.mentions, [])
        self.assertEqual(comment.acknowledged_by, [])

    def test_edited_defaults_false(self) -> None:
        self.assertFalse(self._make().edited)

    def test_requires_author_body_thread(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.Comment(thread=self._thread(), body='x')
        with self.assertRaises(pydantic.ValidationError):
            models.Comment(thread=self._thread(), author='a@x.com')
        with self.assertRaises(pydantic.ValidationError):
            models.Comment(author='a@x.com', body='x')

    def test_in_thread_edge(self) -> None:
        edges = self._edges(models.Comment)
        self.assertIn('thread', edges)
        edge = edges['thread']
        self.assertEqual(edge.rel_type, 'IN_THREAD')
        self.assertEqual(edge.direction, 'OUTGOING')

    def test_body_is_not_embeddable(self) -> None:
        info = models.Comment.model_fields['body']
        self.assertFalse(
            any(isinstance(meta, models.Embeddable) for meta in info.metadata)
        )

    def test_mentions_from_json_string(self) -> None:
        """mentions parses an AGE JSON-string into a list."""
        comment = self._make(
            mentions=json.dumps(['bob@x.com', 'carol@x.com']),
        )
        self.assertEqual(comment.mentions, ['bob@x.com', 'carol@x.com'])

    def test_acknowledged_by_from_json_string(self) -> None:
        comment = self._make(
            acknowledged_by=json.dumps(['dave@x.com']),
        )
        self.assertEqual(comment.acknowledged_by, ['dave@x.com'])

    def test_lists_from_native_list_unchanged(self) -> None:
        comment = self._make(
            mentions=['bob@x.com'],
            acknowledged_by=['dave@x.com'],
        )
        self.assertEqual(comment.mentions, ['bob@x.com'])
        self.assertEqual(comment.acknowledged_by, ['dave@x.com'])

    def test_list_defaults_isolated_per_instance(self) -> None:
        a = self._make()
        b = self._make()
        a.mentions.append('bob@x.com')
        a.acknowledged_by.append('dave@x.com')
        self.assertEqual(b.mentions, [])
        self.assertEqual(b.acknowledged_by, [])

    def test_round_trip_json(self) -> None:
        original = self._make(
            mentions=['bob@x.com', 'carol@x.com'],
            acknowledged_by=['dave@x.com'],
            edited=True,
        )
        roundtrip = models.Comment.model_validate_json(
            original.model_dump_json(),
        )
        self.assertEqual(roundtrip.mentions, ['bob@x.com', 'carol@x.com'])
        self.assertEqual(roundtrip.acknowledged_by, ['dave@x.com'])
        self.assertTrue(roundtrip.edited)

    def test_is_graph_model(self) -> None:
        self.assertIsInstance(self._make(), models.GraphModel)

    def test_in_all(self) -> None:
        self.assertIn('Comment', models.__all__)


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
            'plugin_slug',
            'external_run_id',
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

    def test_plugin_slug_defaults_to_empty_string(self) -> None:
        entry = models.OperationLog(**self._minimum_kwargs())
        self.assertEqual(entry.plugin_slug, '')

    def test_plugin_slug_can_be_set(self) -> None:
        entry = models.OperationLog(
            **self._minimum_kwargs(),
            plugin_slug='ssm',
        )
        self.assertEqual(entry.plugin_slug, 'ssm')


class EventTestCase(unittest.TestCase):
    """Tests for the Event model."""

    def _make(self, **overrides) -> models.Event:
        defaults = {
            'project_id': 'abc123',
            'third_party_service': 'github',
        }
        defaults.update(overrides)
        return models.Event(**defaults)

    def test_recorded_at_defaults_to_utc_now(self) -> None:
        event = self._make()
        self.assertIsNotNone(event.recorded_at)
        self.assertEqual(event.recorded_at.tzinfo, datetime.UTC)

    def test_attributed_to_defaults_to_empty_string(self) -> None:
        event = self._make()
        self.assertEqual(event.attributed_to, '')

    def test_attributed_to_none_is_coerced_to_empty_string(self) -> None:
        """``None`` must be coerced to ``''`` to match the non-Nullable
        ``LowCardinality(String) DEFAULT ''`` column on the events table.
        """
        event = self._make(attributed_to=None)
        self.assertEqual(event.attributed_to, '')

    def test_metadata_and_payload_default_to_empty_dict(self) -> None:
        event = self._make()
        self.assertEqual(event.metadata, {})
        self.assertEqual(event.payload, {})

    def test_id_defaults_to_nonempty_string(self) -> None:
        event = self._make()
        self.assertIsInstance(event.id, str)
        self.assertNotEqual(event.id, '')

    def test_id_is_unique_per_instance(self) -> None:
        a = self._make()
        b = self._make()
        self.assertNotEqual(a.id, b.id)

    def test_type_defaults_to_empty_string(self) -> None:
        event = self._make()
        self.assertEqual(event.type, '')

    def test_optional_fields_can_be_set(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        event = self._make(
            id='custom-id',
            recorded_at=now,
            type='deployment-status',
            attributed_to='user@example.com',
            metadata={'source': 'webhook'},
            payload={'action': 'opened', 'number': 42},
        )
        self.assertEqual(event.id, 'custom-id')
        self.assertEqual(event.recorded_at, now)
        self.assertEqual(event.type, 'deployment-status')
        self.assertEqual(event.attributed_to, 'user@example.com')
        self.assertEqual(event.metadata, {'source': 'webhook'})
        self.assertEqual(event.payload, {'action': 'opened', 'number': 42})

    def test_required_fields(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.Event(third_party_service='github')
        with self.assertRaises(pydantic.ValidationError):
            models.Event(project_id='abc123')

    def test_model_dump_column_order_matches_ddl(self) -> None:
        """key order from model_dump(by_alias=True) must mirror DDL."""
        event = self._make()
        keys = list(event.model_dump(by_alias=True).keys())
        expected = [
            'id',
            'project_id',
            'recorded_at',
            'type',
            'third_party_service',
            'attributed_to',
            'metadata',
            'payload',
            'version',
        ]
        self.assertEqual(keys, expected)

    def test_event_in_all(self) -> None:
        self.assertIn('Event', models.__all__)

    def test_metadata_default_is_isolated_per_instance(self) -> None:
        a = self._make()
        b = self._make()
        a.metadata['k'] = 'v'
        self.assertEqual(b.metadata, {})

    def test_version_defaults_to_zero(self) -> None:
        event = self._make()
        self.assertEqual(event.version, 0)

    def test_version_can_be_set(self) -> None:
        event = self._make(version=1)
        self.assertEqual(event.version, 1)

    def test_version_rejects_values_outside_uint8(self) -> None:
        for value in (-1, 256):
            with self.assertRaises(pydantic.ValidationError):
                self._make(version=value)


def _make_project() -> models.Project:
    org = models.Organization(name='Org', slug='org')
    team = models.Team(name='Team', slug='team', organization=org)
    return models.Project(
        name='Service',
        slug='service',
        team=team,
    )


class DeploymentEventTestCase(unittest.TestCase):
    """Tests for the DeploymentEvent model."""

    def test_timestamp_defaults_to_utc_now(self) -> None:
        event = models.DeploymentEvent(status='pending')
        self.assertIsNotNone(event.timestamp)
        self.assertEqual(event.timestamp.tzinfo, datetime.UTC)

    def test_note_defaults_to_none(self) -> None:
        event = models.DeploymentEvent(status='pending')
        self.assertIsNone(event.note)

    def test_all_statuses_accepted(self) -> None:
        for status in (
            'pending',
            'in_progress',
            'success',
            'failed',
            'rolled_back',
        ):
            with self.subTest(status=status):
                event = models.DeploymentEvent(status=status)
                self.assertEqual(event.status, status)

    def test_invalid_status_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.DeploymentEvent(status='bogus')

    def test_round_trip_json(self) -> None:
        original = models.DeploymentEvent(
            status='success',
            note='shipped',
        )
        roundtrip = models.DeploymentEvent.model_validate_json(
            original.model_dump_json(),
        )
        self.assertEqual(roundtrip.status, 'success')
        self.assertEqual(roundtrip.note, 'shipped')
        self.assertEqual(roundtrip.timestamp, original.timestamp)

    def test_external_run_fields_default_to_none(self) -> None:
        event = models.DeploymentEvent(status='pending')
        self.assertIsNone(event.external_run_id)
        self.assertIsNone(event.external_run_url)

    def test_external_run_fields_round_trip(self) -> None:
        original = models.DeploymentEvent(
            status='in_progress',
            external_run_id='12345678',
            external_run_url='https://github.com/org/repo/actions/runs/12345678',
        )
        roundtrip = models.DeploymentEvent.model_validate_json(
            original.model_dump_json(),
        )
        self.assertEqual(roundtrip.external_run_id, '12345678')
        self.assertEqual(
            roundtrip.external_run_url,
            'https://github.com/org/repo/actions/runs/12345678',
        )


class ReleaseLinkTestCase(unittest.TestCase):
    """Tests for the ReleaseLink model."""

    def test_minimal(self) -> None:
        link = models.ReleaseLink(
            type='github_release',
            url='https://github.com/org/repo/releases/tag/v1',
        )
        self.assertEqual(link.type, 'github_release')
        self.assertIsNone(link.label)

    def test_with_label(self) -> None:
        link = models.ReleaseLink(
            type='jira_version',
            url='https://example.atlassian.net/versions/1',
            label='JIRA version',
        )
        self.assertEqual(link.label, 'JIRA version')

    def test_invalid_url_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.ReleaseLink(type='github_release', url='not-a-url')


class ReleaseModelTestCase(unittest.TestCase):
    """Tests for the Release model."""

    def _make(self, **overrides: typing.Any) -> models.Release:
        defaults: dict[str, typing.Any] = {
            'project': _make_project(),
            'tag': '1.0.0',
            'title': 'Initial release',
            'created_by': 'alice@example.com',
            'committish': 'a1b2c3d',
        }
        defaults.update(overrides)
        return models.Release(**defaults)

    def test_release_is_graph_model(self) -> None:
        release = self._make()
        self.assertIsInstance(release, models.GraphModel)

    def test_release_not_a_node(self) -> None:
        # Release intentionally extends GraphModel, not Node — no
        # name/slug/icon.
        self.assertFalse(issubclass(models.Release, models.Node))

    def test_identity_fields(self) -> None:
        release = self._make()
        self.assertIsInstance(release.id, str)
        self.assertTrue(len(release.id) > 0)
        self.assertIsNotNone(release.created_at)
        self.assertEqual(release.created_at.tzinfo, datetime.UTC)
        self.assertIsNone(release.updated_at)

    def test_defaults(self) -> None:
        release = self._make()
        self.assertIsNone(release.description)
        self.assertEqual(release.links, [])

    def test_committish_accepts_seven_char_short_sha(self) -> None:
        release = self._make(committish='a1b2c3d')
        self.assertEqual(release.committish, 'a1b2c3d')

    def test_committish_is_required(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.Release(
                project=_make_project(),
                tag='1.0.0',
                title='x',
                created_by='alice@example.com',
            )

    def test_committish_rejects_wrong_length(self) -> None:
        for value in ('abc', 'a1b2c3', 'a1b2c3de', 'abcdef0123'):
            with self.assertRaises(pydantic.ValidationError):
                self._make(committish=value)

    def test_committish_rejects_uppercase(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            self._make(committish='A1B2C3D')

    def test_committish_rejects_non_alphanumeric(self) -> None:
        for value in ('abcd-12', 'abcd 12', 'abcd!12'):
            with self.assertRaises(pydantic.ValidationError):
                self._make(committish=value)

    def test_committish_rejects_non_hex_letters(self) -> None:
        # Short SHAs are hex only; letters g-z must be rejected.
        for value in ('g123456', 'abcdefg', 'zzzzzzz'):
            with self.assertRaises(pydantic.ValidationError):
                self._make(committish=value)

    def test_tag_is_optional(self) -> None:
        release = self._make(tag=None)
        self.assertIsNone(release.tag)

    def test_tag_is_plain_string(self) -> None:
        # Model must accept any string — format validation is a
        # runtime concern at the endpoint boundary.
        release = self._make(tag='deadbeef')
        self.assertEqual(release.tag, 'deadbeef')

    def test_release_with_links(self) -> None:
        release = self._make(
            links=[
                models.ReleaseLink(
                    type='github_release',
                    url='https://github.com/org/repo/releases/tag/v1',
                ),
            ],
        )
        self.assertEqual(len(release.links), 1)
        self.assertEqual(release.links[0].type, 'github_release')

    def test_release_round_trip_json(self) -> None:
        release = self._make(
            description='# Initial',
            links=[
                models.ReleaseLink(
                    type='github_release',
                    url='https://github.com/org/repo/releases/tag/v1',
                    label='GitHub',
                ),
            ],
        )
        dumped = release.model_dump_json()
        parsed = json.loads(dumped)
        self.assertEqual(parsed['tag'], '1.0.0')
        self.assertEqual(parsed['title'], 'Initial release')
        self.assertEqual(parsed['description'], '# Initial')
        self.assertEqual(len(parsed['links']), 1)
        self.assertEqual(parsed['links'][0]['type'], 'github_release')
        self.assertEqual(parsed['links'][0]['label'], 'GitHub')

        roundtrip = models.Release.model_validate_json(dumped)
        self.assertEqual(roundtrip.tag, release.tag)
        self.assertEqual(roundtrip.title, release.title)
        self.assertEqual(len(roundtrip.links), 1)
        self.assertEqual(roundtrip.links[0].type, 'github_release')

    def test_release_missing_project_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.Release(
                tag='1.0.0',
                title='x',
                created_by='alice@example.com',
                committish='a1b2c3d',
            )

    def test_release_in_all(self) -> None:
        self.assertIn('Release', models.__all__)
        self.assertIn('ReleaseLink', models.__all__)
        self.assertIn('ReleaseDeploymentEdge', models.__all__)
        self.assertIn('DeploymentEvent', models.__all__)


class ReleaseDeploymentEdgeTestCase(unittest.TestCase):
    """Tests for the ReleaseDeploymentEdge relationship model."""

    def test_is_relationship_edge(self) -> None:
        edge = models.ReleaseDeploymentEdge()
        self.assertIsInstance(edge, models.RelationshipEdge)

    def test_default_deployments_empty(self) -> None:
        edge = models.ReleaseDeploymentEdge()
        self.assertEqual(edge.deployments, [])

    def test_deployment_events_round_trip(self) -> None:
        edge = models.ReleaseDeploymentEdge(
            deployments=[
                models.DeploymentEvent(
                    status='pending',
                    note='queued',
                ),
                models.DeploymentEvent(
                    status='success',
                    note='ok',
                ),
            ],
        )
        roundtrip = models.ReleaseDeploymentEdge.model_validate_json(
            edge.model_dump_json(),
        )
        self.assertEqual(len(roundtrip.deployments), 2)
        self.assertEqual(roundtrip.deployments[0].status, 'pending')
        self.assertEqual(roundtrip.deployments[0].note, 'queued')
        self.assertEqual(roundtrip.deployments[1].status, 'success')

    def test_deployment_events_serialize_as_list(self) -> None:
        edge = models.ReleaseDeploymentEdge(
            deployments=[
                models.DeploymentEvent(status='pending'),
            ],
        )
        dumped = json.loads(edge.model_dump_json())
        self.assertIsInstance(dumped['deployments'], list)
        self.assertEqual(len(dumped['deployments']), 1)
        self.assertEqual(dumped['deployments'][0]['status'], 'pending')


class PluginEdgeTestCase(unittest.TestCase):
    """Tests for the Plugin <-> ServiceApplication edge."""

    def _edges(
        self, model_cls: type[pydantic.BaseModel]
    ) -> dict[str, models.Edge]:
        result: dict[str, models.Edge] = {}
        for name, field in model_cls.model_fields.items():
            for meta in field.metadata:
                if isinstance(meta, models.Edge):
                    result[name] = meta
        return result

    def test_plugin_uses_application_edge(self) -> None:
        edges = self._edges(models.Plugin)
        self.assertIn('service_application', edges)
        edge = edges['service_application']
        self.assertEqual(edge.rel_type, 'USES_APPLICATION')
        self.assertEqual(edge.direction, 'OUTGOING')

    def test_plugin_service_application_defaults_none(self) -> None:
        org = models.Organization(name='Org', slug='org')
        svc = models.ThirdPartyService(
            name='GitHub',
            slug='github',
            organization=org,
        )
        plugin = models.Plugin(
            plugin_slug='github-oauth2',
            label='GitHub OAuth2',
            service=svc,
        )
        self.assertIsNone(plugin.service_application)

    def test_plugin_service_application_assignment(self) -> None:
        org = models.Organization(name='Org', slug='org')
        svc = models.ThirdPartyService(
            name='GitHub',
            slug='github',
            organization=org,
        )
        app = models.ServiceApplication(
            slug='github-oauth-app',
            name='GitHub OAuth App',
        )
        plugin = models.Plugin(
            plugin_slug='github-oauth2',
            label='GitHub OAuth2',
            service=svc,
            service_application=app,
        )
        self.assertIs(plugin.service_application, app)

    def test_third_party_service_has_no_service_application_field(
        self,
    ) -> None:
        self.assertNotIn(
            'service_application', models.ThirdPartyService.model_fields
        )


class ComponentIdentifierTestCase(unittest.TestCase):
    """Tests for the ComponentIdentifier model."""

    def test_creation_with_purl(self) -> None:
        ident = models.ComponentIdentifier(
            kind='purl',
            value='pkg:npm/express',
        )
        self.assertEqual(ident.kind, 'purl')
        self.assertEqual(ident.value, 'pkg:npm/express')

    def test_all_kinds_accepted(self) -> None:
        for kind in ('purl', 'cpe', 'bom-ref', 'swid'):
            with self.subTest(kind=kind):
                ident = models.ComponentIdentifier(kind=kind, value='x')
                self.assertEqual(ident.kind, kind)

    def test_unknown_kind_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.ComponentIdentifier(kind='gibberish', value='x')

    def test_value_required(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.ComponentIdentifier(kind='purl')

    def test_is_graph_model(self) -> None:
        ident = models.ComponentIdentifier(kind='purl', value='pkg:npm/x')
        self.assertIsInstance(ident, models.GraphModel)

    def test_in_all(self) -> None:
        self.assertIn('ComponentIdentifier', models.__all__)


class ComponentTestCase(unittest.TestCase):
    """Tests for the Component model."""

    def _make(self, **overrides: typing.Any) -> models.Component:
        defaults: dict[str, typing.Any] = {
            'purl_name': 'pkg:npm/express',
            'name': 'express',
            'ecosystem': 'npm',
        }
        defaults.update(overrides)
        return models.Component(**defaults)

    def test_minimal(self) -> None:
        component = self._make()
        self.assertEqual(component.purl_name, 'pkg:npm/express')
        self.assertEqual(component.name, 'express')
        self.assertEqual(component.ecosystem, 'npm')
        self.assertIsNone(component.description)
        self.assertEqual(component.identifiers, [])

    def test_identifiers_default_isolated_per_instance(self) -> None:
        a = self._make()
        b = self._make()
        a.identifiers.append(
            models.ComponentIdentifier(kind='purl', value='pkg:npm/express'),
        )
        self.assertEqual(b.identifiers, [])

    def test_identifiers_round_trip(self) -> None:
        component = self._make(
            identifiers=[
                models.ComponentIdentifier(
                    kind='purl', value='pkg:npm/express'
                ),
                models.ComponentIdentifier(
                    kind='cpe', value='cpe:2.3:a:expressjs:express'
                ),
            ],
        )
        self.assertEqual(len(component.identifiers), 2)
        kinds = {i.kind for i in component.identifiers}
        self.assertEqual(kinds, {'purl', 'cpe'})

    def test_required_fields(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.Component(name='express', ecosystem='npm')
        with self.assertRaises(pydantic.ValidationError):
            models.Component(purl_name='pkg:npm/x', ecosystem='npm')
        with self.assertRaises(pydantic.ValidationError):
            models.Component(purl_name='pkg:npm/x', name='x')

    def test_is_graph_model(self) -> None:
        self.assertIsInstance(self._make(), models.GraphModel)

    def test_in_all(self) -> None:
        self.assertIn('Component', models.__all__)


class ComponentReleaseTestCase(unittest.TestCase):
    """Tests for the ComponentRelease model."""

    def _component(self) -> models.Component:
        return models.Component(
            purl_name='pkg:npm/express',
            name='express',
            ecosystem='npm',
        )

    def _make(self, **overrides: typing.Any) -> models.ComponentRelease:
        defaults: dict[str, typing.Any] = {
            'component': self._component(),
            'version': '4.18.2',
        }
        defaults.update(overrides)
        return models.ComponentRelease(**defaults)

    def test_minimal(self) -> None:
        release = self._make()
        self.assertEqual(release.version, '4.18.2')
        self.assertIsNone(release.license)
        self.assertIsNone(release.supplier)
        self.assertEqual(release.hashes, {})

    def test_optional_fields_round_trip(self) -> None:
        release = self._make(
            license='MIT',
            supplier='OpenJS Foundation',
            hashes={'SHA-256': 'a' * 64},
        )
        self.assertEqual(release.license, 'MIT')
        self.assertEqual(release.supplier, 'OpenJS Foundation')
        self.assertEqual(release.hashes['SHA-256'], 'a' * 64)

    def test_hashes_default_isolated_per_instance(self) -> None:
        a = self._make()
        b = self._make()
        a.hashes['SHA-256'] = 'aaa'
        self.assertEqual(b.hashes, {})

    def test_required_fields(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.ComponentRelease(version='1.0.0')
        with self.assertRaises(pydantic.ValidationError):
            models.ComponentRelease(component=self._component())

    def test_is_graph_model(self) -> None:
        self.assertIsInstance(self._make(), models.GraphModel)

    def test_in_all(self) -> None:
        self.assertIn('ComponentRelease', models.__all__)


class ReleaseComponentEdgeTestCase(unittest.TestCase):
    """Tests for Release.component_releases (USES_COMPONENT_RELEASE)."""

    def _edges(
        self, model_cls: type[pydantic.BaseModel]
    ) -> dict[str, models.Edge]:
        result: dict[str, models.Edge] = {}
        for name, field in model_cls.model_fields.items():
            for meta in field.metadata:
                if isinstance(meta, models.Edge):
                    result[name] = meta
        return result

    def test_release_has_component_releases_edge(self) -> None:
        edges = self._edges(models.Release)
        self.assertIn('component_releases', edges)
        edge = edges['component_releases']
        self.assertEqual(edge.rel_type, 'USES_COMPONENT_RELEASE')
        self.assertEqual(edge.direction, 'OUTGOING')

    def test_release_component_releases_defaults_empty(self) -> None:
        release = models.Release(
            project=_make_project(),
            tag='1.0.0',
            title='x',
            created_by='alice@example.com',
            committish='a1b2c3d',
        )
        self.assertEqual(release.component_releases, [])

    def test_release_component_releases_round_trip(self) -> None:
        component = models.Component(
            purl_name='pkg:npm/express',
            name='express',
            ecosystem='npm',
        )
        cr = models.ComponentRelease(
            component=component,
            version='4.18.2',
        )
        release = models.Release(
            project=_make_project(),
            tag='1.0.0',
            title='x',
            created_by='alice@example.com',
            committish='a1b2c3d',
            component_releases=[cr],
        )
        self.assertEqual(len(release.component_releases), 1)
        self.assertEqual(release.component_releases[0].version, '4.18.2')


class ReleaseComponentEdgePropertiesTestCase(unittest.TestCase):
    """Tests for ``ReleaseComponentEdge`` (the edge-properties model)."""

    def test_is_relationship_edge(self) -> None:
        edge = models.ReleaseComponentEdge()
        self.assertIsInstance(edge, models.RelationshipEdge)

    def test_defaults(self) -> None:
        edge = models.ReleaseComponentEdge()
        self.assertIsNone(edge.scope)
        self.assertEqual(edge.groups, [])

    def test_groups_default_isolated_per_instance(self) -> None:
        a = models.ReleaseComponentEdge()
        b = models.ReleaseComponentEdge()
        a.groups.append('dev')
        self.assertEqual(b.groups, [])

    def test_scope_literal_values(self) -> None:
        for scope in ('required', 'optional', 'excluded'):
            with self.subTest(scope=scope):
                edge = models.ReleaseComponentEdge(scope=scope)
                self.assertEqual(edge.scope, scope)

    def test_invalid_scope_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.ReleaseComponentEdge(scope='unknown')

    def test_round_trip(self) -> None:
        edge = models.ReleaseComponentEdge(
            scope='optional', groups=['dev', 'test']
        )
        round_trip = models.ReleaseComponentEdge.model_validate_json(
            edge.model_dump_json()
        )
        self.assertEqual(round_trip.scope, 'optional')
        self.assertEqual(round_trip.groups, ['dev', 'test'])

    def test_in_all(self) -> None:
        self.assertIn('ReleaseComponentEdge', models.__all__)


class MCPServerModelTestCase(unittest.TestCase):
    """Test the MCPServer model."""

    def test_defaults(self) -> None:
        """Test MCPServer default field values."""
        server = models.MCPServer(
            name='Example',
            slug='example',
            url='https://mcp.example.com/mcp',
        )
        self.assertEqual(str(server.url), 'https://mcp.example.com/mcp')
        self.assertTrue(server.enabled)
        self.assertIsNone(server.tool_prefix)
        self.assertEqual(server.timeout, 30)
        self.assertTrue(server.verify_ssl)
        self.assertEqual(server.ignored_tools, [])
        self.assertEqual(server.auth_type, 'none')
        self.assertIsNone(server.static_header)
        self.assertIsNone(server.static_value_encrypted)
        self.assertIsNone(server.oauth_token_url)
        self.assertIsNone(server.oauth_client_id)
        self.assertIsNone(server.oauth_client_secret_encrypted)
        self.assertIsNone(server.oauth_scope)
        self.assertEqual(server.status, 'unknown')
        self.assertIsNone(server.last_tested_at)
        self.assertIsNone(server.last_tested_latency_ms)
        self.assertIsNone(server.tools_discovered)
        self.assertIsNone(server.last_error)

    def test_url_rejects_non_url(self) -> None:
        """url must be a valid HTTP(S) URL, not an arbitrary string."""
        with self.assertRaises(pydantic.ValidationError):
            models.MCPServer(name='Example', slug='example', url='not-a-url')

    def test_oauth_token_url_rejects_non_url(self) -> None:
        """oauth_token_url must be a valid HTTP(S) URL when provided."""
        with self.assertRaises(pydantic.ValidationError):
            models.MCPServer(
                name='Example',
                slug='example',
                url='https://mcp.example.com/mcp',
                auth_type='oauth_client_credentials',
                oauth_token_url='not-a-url',
                oauth_client_id='client',
                oauth_client_secret_encrypted='ciphertext',
            )

    def test_ignored_tools_from_json_string(self) -> None:
        """ignored_tools parses an AGE JSON-string into a list."""
        server = models.MCPServer(
            name='Example',
            slug='example',
            url='https://mcp.example.com/mcp',
            ignored_tools=json.dumps(['drop_table', 'rm_rf']),
        )
        self.assertEqual(server.ignored_tools, ['drop_table', 'rm_rf'])

    def test_ignored_tools_from_list(self) -> None:
        """ignored_tools accepts a native list unchanged."""
        server = models.MCPServer(
            name='Example',
            slug='example',
            url='https://mcp.example.com/mcp',
            ignored_tools=['drop_table'],
        )
        self.assertEqual(server.ignored_tools, ['drop_table'])

    def test_auth_type_rejects_unknown_value(self) -> None:
        """auth_type only accepts the known literal values."""
        with self.assertRaises(pydantic.ValidationError):
            models.MCPServer(
                name='Example',
                slug='example',
                url='https://mcp.example.com/mcp',
                auth_type='basic',
            )

    def test_static_auth_requires_header_and_value(self) -> None:
        """auth_type 'static' requires header and (encrypted) value."""
        with self.assertRaises(pydantic.ValidationError):
            models.MCPServer(
                name='Example',
                slug='example',
                url='https://mcp.example.com/mcp',
                auth_type='static',
            )

    def test_static_auth_valid(self) -> None:
        """A fully specified static auth config validates."""
        server = models.MCPServer(
            name='Example',
            slug='example',
            url='https://mcp.example.com/mcp',
            auth_type='static',
            static_header='Authorization',
            static_value_encrypted='ciphertext',
        )
        self.assertEqual(server.auth_type, 'static')

    def test_oauth_auth_requires_all_fields(self) -> None:
        """auth_type 'oauth_client_credentials' requires its fields."""
        with self.assertRaises(pydantic.ValidationError):
            models.MCPServer(
                name='Example',
                slug='example',
                url='https://mcp.example.com/mcp',
                auth_type='oauth_client_credentials',
                oauth_token_url='https://auth.example.com/token',
            )

    def test_oauth_auth_valid(self) -> None:
        """A fully specified oauth config validates."""
        server = models.MCPServer(
            name='Example',
            slug='example',
            url='https://mcp.example.com/mcp',
            auth_type='oauth_client_credentials',
            oauth_token_url='https://auth.example.com/token',
            oauth_client_id='client',
            oauth_client_secret_encrypted='ciphertext',
        )
        self.assertEqual(server.auth_type, 'oauth_client_credentials')

    def test_health_counts_accept_non_negative(self) -> None:
        """Zero and positive values are accepted for the health counts."""
        for value in (0, 5, 250):
            with self.subTest(value=value):
                server = models.MCPServer(
                    name='Example',
                    slug='example',
                    url='https://mcp.example.com/mcp',
                    last_tested_latency_ms=value,
                    tools_discovered=value,
                )
                self.assertEqual(server.last_tested_latency_ms, value)
                self.assertEqual(server.tools_discovered, value)

    def test_health_counts_default_none(self) -> None:
        """None is accepted (the untested default) for the health counts."""
        server = models.MCPServer(
            name='Example',
            slug='example',
            url='https://mcp.example.com/mcp',
            last_tested_latency_ms=None,
            tools_discovered=None,
        )
        self.assertIsNone(server.last_tested_latency_ms)
        self.assertIsNone(server.tools_discovered)

    def test_last_tested_latency_ms_rejects_negative(self) -> None:
        """last_tested_latency_ms must be non-negative."""
        with self.assertRaises(pydantic.ValidationError):
            models.MCPServer(
                name='Example',
                slug='example',
                url='https://mcp.example.com/mcp',
                last_tested_latency_ms=-1,
            )

    def test_tools_discovered_rejects_negative(self) -> None:
        """tools_discovered must be non-negative."""
        with self.assertRaises(pydantic.ValidationError):
            models.MCPServer(
                name='Example',
                slug='example',
                url='https://mcp.example.com/mcp',
                tools_discovered=-1,
            )


class CommitRecordTestCase(unittest.TestCase):
    """Test cases for the CommitRecord ClickHouse insert model."""

    # Mirror of the ``commits`` table columns in schemata.toml; the
    # round-trip assertion below fails if the model drifts from the DDL.
    _COLUMNS: typing.ClassVar[list[str]] = [
        'project_id',
        'sha',
        'short_sha',
        'ref',
        'message',
        'author_name',
        'author_email',
        'author_login',
        'author_user',
        'committer_name',
        'authored_at',
        'committed_at',
        'url',
        'pushed_at',
        'recorded_at',
    ]

    def test_minimal_fields_and_defaults(self) -> None:
        now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        record = models.CommitRecord(
            project_id='p-1',
            sha='abc123def456',
            short_sha='abc123d',
            ref='main',
            message='Initial commit',
            authored_at=now,
            pushed_at=now,
        )
        self.assertEqual(record.author_name, '')
        self.assertEqual(record.author_email, '')
        self.assertEqual(record.author_login, '')
        self.assertEqual(record.author_user, '')
        self.assertEqual(record.committer_name, '')
        self.assertIsNone(record.committed_at)
        self.assertEqual(record.url, '')
        self.assertEqual(record.recorded_at.tzinfo, datetime.UTC)

    def test_field_names_match_commits_columns(self) -> None:
        self.assertEqual(list(models.CommitRecord.model_fields), self._COLUMNS)

    def test_exported(self) -> None:
        self.assertIn('CommitRecord', models.__all__)


class TagRecordTestCase(unittest.TestCase):
    """Test cases for the TagRecord ClickHouse insert model."""

    _COLUMNS: typing.ClassVar[list[str]] = [
        'project_id',
        'name',
        'sha',
        'message',
        'tagger_name',
        'tagger_email',
        'tagged_at',
        'url',
        'recorded_at',
    ]

    def test_minimal_fields_and_defaults(self) -> None:
        record = models.TagRecord(
            project_id='p-1', name='v1.0.0', sha='abc123'
        )
        self.assertEqual(record.message, '')
        self.assertEqual(record.tagger_name, '')
        self.assertEqual(record.tagger_email, '')
        self.assertIsNone(record.tagged_at)
        self.assertEqual(record.url, '')
        self.assertEqual(record.recorded_at.tzinfo, datetime.UTC)

    def test_field_names_match_tags_columns(self) -> None:
        self.assertEqual(list(models.TagRecord.model_fields), self._COLUMNS)

    def test_exported(self) -> None:
        self.assertIn('TagRecord', models.__all__)
