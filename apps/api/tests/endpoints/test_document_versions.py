"""Tests for document version-history endpoints."""

import datetime
import typing
import unittest
from unittest import mock

import fastapi.testclient

from apps.api.tests import support
from imbi.api import models
from imbi.common import graph


class DocumentVersionEndpointsTestCase(support.SharedAppTestCase):
    """Version list/get/restore endpoints."""

    def setUp(self) -> None:
        from imbi.api.auth import permissions

        self.admin_user = models.User(
            email='admin@example.com',
            display_name='Admin User',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=True,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.admin_user,
            session_id='test-session',
            auth_method='jwt',
            permissions={
                'document:read',
                'document:write',
            },
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.ch_insert = mock.AsyncMock()
        self.ch_query = mock.AsyncMock(return_value=[])
        for target, replacement in (
            ('imbi.common.clickhouse.insert', self.ch_insert),
            ('imbi.common.clickhouse.query', self.ch_query),
        ):
            patcher = mock.patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.client = fastapi.testclient.TestClient(self.test_app)

    def _document_data(self, **overrides: typing.Any) -> dict:
        data: dict[str, typing.Any] = {
            'id': 'document-1',
            'title': 'DB lock runbook',
            'content': 'Watch out for DB locks',
            'created_by': 'admin@example.com',
            'created_at': '2026-03-17T12:00:00Z',
            'updated_by': None,
            'updated_at': None,
        }
        data.update(overrides)
        return data

    def _project_row(self, n: dict | None = None, **kwargs) -> dict:
        return {
            'n': n if n is not None else self._document_data(),
            'p': {'id': 'proj-abc', 'slug': 'billing', 'name': 'Billing'},
            'team': {'name': 'Platform', 'slug': 'platform'},
            'pt': None,
            'u': None,
            'ptype_names': [],
            'tags': kwargs.get('tags', []),
            'comment_count': 0,
            'author': None,
        }

    def _version_row(self, **overrides: typing.Any) -> dict[str, typing.Any]:
        row: dict[str, typing.Any] = {
            'version': 1,
            'title': 'DB lock runbook',
            'change_kind': 'create',
            'updated_by': 'admin@example.com',
            'updated_at': datetime.datetime(2026, 3, 17, 12, 0, 0),
        }
        row.update(overrides)
        return row

    # -- List ------------------------------------------------------------

    def test_list_versions(self) -> None:
        self.mock_db.execute.return_value = [self._project_row()]
        self.ch_query.return_value = [
            self._version_row(version=2, change_kind='update'),
            self._version_row(),
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/documents/document-1/versions'
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual([v['version'] for v in data], [2, 1])
        self.assertEqual(data[0]['change_kind'], 'update')
        # Naive ClickHouse timestamps must serialize with a UTC offset.
        self.assertTrue(data[0]['updated_at'].endswith('Z'))

    def test_list_versions_document_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.get(
            '/organizations/engineering/documents/ghost/versions'
        )
        self.assertEqual(response.status_code, 404)
        self.ch_query.assert_not_awaited()

    # -- Get -------------------------------------------------------------

    def test_get_version(self) -> None:
        self.mock_db.execute.return_value = [self._project_row()]
        self.ch_query.return_value = [
            self._version_row(
                content='Watch out for DB locks', tags=['runbook']
            )
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/documents/document-1/versions/1'
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['version'], 1)
        self.assertEqual(body['content'], 'Watch out for DB locks')
        self.assertEqual(body['tags'], ['runbook'])

    def test_get_version_not_found(self) -> None:
        self.mock_db.execute.return_value = [self._project_row()]
        self.ch_query.return_value = []
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/documents/document-1/versions/9'
            )
        self.assertEqual(response.status_code, 404)

    # -- Restore ---------------------------------------------------------

    def test_restore_version(self) -> None:
        """Restore applies the snapshot as a new ``restore`` version."""
        # ClickHouse calls: _require_document is graph-side; then
        # 1: _fetch_version, 2: _max_recorded_version inside capture.
        self.ch_query.side_effect = [
            [self._version_row(content='Original text', tags=['runbook'])],
            [{'v': 2, 'c': 2}],
        ]
        # Graph calls: 1: _require_document, 2: patch fetch-existing,
        # 3: validate tags, 4: SET, 5: detach tags, 6: attach tags,
        # 7: final fetch.
        current = self._document_data(
            content='Newer text', version=2, updated_by='admin@example.com'
        )
        restored = self._document_data(
            content='Original text',
            version=3,
            updated_by='admin@example.com',
        )
        self.mock_db.execute.side_effect = [
            [self._project_row(n=current)],
            [self._project_row(n=current)],
            [{'tag_slug': 'runbook', 'found': True}],
            [{'id': 'document-1'}],
            [{'removed': 0}],
            [{'attached': 1}],
            [
                self._project_row(
                    n=restored, tags=[{'name': 'Runbook', 'slug': 'runbook'}]
                )
            ],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/documents/document-1'
                '/versions/1/restore'
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['content'], 'Original text')
        self.assertEqual(body['version'], 3)
        # The SET query carries the bumped version.
        set_call = self.mock_db.execute.await_args_list[3]
        self.assertEqual(set_call.args[1]['version'], 3)
        self.assertEqual(set_call.args[1]['content'], 'Original text')
        # The new snapshot is recorded as a restore.
        self.ch_insert.assert_awaited_once()
        _, rows = self.ch_insert.await_args.args
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].version, 3)
        self.assertEqual(rows[0].change_kind, 'restore')

    def test_restore_version_not_found(self) -> None:
        self.mock_db.execute.return_value = [self._project_row()]
        self.ch_query.return_value = []
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/documents/document-1'
                '/versions/9/restore'
            )
        self.assertEqual(response.status_code, 404)

    def test_restore_document_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.post(
            '/organizations/engineering/documents/ghost/versions/1/restore'
        )
        self.assertEqual(response.status_code, 404)
        self.ch_query.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
