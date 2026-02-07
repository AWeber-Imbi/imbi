"""Tests for team CRUD endpoints and membership."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient

from imbi_api import app, models


class TeamEndpointsTestCase(unittest.TestCase):
    """Test cases for team CRUD endpoints."""

    def setUp(self) -> None:
        """Set up test app with admin authentication."""
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
                'team:create',
                'team:read',
                'team:update',
                'team:delete',
            },
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.client = testclient.TestClient(self.test_app)

        self.test_org = models.Organization(
            name='Engineering',
            slug='engineering',
            description='Engineering organization',
        )

        self.test_team = models.Team(
            name='Backend',
            slug='backend',
            description='Backend team',
            organization=self.test_org,
        )

    def test_create_team_success(self) -> None:
        """Test successful team creation."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'team': {
                    'name': 'Backend',
                    'slug': 'backend',
                    'description': 'Backend team',
                    'organization': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                },
            }
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=mock_result,
            ),
        ):
            mock_get_model.return_value = models.Team

            response = self.client.post(
                '/teams/',
                json={
                    'name': 'Backend',
                    'slug': 'backend',
                    'description': 'Backend team',
                    'organization_slug': 'engineering',
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'backend')
        self.assertEqual(data['name'], 'Backend')

    def test_create_team_missing_org_slug(self) -> None:
        """Test creating team without organization_slug."""
        response = self.client.post(
            '/teams/',
            json={
                'name': 'Backend',
                'slug': 'backend',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'organization_slug',
            response.json()['detail'],
        )

    def test_create_team_org_not_found(self) -> None:
        """Test creating team with nonexistent organization."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=mock_result,
            ),
        ):
            mock_get_model.return_value = models.Team

            response = self.client.post(
                '/teams/',
                json={
                    'name': 'Backend',
                    'slug': 'backend',
                    'organization_slug': 'nonexistent',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_team_validation_error(self) -> None:
        """Test creating team with invalid data."""
        with mock.patch(
            'imbi_common.blueprints.get_model',
        ) as mock_get_model:
            mock_get_model.return_value = models.Team

            response = self.client.post(
                '/teams/',
                json={
                    'organization_slug': 'engineering',
                    # Missing required 'name' and 'slug'
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            'Validation error',
            response.json()['detail'],
        )

    def test_list_teams(self) -> None:
        """Test listing all teams."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'team': {
                    'name': 'Backend',
                    'slug': 'backend',
                    'organization': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                },
            }
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.get('/teams/')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'backend')

    def test_get_team(self) -> None:
        """Test retrieving a single team."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                'team': {
                    'name': 'Backend',
                    'slug': 'backend',
                    'description': 'Backend team',
                    'organization': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                },
            }
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.get('/teams/backend')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'backend')
        self.assertEqual(data['name'], 'Backend')

    def test_get_team_not_found(self) -> None:
        """Test retrieving nonexistent team."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.get('/teams/nonexistent')

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_update_team(self) -> None:
        """Test updating a team."""
        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.fetch_node',
            ) as mock_fetch,
            mock.patch(
                'imbi_common.neo4j.upsert',
            ) as mock_upsert,
        ):
            mock_get_model.return_value = models.Team
            mock_fetch.return_value = self.test_team
            mock_upsert.return_value = None

            response = self.client.put(
                '/teams/backend',
                json={
                    'name': 'Backend Services',
                    'slug': 'backend',
                    'description': 'Updated description',
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'Backend Services')
        mock_upsert.assert_called_once()

    def test_update_team_slug_mismatch(self) -> None:
        """Test updating with mismatched slugs."""
        response = self.client.put(
            '/teams/backend',
            json={
                'name': 'Backend',
                'slug': 'different-slug',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('must match', response.json()['detail'])

    def test_update_team_not_found(self) -> None:
        """Test updating nonexistent team."""
        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.fetch_node',
            ) as mock_fetch,
        ):
            mock_get_model.return_value = models.Team
            mock_fetch.return_value = None

            response = self.client.put(
                '/teams/nonexistent',
                json={
                    'name': 'Test',
                    'slug': 'nonexistent',
                },
            )

        self.assertEqual(response.status_code, 404)

    def test_delete_team(self) -> None:
        """Test deleting a team."""
        with mock.patch(
            'imbi_common.neo4j.delete_node',
        ) as mock_delete:
            mock_delete.return_value = True

            response = self.client.delete('/teams/backend')

        self.assertEqual(response.status_code, 204)
        mock_delete.assert_called_once_with(
            models.Team,
            {'slug': 'backend'},
        )

    def test_delete_team_not_found(self) -> None:
        """Test deleting nonexistent team."""
        with mock.patch(
            'imbi_common.neo4j.delete_node',
        ) as mock_delete:
            mock_delete.return_value = False

            response = self.client.delete(
                '/teams/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])


class TeamMembershipTestCase(unittest.TestCase):
    """Test cases for team membership endpoints."""

    def setUp(self) -> None:
        """Set up test app with admin authentication."""
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
                'team:create',
                'team:read',
                'team:update',
                'team:delete',
            },
        )

        async def mock_get_current_user():
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.client = testclient.TestClient(self.test_app)

    def test_list_members_empty(self) -> None:
        """Test listing members of a team with no members."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                't': {'name': 'Backend', 'slug': 'backend'},
                'members': [
                    {'email': None, 'display_name': None},
                ],
            }
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.get(
                '/teams/backend/members',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_members_populated(self) -> None:
        """Test listing members of a team with members."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {
                't': {'name': 'Backend', 'slug': 'backend'},
                'members': [
                    {
                        'email': 'dev@example.com',
                        'display_name': 'Developer',
                    },
                ],
            }
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.get(
                '/teams/backend/members',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['email'], 'dev@example.com')

    def test_list_members_team_not_found(self) -> None:
        """Test listing members of nonexistent team."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {'t': None, 'members': []},
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.get(
                '/teams/nonexistent/members',
            )

        self.assertEqual(response.status_code, 404)

    def test_add_member(self) -> None:
        """Test adding a user to a team."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [
            {'u': {'email': 'dev@example.com'}, 't': {}},
        ]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.post(
                '/teams/backend/members',
                json={'email': 'dev@example.com'},
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['email'], 'dev@example.com')
        self.assertEqual(data['team'], 'backend')

    def test_add_member_missing_email(self) -> None:
        """Test adding member without email."""
        response = self.client.post(
            '/teams/backend/members',
            json={},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.json()['detail'])

    def test_add_member_not_found(self) -> None:
        """Test adding nonexistent user to team."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.post(
                '/teams/backend/members',
                json={'email': 'nobody@example.com'},
            )

        self.assertEqual(response.status_code, 404)

    def test_remove_member(self) -> None:
        """Test removing a user from a team."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'deleted': 1}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.delete(
                '/teams/backend/members/dev@example.com',
            )

        self.assertEqual(response.status_code, 204)

    def test_remove_member_not_found(self) -> None:
        """Test removing nonexistent membership."""
        mock_result = mock.AsyncMock()
        mock_result.data.return_value = [{'deleted': 0}]
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None

        with mock.patch(
            'imbi_common.neo4j.run',
            return_value=mock_result,
        ):
            response = self.client.delete(
                '/teams/backend/members/nobody@example.com',
            )

        self.assertEqual(response.status_code, 404)
