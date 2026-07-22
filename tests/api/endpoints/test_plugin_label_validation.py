"""Verify plugin label/edge names are validated before Cypher interpolation.

The endpoints in :mod:`imbi.api.endpoints.plugin_entities` and
:mod:`imbi.api.endpoints.plugin_edges` interpolate label and
relationship-type strings directly into Cypher queries. A malformed
plugin manifest must not be able to break out of the label position.
"""

import unittest
from unittest import mock

import fastapi

from imbi.api.endpoints import plugin_edges, plugin_entities
from imbi.common.plugins.base import (
    Capability,
    ConfigurationCapability,
    PluginEdgeLabel,
    PluginManifest,
    PluginVertexLabel,
)
from imbi.common.plugins.registry import RegistryEntry
from tests.api import support


class _FakeConfiguration(ConfigurationCapability):
    async def list_keys(self, ctx, credentials):  # type: ignore[override]
        return []

    async def get_values(self, ctx, credentials, keys=None):  # type: ignore[override]
        return []

    async def set_value(self, ctx, credentials, key, value):  # type: ignore[override]
        raise NotImplementedError

    async def delete_key(self, ctx, credentials, key):  # type: ignore[override]
        return None


def _registry_entry(
    *,
    vertex_labels: list[PluginVertexLabel] | None = None,
    edge_labels: list[PluginEdgeLabel] | None = None,
) -> RegistryEntry:
    manifest = PluginManifest(
        slug='evil',
        name='Evil Plugin',
        vertex_labels=vertex_labels or [],
        edge_labels=edge_labels or [],
        capabilities=[
            Capability(
                kind='configuration',
                label='Configuration',
                handler=_FakeConfiguration,
            )
        ],
    )

    return support.registry_entry(manifest)


class ResolveLabelValidationTests(unittest.IsolatedAsyncioTestCase):
    def test_valid_label_resolves(self) -> None:
        entry = _registry_entry(
            vertex_labels=[
                PluginVertexLabel(
                    name='AwsAccount',
                    model_ref='imbi.common.models:Organization',
                )
            ]
        )
        with mock.patch.object(
            plugin_entities, 'get_plugin', return_value=entry
        ):
            _model, vlabel = plugin_entities._resolve_label(
                'evil', 'AwsAccount'
            )
        self.assertEqual(vlabel, 'AwsAccount')

    def test_malicious_label_with_space_is_rejected(self) -> None:
        entry = _registry_entry(
            vertex_labels=[
                PluginVertexLabel(
                    name='Node) DETACH DELETE n MATCH (x',
                    model_ref='imbi.common.models:Organization',
                )
            ]
        )
        with mock.patch.object(
            plugin_entities, 'get_plugin', return_value=entry
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                plugin_entities._resolve_label(
                    'evil', 'Node) DETACH DELETE n MATCH (x'
                )
        self.assertEqual(ctx.exception.status_code, 500)

    def test_label_starting_with_digit_is_rejected(self) -> None:
        entry = _registry_entry(
            vertex_labels=[
                PluginVertexLabel(
                    name='1Bad',
                    model_ref='imbi.common.models:Organization',
                )
            ]
        )
        with mock.patch.object(
            plugin_entities, 'get_plugin', return_value=entry
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                plugin_entities._resolve_label('evil', '1Bad')
        self.assertEqual(ctx.exception.status_code, 500)


class ResolveEdgeValidationTests(unittest.IsolatedAsyncioTestCase):
    def test_malicious_rel_type_is_rejected(self) -> None:
        with self.assertRaises(fastapi.HTTPException) as ctx:
            plugin_edges.resolve_edge_for(
                'Environment',
                'MAPS_TO]->() DETACH DELETE x MATCH (a:Environment',
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_malicious_anchor_label_is_rejected(self) -> None:
        with self.assertRaises(fastapi.HTTPException) as ctx:
            plugin_edges.resolve_edge_for(
                'Environment) DETACH DELETE x MATCH (y', 'MAPS_TO'
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_malicious_target_label_in_manifest_is_rejected(self) -> None:
        entry = _registry_entry(
            edge_labels=[
                PluginEdgeLabel(
                    name='MAPS_TO',
                    from_labels=['Environment'],
                    to_labels=['Foo) DETACH DELETE n MATCH (x'],
                )
            ]
        )
        with mock.patch.object(
            plugin_edges, 'list_plugins', return_value=[entry]
        ):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                plugin_edges.resolve_edge_for('Environment', 'MAPS_TO')
        self.assertEqual(ctx.exception.status_code, 400)

    def test_valid_edge_resolves(self) -> None:
        entry = _registry_entry(
            edge_labels=[
                PluginEdgeLabel(
                    name='MAPS_TO',
                    from_labels=['Environment'],
                    to_labels=['AwsAccount'],
                )
            ]
        )
        with mock.patch.object(
            plugin_edges, 'list_plugins', return_value=[entry]
        ):
            edge = plugin_edges.resolve_edge_for('Environment', 'MAPS_TO')
        self.assertEqual(edge.name, 'MAPS_TO')
