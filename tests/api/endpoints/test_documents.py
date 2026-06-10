"""Tests for documents CRUD endpoints."""

import datetime
import typing
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from imbi_common import graph

from imbi_api import models
from tests import support


class DocumentEndpointsTestCase(support.SharedAppTestCase):
    """Test cases for documents CRUD + the org-wide index."""

    def setUp(self) -> None:
        from imbi_api.auth import permissions

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
                'document:create',
                'document:read',
                'document:write',
                'document:delete',
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

        self.client = TestClient(self.test_app)

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

    def _project(self, **overrides: typing.Any) -> dict:
        data: dict[str, typing.Any] = {
            'id': 'proj-abc',
            'slug': 'billing-api',
            'name': 'Billing API',
        }
        data.update(overrides)
        return data

    def _row(
        self,
        n: dict | None = None,
        p: dict | None = None,
        team: dict | None = None,
        pt: dict | None = None,
        u: dict | None = None,
        ptype_names: list[str] | None = None,
        tags: list[dict] | None = None,
        comment_count: int = 0,
        author: dict | None = None,
    ) -> dict[str, typing.Any]:
        """A full document row as returned by the enriched queries."""
        return {
            'n': n if n is not None else self._document_data(),
            'p': p,
            'team': team,
            'pt': pt,
            'u': u,
            'ptype_names': ptype_names or [],
            'tags': tags or [],
            'comment_count': comment_count,
            'author': author,
        }

    def _project_row(self, n: dict | None = None, **kwargs) -> dict:
        kwargs.setdefault('p', self._project())
        kwargs.setdefault('team', {'name': 'Platform', 'slug': 'platform'})
        return self._row(n=n, **kwargs)

    # -- Create --------------------------------------------------------

    def test_create_success_no_tags(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': 'document-1'}],
            [self._project_row()],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/projects/proj-abc/documents/',
                json={
                    'title': 'DB lock runbook',
                    'content': 'Watch out for DB locks',
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['project_id'], 'proj-abc')
        self.assertEqual(response.json()['title'], 'DB lock runbook')
        self.assertEqual(response.json()['tags'], [])
        attached = response.json()['attached_to']
        self.assertEqual(attached['kind'], 'project')
        self.assertEqual(attached['id'], 'proj-abc')
        self.assertEqual(attached['name'], 'Billing API')
        self.assertEqual(attached['team'], 'Platform')

    def test_create_with_tags(self) -> None:
        # Calls: validate_tags, create_document, attach_tags, fetch_document
        self.mock_db.execute.side_effect = [
            [
                {'tag_slug': 'runbook', 'found': True},
                {'tag_slug': 'alert', 'found': True},
            ],
            [{'id': 'document-1'}],
            [{'attached': 2}],
            [
                self._project_row(
                    tags=[
                        {'name': 'Runbook', 'slug': 'runbook'},
                        {'name': 'Alert', 'slug': 'alert'},
                    ],
                )
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/projects/proj-abc/documents/',
                json={
                    'title': 't',
                    'content': 'x',
                    'tags': ['runbook', 'alert'],
                },
            )
        self.assertEqual(response.status_code, 201)
        tags = {t['slug'] for t in response.json()['tags']}
        self.assertEqual(tags, {'runbook', 'alert'})
        attach_call = self.mock_db.execute.await_args_list[2]
        self.assertEqual(
            attach_call.args[1]['tag_slugs'], ['runbook', 'alert']
        )

    def test_create_unknown_tag_returns_422(self) -> None:
        self.mock_db.execute.return_value = [
            {'tag_slug': 'runbook', 'found': True},
            {'tag_slug': 'ghost', 'found': False},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/projects/proj-abc/documents/',
                json={
                    'title': 't',
                    'content': 'x',
                    'tags': ['runbook', 'ghost'],
                },
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn('ghost', response.json()['detail'])

    def test_create_project_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/projects/missing/documents/',
                json={'title': 't', 'content': 'x'},
            )
        self.assertEqual(response.status_code, 404)

    def test_create_empty_content_rejected(self) -> None:
        response = self.client.post(
            '/organizations/engineering/projects/proj-abc/documents/',
            json={'title': 't', 'content': ''},
        )
        self.assertEqual(response.status_code, 422)

    def test_create_missing_title_rejected(self) -> None:
        response = self.client.post(
            '/organizations/engineering/projects/proj-abc/documents/',
            json={'content': 'x'},
        )
        self.assertEqual(response.status_code, 422)

    def test_create_empty_title_rejected(self) -> None:
        response = self.client.post(
            '/organizations/engineering/projects/proj-abc/documents/',
            json={'title': '', 'content': 'x'},
        )
        self.assertEqual(response.status_code, 422)

    def test_create_user_document(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': 'document-1'}],
            [
                self._row(
                    u={
                        'email': 'gavinr@example.com',
                        'display_name': 'Gavin M. Roy',
                    },
                )
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/users/gavinr@example.com'
                '/documents/',
                json={'title': 't', 'content': 'x'},
            )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIsNone(body['project_id'])
        self.assertEqual(body['attached_to']['kind'], 'user')
        self.assertEqual(body['attached_to']['id'], 'gavinr@example.com')
        self.assertEqual(body['attached_to']['name'], 'Gavin M. Roy')
        create_call = self.mock_db.execute.await_args_list[0]
        self.assertEqual(create_call.args[1]['email'], 'gavinr@example.com')

    def test_create_user_document_user_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/users/ghost@example.com'
                '/documents/',
                json={'title': 't', 'content': 'x'},
            )
        self.assertEqual(response.status_code, 404)

    def test_create_project_type_document(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': 'document-1'}],
            [
                self._row(
                    pt={'slug': 'http-api', 'name': 'HTTP API'},
                )
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/project-types/http-api/documents/',
                json={'title': 't', 'content': 'x'},
            )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIsNone(body['project_id'])
        self.assertEqual(body['attached_to']['kind'], 'project_type')
        self.assertEqual(body['attached_to']['id'], 'http-api')
        self.assertEqual(body['attached_to']['name'], 'HTTP API')
        create_call = self.mock_db.execute.await_args_list[0]
        self.assertEqual(create_call.args[1]['type_slug'], 'http-api')

    # -- List ----------------------------------------------------------

    def test_list_project_documents(self) -> None:
        self.mock_db.execute.return_value = [
            self._project_row(n=self._document_data(id='n1')),
            self._project_row(
                n=self._document_data(id='n2'),
                tags=[{'name': 'Runbook', 'slug': 'runbook'}],
            ),
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/projects/proj-abc/documents/'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['data']), 2)

    def test_list_cross_project_by_tag(self) -> None:
        self.mock_db.execute.return_value = [
            self._project_row(
                n=self._document_data(id='n1'),
                p=self._project(id='proj-a', slug='a'),
                tags=[{'name': 'Runbook', 'slug': 'runbook'}],
            ),
            self._project_row(
                n=self._document_data(id='n2'),
                p=self._project(id='proj-b', slug='b'),
                tags=[{'name': 'Runbook', 'slug': 'runbook'}],
            ),
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/documents/?tag=runbook'
            )
        self.assertEqual(response.status_code, 200)
        projects = {n['project_id'] for n in response.json()['data']}
        self.assertEqual(projects, {'proj-a', 'proj-b'})

    def test_list_mixed_attachments(self) -> None:
        """The org index returns project, project-type, and user docs."""
        self.mock_db.execute.return_value = [
            self._project_row(
                n=self._document_data(id='n1'),
                ptype_names=['API', 'Consumer'],
                comment_count=3,
                author={
                    'email': 'admin@example.com',
                    'display_name': 'Admin User',
                },
            ),
            self._row(
                n=self._document_data(id='n2'),
                pt={'slug': 'http-api', 'name': 'HTTP API'},
            ),
            self._row(
                n=self._document_data(id='n3'),
                u={
                    'email': 'gavinr@example.com',
                    'display_name': 'Gavin M. Roy',
                },
            ),
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get('/organizations/engineering/documents/')
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(len(data), 3)
        self.assertEqual(data[0]['attached_to']['kind'], 'project')
        self.assertEqual(
            data[0]['attached_to']['project_types'], ['API', 'Consumer']
        )
        self.assertEqual(data[0]['comment_count'], 3)
        self.assertEqual(data[0]['created_by_name'], 'Admin User')
        self.assertEqual(data[1]['attached_to']['kind'], 'project_type')
        self.assertEqual(data[2]['attached_to']['kind'], 'user')

    def test_list_user_documents(self) -> None:
        self.mock_db.execute.return_value = [
            self._row(
                u={
                    'email': 'gavinr@example.com',
                    'display_name': 'Gavin M. Roy',
                },
            )
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/users/gavinr@example.com'
                '/documents/'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['data']), 1)
        call = self.mock_db.execute.await_args_list[0]
        self.assertEqual(call.args[1]['user_email'], 'gavinr@example.com')

    def test_list_project_type_documents(self) -> None:
        self.mock_db.execute.return_value = [
            self._row(pt={'slug': 'http-api', 'name': 'HTTP API'})
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/project-types/http-api/documents/'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['data']), 1)
        call = self.mock_db.execute.await_args_list[0]
        self.assertEqual(call.args[1]['project_type_slug'], 'http-api')

    def test_list_invalid_limit(self) -> None:
        response = self.client.get(
            '/organizations/engineering/documents/?limit=99999'
        )
        self.assertEqual(response.status_code, 400)

    def test_list_mutually_exclusive_filters(self) -> None:
        response = self.client.get(
            '/organizations/engineering/documents/'
            '?project_id=proj-abc&project_type=http-api'
        )
        self.assertEqual(response.status_code, 400)
        self.mock_db.execute.assert_not_called()

    def test_list_invalid_cursor(self) -> None:
        response = self.client.get(
            '/organizations/engineering/documents/?cursor=!!not-base64!!'
        )
        # malformed base64 decodes to empty/garbage -> 400 via _decode_cursor
        self.assertIn(response.status_code, {400})

    # -- Get -----------------------------------------------------------

    def test_get_single(self) -> None:
        self.mock_db.execute.return_value = [self._project_row()]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/projects/proj-abc/documents/document-1'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['id'], 'document-1')

    def test_get_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.get(
            '/organizations/engineering/projects/proj-abc/documents/ghost'
        )
        self.assertEqual(response.status_code, 404)

    def test_get_org_document(self) -> None:
        """The generic route resolves a user-attached document."""
        self.mock_db.execute.return_value = [
            self._row(
                u={
                    'email': 'gavinr@example.com',
                    'display_name': 'Gavin M. Roy',
                },
            )
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/documents/document-1'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['attached_to']['kind'], 'user')

    def test_get_org_document_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.get(
            '/organizations/engineering/documents/ghost'
        )
        self.assertEqual(response.status_code, 404)

    # -- Patch ---------------------------------------------------------

    def test_patch_content(self) -> None:
        # 1: _fetch_document (existing), 2: SET query,
        # 3: _fetch_document (final)
        self.mock_db.execute.side_effect = [
            [self._project_row()],
            [{'id': 'document-1'}],
            [self._project_row(n=self._document_data(content='Updated text'))],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/documents/document-1',
                json=[
                    {
                        'op': 'replace',
                        'path': '/content',
                        'value': 'Updated text',
                    }
                ],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['content'], 'Updated text')

    def test_patch_org_document(self) -> None:
        """The generic route patches a user-attached document."""
        user = {
            'email': 'gavinr@example.com',
            'display_name': 'Gavin M. Roy',
        }
        self.mock_db.execute.side_effect = [
            [self._row(u=user)],
            [{'id': 'document-1'}],
            [
                self._row(
                    n=self._document_data(content='Updated text'),
                    u=user,
                )
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/documents/document-1',
                json=[
                    {
                        'op': 'replace',
                        'path': '/content',
                        'value': 'Updated text',
                    }
                ],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['content'], 'Updated text')

    def test_patch_replace_tags(self) -> None:
        # fetch-existing, validate, SET, detach, attach, fetch-final
        self.mock_db.execute.side_effect = [
            [self._project_row()],
            [{'tag_slug': 'runbook', 'found': True}],
            [{'id': 'document-1'}],
            [{'removed': 0}],
            [{'attached': 1}],
            [
                self._project_row(
                    n=self._document_data(updated_by='admin@example.com'),
                    tags=[{'name': 'Runbook', 'slug': 'runbook'}],
                )
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/documents/document-1',
                json=[
                    {
                        'op': 'replace',
                        'path': '/tags',
                        'value': ['runbook'],
                    }
                ],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [t['slug'] for t in response.json()['tags']], ['runbook']
        )

    def test_create_defaults_is_pinned_false(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': 'document-1'}],
            [self._project_row()],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/projects/proj-abc/documents/',
                json={
                    'title': 'DB lock runbook',
                    'content': 'Watch out for DB locks',
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()['is_pinned'])
        create_call = self.mock_db.execute.await_args_list[0]
        self.assertFalse(create_call.args[1]['is_pinned'])

    def test_patch_title(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._project_row()],
            [{'id': 'document-1'}],
            [self._project_row(n=self._document_data(title='New title'))],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/documents/document-1',
                json=[
                    {
                        'op': 'replace',
                        'path': '/title',
                        'value': 'New title',
                    }
                ],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['title'], 'New title')
        # SET query is the second call (after the initial _fetch_document).
        write_call = self.mock_db.execute.await_args_list[1]
        self.assertEqual(write_call.args[1]['title'], 'New title')

    def test_patch_is_pinned(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._project_row()],
            [{'id': 'document-1'}],
            [self._project_row(n=self._document_data(is_pinned=True))],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/documents/document-1',
                json=[
                    {
                        'op': 'replace',
                        'path': '/is_pinned',
                        'value': True,
                    }
                ],
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['is_pinned'])
        # SET query is the second call (after the initial _fetch_document).
        write_call = self.mock_db.execute.await_args_list[1]
        self.assertTrue(write_call.args[1]['is_pinned'])

    def test_patch_title_null_rejected(self) -> None:
        """Explicit ``replace /title -> null`` must 400, not silently no-op."""
        self.mock_db.execute.return_value = [self._project_row()]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/documents/document-1',
                json=[{'op': 'replace', 'path': '/title', 'value': None}],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_is_pinned_null_rejected(self) -> None:
        """Explicit ``replace /is_pinned -> null`` must 400."""
        self.mock_db.execute.return_value = [self._project_row()]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/documents/document-1',
                json=[{'op': 'replace', 'path': '/is_pinned', 'value': None}],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_content_null_rejected(self) -> None:
        """Explicit ``replace /content -> null`` must 400."""
        self.mock_db.execute.return_value = [self._project_row()]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/documents/document-1',
                json=[{'op': 'replace', 'path': '/content', 'value': None}],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_readonly_path_rejected(self) -> None:
        self.mock_db.execute.return_value = [self._project_row()]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/documents/document-1',
                json=[
                    {
                        'op': 'replace',
                        'path': '/created_by',
                        'value': 'attacker',
                    }
                ],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_attached_to_rejected(self) -> None:
        """The attachment is immutable over the PATCH API."""
        self.mock_db.execute.return_value = [self._project_row()]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/documents/document-1',
                json=[
                    {
                        'op': 'replace',
                        'path': '/attached_to',
                        'value': {'kind': 'user', 'id': 'x'},
                    }
                ],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.patch(
            '/organizations/engineering/projects/proj-abc/documents/ghost',
            json=[{'op': 'replace', 'path': '/content', 'value': 'x'}],
        )
        self.assertEqual(response.status_code, 404)

    # -- Delete --------------------------------------------------------

    def test_delete_success(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 1}]
        response = self.client.delete(
            '/organizations/engineering/projects/proj-abc/documents/document-1'
        )
        self.assertEqual(response.status_code, 204)

    def test_delete_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.delete(
            '/organizations/engineering/projects/proj-abc/documents/ghost'
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_org_document(self) -> None:
        self.mock_db.execute.return_value = [{'deleted': 1}]
        response = self.client.delete(
            '/organizations/engineering/documents/document-1'
        )
        self.assertEqual(response.status_code, 204)

    # -- Pagination + cursor edge cases --------------------------------

    def test_list_pagination_emits_next_cursor(self) -> None:
        """Returning limit+1 rows emits a Link header with rel=next."""
        rows = [
            self._project_row(
                n=self._document_data(
                    id=f'n{i}',
                    created_at=f'2026-03-1{i % 10}T12:00:00Z',
                ),
            )
            for i in range(3)
        ]
        self.mock_db.execute.return_value = rows
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/documents/?limit=2'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['data']), 2)
        self.assertIn('rel="next"', response.headers.get('Link', ''))

    def test_list_cursor_roundtrip(self) -> None:
        """A valid cursor decodes and paginates."""
        import base64

        cursor = (
            base64.urlsafe_b64encode(b'2026-03-17T12:00:00+00:00|n-prev')
            .rstrip(b'=')
            .decode()
        )
        self.mock_db.execute.return_value = [
            self._project_row(n=self._document_data(id='n-next'))
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                f'/organizations/engineering/documents/?cursor={cursor}'
            )
        self.assertEqual(response.status_code, 200)

    def test_patch_validation_error(self) -> None:
        """Patching /content to an empty string returns 400."""
        self.mock_db.execute.return_value = [self._project_row()]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/documents/document-1',
                json=[{'op': 'replace', 'path': '/content', 'value': ''}],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_concurrent_delete_returns_404(self) -> None:
        """Update query returning no rows after fetch yields 404."""
        self.mock_db.execute.side_effect = [
            [self._project_row()],
            [],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/documents/document-1',
                json=[
                    {
                        'op': 'replace',
                        'path': '/content',
                        'value': 'new',
                    }
                ],
            )
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    unittest.main()
