"""Tests for the plugin-declared schema audit (imbi_api.plugins.schemas)."""

import types
import unittest
from unittest import mock

from imbi_api.plugins import schemas


class AgLabelNamesTests(unittest.IsolatedAsyncioTestCase):
    """_ag_label_names must drop AGE's built-in inheritance labels."""

    async def test_excludes_ag_internal_labels(self) -> None:
        rows = [
            ('Document',),
            ('_ag_label_vertex',),
            ('_ag_label_edge',),
            ('Project',),
        ]
        cursor = mock.MagicMock()
        cursor.execute = mock.AsyncMock()
        cursor.fetchall = mock.AsyncMock(return_value=rows)
        cursor_cm = mock.MagicMock()
        cursor_cm.__aenter__ = mock.AsyncMock(return_value=cursor)
        cursor_cm.__aexit__ = mock.AsyncMock(return_value=False)
        conn = mock.MagicMock()
        conn.cursor = mock.MagicMock(return_value=cursor_cm)
        conn_cm = mock.MagicMock()
        conn_cm.__aenter__ = mock.AsyncMock(return_value=conn)
        conn_cm.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch(
            'psycopg.AsyncConnection.connect',
            new=mock.AsyncMock(return_value=conn_cm),
        ):
            result = await schemas._ag_label_names()

        self.assertEqual(result, {'Document', 'Project'})
        self.assertNotIn('_ag_label_vertex', result)
        self.assertNotIn('_ag_label_edge', result)


class AuditPluginSchemasTests(unittest.IsolatedAsyncioTestCase):
    """audit_plugin_schemas distinguishes real orphans from false positives."""

    def _plugin(self, *vlabels: str) -> types.SimpleNamespace:
        return types.SimpleNamespace(
            manifest=types.SimpleNamespace(
                vertex_labels=[
                    types.SimpleNamespace(name=name) for name in vlabels
                ]
            )
        )

    async def test_only_true_orphans_reported(self) -> None:
        # Document/Tag/LocalAuthConfig are in-use non-plugin GraphModels;
        # AwsAccount is plugin-declared; Organization is a core vlabel;
        # only NoSuchLabel maps to nothing and is a genuine orphan.
        age_labels = {
            'Organization',
            'Document',
            'Tag',
            'LocalAuthConfig',
            'AwsAccount',
            'NoSuchLabel',
        }
        with (
            mock.patch.object(
                schemas,
                '_ag_label_names',
                new=mock.AsyncMock(return_value=age_labels),
            ),
            mock.patch.object(
                schemas,
                'list_plugins',
                return_value=[self._plugin('AwsAccount')],
            ),
        ):
            result = await schemas.audit_plugin_schemas()

        self.assertEqual(result, [{'vlabel': 'NoSuchLabel'}])

    async def test_in_use_model_not_flagged(self) -> None:
        with (
            mock.patch.object(
                schemas,
                '_ag_label_names',
                new=mock.AsyncMock(return_value={'Document'}),
            ),
            mock.patch.object(schemas, 'list_plugins', return_value=[]),
        ):
            result = await schemas.audit_plugin_schemas()

        self.assertEqual(result, [])

    async def test_no_labels_returns_empty(self) -> None:
        # _ag_label_names already filters AGE internals, so a graph with
        # only the built-in parent labels surfaces as an empty set here.
        with (
            mock.patch.object(
                schemas,
                '_ag_label_names',
                new=mock.AsyncMock(return_value=set()),
            ),
            mock.patch.object(schemas, 'list_plugins', return_value=[]),
        ):
            result = await schemas.audit_plugin_schemas()

        self.assertEqual(result, [])


if __name__ == '__main__':
    unittest.main()
