"""Tests for sibling-identity resolution in analysis fan-out."""

from __future__ import annotations

import unittest
from unittest import mock

from imbi_api.plugins import resolution


def _types(slug: str) -> str:
    return 'identity' if 'enterprise-cloud' in slug else 'analysis'


class TpsIdentityPluginIdsTestCase(unittest.TestCase):
    def test_used_as_login_wins(self) -> None:
        raw = [
            {'id': 'a', 'slug': 'github-doctor-ec', 'tps_slug': 'gh'},
            {'id': 'b', 'slug': 'github-enterprise-cloud', 'tps_slug': 'gh'},
            {
                'id': 'c',
                'slug': 'github-enterprise-cloud',
                'tps_slug': 'gh',
                'used_as_login': True,
            },
        ]
        with mock.patch.object(
            resolution, '_registry_plugin_type', side_effect=_types
        ):
            out = resolution._tps_identity_plugin_ids(raw)
        self.assertEqual({'gh': 'c'}, out)

    def test_no_identity_plugin_yields_empty(self) -> None:
        raw = [{'id': 'a', 'slug': 'github-doctor-ec', 'tps_slug': 'gh'}]
        with mock.patch.object(
            resolution, '_registry_plugin_type', side_effect=_types
        ):
            out = resolution._tps_identity_plugin_ids(raw)
        self.assertEqual({}, out)

    def test_first_identity_used_without_login_flag(self) -> None:
        raw = [
            {'id': 'b', 'slug': 'github-enterprise-cloud', 'tps_slug': 'gh'},
        ]
        with mock.patch.object(
            resolution, '_registry_plugin_type', side_effect=_types
        ):
            out = resolution._tps_identity_plugin_ids(raw)
        self.assertEqual({'gh': 'b'}, out)
