"""Tests for team CRUD endpoints and membership."""

import datetime
import unittest
from unittest import mock

import psycopg.errors
from fastapi import testclient
from imbi_common import graph

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

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
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
        self.mock_db.execute.return_value = [
            {
                't': {
                    'name': 'Backend',
                    'slug': 'backend',
                    'description': 'Backend team',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
            }
        ]

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_get_model.return_value = models.Team

            response = self.client.post(
                '/organizations/engineering/teams/',
                json={
                    'name': 'Backend',
                    'slug': 'backend',
                    'description': 'Backend team',
                },
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'backend')
        self.assertEqual(data['name'], 'Backend')
        self.assertIn('relationships', data)
        rels = data['relationships']
        self.assertEqual(
            rels['projects']['count'],
            0,
        )
        self.assertEqual(
            rels['members']['count'],
            0,
        )

    def test_create_team_org_not_found_in_url(self) -> None:
        """Test that a nonexistent org in URL returns 404."""
        self.mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_get_model.return_value = models.Team

            response = self.client.post(
                '/organizations/nonexistent/teams/',
                json={
                    'name': 'Backend',
                    'slug': 'backend',
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_create_team_org_not_found(self) -> None:
        """Test creating team with nonexistent organization."""
        self.mock_db.execute.return_value = []

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_get_model.return_value = models.Team

            response = self.client.post(
                '/organizations/nonexistent/teams/',
                json={
                    'name': 'Backend',
                    'slug': 'backend',
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
                '/organizations/engineering/teams/',
                json={
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
        self.mock_db.execute.side_effect = psycopg.errors.UniqueViolation()

        with (
            mock.patch(
                'imbi_common.blueprints.get_model',
            ) as mock_get_model,
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            mock_get_model.return_value = models.Team

            response = self.client.post(
                '/organizations/engineering/teams/',
                json={
                    'name': 'Backend',
                    'slug': 'backend',
                    'description': 'Backend team',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    def test_list_teams(self) -> None:
        """Test listing all teams with relationships."""
        self.mock_db.execute.return_value = [
            {
                't': {
                    'name': 'Backend',
                    'slug': 'backend',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
                'project_count': 5,
                'member_count': 3,
            }
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/teams/',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'backend')
        rels = data[0]['relationships']
        self.assertEqual(
            rels['projects']['count'],
            5,
        )
        self.assertEqual(
            rels['members']['count'],
            3,
        )

    def test_get_team(self) -> None:
        """Test retrieving a single team."""
        self.mock_db.execute.return_value = [
            {
                't': {
                    'name': 'Backend',
                    'slug': 'backend',
                    'description': 'Backend team',
                },
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
                'project_count': 10,
                'member_count': 4,
            }
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/teams/backend'
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'backend')
        self.assertEqual(data['name'], 'Backend')
        rels = data['relationships']
        self.assertEqual(
            rels['projects']['count'],
            10,
        )

    def test_get_team_not_found(self) -> None:
        """Test retrieving nonexistent team."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/teams/nonexistent'
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_delete_team(self) -> None:
        """Test deleting a team."""
        self.mock_db.execute.return_value = [{'t': True}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                '/organizations/engineering/teams/backend',
            )

        self.assertEqual(response.status_code, 204)

    def test_delete_team_not_found(self) -> None:
        """Test deleting nonexistent team."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                '/organizations/engineering/teams/nonexistent',
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn('not found', response.json()['detail'])

    def test_patch_team_name(self) -> None:
        """Test patching only the team name."""
        from imbi_common import models as common_models

        test_team_dict = {
            'name': 'Platform',
            'slug': 'platform',
            'description': 'Platform team',
        }
        self.mock_db.execute.side_effect = [
            # fetch query
            [
                {
                    't': test_team_dict,
                    'o': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                }
            ],
            # SET update query (returns with counts)
            [
                {
                    't': {
                        'name': 'Platform Eng',
                        'slug': 'platform',
                        'description': 'Platform team',
                    },
                    'o': {
                        'name': 'Engineering',
                        'slug': 'engineering',
                    },
                    'project_count': 0,
                    'member_count': 0,
                }
            ],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            with mock.patch(
                'imbi_common.blueprints.get_model',
                return_value=common_models.Team,
            ):
                response = self.client.patch(
                    '/organizations/engineering/teams/platform',
                    json=[
                        {
                            'op': 'replace',
                            'path': '/name',
                            'value': 'Platform Eng',
                        }
                    ],
                )

        self.assertEqual(response.status_code, 200)

    def test_patch_team_not_found(self) -> None:
        """Test patching a non-existent team returns 404."""
        from imbi_common import models as common_models

        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.blueprints.get_model',
            return_value=common_models.Team,
        ):
            response = self.client.patch(
                '/organizations/engineering/teams/nonexistent',
                json=[
                    {
                        'op': 'replace',
                        'path': '/name',
                        'value': 'X',
                    }
                ],
            )

        self.assertEqual(response.status_code, 404)

    def test_patch_team_readonly_field(self) -> None:
        """Test patching created_at returns 400."""
        from imbi_common import models as common_models

        test_team_dict = {
            'name': 'Platform',
            'slug': 'platform',
            'description': 'Platform team',
        }
        self.mock_db.execute.return_value = [
            {
                't': test_team_dict,
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                },
            }
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            with mock.patch(
                'imbi_common.blueprints.get_model',
                return_value=common_models.Team,
            ):
                response = self.client.patch(
                    '/organizations/engineering/teams/platform',
                    json=[
                        {
                            'op': 'replace',
                            'path': '/created_at',
                            'value': '2025-01-01T00:00:00Z',
                        }
                    ],
                )

        self.assertEqual(response.status_code, 400)

    def test_patch_team_slug_conflict(self) -> None:
        """Renaming team slug to a conflicting value returns 409."""
        from imbi_common import models as common_models

        existing = {
            'name': 'Backend',
            'slug': 'backend',
            'description': 'Backend team',
        }
        self.mock_db.execute.side_effect = [
            [
                {
                    't': existing,
                    'o': {'name': 'Engineering', 'slug': 'engineering'},
                },
            ],
            psycopg.errors.UniqueViolation(),
        ]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi_common.blueprints.get_model',
                return_value=common_models.Team,
            ),
        ):
            response = self.client.patch(
                '/organizations/engineering/teams/backend',
                json=[{'op': 'replace', 'path': '/slug', 'value': 'taken'}],
            )

        self.assertEqual(response.status_code, 409)

    def test_patch_team_concurrent_delete(self) -> None:
        """Update returning no rows yields 404."""
        from imbi_common import models as common_models

        existing = {
            'name': 'Backend',
            'slug': 'backend',
        }
        self.mock_db.execute.side_effect = [
            [
                {
                    't': existing,
                    'o': {'name': 'Engineering', 'slug': 'engineering'},
                },
            ],
            [],
        ]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi_common.blueprints.get_model',
                return_value=common_models.Team,
            ),
        ):
            response = self.client.patch(
                '/organizations/engineering/teams/backend',
                json=[{'op': 'replace', 'path': '/name', 'value': 'New'}],
            )

        self.assertEqual(response.status_code, 404)


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

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )

        self.client = testclient.TestClient(self.test_app)

    def test_list_members_empty(self) -> None:
        """Test listing members of a team with no members."""
        self.mock_db.execute.side_effect = [
            # Team check: team exists
            [{'t': {'name': 'Backend', 'slug': 'backend'}}],
            # Member query: no members
            [],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/teams/backend/members',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_members_populated(self) -> None:
        """Test listing members of a team with members."""
        self.mock_db.execute.side_effect = [
            # Team check: team exists
            [{'t': {'name': 'Backend', 'slug': 'backend'}}],
            # Member query: one member
            [
                {
                    'email': 'dev@example.com',
                    'display_name': 'Developer',
                    'is_active': True,
                    'is_admin': False,
                },
            ],
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/teams/backend/members',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['email'], 'dev@example.com')

    def test_list_members_team_not_found(self) -> None:
        """Test listing members of nonexistent team."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering/teams/nonexistent/members',
            )

        self.assertEqual(response.status_code, 404)

    def test_add_member(self) -> None:
        """Test adding a user to a team."""
        self.mock_db.execute.return_value = [
            {
                'u': {'email': 'dev@example.com'},
                't': {},
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/organizations/engineering/teams/backend/members',
                json={'email': 'dev@example.com'},
            )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['email'], 'dev@example.com')
        self.assertEqual(data['team'], 'backend')

    def test_add_member_missing_email(self) -> None:
        """Test adding member without email."""
        response = self.client.post(
            '/organizations/engineering/teams/backend/members',
            json={},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.json()['detail'])

    def test_add_member_not_found(self) -> None:
        """Test adding nonexistent user to team."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                '/organizations/engineering/teams/backend/members',
                json={'email': 'nobody@example.com'},
            )

        self.assertEqual(response.status_code, 404)

    def test_remove_member(self) -> None:
        """Test removing a user from a team."""
        self.mock_db.execute.return_value = [{'m': True}]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                '/organizations/engineering/teams/backend'
                '/members/dev@example.com',
            )

        self.assertEqual(response.status_code, 204)

    def test_remove_member_not_found(self) -> None:
        """Test removing nonexistent membership."""
        self.mock_db.execute.return_value = []

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.delete(
                '/organizations/engineering/teams/backend'
                '/members/nobody@example.com',
            )

        self.assertEqual(response.status_code, 404)
