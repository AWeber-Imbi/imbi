"""Unit tests for :mod:`imbi.api.plugins.assignments`."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest import mock

from imbi.api.plugins import assignments


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


class HydrateIntegrationTestCase(unittest.TestCase):
    def test_decodes_json_string_map_fields(self) -> None:
        props = {
            'id': 'i1',
            'slug': 'gh',
            'plugin': 'github',
            'options': json.dumps({'host': 'github.com'}),
            'capabilities': json.dumps({'logs': {'enabled': True}}),
            'encrypted_credentials': json.dumps({'token': 'x'}),
            'links': json.dumps({'web': 'u'}),
            'identifiers': json.dumps({'org': 1}),
        }
        out = assignments.hydrate_integration(props)
        self.assertEqual(out['options'], {'host': 'github.com'})
        self.assertEqual(out['capabilities'], {'logs': {'enabled': True}})
        self.assertEqual(out['encrypted_credentials'], {'token': 'x'})
        self.assertEqual(out['links'], {'web': 'u'})
        self.assertEqual(out['identifiers'], {'org': 1})

    def test_missing_fields_default_to_empty(self) -> None:
        out = assignments.hydrate_integration({'id': 'i1'})
        self.assertEqual(out['options'], {})
        self.assertEqual(out['capabilities'], {})


class CapabilityStateTestCase(unittest.TestCase):
    def test_returns_state_for_kind(self) -> None:
        integration = {
            'capabilities': {'logs': {'enabled': True, 'options': {}}}
        }
        self.assertEqual(
            assignments.capability_state(integration, 'logs'),
            {'enabled': True, 'options': {}},
        )

    def test_absent_kind_returns_empty(self) -> None:
        self.assertEqual(assignments.capability_state({}, 'logs'), {})

    def test_enabled_true_and_false(self) -> None:
        self.assertTrue(
            assignments.capability_enabled(
                {'capabilities': {'logs': {'enabled': True}}}, 'logs'
            )
        )
        self.assertFalse(
            assignments.capability_enabled(
                {'capabilities': {'logs': {'enabled': False}}}, 'logs'
            )
        )
        self.assertFalse(assignments.capability_enabled({}, 'logs'))


class MergeEnvPayloadsTestCase(unittest.TestCase):
    def test_project_edge_wins_per_env(self) -> None:
        ptype = json.dumps({'prod': {'a': 1, 'b': 2}})
        project = json.dumps({'prod': {'b': 3}, 'stg': {'c': 4}})
        merged = assignments.merge_env_payloads(ptype, project)
        self.assertEqual(merged['prod'], {'a': 1, 'b': 3})
        self.assertEqual(merged['stg'], {'c': 4})

    def test_ignores_non_dict_payloads(self) -> None:
        merged = assignments.merge_env_payloads(
            json.dumps({'prod': 'nope'}), json.dumps({'stg': {'c': 4}})
        )
        self.assertEqual(merged, {'stg': {'c': 4}})


class EncodeOptionsTestCase(unittest.TestCase):
    def test_encodes_dict(self) -> None:
        self.assertEqual(assignments.encode_options({'a': 1}), '{"a": 1}')

    def test_encodes_empty(self) -> None:
        self.assertEqual(assignments.encode_options({}), '{}')


class EffectiveBindingsTestCase(unittest.TestCase):
    def _project_context(
        self,
        org_slug: str = 'org',
        proj_edges: list | None = None,
        ptype_edges: list | None = None,
    ) -> list[dict]:
        return [
            {
                'org_slug': org_slug,
                'proj_edges': proj_edges or [],
                'ptype_edges': ptype_edges or [],
            }
        ]

    def _integration(self, iid: str, *, enabled: bool = True) -> dict:
        return {
            'id': iid,
            'slug': f'int-{iid}',
            'plugin': 'github',
            'capabilities': json.dumps(
                {'logs': {'enabled': enabled, 'options': {'base': 1}}}
            ),
            'options': json.dumps({}),
        }

    def test_project_not_found_raises_lookup(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        with self.assertRaises(LookupError):
            _run(assignments.effective_bindings(db, 'p1', 'logs'))

    def test_default_all_binds_unassigned_integration(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = [
            self._project_context(),  # project context
            [{'i': self._integration('1')}],  # org integrations
            [{'ids': []}],  # assigned type ids -> none
        ]
        bindings = _run(assignments.effective_bindings(db, 'p1', 'logs'))
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0].source, 'default_all')
        self.assertFalse(bindings[0].default)
        # capability base options carry through
        self.assertEqual(bindings[0].capability_options, {'base': 1})

    def test_disabled_capability_excluded(self) -> None:
        db = mock.AsyncMock()
        db.execute.side_effect = [
            self._project_context(),
            [{'i': self._integration('1', enabled=False)}],
            [{'ids': []}],
        ]
        bindings = _run(assignments.effective_bindings(db, 'p1', 'logs'))
        self.assertEqual(bindings, [])

    def test_assigned_elsewhere_not_default_all(self) -> None:
        db = mock.AsyncMock()
        # integration is assigned to some project type (in assigned_ids)
        # but not to THIS project/type -> excluded.
        db.execute.side_effect = [
            self._project_context(),
            [{'i': self._integration('1')}],
            [{'ids': ['1']}],
        ]
        bindings = _run(assignments.effective_bindings(db, 'p1', 'logs'))
        self.assertEqual(bindings, [])

    def test_project_edge_overrides_options_and_marks_default(self) -> None:
        db = mock.AsyncMock()
        proj_edges = [
            {
                'id': '1',
                'options': json.dumps({'over': 2}),
                'env_payloads': None,
                'default': True,
                'identity_integration_id': None,
            }
        ]
        db.execute.side_effect = [
            self._project_context(proj_edges=proj_edges),
            [{'i': self._integration('1')}],
            [{'ids': ['1']}],
        ]
        bindings = _run(assignments.effective_bindings(db, 'p1', 'logs'))
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0].source, 'project')
        self.assertTrue(bindings[0].default)
        self.assertEqual(
            bindings[0].capability_options, {'base': 1, 'over': 2}
        )


if __name__ == '__main__':
    unittest.main()
