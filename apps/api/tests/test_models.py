import unittest

import pydantic

from imbi.api import models
from imbi.api.domain import models as domain_models


class BlueprintModelTestCase(unittest.TestCase):
    """Test cases for Blueprint model."""

    def test_blueprint_creation(self) -> None:
        """Test creating a Blueprint model."""
        import jsonschema_models

        schema = {
            'type': 'object',
            'properties': {'foo': {'type': 'string'}},
        }
        blueprint = models.Blueprint.model_validate(
            {
                'name': 'Test Blueprint',
                'type': 'Environment',
                'description': 'A test blueprint',
                'json_schema': models.Schema.model_validate(schema),
            }
        )
        self.assertEqual(blueprint.name, 'Test Blueprint')
        self.assertEqual(blueprint.type, 'Environment')
        self.assertEqual(blueprint.description, 'A test blueprint')
        # json_schema gets converted to Schema object
        self.assertIsInstance(blueprint.json_schema, jsonschema_models.Schema)
        # Verify the schema properties are preserved
        self.assertEqual(blueprint.json_schema.type, 'object')
        assert blueprint.json_schema.properties is not None
        self.assertIn('foo', blueprint.json_schema.properties)

    def test_blueprint_validation(self) -> None:
        """Test Blueprint model validation."""
        with self.assertRaises(pydantic.ValidationError):
            models.Blueprint.model_validate(
                {'name': 'Test', 'description': 'test'},
            )  # Missing type and json_schema

    def test_blueprint_slug_auto_generation(self) -> None:
        """Test that slug is auto-generated from name."""
        schema = {'type': 'object', 'properties': {}}
        blueprint = models.Blueprint.model_validate(
            {
                'name': 'My Test Blueprint',
                'type': 'Project',
                'json_schema': models.Schema.model_validate(schema),
            }
        )
        self.assertEqual(blueprint.slug, 'my-test-blueprint')

    def test_blueprint_slug_explicit(self) -> None:
        """Test setting slug explicitly."""
        schema = {'type': 'object', 'properties': {}}
        blueprint = models.Blueprint.model_validate(
            {
                'name': 'Test Blueprint',
                'slug': 'custom-slug',
                'type': 'Project',
                'json_schema': models.Schema.model_validate(schema),
            }
        )
        self.assertEqual(blueprint.slug, 'custom-slug')

    def test_blueprint_slug_special_characters(self) -> None:
        """Test slug generation with special characters."""
        schema = {'type': 'object', 'properties': {}}
        blueprint = models.Blueprint.model_validate(
            {
                'name': 'Test & Blueprint #1',
                'type': 'Project',
                'json_schema': models.Schema.model_validate(schema),
            }
        )
        self.assertEqual(blueprint.slug, 'test-blueprint-1')

    def test_blueprint_slug_unicode(self) -> None:
        """Test slug generation with Unicode characters."""
        schema = {'type': 'object', 'properties': {}}
        blueprint = models.Blueprint.model_validate(
            {
                'name': 'Café Blueprint',
                'type': 'Project',
                'json_schema': models.Schema.model_validate(schema),
            }
        )
        self.assertEqual(blueprint.slug, 'cafe-blueprint')

    def test_blueprint_slug_invalid_characters(self) -> None:
        """Test that invalid characters in explicit slug raise error."""
        schema = {'type': 'object', 'properties': {}}
        with self.assertRaises(pydantic.ValidationError) as ctx:
            models.Blueprint.model_validate(
                {
                    'name': 'Test',
                    'slug': 'invalid slug!',
                    'type': 'Project',
                    'json_schema': models.Schema.model_validate(schema),
                }
            )
        self.assertIn('Slug must contain only', str(ctx.exception))

    def test_blueprint_slug_empty(self) -> None:
        """Test that empty slug raises error."""
        schema = {'type': 'object', 'properties': {}}
        with self.assertRaises(pydantic.ValidationError) as ctx:
            models.Blueprint.model_validate(
                {
                    'name': 'Test',
                    'slug': '',
                    'type': 'Project',
                    'json_schema': models.Schema.model_validate(schema),
                }
            )
        self.assertIn('Slug cannot be empty', str(ctx.exception))


