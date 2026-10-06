"""Tests for tag CRUD endpoints."""

import datetime
import typing
import unittest
from unittest import mock

import psycopg.errors
from fastapi.testclient import TestClient

from apps.api.tests import support
from imbi.api import models
from imbi.common import graph


class TagEndpointsTestCase(support.SharedAppTestCase):
    """Test cases for tag CRUD endpoints."""

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
                'tag:create',
                'tag:read',
                'tag:write',
                'tag:delete',
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

    def _tag_data(self, **overrides: typing.Any) -> dict:
        data: dict[str, typing.Any] = {
            'id': 'tag-123',
            'name': 'Runbook',
            'slug': 'runbook',
            'description': None,
            'created_at': '2026-03-17T12:00:00Z',
            'updated_at': '2026-03-17T12:00:00Z',
        }
        data.update(overrides)
        return data

    def _org_data(self) -> dict:
        return {'name': 'Engineering', 'slug': 'engineering'}

    # -- Create --------------------------------------------------------

    def test_create_success(self) -> None:
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/tags/',
                json={'name': 'Runbook'},
            )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['slug'], 'runbook')
        self.assertEqual(body['relationships']['documents']['count'], 0)

    def test_create_auto_slugifies_from_name(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(name='Post Mortem', slug='post-mortem'),
                'o': self._org_data(),
            }
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/tags/',
                json={'name': 'Post Mortem'},
            )
        self.assertEqual(response.status_code, 201)
        # second positional arg of .execute call contains the params dict
        _, args, _ = self.mock_db.execute.mock_calls[0]
        self.assertEqual(args[1]['slug'], 'post-mortem')

    def test_create_rejects_empty_name(self) -> None:
        response = self.client.post(
            '/organizations/engineering/tags/',
            json={'name': ''},
        )
        self.assertEqual(response.status_code, 422)

    def test_create_rejects_empty_slug(self) -> None:
        response = self.client.post(
            '/organizations/engineering/tags/',
            json={'name': 'Runbook', 'slug': ''},
        )
        self.assertEqual(response.status_code, 422)

    def test_create_slug_conflict(self) -> None:
        self.mock_db.execute.side_effect = psycopg.errors.UniqueViolation()
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/tags/',
                json={'name': 'Runbook', 'slug': 'runbook'},
            )
        self.assertEqual(response.status_code, 409)

    def test_create_org_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/ghost/tags/',
                json={'name': 'Runbook'},
            )
        self.assertEqual(response.status_code, 404)

    # -- List ----------------------------------------------------------

    def test_list_success(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(),
                'o': self._org_data(),
                'document_count': 4,
            },
            {
                't': self._tag_data(name='Alert', slug='alert'),
                'o': self._org_data(),
                'document_count': 0,
            },
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get('/organizations/engineering/tags/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['relationships']['documents']['count'], 4)

    # -- Get -----------------------------------------------------------

    def test_get_success(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(),
                'o': self._org_data(),
                'document_count': 2,
            }
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/tags/runbook'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['relationships']['documents']['count'], 2
        )

    def test_get_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/tags/missing'
            )
        self.assertEqual(response.status_code, 404)

    # -- Patch ---------------------------------------------------------

    def test_patch_rename(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'t': self._tag_data(), 'o': self._org_data()}],
            [
                {
                    't': self._tag_data(name='Runbooks'),
                    'o': self._org_data(),
                    'document_count': 3,
                }
            ],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/name', 'value': 'Runbooks'}],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'Runbooks')

    def test_patch_slug_conflict(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'t': self._tag_data(), 'o': self._org_data()}],
            psycopg.errors.UniqueViolation(),
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/slug', 'value': 'alert'}],
            )
        self.assertEqual(response.status_code, 409)

    def test_patch_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.patch(
            '/organizations/engineering/tags/missing',
            json=[{'op': 'replace', 'path': '/name', 'value': 'X'}],
        )
        self.assertEqual(response.status_code, 404)

    def test_patch_readonly_path_rejected(self) -> None:
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/id', 'value': 'xxx'}],
            )
        self.assertEqual(response.status_code, 400)

    # -- Delete --------------------------------------------------------

    def test_delete_success(self) -> None:
        self.mock_db.execute.return_value = [{'t': True}]
        response = self.client.delete(
            '/organizations/engineering/tags/runbook'
        )
        self.assertEqual(response.status_code, 204)

    def test_delete_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.delete(
            '/organizations/engineering/tags/missing'
        )
        self.assertEqual(response.status_code, 404)

    def test_patch_validation_error(self) -> None:
        """Patching /name to non-string triggers a 400 validation error."""
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/name', 'value': 123}],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_rejects_empty_name(self) -> None:
        """Patching /name to an empty string yields a 400."""
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/name', 'value': ''}],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_rejects_empty_slug(self) -> None:
        """Patching /slug to an empty string yields a 400."""
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/slug', 'value': ''}],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_concurrent_delete_returns_404(self) -> None:
        """Update returning no rows after fetch yields 404."""
        self.mock_db.execute.side_effect = [
            [{'t': self._tag_data(), 'o': self._org_data()}],
            [],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/name', 'value': 'Runbooks'}],
            )
        self.assertEqual(response.status_code, 404)

    # -- Color ---------------------------------------------------------

    def test_create_with_color(self) -> None:
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(color='#3B82F6'), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/tags/',
                json={'name': 'Runbook', 'color': '#3B82F6'},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['color'], '#3B82F6')
        _, args, _ = self.mock_db.execute.mock_calls[0]
        self.assertEqual(args[1]['color'], '#3B82F6')

    def test_create_without_color_stores_null(self) -> None:
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/tags/',
                json={'name': 'Runbook'},
            )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()['color'])
        _, args, _ = self.mock_db.execute.mock_calls[0]
        self.assertIsNone(args[1]['color'])

    def test_create_rejects_invalid_color(self) -> None:
        for color in ('blue', '#3B82F', '#3B82F6AA', '3B82F6', '#GGGGGG'):
            with self.subTest(color=color):
                response = self.client.post(
                    '/organizations/engineering/tags/',
                    json={'name': 'Runbook', 'color': color},
                )
                self.assertEqual(response.status_code, 422)

    def test_get_returns_color(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(color='#abcdef'),
                'o': self._org_data(),
                'document_count': 0,
            }
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/tags/runbook'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['color'], '#abcdef')

    def test_list_returns_color(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(color='#abcdef'),
                'o': self._org_data(),
                'document_count': 0,
            }
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get('/organizations/engineering/tags/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['color'], '#abcdef')

    def _patch_color(
        self,
        existing: str | None,
        operation: dict[str, typing.Any],
        stored: str | None,
    ) -> typing.Any:
        self.mock_db.execute.side_effect = [
            [{'t': self._tag_data(color=existing), 'o': self._org_data()}],
            [
                {
                    't': self._tag_data(color=stored),
                    'o': self._org_data(),
                    'document_count': 0,
                }
            ],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            return self.client.patch(
                '/organizations/engineering/tags/runbook', json=[operation]
            )

    def test_patch_sets_color(self) -> None:
        response = self._patch_color(
            None,
            {'op': 'add', 'path': '/color', 'value': '#FF0000'},
            '#FF0000',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['color'], '#FF0000')
        params = self.mock_db.execute.await_args_list[1].args[1]
        self.assertEqual(params['color'], '#FF0000')

    def test_patch_clears_color(self) -> None:
        response = self._patch_color(
            '#FF0000', {'op': 'replace', 'path': '/color', 'value': None}, None
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['color'])
        params = self.mock_db.execute.await_args_list[1].args[1]
        self.assertIsNone(params['color'])

    def test_patch_other_field_keeps_color(self) -> None:
        response = self._patch_color(
            '#FF0000',
            {'op': 'replace', 'path': '/name', 'value': 'Runbooks'},
            '#FF0000',
        )
        self.assertEqual(response.status_code, 200)
        params = self.mock_db.execute.await_args_list[1].args[1]
        self.assertEqual(params['color'], '#FF0000')

    def test_patch_rejects_invalid_color(self) -> None:
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'add', 'path': '/color', 'value': 'red'}],
            )
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
