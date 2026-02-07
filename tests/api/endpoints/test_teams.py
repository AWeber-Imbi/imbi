"""Tests for team CRUD endpoints and membership."""

import datetime
import unittest
from unittest import mock

from fastapi import testclient
from neo4j import exceptions

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

    def test_create_team_slug_conflict(self) -> None:
        """Test creating team with a slug that already exists."""
        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=exceptions.ConstraintError(),
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

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

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

    def _mock_team_run(self, team_data=None):
        """Create a mock for neo4j.run returning team data."""
        mock_result = mock.AsyncMock()
        if team_data is not None:
            mock_result.data.return_value = [
                {'team': team_data},
            ]
        else:
            mock_result.data.return_value = []
        mock_result.__aenter__.return_value = mock_result
        mock_result.__aexit__.return_value = None
        return mock_result

    def test_update_team(self) -> None:
        """Test updating a team."""
        team_data = {
            'name': 'Backend',
            'slug': 'backend',
            'description': 'Backend team',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        updated_data = {
            'name': 'Backend Services',
            'slug': 'backend',
            'description': 'Updated description',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        fetch_result = self._mock_team_run(team_data)
        update_result = self._mock_team_run(updated_data)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[fetch_result, update_result],
            ),
        ):
            mock_get_model.return_value = models.Team

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

    def test_update_team_slug_rename(self) -> None:
        """Test updating with different slug renames it."""
        team_data = {
            'name': 'Backend',
            'slug': 'backend',
            'description': 'Backend team',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        updated_data = {
            'name': 'Backend',
            'slug': 'new-slug',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        fetch_result = self._mock_team_run(team_data)
        update_result = self._mock_team_run(updated_data)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[fetch_result, update_result],
            ) as mock_run,
        ):
            mock_get_model.return_value = models.Team

            response = self.client.put(
                '/teams/backend',
                json={
                    'name': 'Backend',
                    'slug': 'new-slug',
                },
            )

            self.assertEqual(response.status_code, 200)
            # Second call is the update query with the old slug
            update_call = mock_run.call_args_list[1]
            self.assertEqual(
                update_call.kwargs['slug'],
                'backend',
            )

    def test_update_team_slug_conflict(self) -> None:
        """Test updating team with a slug that already exists."""
        team_data = {
            'name': 'Backend',
            'slug': 'backend',
            'description': 'Backend team',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        fetch_result = self._mock_team_run(team_data)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[
                    fetch_result,
                    exceptions.ConstraintError(),
                ],
            ),
        ):
            mock_get_model.return_value = models.Team

            response = self.client.put(
                '/teams/backend',
                json={
                    'name': 'Backend',
                    'slug': 'existing-slug',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_update_team_concurrent_delete(self) -> None:
        """Test updating a team that is deleted between fetch and update."""
        team_data = {
            'name': 'Backend',
            'slug': 'backend',
            'description': 'Backend team',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        fetch_result = self._mock_team_run(team_data)
        empty_result = self._mock_team_run(None)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                side_effect=[fetch_result, empty_result],
            ),
        ):
            mock_get_model.return_value = models.Team

            response = self.client.put(
                '/teams/backend',
                json={
                    'name': 'Backend Updated',
                    'slug': 'backend',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_update_team_not_found(self) -> None:
        """Test updating nonexistent team."""
        mock_run = self._mock_team_run(None)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=mock_run,
            ),
        ):
            mock_get_model.return_value = models.Team

            response = self.client.put(
                '/teams/nonexistent',
                json={
                    'name': 'Test',
                    'slug': 'nonexistent',
                },
            )

        self.assertEqual(response.status_code, 404)

    def test_update_team_validation_error(self) -> None:
        """Test updating team with invalid data."""
        team_data = {
            'name': 'Backend',
            'slug': 'backend',
            'description': 'Backend team',
            'organization': {
                'name': 'Engineering',
                'slug': 'engineering',
            },
        }
        mock_run = self._mock_team_run(team_data)

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.neo4j.run',
                return_value=mock_run,
            ),
        ):
            mock_get_model.return_value = models.Team

            response = self.client.put(
                '/teams/backend',
                json={'name': 123},
            )

        self.assertEqual(response.status_code, 400)

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
