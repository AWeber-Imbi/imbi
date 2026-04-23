"""Tests for organization CRUD endpoints."""

import datetime
import unittest
from unittest import mock

import psycopg.errors
from fastapi import testclient
from imbi_common import graph

from imbi_api import app, models


class OrganizationEndpointsTestCase(unittest.TestCase):
    """Test cases for organization CRUD endpoints."""

    def setUp(self) -> None:
        """Set up test app with admin authentication context."""
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
                'organization:create',
                'organization:read',
                'organization:update',
                'organization:delete',
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

    def test_create_organization_success(self) -> None:
        """Test successful organization creation."""
        self.mock_db.create.return_value = self.test_org

        response = self.client.post(
            '/organizations/',
            json={
                'name': 'Engineering',
                'slug': 'engineering',
                'description': 'Engineering organization',
            },
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['slug'], 'engineering')
        self.assertEqual(data['name'], 'Engineering')
        self.assertIn('relationships', data)
        rels = data['relationships']
        self.assertIn('teams', rels)
        self.assertIn('members', rels)
        self.assertIn('projects', rels)
        self.assertEqual(
            rels['teams']['count'],
            0,
        )
        self.assertEqual(
            rels['members']['count'],
            0,
        )
        self.assertEqual(
            rels['projects']['count'],
            0,
        )

    def test_create_organization_validation_error(self) -> None:
        """Test creating organization with invalid data."""
        response = self.client.post(
            '/organizations/',
            json={
                'name': 'Engineering',
                # Missing required 'slug' field
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_create_organization_duplicate_slug(self) -> None:
        """Test creating organization with duplicate slug."""
        self.mock_db.create.side_effect = psycopg.errors.UniqueViolation(
            'Duplicate'
        )

        response = self.client.post(
            '/organizations/',
            json={
                'name': 'Engineering',
                'slug': 'engineering',
                'description': 'Engineering organization',
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn(
            'already exists',
            response.json()['detail'],
        )

    def test_list_organizations(self) -> None:
        """Test listing all organizations."""
        self.mock_db.execute.return_value = [
            {
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                    'description': 'Engineering organization',
                },
                'team_count': 3,
                'member_count': 10,
                'project_count': 25,
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get('/organizations/')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['slug'], 'engineering')
        rels = data[0]['relationships']
        self.assertEqual(
            rels['teams']['count'],
            3,
        )
        self.assertEqual(
            rels['teams']['href'],
            '/api/organizations/engineering/teams',
        )
        self.assertEqual(
            rels['members']['count'],
            10,
        )
        self.assertEqual(
            rels['members']['href'],
            '/api/organizations/engineering/members',
        )
        self.assertEqual(
            rels['projects']['count'],
            25,
        )
        self.assertEqual(
            rels['projects']['href'],
            '/api/organizations/engineering/projects',
        )

    def test_get_organization(self) -> None:
        """Test retrieving single organization."""
        self.mock_db.execute.return_value = [
            {
                'o': {
                    'name': 'Engineering',
                    'slug': 'engineering',
                    'description': 'Engineering organization',
                },
                'team_count': 2,
                'member_count': 5,
                'project_count': 12,
            },
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                '/organizations/engineering',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['slug'], 'engineering')
        self.assertEqual(data['name'], 'Engineering')
        rels = data['relationships']
        self.assertEqual(
            rels['teams']['count'],
            2,
        )

    def test_get_organization_not_found(self) -> None:
        """Test retrieving non-existent organization."""
        self.mock_db.execute.return_value = []

        response = self.client.get(
            '/organizations/nonexistent',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn(
            'not found',
            response.json()['detail'],
        )

    def test_delete_organization(self) -> None:
        """Test deleting organization."""
        self.mock_db.execute.return_value = [{'n': 'true'}]

        response = self.client.delete(
            '/organizations/engineering',
        )

        self.assertEqual(response.status_code, 204)
        self.mock_db.execute.assert_called_once()

    def test_delete_organization_not_found(self) -> None:
        """Test deleting non-existent organization."""
        self.mock_db.execute.return_value = []

        response = self.client.delete(
            '/organizations/nonexistent',
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn(
            'not found',
            response.json()['detail'],
        )

    def test_patch_organization_name(self) -> None:
        """Test patching only the organization name."""
        self.mock_db.match.return_value = [self.test_org]
        self.mock_db.execute.side_effect = [
            [{'n': 'true'}],  # SET query
            [
                {'team_count': 1, 'member_count': 2, 'project_count': 3}
            ],  # counts
        ]

        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                '/organizations/engineering',
                json=[{'op': 'replace', 'path': '/name', 'value': 'Eng Dept'}],
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name'], 'Eng Dept')
        self.assertIn('relationships', data)

    def test_patch_organization_not_found(self) -> None:
        """Test patching non-existent organization returns 404."""
        self.mock_db.match.return_value = []

        response = self.client.patch(
            '/organizations/nonexistent',
            json=[{'op': 'replace', 'path': '/name', 'value': 'Test'}],
        )

        self.assertEqual(response.status_code, 404)

    def test_patch_organization_readonly_field(self) -> None:
        """Test patching created_at returns 400."""
        self.mock_db.match.return_value = [self.test_org]

        response = self.client.patch(
            '/organizations/engineering',
            json=[
                {
                    'op': 'replace',
                    'path': '/created_at',
                    'value': '2025-01-01T00:00:00Z',
                }
            ],
        )

        self.assertEqual(response.status_code, 400)

    def test_patch_organization_slug_conflict(self) -> None:
        """Test slug rename to conflicting slug returns 409."""
        self.mock_db.match.return_value = [self.test_org]
        self.mock_db.execute.side_effect = psycopg.errors.UniqueViolation(
            'Duplicate'
        )

        response = self.client.patch(
            '/organizations/engineering',
            json=[{'op': 'replace', 'path': '/slug', 'value': 'taken-slug'}],
        )

        self.assertEqual(response.status_code, 409)

    def test_patch_organization_concurrent_delete(self) -> None:
        """Update query returning no rows yields 404."""
        self.mock_db.match.return_value = [self.test_org]
        self.mock_db.execute.side_effect = [[]]

        response = self.client.patch(
            '/organizations/engineering',
            json=[{'op': 'replace', 'path': '/name', 'value': 'Renamed'}],
        )

        self.assertEqual(response.status_code, 404)

    def test_patch_organization_validation_error(self) -> None:
        """Patch that yields invalid model returns 400."""
        self.mock_db.match.return_value = [self.test_org]

        response = self.client.patch(
            '/organizations/engineering',
            json=[{'op': 'replace', 'path': '/name', 'value': None}],
        )

        self.assertEqual(response.status_code, 400)
