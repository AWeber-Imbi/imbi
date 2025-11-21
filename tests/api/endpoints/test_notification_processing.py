from __future__ import annotations

import json
import unittest
import uuid

import pydantic

from imbi import common
from tests import base


class AsyncHTTPTestCase(base.TestCaseWithReset):
    ADMIN_ACCESS = True
    TRUNCATE_TABLES = [
        'v1.projects',
        'v1.environments',
        'v1.namespaces',
        'v1.notification_filters',
        'v1.notification_rules',
        'v1.integration_notifications',
        'v1.integrations',
        'v1.project_types',
    ]

    def setUp(self) -> None:
        super().setUp()
        self.project = self.create_project()
        self.project_fact_type = self.create_project_fact_type()
        self.integration_name = 'some-app'
        self.notification_name = 'pipeline'
        self.surrogate_id = str(uuid.uuid4())

        rsp = self.fetch('/integrations',
                         method='POST',
                         json_body={
                             'name': self.integration_name,
                             'api_endpoint': 'https://integration.example.com',
                             'api_secret': None,
                         })
        self.assertEqual(200, rsp.code)

        rsp = self.fetch(
            f'/integrations/{self.integration_name}/notifications',
            method='POST',
            json_body={
                'name': self.notification_name,
                'id_pattern': '/id',
                'documentation': None,
                'default_action': 'process',
                'verification_token': None,
            })
        self.assertEqual(200, rsp.code)

        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/rules',
            method='POST',
            json_body={
                'fact_type_id': self.project_fact_type['id'],
                'pattern': '/state',
            })
        self.assertEqual(200, rsp.code)

        rsp = self.fetch(f'/projects/{self.project["id"]}/identifiers',
                         method='POST',
                         json_body={
                             'external_id': self.surrogate_id,
                             'integration_name': self.integration_name,
                         })
        self.assertEqual(200, rsp.code)

    def get_project_fact(self, *, project_id=None, fact_id=None) -> str | None:
        project_id = self.project['id'] if project_id is None else project_id
        rsp = self.fetch(f'/projects/{project_id}/facts')
        self.assertEqual(200, rsp.code)

        fact_id = self.project_fact_type['id'] if fact_id is None else fact_id
        facts = json.loads(rsp.body)
        if facts:
            self.assertEqual(1, len(facts))
            self.assertEqual(fact_id, facts[0]['fact_type_id'])
            return facts[0]['value']
        return None

    def test_processing_with_empty_notification(self) -> None:
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={})
        self.assertEqual(200, rsp.code)

    def test_processing_correct_notification(self) -> None:
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'whatever'
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual('whatever', self.get_project_fact())

    def test_processing_correct_notification_with_get(self) -> None:
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/get?id={self.surrogate_id}&state=whatever',
            method='GET',
        )
        self.assertEqual(200, rsp.code)
        self.assertEqual('whatever', self.get_project_fact())

    def test_processing_correct_notification_with_put(self) -> None:
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/put',
            method='PUT',
            json_body={
                'id': self.surrogate_id,
                'state': 'whatever'
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual('whatever', self.get_project_fact())

    def test_processing_invalid_notification_paths(self) -> None:
        rsp = self.fetch('/integrations/invalid/notifications/invalid/post',
                         method='POST',
                         json_body={})
        self.assertEqual(404, rsp.code)

        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            '/notifications/invalid/post',
            method='POST',
            json_body={})
        self.assertEqual(404, rsp.code)

        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}/get',
            method='POST',
            json_body={})
        self.assertEqual(400, rsp.code)

    def test_filters_for_default_process(self) -> None:
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}/filters',
            method='POST',
            json_body={
                'name': 'reject-tests',
                'pattern': '/test',
                'operation': '==',
                'value': 'true',
                'action': 'ignore'
            })
        self.assertEqual(200, rsp.code)

        # test that matching ignore filter actually ignores
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'whatever',
                'test': 'true',
            })
        self.assertEqual(200, rsp.code)
        self.assertIsNone(self.get_project_fact(),
                          'Matched filter did not ignore update')

        # test that non-matching ignore filter does not ignore
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'whatever',
                'test': 'false',
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual('whatever', self.get_project_fact(),
                         'Unmatched filter ignored update')

        # test that lack of filter condition does not ignore
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'something-else',
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual('something-else', self.get_project_fact(),
                         'Unmatched filter ignored update')

    def test_filters_for_default_ignore(self) -> None:
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}',
            method='PATCH',
            json_body=[{
                'op': 'replace',
                'path': '/default_action',
                'value': 'ignore'
            }])
        self.assertEqual(200, rsp.code)

        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}/filters',
            method='POST',
            json_body={
                'name': 'accept-non-tests',
                'pattern': '/test',
                'operation': '!=',
                'value': 'true',
                'action': 'process'
            })
        self.assertEqual(200, rsp.code)

        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}/filters',
            method='POST',
            json_body={
                'name': 'accept-production',
                'pattern': '/environment',
                'operation': '==',
                'value': 'production',
                'action': 'process'
            })
        self.assertEqual(200, rsp.code)

        # test that non-matching filter ignores
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'whatever',
                'test': 'true',
            })
        self.assertEqual(200, rsp.code)
        self.assertIsNone(self.get_project_fact(),
                          'Unmatched filter did not ignore update')

        # test that matching partial filter does not ignore
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'whatever',
                'test': 'false',
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual('whatever', self.get_project_fact(),
                         'Partial filter match ignored update')

        # test that matching full filter does not ignore
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'something-else',
                'test': 'false',
                'environment': 'production',
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual('something-else', self.get_project_fact(),
                         'Full filter match ignored update')

        # test that half match of filter condition applies
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'yet-another-thing',
                'test': 'false',
                'environment': 'local',
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual('yet-another-thing', self.get_project_fact(),
                         'Half-matched filter ignored update')

        # test that lack of filter condition ignores
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'yet-another-another-thing',
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual('yet-another-thing', self.get_project_fact(),
                         'Unmatched filter applied update')

    def test_different_project_type(self) -> None:
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/filters',
            method='POST',
            json_body={
                'name': 'reject-testing',
                'pattern': '/environment',
                'operation': '!=',
                'value': 'production',
                'action': 'ignore'
            })
        self.assertEqual(200, rsp.code)

        surrogate_id = str(uuid.uuid4())
        new_project_type = self.create_project_type()
        new_project = self.create_project(
            project_type_id=new_project_type['id'])
        rsp = self.fetch(f'/projects/{new_project["id"]}/identifiers',
                         method='POST',
                         json_body={
                             'external_id': surrogate_id,
                             'integration_name': self.integration_name,
                         })
        self.assertEqual(200, rsp.code)

        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/get?id={surrogate_id}&environment=production&state=matched', )
        self.assertEqual(200, rsp.code)
        self.assertIsNone(
            self.get_project_fact(project_id=new_project['id']),
            'Fact should not be updated for different project type')

    def test_get_with_multiple_query_args(self) -> None:
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/get?id={self.surrogate_id}&state=whatever&state=another',
            method='GET',
        )
        self.assertEqual(422, rsp.code)

    def test_nullifying_a_property(self) -> None:
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/get?id={self.surrogate_id}&state',
            method='GET',
        )
        self.assertEqual(200, rsp.code)
        self.assertIsNone(self.get_project_fact(),
                          'Project fact failed to update to None')

    def test_incompatible_fact_value(self) -> None:
        rsp = self.fetch(f'/project-fact-types/{self.project_fact_type["id"]}',
                         method='PATCH',
                         json_body=[{
                             'op': 'replace',
                             'path': '/data_type',
                             'value': 'date'
                         }])
        self.assertEqual(200, rsp.code, 'Failed to update project fact type')

        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'yet-another-thing',
            })
        self.assertEqual(500, rsp.code)

    def test_notification_with_rules_for_different_project_types(self) -> None:
        other_project_type = self.create_project_type()
        other_fact_type = self.create_project_fact_type(
            project_type_ids=[other_project_type['id']])

        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/rules',
            method='POST',
            json_body={
                'fact_type_id': other_fact_type['id'],
                'pattern': '/state',
            })
        self.assertEqual(200, rsp.code)

        other_project = self.create_project(
            project_type_id=other_project_type['id'])
        other_surrogate = str(uuid.uuid4())
        rsp = self.fetch(f'/projects/{other_project["id"]}/identifiers',
                         method='POST',
                         json_body={
                             'external_id': other_surrogate,
                             'integration_name': self.integration_name,
                         })
        self.assertEqual(200, rsp.code)

        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'whatever'
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual('whatever', self.get_project_fact())

        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': other_surrogate,
                'state': 'something-else'
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual(
            'something-else',
            self.get_project_fact(project_id=other_project['id'],
                                  fact_id=other_fact_type['id']))

    def test_notifying_without_imbi_project_match(self) -> None:
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': str(uuid.uuid4()),
                'state': 'whatever'
            })
        self.assertEqual(200, rsp.code)

    def test_cel_expression_passes_filter(self) -> None:
        """Test CEL expression evaluating to True updates the fact"""
        # Update the rule to include a CEL expression that will match
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/rules/{self.project_fact_type["id"]}',
            method='PATCH',
            json_body=[{
                'op': 'add',
                'path': '/filter_expression',
                'value': 'state == "success"',
            }])
        self.assertEqual(200, rsp.code)

        # Send notification that matches CEL expression
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'success'
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual('success', self.get_project_fact())

    def test_cel_expression_filters_out(self) -> None:
        """Test CEL expression evaluating to False skips update"""
        # Update the rule to include a CEL expression that won't match
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/rules/{self.project_fact_type["id"]}',
            method='PATCH',
            json_body=[{
                'op': 'add',
                'path': '/filter_expression',
                'value': 'state == "success"',
            }])
        self.assertEqual(200, rsp.code)

        # Send notification that doesn't match CEL expression
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'failure'
            })
        self.assertEqual(200, rsp.code)
        self.assertIsNone(
            self.get_project_fact(),
            'CEL expression should have filtered out this update')

    def test_cel_expression_with_boolean_logic(self) -> None:
        """Test CEL expression with AND logic"""
        # Update rule with complex CEL expression
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/rules/{self.project_fact_type["id"]}',
            method='PATCH',
            json_body=[{
                'op': 'add',
                'path': '/filter_expression',
                'value': 'state == "success" && branch == "main"',
            }])
        self.assertEqual(200, rsp.code)

        # Test case 1: Matches both conditions
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'success',
                'branch': 'main'
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual('success', self.get_project_fact())

        # Delete the fact for next test
        rsp = self.fetch(
            f'/projects/{self.project["id"]}/facts/'
            f'{self.project_fact_type["id"]}',
            method='DELETE')
        self.assertEqual(204, rsp.code)

        # Test case 2: First condition matches but not second
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'success',
                'branch': 'develop'
            })
        self.assertEqual(200, rsp.code)
        self.assertIsNone(
            self.get_project_fact(),
            'CEL AND expression should have filtered out this update')

    def test_cel_expression_backward_compatibility(self) -> None:
        """Test rules without CEL expression still work"""
        # Rule created in setUp() without filter_expression
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'state': 'any-value'
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual('any-value', self.get_project_fact())

    def test_invalid_cel_syntax_rejected_on_create(self) -> None:
        """Test that invalid CEL syntax is rejected when creating a rule"""
        # Create a second fact type for this test
        fact_type = self.create_project_fact_type()

        # Attempt to create rule with invalid CEL expression
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/rules',
            method='POST',
            json_body={
                'fact_type_id': fact_type['id'],
                'pattern': '/state',
                'filter_expression': 'invalid syntax here ==',  # Invalid CEL
            })
        self.assertEqual(400, rsp.code)
        body = json.loads(rsp.body)
        self.assertIn('Invalid CEL expression', body.get('title', ''))

    def test_invalid_cel_syntax_rejected_on_update(self) -> None:
        """Test that invalid CEL syntax is rejected when updating a rule"""
        # Attempt to update rule with invalid CEL expression
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/rules/{self.project_fact_type["id"]}',
            method='PATCH',
            json_body=[{
                'op': 'add',
                'path': '/filter_expression',
                'value': '== "missing operand"',  # Invalid CEL
            }])
        self.assertEqual(400, rsp.code)
        body = json.loads(rsp.body)
        self.assertIn('Invalid CEL expression', body.get('title', ''))

    def test_cel_expression_with_notification_filters(self) -> None:
        """Test notification filters and rule CEL work together"""
        # Add notification-level filter
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}/filters',
            method='POST',
            json_body={
                'name': 'only-completed',
                'pattern': '/action',
                'operation': '==',
                'value': 'completed',
                'action': 'process'
            })
        self.assertEqual(200, rsp.code)

        # Add CEL expression to rule
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/rules/{self.project_fact_type["id"]}',
            method='PATCH',
            json_body=[{
                'op': 'add',
                'path': '/filter_expression',
                'value': 'branch == "main"',
            }])
        self.assertEqual(200, rsp.code)

        # Test case 1: Passes both notification filter and CEL expression
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'action': 'completed',
                'branch': 'main',
                'state': 'success'
            })
        self.assertEqual(200, rsp.code)
        self.assertEqual('success', self.get_project_fact())

        # Delete fact for next test
        rsp = self.fetch(
            f'/projects/{self.project["id"]}/facts/'
            f'{self.project_fact_type["id"]}',
            method='DELETE')
        self.assertEqual(204, rsp.code)

        # Test case 2: Fails notification filter (should not reach CEL check)
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}'
            f'/post',
            method='POST',
            json_body={
                'id': self.surrogate_id,
                'action': 'started',  # Doesn't match notification filter
                'branch': 'main',
                'state': 'running'
            })
        self.assertEqual(200, rsp.code)
        self.assertIsNone(self.get_project_fact())


