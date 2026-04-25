"""Tests for note template CRUD endpoints."""

import datetime
import typing
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from imbi_common import graph

from imbi_api import app, models


class NoteTemplateEndpointsTestCase(unittest.TestCase):
    """Test cases for note template CRUD."""

    def setUp(self) -> None:
        from imbi_api.auth import permissions

        self.test_app = app.create_app()

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
                'note_template:create',
                'note_template:read',
                'note_template:write',
                'note_template:delete',
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

    def _template_row(self, **overrides: typing.Any) -> dict[str, typing.Any]:
        nt: dict[str, typing.Any] = {
            'id': 'adr',
            'name': 'ADR',
            'slug': 'adr',
            'description': 'Context · Decision · Trade-offs',
            'icon': 'document',
            'title': 'New ADR',
            'content': '# Context\n\n# Decision\n\n# Trade-offs',
            'project_type_slugs': [],
            'sort_order': 0,
            'created_at': '2026-04-24T12:00:00Z',
            'updated_at': '2026-04-24T12:00:00Z',
        }
        nt.update(overrides)
        return {
            'nt': nt,
            'o': {'name': 'Engineering', 'slug': 'engineering'},
            'tags': [],
        }

    # -- Create --------------------------------------------------------

    def test_create_success_no_tags(self) -> None:
        # No tags -> dup check (empty), create, fetch
        self.mock_db.execute.side_effect = [
            [],
            [
                {
                    'nt': self._template_row()['nt'],
                    'o': self._template_row()['o'],
                }
            ],
            [self._template_row()],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/note-templates/',
                json={
                    'name': 'ADR',
                    'slug': 'adr',
                    'description': 'Context · Decision · Trade-offs',
                    'content': '# Context',
                },
            )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['slug'], 'adr')
        self.assertEqual(body['organization']['slug'], 'engineering')
        self.assertEqual(body['tags'], [])

    def test_create_with_tags(self) -> None:
        # Calls: validate_tags, dup check, create, attach_tags, fetch
        fetch_with_tags = {
            'nt': self._template_row()['nt'],
            'o': self._template_row()['o'],
            'tags': [
                {'name': 'ADR', 'slug': 'adr'},
                {'name': 'Architecture', 'slug': 'architecture'},
            ],
        }
        self.mock_db.execute.side_effect = [
            [
                {'tag_slug': 'adr', 'found': True},
                {'tag_slug': 'architecture', 'found': True},
            ],
            [],
            [
                {
                    'nt': self._template_row()['nt'],
                    'o': self._template_row()['o'],
                }
            ],
            [{'attached': 2}],
            [fetch_with_tags],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/note-templates/',
                json={
                    'name': 'ADR',
                    'slug': 'adr',
                    'content': '# Context',
                    'tags': ['adr', 'architecture'],
                },
            )
        self.assertEqual(response.status_code, 201)
        slugs = {t['slug'] for t in response.json()['tags']}
        self.assertEqual(slugs, {'adr', 'architecture'})

    def test_create_unknown_tag_returns_422(self) -> None:
        self.mock_db.execute.return_value = [
            {'tag_slug': 'adr', 'found': True},
            {'tag_slug': 'ghost', 'found': False},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/note-templates/',
                json={
                    'name': 'ADR',
                    'slug': 'adr',
                    'tags': ['adr', 'ghost'],
                },
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn('ghost', response.json()['detail'])

    def test_create_org_not_found(self) -> None:
        # No tags -> first execute is the create; returning [] -> 404
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/missing/note-templates/',
                json={'name': 'ADR', 'slug': 'adr'},
            )
        self.assertEqual(response.status_code, 404)

    def test_create_slug_conflict(self) -> None:
        # No tags -> first execute is the per-org duplicate check.
        self.mock_db.execute.return_value = [{'slug': 'adr'}]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/note-templates/',
                json={'name': 'ADR', 'slug': 'adr'},
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_create_missing_name_rejected(self) -> None:
        response = self.client.post(
            '/organizations/engineering/note-templates/',
            json={'slug': 'adr'},
        )
        self.assertEqual(response.status_code, 422)

    # -- List ----------------------------------------------------------

    def test_list_success(self) -> None:
        self.mock_db.execute.return_value = [
            self._template_row(),
            {
                'nt': self._template_row(name='Runbook', slug='runbook')['nt'],
                'o': self._template_row()['o'],
                'tags': [],
            },
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/note-templates/'
            )
        self.assertEqual(response.status_code, 200)
        slugs = [t['slug'] for t in response.json()]
        self.assertEqual(slugs, ['adr', 'runbook'])

    def test_list_filter_by_project_type(self) -> None:
        self.mock_db.execute.return_value = [
            {
                'nt': self._template_row(slug='global', project_type_slugs=[])[
                    'nt'
                ],
                'o': self._template_row()['o'],
                'tags': [],
            },
            {
                'nt': self._template_row(
                    slug='only-api', project_type_slugs=['http-api']
                )['nt'],
                'o': self._template_row()['o'],
                'tags': [],
            },
            {
                'nt': self._template_row(
                    slug='only-mobile', project_type_slugs=['mobile-app']
                )['nt'],
                'o': self._template_row()['o'],
                'tags': [],
            },
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/note-templates/'
                '?project_type=http-api'
            )
        self.assertEqual(response.status_code, 200)
        slugs = [t['slug'] for t in response.json()]
        self.assertEqual(slugs, ['global', 'only-api'])

    # -- Get -----------------------------------------------------------

    def test_get_success(self) -> None:
        self.mock_db.execute.return_value = [self._template_row()]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/note-templates/adr'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['slug'], 'adr')

    def test_get_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.get(
            '/organizations/engineering/note-templates/nope'
        )
        self.assertEqual(response.status_code, 404)

    # -- Update --------------------------------------------------------

    def test_update_success(self) -> None:
        # Calls: fetch_existing, persist (set), fetch fresh
        self.mock_db.execute.side_effect = [
            [self._template_row()],
            [{'slug': 'adr'}],
            [
                {
                    'nt': self._template_row(name='Architecture Decision')[
                        'nt'
                    ],
                    'o': self._template_row()['o'],
                    'tags': [],
                }
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.put(
                '/organizations/engineering/note-templates/adr',
                json={'name': 'Architecture Decision'},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'Architecture Decision')

    def test_update_with_tags_replaces(self) -> None:
        # fetch_existing, validate_tags, set, detach, attach, fetch fresh
        self.mock_db.execute.side_effect = [
            [self._template_row()],
            [{'tag_slug': 'incident', 'found': True}],
            [{'slug': 'adr'}],
            [{'removed': 0}],
            [{'attached': 1}],
            [
                {
                    'nt': self._template_row()['nt'],
                    'o': self._template_row()['o'],
                    'tags': [{'name': 'Incident', 'slug': 'incident'}],
                }
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.put(
                '/organizations/engineering/note-templates/adr',
                json={'tags': ['incident']},
            )
        self.assertEqual(response.status_code, 200)
        slugs = [t['slug'] for t in response.json()['tags']]
        self.assertEqual(slugs, ['incident'])

    def test_update_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.put(
            '/organizations/engineering/note-templates/nope',
            json={'name': 'X'},
        )
        self.assertEqual(response.status_code, 404)

    def test_update_slug_conflict(self) -> None:
        # fetch existing, then per-org dup check returns conflict
        self.mock_db.execute.side_effect = [
            [self._template_row()],
            [{'slug': 'taken'}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.put(
                '/organizations/engineering/note-templates/adr',
                json={'slug': 'taken'},
            )
        self.assertEqual(response.status_code, 409)

    # -- Patch ---------------------------------------------------------

    def test_patch_template_name(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._template_row()],
            [{'slug': 'adr'}],
            [
                {
                    'nt': self._template_row(name='ADR v2')['nt'],
                    'o': self._template_row()['o'],
                    'tags': [],
                }
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/note-templates/adr',
                json=[{'op': 'replace', 'path': '/name', 'value': 'ADR v2'}],
            )
        self.assertEqual(response.status_code, 200)

    def test_patch_invalid_type_rejected(self) -> None:
        # apply_patch is type-blind — re-validation must catch this
        self.mock_db.execute.return_value = [self._template_row()]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/note-templates/adr',
                json=[
                    {
                        'op': 'replace',
                        'path': '/sort_order',
                        'value': 'oops',
                    }
                ],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_empty_name_rejected(self) -> None:
        self.mock_db.execute.return_value = [self._template_row()]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/note-templates/adr',
                json=[{'op': 'replace', 'path': '/name', 'value': ''}],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_template_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.patch(
            '/organizations/engineering/note-templates/nope',
            json=[{'op': 'replace', 'path': '/name', 'value': 'X'}],
        )
        self.assertEqual(response.status_code, 404)

    # -- Delete --------------------------------------------------------

    def test_delete_success(self) -> None:
        self.mock_db.execute.return_value = [{'nt': True}]
        response = self.client.delete(
            '/organizations/engineering/note-templates/adr'
        )
        self.assertEqual(response.status_code, 204)

    def test_delete_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.delete(
            '/organizations/engineering/note-templates/nope'
        )
        self.assertEqual(response.status_code, 404)
