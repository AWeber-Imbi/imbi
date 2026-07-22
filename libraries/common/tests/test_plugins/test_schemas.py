import pathlib
import tempfile
import unittest

from imbi.common.plugins.base import (
    Capability,
    ConfigurationCapability,
    PluginEdgeLabel,
    PluginIndex,
    PluginManifest,
    PluginVertexLabel,
)
from imbi.common.plugins.errors import PluginSchemaCollisionError
from imbi.common.plugins.schemas import validate_no_collisions


class _StubConfiguration(ConfigurationCapability):
    async def list_keys(self, ctx, credentials):
        return []

    async def get_values(self, ctx, credentials, keys=None):
        return []

    async def set_value(self, ctx, credentials, key, value): ...

    async def delete_key(self, ctx, credentials, key): ...


def _make_manifest(
    slug: str,
    vlabels: list[PluginVertexLabel],
    elabels: list[PluginEdgeLabel] | None = None,
) -> PluginManifest:
    return PluginManifest(
        slug=slug,
        name=slug,
        vertex_labels=vlabels,
        edge_labels=elabels or [],
        capabilities=[
            Capability(
                kind='configuration',
                label='Configuration',
                handler=_StubConfiguration,
            )
        ],
    )


def _write_core_schemata(tmp: pathlib.Path, names: list[str]) -> pathlib.Path:
    body = '[vlabels]\nname = [\n'
    body += ''.join(f'  "{n}",\n' for n in names)
    body += ']\n'
    path = tmp / 'schemata.toml'
    path.write_text(body)
    return path