class CELEvaluationTests(base.TestCaseWithReset):
    """Unit tests for CEL expression evaluation function"""
    ADMIN_ACCESS = True
    TRUNCATE_TABLES = [
        'v1.projects',
        'v1.notification_rules',
        'v1.integration_notifications',
        'v1.automations',
        'v1.integrations',
        'v1.project_types',
    ]

    def setUp(self) -> None:
        super().setUp()
        self.project = self.create_project()
        self.project_fact_type = self.create_project_fact_type()
        self.integration_name = 'test-app'
        self.notification_name = 'test-notification'
        self.surrogate_id = str(uuid.uuid4())

        # Create minimal integration and notification for testing
        rsp = self.fetch('/integrations',
                         method='POST',
                         json_body={
                             'name': self.integration_name,
                             'api_endpoint': 'https://test.example.com',
                             'api_secret': None,
                         })
        self.assertEqual(200, rsp.code)

        rsp = self.fetch(
            f'/integrations/{self.integration_name}/notifications',
            method='POST',
            json_body={
                'name': self.notification_name,
                'id_pattern': '/id',
                'documentation': None,
                'default_action': 'process',
                'verification_token': None,
            })
        self.assertEqual(200, rsp.code)

    def test_cel_boolean_operators(self) -> None:
        """Test CEL boolean operators (&&, ||, !)"""
        # Create rule with AND operator
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}/rules',
            method='POST',
            json_body={
                'fact_type_id': self.project_fact_type['id'],
                'pattern': '/value',
                'filter_expression': 'status == "pass"'
                ' && environment == "prod"',
            })
        self.assertEqual(200, rsp.code)

    def test_cel_comparison_operators(self) -> None:
        """Test CEL comparison operators (==, !=, <, >, <=, >=)"""
        # Test equality
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}/rules',
            method='POST',
            json_body={
                'fact_type_id': self.project_fact_type['id'],
                'pattern': '/value',
                'filter_expression': 'count > 10',
            })
        self.assertEqual(200, rsp.code)

    def test_cel_string_methods(self) -> None:
        """Test CEL string methods (startsWith, endsWith, contains)"""
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}/rules',
            method='POST',
            json_body={
                'fact_type_id': self.project_fact_type['id'],
                'pattern': '/value',
                'filter_expression': 'branch.startsWith("release/")',
            })
        self.assertEqual(200, rsp.code)

    def test_cel_in_operator(self) -> None:
        """Test CEL 'in' operator for list membership"""
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}/rules',
            method='POST',
            json_body={
                'fact_type_id': self.project_fact_type['id'],
                'pattern': '/value',
                'filter_expression': 'status in '
                '["success", "pass", "completed"]',
            })
        self.assertEqual(200, rsp.code)

    def test_cel_has_function(self) -> None:
        """Test CEL has() function for optional field checking"""
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}/rules',
            method='POST',
            json_body={
                'fact_type_id': self.project_fact_type['id'],
                'pattern': '/value',
                'filter_expression': 'has(conclusion)'
                ' && conclusion == "success"',
            })
        self.assertEqual(200, rsp.code)

    def test_cel_nested_field_access(self) -> None:
        """Test CEL nested field access with dot notation"""
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}/rules',
            method='POST',
            json_body={
                'fact_type_id': self.project_fact_type['id'],
                'pattern': '/value',
                'filter_expression': 'workflow.run.status == "completed"',
            })
        self.assertEqual(200, rsp.code)

    def test_cel_complex_nested_logic(self) -> None:
        """Test CEL with complex nested boolean logic"""
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}/rules',
            method='POST',
            json_body={
                'fact_type_id': self.project_fact_type['id'],
                'pattern': '/value',
                'filter_expression': '(environment == "prod" '
                '&& status == "success") '
                '|| (environment == "staging" '
                '&& branch.startsWith("release/"))',
            })
        self.assertEqual(200, rsp.code)

    def test_cel_ternary_operator(self) -> None:
        """Test CEL ternary operator for conditional expressions"""
        rsp = self.fetch(
            f'/integrations/{self.integration_name}'
            f'/notifications/{self.notification_name}/rules',
            method='POST',
            json_body={
                'fact_type_id': self.project_fact_type['id'],
                'pattern': '/value',
                'filter_expression': 'has(environment) '
                '? environment == "production" : false',
            })
        self.assertEqual(200, rsp.code)


class EdgeTests(unittest.TestCase):

    def test_json_pointer_validation(self) -> None:
        Adapter = pydantic.TypeAdapter(common.JsonPointer)
        with self.assertRaises(TypeError):
            Adapter.validate_python(1.0)
        with self.assertRaises(ValueError):
            Adapter.validate_python('not-a-slash')
        with self.assertRaises(ValueError):
            Adapter.validate_python('')
