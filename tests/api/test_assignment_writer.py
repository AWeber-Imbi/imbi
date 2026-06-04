"""Tests for ``imbi_api.plugins.assignment_writer``.

Focuses on the Cypher-template construction: the fused delete+UNWIND
write is a pure transformation of inputs to query+params, so direct
template assertions are tighter and faster than a graph round-trip
through the endpoint tests.
"""

import asyncio
import json
import unittest
import unittest.mock as mock

from imbi_api.plugins.assignment_writer import (
    _assignment_rows_template,
    replace_assignments,
)
from imbi_api.plugins.assignments import PluginAssignmentRow


class AssignmentRowsTemplateTestCase(unittest.TestCase):
    def test_empty_rows_yields_empty_literal(self) -> None:
        tpl, params = _assignment_rows_template([])
        self.assertEqual(tpl, '[]')
        self.assertEqual(params, {})

    def test_serializes_options_and_env_payloads_as_json(self) -> None:
        row: PluginAssignmentRow = {
            'plugin_id': 'p1',
            'plugin_type': 'configuration',
            'default': True,
            'options': {'k': 'v'},
            'identity_plugin_id': None,
            'env_payloads': {'prod': {'inputs': {'a': 1}}},
        }
        _, params = _assignment_rows_template([row])
        self.assertEqual(params['asgn_0_options'], json.dumps({'k': 'v'}))
        self.assertEqual(
            params['asgn_0_env_payloads'],
            json.dumps({'prod': {'inputs': {'a': 1}}}),
        )
        self.assertIsNone(params['asgn_0_identity_plugin_id'])

    def test_empty_env_payloads_collapse_to_null(self) -> None:
        row: PluginAssignmentRow = {
            'plugin_id': 'p1',
            'plugin_type': 'configuration',
            'default': True,
            'options': {},
            'identity_plugin_id': None,
            'env_payloads': {},
        }
        _, params = _assignment_rows_template([row])
        self.assertIsNone(params['asgn_0_env_payloads'])


class ReplaceAssignmentsQueryTestCase(unittest.TestCase):
    """Snapshot tests for the fused delete+create query."""

    def _captured_call(
        self, rows: list[PluginAssignmentRow], **kwargs: str
    ) -> tuple[str, dict[str, object]]:
        db = mock.MagicMock()
        db.execute = mock.AsyncMock(return_value=[])
        asyncio.run(replace_assignments(db, rows=rows, **kwargs))  # type: ignore[arg-type]
        args, _ = db.execute.call_args
        return args[0], args[1]

    def test_project_with_rows_emits_single_fused_query(self) -> None:
        rows: list[PluginAssignmentRow] = [
            {
                'plugin_id': 'p1',
                'plugin_type': 'configuration',
                'default': True,
                'options': {},
                'identity_plugin_id': None,
                'env_payloads': None,  # type: ignore[typeddict-item]
            }
        ]
        query, params = self._captured_call(
            rows,
            parent_label='Project',
            parent_key='id',
            parent_value='proj-1',
            org_slug='myorg',
        )
        self.assertIn('OPTIONAL MATCH (parent)-[old:USES_PLUGIN]', query)
        self.assertIn('DELETE old', query)
        self.assertIn('UNWIND', query)
        self.assertIn('CREATE (parent)-[:USES_PLUGIN', query)
        self.assertIn(':Team', query)
        # The post-DELETE rows must be collapsed before the UNWIND, else
        # a parent with K prior edges yields K x N duplicate edges.
        self.assertIn('count(old)', query)
        self.assertEqual(params['parent_value'], 'proj-1')
        self.assertEqual(params['org_slug'], 'myorg')
        self.assertEqual(params['asgn_0_plugin_id'], 'p1')

    def test_project_type_uses_belongs_to_chain(self) -> None:
        rows: list[PluginAssignmentRow] = []
        query, _ = self._captured_call(
            rows,
            parent_label='ProjectType',
            parent_key='slug',
            parent_value='web',
            org_slug='myorg',
        )
        self.assertIn('-[:BELONGS_TO]->', query)
        self.assertNotIn(':Team', query)
        self.assertNotIn('UNWIND', query)

    def test_empty_rows_emits_delete_only(self) -> None:
        query, _ = self._captured_call(
            [],
            parent_label='Project',
            parent_key='id',
            parent_value='proj-1',
            org_slug='myorg',
        )
        self.assertIn('DELETE old', query)
        self.assertNotIn('CREATE', query)
        self.assertNotIn('UNWIND', query)


if __name__ == '__main__':
    unittest.main()
