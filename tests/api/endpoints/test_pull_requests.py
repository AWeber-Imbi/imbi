"""Tests for the pull request read endpoints."""

import datetime
import typing
import unittest
from unittest import mock

import fastapi.testclient
from imbi_common import graph

from imbi_api import app, models

ORG = 'engineering'
PROJECT_ID = 'proj123nanoid'


def _pr_row(**overrides: typing.Any) -> dict[str, typing.Any]:
    """Build a ClickHouse-shaped pull_requests row."""
    data: dict[str, typing.Any] = {
        'project_id': PROJECT_ID,
        'pr_id': 'pr-1',
        'pr_number': 42,
        'title': 'Fix bug',
        'url': 'https://github.com/example/repo/pull/42',
        'state': 'open',
        'author': 'alice',
        'draft': False,
        'merged': False,
        # ClickHouse returns naive datetimes; the endpoint attaches
        # UTC via ``_row_to_response``.
        'created_at': datetime.datetime(2026, 4, 1, 12, 0, 0),  # noqa: DTZ001
        'updated_at': datetime.datetime(2026, 4, 2, 12, 0, 0),  # noqa: DTZ001
        'merged_at': None,
        'additions': 5,
        'deletions': 2,
        'changed_files': 1,
    }
    data.update(overrides)
    return data


class _PullRequestsTestBase(unittest.TestCase):
    """Shared setup mounting pull request endpoints with admin auth."""

    permissions_granted: typing.ClassVar[set[str]] = {'project:read'}

    def setUp(self) -> None:
        from imbi_api.auth import permissions

        self.test_app = app.create_app()

        self.admin_user = models.User(
            email='alice@example.com',
            display_name='Alice',
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
            permissions=self.permissions_granted,
        )

        async def _current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            _current_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )
        self.client = fastapi.testclient.TestClient(self.test_app)
        self.addCleanup(self.client.close)


class ListProjectPullRequestsTestCase(_PullRequestsTestBase):
    """GET /organizations/{org}/projects/{pid}/pull-requests/"""

    def _url(self, query: str = '') -> str:
        base = f'/organizations/{ORG}/projects/{PROJECT_ID}/pull-requests/'
        return f'{base}{query}'

    def test_list_returns_prs_after_org_scope_check(self) -> None:
        # First db.execute is the org->project_ids check; subsequent
        # calls are ClickHouse, mocked separately.
        self.mock_db.execute.return_value = [{'id': PROJECT_ID}]
        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.pull_requests.clickhouse.query',
                new=mock.AsyncMock(
                    side_effect=[
                        [{'total': 1, 'project_count': 1}],
                        [_pr_row()],
                    ]
                ),
            ),
        ):
            response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['total'], 1)
        self.assertEqual(body['project_count'], 1)
        self.assertEqual(len(body['data']), 1)
        self.assertEqual(body['data'][0]['pr_number'], 42)

    def test_list_404_when_project_not_in_org(self) -> None:
        # Org scope check returns no rows → project_id not in org.
        self.mock_db.execute.return_value = []
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)
        self.assertIn('not found in organization', response.json()['detail'])

    def test_list_400_on_invalid_limit(self) -> None:
        self.mock_db.execute.return_value = [{'id': PROJECT_ID}]
        response = self.client.get(self._url('?limit=0'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('limit must be', response.json()['detail'])

    def test_list_400_on_negative_offset(self) -> None:
        self.mock_db.execute.return_value = [{'id': PROJECT_ID}]
        response = self.client.get(self._url('?offset=-1'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('offset must be >= 0', response.json()['detail'])


class ListOrgPullRequestsTestCase(_PullRequestsTestBase):
    """GET /organizations/{org}/pull-requests/"""

    def _url(self, query: str = '') -> str:
        return f'/organizations/{ORG}/pull-requests/{query}'

    def test_list_empty_when_no_projects(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['total'], 0)
        self.assertEqual(body['project_count'], 0)
        self.assertEqual(body['data'], [])

    def test_list_returns_prs_across_org_projects(self) -> None:
        self.mock_db.execute.return_value = [
            {'id': PROJECT_ID},
            {'id': 'proj-2'},
        ]
        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.pull_requests.clickhouse.query',
                new=mock.AsyncMock(
                    side_effect=[
                        [{'total': 2, 'project_count': 2}],
                        [
                            _pr_row(pr_id='pr-a', pr_number=1),
                            _pr_row(pr_id='pr-b', pr_number=2),
                        ],
                    ]
                ),
            ),
        ):
            response = self.client.get(
                self._url('?state=open&author=alice&limit=10&offset=0')
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['total'], 2)
        self.assertEqual(len(body['data']), 2)
