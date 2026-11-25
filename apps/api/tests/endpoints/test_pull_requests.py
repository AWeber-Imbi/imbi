"""Tests for the pull request read endpoints."""

import datetime
import typing
import unittest
from unittest import mock

import fastapi.testclient

from apps.api.tests import support
from imbi.api import models
from imbi.api.auth import organizations as org_auth
from imbi.api.endpoints import pull_requests
from imbi.common import graph

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


def _naive(hour: int) -> datetime.datetime:
    """A naive 2026-04-02 timestamp, as ClickHouse returns them."""
    aware = datetime.datetime(2026, 4, 2, hour, tzinfo=datetime.UTC)
    return aware.replace(tzinfo=None)


class _PullRequestsTestBase(support.SharedAppTestCase):
    """Shared setup mounting pull request endpoints with admin auth."""

    permissions_granted: typing.ClassVar[set[str]] = {'project:read'}

    def setUp(self) -> None:
        from imbi.api.auth import permissions

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

        self.test_app.dependency_overrides[org_auth.member_project_org_id] = (
            lambda: 'org-1'
        )
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
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.pull_requests.clickhouse.query',
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

    def test_list_merges_requested_and_past_reviewers(self) -> None:
        self.mock_db.execute.return_value = [{'id': PROJECT_ID}]
        query = mock.AsyncMock(
            side_effect=[
                [{'total': 1, 'project_count': 1}],
                [_pr_row()],
                [
                    {
                        'pr_id': 'pr-1',
                        'reviewer': 'bob',
                        'review_state': 'approved',
                        'last_submitted_at': _naive(9),
                    },
                    {
                        'pr_id': 'pr-1',
                        'reviewer': 'dave',
                        'review_state': 'changes_requested',
                        'last_submitted_at': _naive(10),
                    },
                    # The author's replies are recorded as reviews too.
                    {
                        'pr_id': 'pr-1',
                        'reviewer': 'alice',
                        'review_state': 'commented',
                        'last_submitted_at': _naive(11),
                    },
                ],
                [
                    {
                        'pr_id': 'pr-1',
                        'requested_reviewers': ['carol', 'bob'],
                        'requested_teams': ['platform'],
                    }
                ],
            ]
        )
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.pull_requests.clickhouse.query',
                new=query,
            ),
        ):
            response = self.client.get(self._url('?state=open'))
        self.assertEqual(response.status_code, 200)
        reviewers = response.json()['data'][0]['reviewers']
        self.assertEqual(
            [(r['login'], r['state'], r['team']) for r in reviewers],
            [
                # bob was re-requested after approving.
                ('bob', 'requested', False),
                ('dave', 'changes_requested', False),
                ('carol', 'requested', False),
                ('platform', 'requested', True),
            ],
        )
        self.assertEqual(reviewers[1]['submitted_at'], '2026-04-02T10:00:00Z')
        sql, params = query.call_args_list[2].args
        self.assertIn('FROM pull_request_reviews FINAL', sql)
        self.assertEqual(params['pr_ids'], ['pr-1'])
        sql, _params = query.call_args_list[3].args
        self.assertIn('FROM pull_request_review_requests FINAL', sql)

    def _list_with(self, query: mock.AsyncMock, url: str) -> typing.Any:
        self.mock_db.execute.return_value = [{'id': PROJECT_ID}]
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.pull_requests.clickhouse.query',
                new=query,
            ),
        ):
            return self.client.get(url)

    def test_closed_list_skips_reviewer_queries(self) -> None:
        query = mock.AsyncMock(
            side_effect=[
                [{'total': 1, 'project_count': 1}],
                [_pr_row(state='closed')],
            ]
        )
        response = self._list_with(query, self._url('?state=closed'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(query.await_count, 2)
        self.assertEqual(response.json()['data'][0]['reviewers'], [])

    def test_reviewer_query_failure_still_lists_prs(self) -> None:
        query = mock.AsyncMock(
            side_effect=[
                [{'total': 1, 'project_count': 1}],
                [_pr_row()],
                RuntimeError('no such table'),
            ]
        )
        with self.assertLogs(pull_requests.LOGGER, level='ERROR'):
            response = self._list_with(query, self._url('?state=open'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'][0]['reviewers'], [])

    def test_list_keeps_drafts_and_archived_projects(self) -> None:
        # The project page has its own Draft tab and must stay readable
        # after the project is archived, so neither filter applies here.
        self.mock_db.execute.return_value = [{'id': PROJECT_ID}]
        query = mock.AsyncMock(
            side_effect=[[{'total': 0, 'project_count': 0}], []]
        )
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.pull_requests.clickhouse.query',
                new=query,
            ),
        ):
            response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        # The router dependency checks the project; no project query.
        self.mock_db.execute.assert_not_called()
        for call in query.call_args_list:
            self.assertNotIn('draft', call.args[0])

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
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.pull_requests.clickhouse.query',
                new=mock.AsyncMock(
                    side_effect=[
                        [{'total': 2, 'project_count': 2}],
                        [
                            _pr_row(pr_id='pr-a', pr_number=1),
                            _pr_row(pr_id='pr-b', pr_number=2),
                        ],
                        [],
                        [],
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

    def test_list_skips_drafts_and_archived_projects(self) -> None:
        self.mock_db.execute.return_value = [{'id': PROJECT_ID}]
        query = mock.AsyncMock(
            side_effect=[[{'total': 0, 'project_count': 0}], []]
        )
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.pull_requests.clickhouse.query',
                new=query,
            ),
        ):
            response = self.client.get(self._url('?state=open'))
        self.assertEqual(response.status_code, 200)
        cypher = self.mock_db.execute.call_args.args[0]
        self.assertIn('coalesce(p.archived, false) = false', cypher)
        count_sql, data_sql = (call.args[0] for call in query.call_args_list)
        self.assertIn('state = {state:String} AND NOT draft', count_sql)
        self.assertIn('state = {state:String} AND NOT draft', data_sql)


def _identities(*rows: dict[str, typing.Any]) -> typing.Any:
    """Patch the identity connections of the caller."""
    return mock.patch(
        'imbi.api.endpoints.pull_requests.identity_repository.list_for_user',
        new=mock.AsyncMock(return_value=list(rows)),
    )


GITHUB_IDENTITY: dict[str, typing.Any] = {
    'plugin': 'github',
    'status': 'active',
    'metadata': {'login': 'alice-gh'},
}


class GithubLoginTestCase(unittest.IsolatedAsyncioTestCase):
    """``github_login`` reads the login of a GitHub connection."""

    def _auth(self) -> typing.Any:
        return mock.Mock(user=mock.Mock(id='u1'))

    async def test_login_of_active_github_connection(self) -> None:
        other = {'plugin': 'sentry', 'status': 'active', 'metadata': {}}
        with _identities(other, GITHUB_IDENTITY):
            login = await pull_requests.github_login(mock.Mock(), self._auth())
        self.assertEqual(login, 'alice-gh')

    async def test_none_without_an_active_github_connection(self) -> None:
        rows = (
            {**GITHUB_IDENTITY, 'status': 'revoked'},
            {**GITHUB_IDENTITY, 'plugin': 'github-enterprise-cloud'},
            {**GITHUB_IDENTITY, 'metadata': {}},
        )
        with _identities(*rows):
            login = await pull_requests.github_login(mock.Mock(), self._auth())
        self.assertIsNone(login)

    async def test_none_for_a_service_account(self) -> None:
        login = await pull_requests.github_login(
            mock.Mock(), mock.Mock(user=None)
        )
        self.assertIsNone(login)


class MeFiltersTestCase(_PullRequestsTestBase):
    """``@me`` on ``author`` and ``reviewer`` (Slack App Home)."""

    def _list(self, query: str) -> tuple[typing.Any, mock.AsyncMock]:
        self.mock_db.execute.return_value = [{'id': PROJECT_ID}]
        ch = mock.AsyncMock(
            side_effect=[[{'total': 1, 'project_count': 1}], [_pr_row()]]
        )
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype', side_effect=lambda x: x
            ),
            mock.patch(
                'imbi.api.endpoints.pull_requests.clickhouse.query', new=ch
            ),
        ):
            response = self.client.get(
                f'/organizations/{ORG}/pull-requests/{query}'
            )
        return response, ch

    def test_author_me_resolves_to_login(self) -> None:
        with _identities(GITHUB_IDENTITY):
            response, ch = self._list('?author=@me')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['github_identity_missing'])
        self.assertEqual(ch.call_args.args[1]['author'], 'alice-gh')

    def test_me_without_identity_is_empty_with_flag(self) -> None:
        for query in ('?author=@me', '?state=open&reviewer=@me'):
            with self.subTest(query=query), _identities():
                response, ch = self._list(query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(),
                    {
                        'data': [],
                        'project_count': 0,
                        'total': 0,
                        'github_identity_missing': True,
                    },
                )
                ch.assert_not_awaited()

    def test_me_without_identity_validates_pagination(self) -> None:
        for query in ('?author=@me&limit=0', '?author=@me&offset=-1'):
            with self.subTest(query=query), _identities():
                response, ch = self._list(query)
                self.assertEqual(response.status_code, 400)
                ch.assert_not_awaited()

    def test_reviewer_filter_is_in_the_query_before_the_limit(self) -> None:
        with _identities(GITHUB_IDENTITY):
            response, ch = self._list('?reviewer=@me')
        self.assertEqual(response.status_code, 200)
        count_sql, data_sql = (c.args[0] for c in ch.call_args_list)
        clause = 'has(requested_reviewers, {reviewer:String})'
        self.assertIn(clause, count_sql)
        self.assertLess(data_sql.index(clause), data_sql.index('LIMIT'))
        self.assertIn("state = 'open' AND pr_id IN", data_sql)
        self.assertEqual(ch.call_args.args[1]['reviewer'], 'alice-gh')

    def test_reviewer_login_needs_no_identity(self) -> None:
        with _identities() as list_for_user:
            response, ch = self._list('?reviewer=bob')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ch.call_args.args[1]['reviewer'], 'bob')
        list_for_user.assert_not_awaited()

    def test_pending_deploy_author_me(self) -> None:
        self.mock_db.execute.return_value = []
        url = f'/organizations/{ORG}/pull-requests/pending-deploy?author=@me'
        pending = mock.AsyncMock(return_value=([], 0))
        with (
            mock.patch.object(pull_requests, '_list_pending_deploy', pending),
            _identities(GITHUB_IDENTITY),
        ):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['github_identity_missing'])
        self.assertEqual(pending.call_args.kwargs['author'], 'alice-gh')
        with (
            mock.patch.object(pull_requests, '_list_pending_deploy', pending),
            _identities(),
        ):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['github_identity_missing'])
        self.assertEqual(body['data'], [])
        self.assertEqual(body['total'], 0)
        pending.assert_awaited_once()

    def test_pending_deploy_environment_name(self) -> None:
        now = datetime.datetime.now(datetime.UTC)
        rows = [
            pull_requests.PendingDeployPullRequest(
                project_id='p1',
                pr_id=f'PR_{n}',
                pr_number=n,
                title='Ship it',
                url='https://example.test/pr',
                author='gmr',
                merged_at=now,
                additions=1,
                deletions=0,
                last_deployed_at=now,
                last_deployed_environment=slug,
            )
            for n, slug in enumerate(['production', None])
        ]
        envs = mock.AsyncMock(return_value={'production': 'Production'})
        with (
            mock.patch.object(
                pull_requests,
                '_list_pending_deploy',
                mock.AsyncMock(return_value=(rows, 2)),
            ),
            mock.patch.object(
                pull_requests, '_fetch_terminal_environments', envs
            ),
        ):
            response = self.client.get(
                f'/organizations/{ORG}/pull-requests/pending-deploy'
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(['production'], body['environments'])
        self.assertEqual(2, body['total'])
        first, second = body['data']
        self.assertEqual('production', first['last_deployed_environment'])
        self.assertEqual('Production', first['last_deployed_environment_name'])
        self.assertIsNone(second['last_deployed_environment'])
        self.assertIsNone(second['last_deployed_environment_name'])

    def _pending(self, query: str) -> tuple[typing.Any, mock.AsyncMock]:
        self.mock_db.execute.return_value = []
        pending = mock.AsyncMock(return_value=([], 250))
        envs = mock.AsyncMock(return_value={'production': 'Production'})
        with (
            mock.patch.object(pull_requests, '_list_pending_deploy', pending),
            mock.patch.object(
                pull_requests, '_fetch_terminal_environments', envs
            ),
        ):
            response = self.client.get(
                f'/organizations/{ORG}/pull-requests/pending-deploy{query}'
            )
        return response, pending

    def test_pending_deploy_pages(self) -> None:
        response, pending = self._pending('')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(pending.call_args.kwargs['limit'], 200)
        self.assertEqual(pending.call_args.kwargs['offset'], 0)
        response, pending = self._pending('?limit=200&offset=200')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['total'], 250)
        self.assertEqual(pending.call_args.kwargs['limit'], 200)
        self.assertEqual(pending.call_args.kwargs['offset'], 200)

    def test_pending_deploy_validates_pagination(self) -> None:
        for query in ('?limit=0', '?limit=501', '?offset=-1'):
            with self.subTest(query=query):
                response, pending = self._pending(query)
                self.assertEqual(response.status_code, 400)
                pending.assert_not_awaited()