class NodeModelTestCase(unittest.TestCase):
    """Test cases for Node-based models."""

    def test_organization_creation(self) -> None:
        """Test creating an Organization model."""
        org = models.Organization.model_validate(
            {
                'name': 'ACME Corp',
                'slug': 'acme',
                'description': 'Test organization',
            }
        )
        self.assertEqual(org.name, 'ACME Corp')
        self.assertEqual(org.slug, 'acme')
        self.assertEqual(org.description, 'Test organization')

    def test_environment_creation(self) -> None:
        """Test creating an Environment model."""
        org = models.Organization.model_validate(
            {'name': 'Org', 'slug': 'org'},
        )
        env = models.Environment.model_validate(
            {
                'name': 'Production',
                'slug': 'prod',
                'description': 'Production environment',
                'organization': org,
            }
        )
        self.assertEqual(env.name, 'Production')
        self.assertEqual(env.slug, 'prod')
        self.assertEqual(env.description, 'Production environment')

    def test_project_type_creation(self) -> None:
        """Test creating a ProjectType model."""
        org = models.Organization.model_validate(
            {'name': 'Org', 'slug': 'org'},
        )
        project_type = models.ProjectType.model_validate(
            {
                'name': 'Web Service',
                'slug': 'web-service',
                'description': 'HTTP-based services',
                'organization': org,
            }
        )
        self.assertEqual(project_type.name, 'Web Service')
        self.assertEqual(project_type.slug, 'web-service')
        self.assertEqual(
            project_type.description,
            'HTTP-based services',
        )

    def test_node_validation(self) -> None:
        """Test Node model validation."""
        with self.assertRaises(pydantic.ValidationError):
            models.Environment.model_validate(
                {'name': 'Test'},
            )  # Missing slug


class ProjectModelTestCase(unittest.TestCase):
    """Test cases for Project model."""

    def test_project_url_validation(self) -> None:
        """Test Project URL validation."""
        # Create minimal valid related objects
        org = models.Organization.model_validate(
            {'name': 'Org', 'slug': 'org'},
        )
        team = models.Team.model_validate(
            {
                'name': 'Team',
                'slug': 'team',
                'organization': org,
            }
        )
        project_type = models.ProjectType.model_validate(
            {
                'name': 'Type',
                'slug': 'type',
                'organization': org,
            }
        )

        with self.assertRaises(pydantic.ValidationError):
            models.Project.model_validate(
                {
                    'name': 'Test',
                    'slug': 'test',
                    'team': team,
                    'project_type': project_type,
                    'links': {'repo': 'not-a-url'},
                    'urls': {},
                    'identifiers': {},
                }
            )


