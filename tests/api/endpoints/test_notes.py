"""Tests for notes CRUD endpoints."""

import datetime
import typing
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from imbi_common import graph

from imbi_api import app, models


class NoteEndpointsTestCase(unittest.TestCase):
    """Test cases for notes CRUD + cross-project search."""

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
                'note:create',
                'note:read',
                'note:write',
                'note:delete',
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

    def _note_data(self, **overrides: typing.Any) -> dict:
        data: dict[str, typing.Any] = {
            'id': 'note-1',
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
        }
        data.update(overrides)
        return data

    # -- Create --------------------------------------------------------

    def test_create_success_no_tags(self) -> None:
        self.mock_db.execute.return_value = [
            {'n': self._note_data(), 'p': self._project(), 'tags': []}
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/projects/proj-abc/notes/',
                json={'content': 'Watch out for DB locks'},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['project_id'], 'proj-abc')
        self.assertEqual(response.json()['tags'], [])

    def test_create_with_tags(self) -> None:
        # first call = _validate_tag_slugs (both found), second = insert
        self.mock_db.execute.side_effect = [
            [
                {'tag_slug': 'runbook', 'found': True},
                {'tag_slug': 'alert', 'found': True},
            ],
            [
                {
                    'n': self._note_data(),
                    'p': self._project(),
                    'tags': [
                        {'name': 'Runbook', 'slug': 'runbook'},
                        {'name': 'Alert', 'slug': 'alert'},
                    ],
                }
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/projects/proj-abc/notes/',
                json={'content': 'x', 'tags': ['runbook', 'alert']},
            )
        self.assertEqual(response.status_code, 201)
        tags = {t['slug'] for t in response.json()['tags']}
        self.assertEqual(tags, {'runbook', 'alert'})

    def test_create_unknown_tag_returns_422(self) -> None:
        self.mock_db.execute.return_value = [
            {'tag_slug': 'runbook', 'found': True},
            {'tag_slug': 'ghost', 'found': False},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/projects/proj-abc/notes/',
                json={'content': 'x', 'tags': ['runbook', 'ghost']},
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn('ghost', response.json()['detail'])

    def test_create_project_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/projects/missing/notes/',
                json={'content': 'x'},
            )
        self.assertEqual(response.status_code, 404)

    def test_create_empty_content_rejected(self) -> None:
        response = self.client.post(
            '/organizations/engineering/projects/proj-abc/notes/',
            json={'content': ''},
        )
        self.assertEqual(response.status_code, 422)

    # -- List ----------------------------------------------------------

    def test_list_project_notes(self) -> None:
        self.mock_db.execute.return_value = [
            {
                'n': self._note_data(id='n1'),
                'p': self._project(),
                'tags': [],
            },
            {
                'n': self._note_data(id='n2'),
                'p': self._project(),
                'tags': [{'name': 'Runbook', 'slug': 'runbook'}],
            },
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/projects/proj-abc/notes/'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['data']), 2)

    def test_list_cross_project_by_tag(self) -> None:
        self.mock_db.execute.return_value = [
            {
                'n': self._note_data(id='n1'),
                'p': self._project(id='proj-a', slug='a'),
                'tags': [{'name': 'Runbook', 'slug': 'runbook'}],
            },
            {
                'n': self._note_data(id='n2'),
                'p': self._project(id='proj-b', slug='b'),
                'tags': [{'name': 'Runbook', 'slug': 'runbook'}],
            },
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/notes/?tag=runbook'
            )
        self.assertEqual(response.status_code, 200)
        projects = {n['project_id'] for n in response.json()['data']}
        self.assertEqual(projects, {'proj-a', 'proj-b'})

    def test_list_invalid_limit(self) -> None:
        response = self.client.get(
            '/organizations/engineering/notes/?limit=99999'
        )
        self.assertEqual(response.status_code, 400)

    def test_list_invalid_cursor(self) -> None:
        response = self.client.get(
            '/organizations/engineering/notes/?cursor=!!not-base64!!'
        )
        # malformed base64 decodes to empty/garbage -> 400 via _decode_cursor
        self.assertIn(response.status_code, {400})

    # -- Get -----------------------------------------------------------

    def test_get_single(self) -> None:
        self.mock_db.execute.return_value = [
            {
                'n': self._note_data(),
                'p': self._project(),
                'tags': [],
            }
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/projects/proj-abc/notes/note-1'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['id'], 'note-1')

    def test_get_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.get(
            '/organizations/engineering/projects/proj-abc/notes/ghost'
        )
        self.assertEqual(response.status_code, 404)

    # -- Patch ---------------------------------------------------------

    def test_patch_content(self) -> None:
        self.mock_db.execute.side_effect = [
            [
                {
                    'n': self._note_data(),
                    'p': self._project(),
                    'tags': [],
                }
            ],
            [
                {
                    'n': self._note_data(content='Updated text'),
                    'p': self._project(),
                    'tags': [],
                }
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/notes/note-1',
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
        self.mock_db.execute.side_effect = [
            [
                {
                    'n': self._note_data(),
                    'p': self._project(),
                    'tags': [],
                }
            ],
            [  # _validate_tag_slugs
                {'tag_slug': 'runbook', 'found': True},
            ],
            [
                {
                    'n': self._note_data(updated_by='admin@example.com'),
                    'p': self._project(),
                    'tags': [{'name': 'Runbook', 'slug': 'runbook'}],
                }
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/notes/note-1',
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

    def test_patch_readonly_path_rejected(self) -> None:
        self.mock_db.execute.return_value = [
            {
                'n': self._note_data(),
                'p': self._project(),
                'tags': [],
            }
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/notes/note-1',
                json=[
                    {
                        'op': 'replace',
                        'path': '/created_by',
                        'value': 'attacker',
                    }
                ],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.patch(
            '/organizations/engineering/projects/proj-abc/notes/ghost',
            json=[{'op': 'replace', 'path': '/content', 'value': 'x'}],
        )
        self.assertEqual(response.status_code, 404)

    # -- Delete --------------------------------------------------------

    def test_delete_success(self) -> None:
        self.mock_db.execute.return_value = [{'n': True}]
        response = self.client.delete(
            '/organizations/engineering/projects/proj-abc/notes/note-1'
        )
        self.assertEqual(response.status_code, 204)

    def test_delete_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.delete(
            '/organizations/engineering/projects/proj-abc/notes/ghost'
        )
        self.assertEqual(response.status_code, 404)

    # -- Pagination + cursor edge cases --------------------------------

    def test_list_pagination_emits_next_cursor(self) -> None:
        """Returning limit+1 rows emits a Link header with rel=next."""
        rows = [
            {
                'n': self._note_data(
                    id=f'n{i}',
                    created_at=f'2026-03-1{i % 10}T12:00:00Z',
                ),
                'p': self._project(),
                'tags': [],
            }
            for i in range(3)
        ]
        self.mock_db.execute.return_value = rows
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/notes/?limit=2'
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
            {
                'n': self._note_data(id='n-next'),
                'p': self._project(),
                'tags': [],
            }
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                f'/organizations/engineering/notes/?cursor={cursor}'
            )
        self.assertEqual(response.status_code, 200)

    def test_patch_validation_error(self) -> None:
        """Patching /content to an empty string returns 400."""
        self.mock_db.execute.return_value = [
            {
                'n': self._note_data(),
                'p': self._project(),
                'tags': [],
            }
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/notes/note-1',
                json=[{'op': 'replace', 'path': '/content', 'value': ''}],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_concurrent_delete_returns_404(self) -> None:
        """Update query returning no rows after fetch yields 404."""
        self.mock_db.execute.side_effect = [
            [
                {
                    'n': self._note_data(),
                    'p': self._project(),
                    'tags': [],
                }
            ],
            [],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/projects/proj-abc/notes/note-1',
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
