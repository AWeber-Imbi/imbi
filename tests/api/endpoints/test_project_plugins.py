"""Tests for the project plugins read-projection endpoint."""

import typing
import unittest
from unittest import mock

import fastapi

from imbi_api.endpoints import project_plugins as pp

_GHEC = {
    'id': 'int-1',
    'plugin': 'github',
    'name': 'GHEC',
    'icon': 'si-github',
    'capabilities': {
        'identity': {'enabled': True},
        'deployment': {'enabled': True},
    },
}


def _binding(**over: typing.Any) -> mock.MagicMock:
    binding = mock.MagicMock()
    binding.integration = over.get('integration', _GHEC)
    binding.source = over.get('source', 'project_type')
    binding.default = over.get('default', False)
    binding.capability_options = over.get('capability_options', {})
    binding.env_payloads = over.get('env_payloads', {})
    binding.identity_integration_id = over.get('identity_integration_id')
    return binding


def _cap(**hints: typing.Any) -> mock.MagicMock:
    return mock.MagicMock(hints=hints)


class ToResponseTestCase(unittest.TestCase):
    def test_self_resolves_identity_and_maps_fields(self) -> None:
        resp = pp._to_response(
            _binding(), 'deployment', _cap(supports_deployment_sync=True)
        )
        self.assertEqual(resp.plugin_type, 'deployment')
        self.assertEqual(resp.plugin_id, 'int-1')
        self.assertEqual(resp.plugin_slug, 'github')
        self.assertEqual(resp.label, 'GHEC')
        self.assertEqual(resp.service_icon, 'si-github')
        # No explicit binding -> defaults to the serving integration.
        self.assertEqual(resp.identity_plugin_id, 'int-1')
        self.assertTrue(resp.supports_deployment_sync)
        self.assertEqual(resp.source, 'project_type')

    def test_prefers_explicit_identity_binding(self) -> None:
        resp = pp._to_response(
            _binding(identity_integration_id='other'), 'deployment', _cap()
        )
        self.assertEqual(resp.identity_plugin_id, 'other')

    def test_no_identity_when_integration_lacks_capability(self) -> None:
        integ = {
            'id': 'int-2',
            'plugin': 'sonarqube',
            'name': 'SonarQube',
            'capabilities': {'analysis': {'enabled': True}},
        }
        resp = pp._to_response(_binding(integration=integ), 'analysis', _cap())
        self.assertIsNone(resp.identity_plugin_id)

    def test_default_all_source_maps_to_merged(self) -> None:
        resp = pp._to_response(_binding(source='default_all'), 'logs', _cap())
        self.assertEqual(resp.source, 'merged')


class ListProjectPluginsTestCase(unittest.IsolatedAsyncioTestCase):
    def _entry(self) -> mock.MagicMock:
        entry = mock.MagicMock()
        dep, ident = mock.MagicMock(), mock.MagicMock()
        dep.kind, ident.kind = 'deployment', 'identity'
        entry.manifest.capabilities = [dep, ident]
        caps = {
            'deployment': _cap(supports_deployment_sync=True),
            'identity': _cap(),
        }
        entry.manifest.get_capability.side_effect = caps.get
        return entry

    async def test_emits_entry_per_enabled_bound_capability(self) -> None:
        entry = self._entry()
        bindings = {'deployment': [_binding()], 'identity': [_binding()]}
        with (
            mock.patch.object(pp, 'list_plugins', return_value=[entry]),
            mock.patch.object(pp, 'get_plugin', return_value=entry),
            mock.patch.object(
                pp,
                'effective_bindings',
                new=mock.AsyncMock(
                    side_effect=lambda _db, _pid, kind: bindings.get(kind, [])
                ),
            ),
            mock.patch.object(
                pp, 'is_plugin_enabled', new=mock.AsyncMock(return_value=True)
            ),
        ):
            out = await pp.list_project_plugins(
                'org', 'proj', mock.AsyncMock(), mock.MagicMock()
            )
        kinds = sorted(r.plugin_type for r in out)
        self.assertEqual(kinds, ['deployment', 'identity'])

    async def test_skips_disabled_plugins(self) -> None:
        entry = self._entry()
        with (
            mock.patch.object(pp, 'list_plugins', return_value=[entry]),
            mock.patch.object(pp, 'get_plugin', return_value=entry),
            mock.patch.object(
                pp,
                'effective_bindings',
                new=mock.AsyncMock(return_value=[_binding()]),
            ),
            mock.patch.object(
                pp, 'is_plugin_enabled', new=mock.AsyncMock(return_value=False)
            ),
        ):
            out = await pp.list_project_plugins(
                'org', 'proj', mock.AsyncMock(), mock.MagicMock()
            )
        self.assertEqual(out, [])

    async def test_missing_project_raises_404(self) -> None:
        entry = self._entry()
        with (
            mock.patch.object(pp, 'list_plugins', return_value=[entry]),
            mock.patch.object(
                pp,
                'effective_bindings',
                new=mock.AsyncMock(side_effect=LookupError('nope')),
            ),
            self.assertRaises(fastapi.HTTPException) as cm,
        ):
            await pp.list_project_plugins(
                'org', 'proj', mock.AsyncMock(), mock.MagicMock()
            )
        self.assertEqual(cm.exception.status_code, 404)