class WebhookCreateModelTestCase(unittest.TestCase):
    """Test cases for WebhookCreate validation."""

    def _valid_payload(
        self,
        **overrides: object,
    ) -> dict[str, object]:
        defaults: dict[str, object] = {
            'name': 'GitHub Events',
        }
        defaults.update(overrides)
        return defaults

    def test_valid_creation(self) -> None:
        obj = domain_models.WebhookCreate.model_validate(
            self._valid_payload(),
        )
        self.assertIsNone(obj.secret)
        self.assertEqual(obj.rules, [])
        self.assertIsNone(obj.integration_slug)

    def test_identifier_selector_requires_tps(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            domain_models.WebhookCreate.model_validate(
                self._valid_payload(
                    identifier_selector='$.repo.name',
                ),
            )

    def test_identifier_selector_with_tps_valid(self) -> None:
        obj = domain_models.WebhookCreate.model_validate(
            self._valid_payload(
                integration_slug='github',
                identifier_selector='$.repo.name',
            ),
        )
        self.assertEqual(obj.identifier_selector, '$.repo.name')

    def test_with_rules(self) -> None:
        obj = domain_models.WebhookCreate.model_validate(
            self._valid_payload(
                rules=[
                    {
                        'filter_expression': '$.action',
                        'handler': 'my.handler',
                    },
                ],
            ),
        )
        self.assertEqual(len(obj.rules), 1)
        self.assertEqual(obj.rules[0].handler_config, {})


class WebhookUpdateModelTestCase(unittest.TestCase):
    """Test cases for WebhookUpdate validation."""

    def test_valid_update(self) -> None:
        obj = domain_models.WebhookUpdate.model_validate(
            {
                'name': 'Updated',
                'slug': 'updated',
                'notification_path': '/updated',
            }
        )
        self.assertEqual(obj.name, 'Updated')
        self.assertEqual(obj.rules, [])

    def test_identifier_selector_requires_tps(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            domain_models.WebhookUpdate.model_validate(
                {
                    'name': 'Test',
                    'slug': 'test',
                    'notification_path': '/test',
                    'identifier_selector': '$.repo',
                }
            )


class WebhookRuleCreateModelTestCase(unittest.TestCase):
    """Test cases for WebhookRuleCreate validation."""

    def test_valid_rule(self) -> None:
        obj = domain_models.WebhookRuleCreate.model_validate(
            {
                'filter_expression': '$.action == "push"',
                'handler': 'my.module.handle_push',
            }
        )
        self.assertEqual(obj.handler_config, {})

    def test_handler_config_as_list(self) -> None:
        obj = domain_models.WebhookRuleCreate.model_validate(
            {
                'filter_expression': '$.action',
                'handler': 'my.handler',
                'handler_config': ['step1', 'step2'],
            }
        )
        self.assertEqual(obj.handler_config, ['step1', 'step2'])

    def test_empty_filter_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            domain_models.WebhookRuleCreate.model_validate(
                {
                    'filter_expression': '',
                    'handler': 'my.handler',
                }
            )

    def test_empty_handler_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            domain_models.WebhookRuleCreate.model_validate(
                {
                    'filter_expression': '$.action',
                    'handler': '',
                }
            )


class ExistsInModelTestCase(unittest.TestCase):
    """Test cases for ExistsIn models."""

    def test_exists_in_create(self) -> None:
        obj = domain_models.ExistsInCreate.model_validate(
            {
                'integration_slug': 'github',
                'identifier': 'org/repo',
            }
        )
        self.assertIsNone(obj.canonical_url)

    def test_exists_in_create_with_link(self) -> None:
        obj = domain_models.ExistsInCreate.model_validate(
            {
                'integration_slug': 'github',
                'identifier': 'org/repo',
                'canonical_url': 'https://github.com/org/repo',
            }
        )
        self.assertEqual(
            obj.canonical_url,
            'https://github.com/org/repo',
        )

    def test_exists_in_empty_identifier_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            domain_models.ExistsInCreate.model_validate(
                {
                    'integration_slug': 'github',
                    'identifier': '',
                }
            )

    def test_exists_in_response(self) -> None:
        obj = domain_models.ExistsInResponse.model_validate(
            {
                'integration_slug': 'github',
                'integration_name': 'GitHub',
                'identifier': 'org/repo',
            }
        )
        self.assertEqual(obj.integration_name, 'GitHub')
        self.assertIsNone(obj.canonical_url)


class WebhookResponseFromGraphRecordTestCase(unittest.TestCase):
    """Tests for WebhookResponse.from_graph_record.

    Apache AGE returns [{}] (a list containing one empty map) instead
    of [] when collect() is used with a map projection on a node that
    was NULL due to an OPTIONAL MATCH with no results.  This is an AGE
    quirk: standard Cypher map projection on a NULL node returns NULL
    (which collect() skips), but AGE returns {}.

    These tests verify that from_graph_record produces an empty rules
    list in all the forms the database can return "no rules".
    """

    def _minimal_record(
        self,
        **overrides: object,
    ) -> dict[str, object]:
        record: dict[str, object] = {
            'webhook': {
                'id': 'wh_test0001',
                'name': 'Test Webhook',
                'slug': 'test-webhook',
                'notification_path': '/webhooks/test',
            },
            'tps': None,
            'identifier_selector': None,
            'rules': '[]',
        }
        record.update(overrides)
        return record

    def test_age_empty_map_projection_gives_no_rules(self) -> None:
        """AGE bug: collect(r{...}) with no rows returns '[{}]' not '[]'."""
        record = self._minimal_record(rules='[{}]')
        response = domain_models.WebhookResponse.from_graph_record(record)
        self.assertEqual(response.rules, [])

    def test_age_multiple_empty_maps_gives_no_rules(self) -> None:
        """Defensive: multiple empty maps are all filtered out."""
        record = self._minimal_record(rules='[{}, {}]')
        response = domain_models.WebhookResponse.from_graph_record(record)
        self.assertEqual(response.rules, [])

    def test_empty_rules_json_string(self) -> None:
        record = self._minimal_record(rules='[]')
        response = domain_models.WebhookResponse.from_graph_record(record)
        self.assertEqual(response.rules, [])

    def test_none_rules(self) -> None:
        record = self._minimal_record(rules=None)
        response = domain_models.WebhookResponse.from_graph_record(record)
        self.assertEqual(response.rules, [])

    def test_missing_rules_key(self) -> None:
        record = self._minimal_record()
        del record['rules']  # type: ignore[arg-type]
        response = domain_models.WebhookResponse.from_graph_record(record)
        self.assertEqual(response.rules, [])

    def test_empty_python_list(self) -> None:
        """parse_agtype passes lists through unchanged."""
        record = self._minimal_record(rules=[])
        response = domain_models.WebhookResponse.from_graph_record(record)
        self.assertEqual(response.rules, [])

    def test_python_list_with_empty_dict(self) -> None:
        """parse_agtype passes [{}] through; from_graph_record filters it."""
        record = self._minimal_record(rules=[{}])
        response = domain_models.WebhookResponse.from_graph_record(record)
        self.assertEqual(response.rules, [])

    def test_with_one_rule(self) -> None:
        record = self._minimal_record(
            rules=[
                {
                    'filter_expression': '$.action == "push"',
                    'handler': 'my.module.handle_push',
                    'handler_config': '{"branch": "main"}',
                },
            ],
        )
        response = domain_models.WebhookResponse.from_graph_record(record)
        self.assertEqual(len(response.rules), 1)
        self.assertEqual(response.rules[0].handler, 'my.module.handle_push')
        self.assertEqual(
            response.rules[0].handler_config,
            {'branch': 'main'},
        )

    def test_rule_with_missing_handler_config(self) -> None:
        """handler_config absent in rule defaults to {}."""
        record = self._minimal_record(
            rules=[
                {
                    'filter_expression': '$.action',
                    'handler': 'my.handler',
                },
            ],
        )
        response = domain_models.WebhookResponse.from_graph_record(record)
        self.assertEqual(response.rules[0].handler_config, {})

    def test_with_tps_and_identifier_selector(self) -> None:
        record = self._minimal_record(
            tps={'name': 'GitHub', 'slug': 'github'},
            identifier_selector='$.repository.full_name',
        )
        response = domain_models.WebhookResponse.from_graph_record(record)
        self.assertIsNotNone(response.integration)
        assert response.integration is not None
        self.assertEqual(response.integration['slug'], 'github')
        self.assertEqual(
            response.identifier_selector,
            '$.repository.full_name',
        )

    def test_without_tps(self) -> None:
        record = self._minimal_record(tps=None, identifier_selector=None)
        response = domain_models.WebhookResponse.from_graph_record(record)
        self.assertIsNone(response.integration)
        self.assertIsNone(response.identifier_selector)
