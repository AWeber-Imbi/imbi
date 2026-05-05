import pathlib
import tempfile
import unittest

from imbi_common.plugins.base import (
    PluginEdgeLabel,
    PluginIndex,
    PluginManifest,
    PluginVertexLabel,
)
from imbi_common.plugins.errors import PluginSchemaCollisionError
from imbi_common.plugins.schemas import validate_no_collisions


def _make_manifest(
    slug: str,
    vlabels: list[PluginVertexLabel],
    elabels: list[PluginEdgeLabel] | None = None,
) -> PluginManifest:
    return PluginManifest(
        slug=slug,
        name=slug,
        plugin_type='identity',
        vertex_labels=vlabels,
        edge_labels=elabels or [],
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