class PullRequestActivityTestCase(_PullRequestsTestBase):
    """GET /organizations/{org}/pull-requests/activity"""

    def _url(self, query: str = '') -> str:
        return f'/organizations/{ORG}/pull-requests/activity{query}'

    def test_activity_maps_logins_and_sorts(self) -> None:
        # db.execute is called twice: org->project_ids, then the
        # identity-connection map. clickhouse.query returns the counts.
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {
                    'email': 'alice@example.com',
                    'display_name': 'Alice',
                    'avatar_url': None,
                    'metadata': {'login': 'Alice'},
                }
            ],
        ]
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.pull_requests.clickhouse.query',
                new=mock.AsyncMock(
                    return_value=[
                        {
                            'author': 'alice',
                            'created_count': 5,
                            'open_count': 1,
                            'closed_count': 2,
                            'merged_count': 3,
                        },
                        {
                            'author': 'ghost',
                            'created_count': 2,
                            'open_count': 0,
                            'closed_count': 1,
                            'merged_count': 1,
                        },
                        {
                            'author': 'idle',
                            'created_count': 0,
                            'open_count': 0,
                            'closed_count': 0,
                            'merged_count': 0,
                        },
                    ]
                ),
            ),
        ):
            response = self.client.get(self._url('?since=2026-04-01'))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        # 'idle' is dropped (no activity); 'alice' sorts above 'ghost'.
        self.assertEqual(body['members'], 2)
        self.assertEqual(body['since'], '2026-04-01T00:00:00Z')
        rows = body['rows']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['login'], 'alice')
        self.assertEqual(rows[0]['display_name'], 'Alice')
        self.assertEqual(rows[0]['email'], 'alice@example.com')
        self.assertEqual(rows[0]['merged'], 3)
        self.assertEqual(rows[0]['open'], 1)
        self.assertEqual(rows[0]['closed'], 2)
        # Unresolved login: raw login, no user fields.
        self.assertEqual(rows[1]['login'], 'ghost')
        self.assertIsNone(rows[1]['display_name'])
        self.assertIsNone(rows[1]['email'])

    def test_activity_skips_drafts_and_archived_projects(self) -> None:
        self.mock_db.execute.side_effect = [[{'id': PROJECT_ID}], []]
        query = mock.AsyncMock(return_value=[])
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.pull_requests.clickhouse.query',
                new=query,
            ),
        ):
            response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        cypher = self.mock_db.execute.call_args_list[0].args[0]
        self.assertIn('coalesce(p.archived, false) = false', cypher)
        self.assertIn(' AND NOT draft', query.call_args.args[0])

    def test_activity_anchors_every_column_on_created_at(self) -> None:
        self.mock_db.execute.side_effect = [[{'id': PROJECT_ID}], []]
        query = mock.AsyncMock(return_value=[])
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.pull_requests.clickhouse.query',
                new=query,
            ),
        ):
            self.client.get(self._url())
        sql = query.call_args.args[0]
        self.assertNotIn('merged_at >=', sql)
        since = 'created_at >= {since:DateTime64(3)}'
        for fragment in (
            f'countIf({since}) AS created_count',
            f"countIf(state = 'open' AND {since}) AS open_count",
            f"countIf(state != 'open' AND NOT merged AND {since})"
            ' AS closed_count',
            f'countIf(merged AND {since}) AS merged_count',
            f' AND NOT draft AND {since} GROUP BY author',
        ):
            self.assertIn(fragment, sql)

    def test_activity_empty_when_no_projects(self) -> None:
        self.mock_db.execute.side_effect = [[], []]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['members'], 0)
        self.assertEqual(body['rows'], [])

    def test_activity_400_on_bad_since(self) -> None:
        response = self.client.get(self._url('?since=not-a-date'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('since must be', response.json()['detail'])


class ParseSinceTestCase(unittest.TestCase):
    def test_naive_timestamp_gets_utc(self) -> None:
        parsed = pull_requests._parse_since('2026-04-01T10:00:00')
        self.assertEqual(
            parsed,
            datetime.datetime(2026, 4, 1, 10, 0, tzinfo=datetime.UTC),
        )

    def test_aware_timestamp_normalized_to_utc(self) -> None:
        parsed = pull_requests._parse_since('2026-04-01T10:00:00+02:00')
        self.assertEqual(parsed.tzinfo, datetime.UTC)
        self.assertEqual(
            parsed,
            datetime.datetime(2026, 4, 1, 8, 0, tzinfo=datetime.UTC),
        )