class ValidateNoCollisionsTestCase(unittest.TestCase):
    def test_disjoint_manifests_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            schemata = _write_core_schemata(
                pathlib.Path(tmp), ['Project', 'User']
            )
            validate_no_collisions(
                [
                    _make_manifest(
                        'aws',
                        [
                            PluginVertexLabel(
                                name='AwsAccount',
                                indexes=[],
                                model_ref='aws.models:AwsAccount',
                            )
                        ],
                    ),
                    _make_manifest(
                        'gh',
                        [
                            PluginVertexLabel(
                                name='GithubOrg',
                                indexes=[],
                                model_ref='gh.models:GithubOrg',
                            )
                        ],
                    ),
                ],
                schemata,
            )

    def test_collision_with_core(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            schemata = _write_core_schemata(
                pathlib.Path(tmp), ['Project', 'User']
            )
            with self.assertRaises(PluginSchemaCollisionError):
                validate_no_collisions(
                    [
                        _make_manifest(
                            'evil',
                            [
                                PluginVertexLabel(
                                    name='User',
                                    indexes=[],
                                    model_ref='evil.models:User',
                                )
                            ],
                        )
                    ],
                    schemata,
                )

    def test_collision_between_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            schemata = _write_core_schemata(pathlib.Path(tmp), ['Project'])
            with self.assertRaises(PluginSchemaCollisionError):
                validate_no_collisions(
                    [
                        _make_manifest(
                            'aws',
                            [
                                PluginVertexLabel(
                                    name='Account',
                                    indexes=[],
                                    model_ref='aws:Account',
                                )
                            ],
                        ),
                        _make_manifest(
                            'gcp',
                            [
                                PluginVertexLabel(
                                    name='Account',
                                    indexes=[],
                                    model_ref='gcp:Account',
                                )
                            ],
                        ),
                    ],
                    schemata,
                )

    def test_index_field_round_trip(self) -> None:
        index = PluginIndex(fields=['account_id'], unique=True)
        self.assertEqual(index.fields, ['account_id'])
        self.assertTrue(index.unique)

    def test_edge_label_collision_between_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            schemata = _write_core_schemata(pathlib.Path(tmp), ['Project'])
            with self.assertRaises(PluginSchemaCollisionError):
                validate_no_collisions(
                    [
                        _make_manifest(
                            'aws',
                            [],
                            [
                                PluginEdgeLabel(
                                    name='MAPS_TO',
                                    from_labels=['Project'],
                                    to_labels=['AwsAccount'],
                                )
                            ],
                        ),
                        _make_manifest(
                            'gcp',
                            [],
                            [
                                PluginEdgeLabel(
                                    name='MAPS_TO',
                                    from_labels=['Project'],
                                    to_labels=['GcpProject'],
                                )
                            ],
                        ),
                    ],
                    schemata,
                )

    def test_disjoint_edge_labels_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            schemata = _write_core_schemata(pathlib.Path(tmp), ['Project'])
            validate_no_collisions(
                [
                    _make_manifest(
                        'aws',
                        [],
                        [
                            PluginEdgeLabel(
                                name='MAPS_TO_AWS',
                                from_labels=['Project'],
                                to_labels=['AwsAccount'],
                            )
                        ],
                    ),
                    _make_manifest(
                        'gcp',
                        [],
                        [
                            PluginEdgeLabel(
                                name='MAPS_TO_GCP',
                                from_labels=['Project'],
                                to_labels=['GcpProject'],
                            )
                        ],
                    ),
                ],
                schemata,
            )

    def test_identical_edge_labels_allowed(self) -> None:
        """Sibling plugins may share an edge label with the same shape."""

        def _shared_edge() -> PluginEdgeLabel:
            return PluginEdgeLabel(
                name='DEPLOYS_VIA',
                from_labels=['ProjectType', 'Project'],
                to_labels=['Environment'],
                properties={'action': 'str'},
            )

        with tempfile.TemporaryDirectory() as tmp:
            schemata = _write_core_schemata(pathlib.Path(tmp), ['Project'])
            validate_no_collisions(
                [
                    _make_manifest('github-deployment', [], [_shared_edge()]),
                    _make_manifest(
                        'github-deployment-ec', [], [_shared_edge()]
                    ),
                    _make_manifest(
                        'github-deployment-es', [], [_shared_edge()]
                    ),
                ],
                schemata,
            )

    def test_diverging_edge_label_shape_rejected(self) -> None:
        """Same name + different shape is still a collision."""
        with tempfile.TemporaryDirectory() as tmp:
            schemata = _write_core_schemata(pathlib.Path(tmp), ['Project'])
            with self.assertRaises(PluginSchemaCollisionError):
                validate_no_collisions(
                    [
                        _make_manifest(
                            'a',
                            [],
                            [
                                PluginEdgeLabel(
                                    name='DEPLOYS_VIA',
                                    from_labels=['Project'],
                                    to_labels=['Environment'],
                                    properties={'action': 'str'},
                                )
                            ],
                        ),
                        _make_manifest(
                            'b',
                            [],
                            [
                                PluginEdgeLabel(
                                    name='DEPLOYS_VIA',
                                    from_labels=['Project'],
                                    to_labels=['Environment'],
                                    # extra property → different shape
                                    properties={
                                        'action': 'str',
                                        'extra': 'str',
                                    },
                                )
                            ],
                        ),
                    ],
                    schemata,
                )

    def test_identical_vlabels_allowed(self) -> None:
        """Sibling plugins may share a vlabel with the same shape."""

        def _shared_vlabel() -> PluginVertexLabel:
            return PluginVertexLabel(
                name='SharedAccount',
                indexes=[],
                model_ref='shared.models:SharedAccount',
            )

        with tempfile.TemporaryDirectory() as tmp:
            schemata = _write_core_schemata(pathlib.Path(tmp), ['Project'])
            validate_no_collisions(
                [
                    _make_manifest('a', [_shared_vlabel()]),
                    _make_manifest('b', [_shared_vlabel()]),
                ],
                schemata,
            )


class PluginIndexValidationTestCase(unittest.TestCase):
    def test_empty_fields_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PluginIndex(fields=[])

    def test_empty_string_field_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PluginIndex(fields=[''])

    def test_whitespace_field_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PluginIndex(fields=['   '])

    def test_one_empty_among_many_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PluginIndex(fields=['account_id', ''])
