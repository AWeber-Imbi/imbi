"""Tests for release CRUD and deployment-edge endpoints."""

import datetime
import json
import typing
import unittest
from unittest import mock

import fastapi.testclient
from imbi_common import graph

from imbi_api import app, models

PROJECT_ID = 'proj123nanoid'
RELEASE_ID = 'rel456nanoid'
ORG = 'engineering'


def _release_row(**overrides: typing.Any) -> dict[str, typing.Any]:
    data: dict[str, typing.Any] = {
        'id': RELEASE_ID,
        'version': '1.2.3',
        'title': 'Initial release',
        'description': None,
        'links': json.dumps([]),
        'created_by': 'alice@example.com',
        'created_at': '2026-04-20T12:00:00+00:00',
        'updated_at': '2026-04-20T12:00:00+00:00',
    }
    data.update(overrides)
    return data


class _ReleasesTestBase(unittest.TestCase):
    """Shared setup mounting release endpoints with admin auth."""

    permissions_granted: typing.ClassVar[set[str]] = {
        'project:read',
        'project:write',
    }

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
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )
        self.client = fastapi.testclient.TestClient(self.test_app)
        self.addCleanup(self.client.close)

    def _url(self, tail: str = '') -> str:
        base = f'/organizations/{ORG}/projects/{PROJECT_ID}/releases'
        return f'{base}{tail}'


class CreateReleaseTestCase(_ReleasesTestBase):
    """POST /releases/"""

    def test_create_success(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],  # project_exists
            [],  # version uniqueness check
            [{'release': _release_row()}],  # create
        ]

        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.releases.nanoid.generate',
                return_value=RELEASE_ID,
            ),
        ):
            response = self.client.post(
                self._url('/'),
                json={
                    'version': '1.2.3',
                    'title': 'Initial release',
                    'description': 'First cut',
                    'links': [
                        {
                            'type': 'github_release',
                            'url': 'https://example.com/r/1.2.3',
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['version'], '1.2.3')
        self.assertEqual(body['project_id'], PROJECT_ID)
        self.assertEqual(body['id'], RELEASE_ID)
        self.assertEqual(body['created_by'], 'alice@example.com')

    def test_create_with_explicit_created_by(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [],
            [{'release': _release_row(created_by='deploy-bot')}],
        ]
        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.releases.nanoid.generate',
                return_value=RELEASE_ID,
            ),
        ):
            response = self.client.post(
                self._url('/'),
                json={
                    'version': '1.2.3',
                    'title': 'Initial release',
                    'created_by': 'deploy-bot',
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['created_by'], 'deploy-bot')

    def test_create_invalid_semver(self) -> None:
        response = self.client.post(
            self._url('/'),
            json={'version': 'not.a.version', 'title': 'x'},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn('semver', response.json()['detail'].lower())

    def test_create_project_not_found(self) -> None:
        self.mock_db.execute.side_effect = [[]]  # project_exists -> no rows
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url('/'),
                json={'version': '1.0.0', 'title': 'x'},
            )
        self.assertEqual(response.status_code, 404)

    def test_create_duplicate_version_same_project(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [{'id': RELEASE_ID}],  # duplicate
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url('/'),
                json={'version': '1.2.3', 'title': 'x'},
            )
        self.assertEqual(response.status_code, 409)

    def test_create_cross_project_duplicate_ok(self) -> None:
        """Uniqueness is per-project: another project may reuse 1.2.3."""
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [],  # no existing release under THIS project
            [{'release': _release_row()}],
        ]
        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.releases.nanoid.generate',
                return_value=RELEASE_ID,
            ),
        ):
            response = self.client.post(
                self._url('/'),
                json={'version': '1.2.3', 'title': 'x'},
            )
        self.assertEqual(response.status_code, 201)

    def test_create_commitish_format_rejects_semver(self) -> None:
        """With version_format=commitish the semver regex is rejected."""
        with mock.patch(
            'imbi_api.endpoints.releases.common_settings.Releases'
        ) as mock_releases:
            mock_releases.return_value.version_format = 'commitish'
            response = self.client.post(
                self._url('/'),
                json={'version': '1.2.3', 'title': 'x'},
            )
            self.assertEqual(response.status_code, 422)
            self.assertIn('commitish', response.json()['detail'].lower())

    def test_create_commitish_valid_sha(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [],
            [{'release': _release_row(version='abc1234')}],
        ]
        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.releases.nanoid.generate',
                return_value=RELEASE_ID,
            ),
            mock.patch(
                'imbi_api.endpoints.releases.common_settings.Releases'
            ) as mock_releases,
        ):
            mock_releases.return_value.version_format = 'commitish'
            response = self.client.post(
                self._url('/'),
                json={'version': 'abc1234', 'title': 'x'},
            )
        self.assertEqual(response.status_code, 201)


class ListGetReleaseTestCase(_ReleasesTestBase):
    """GET list / get single / 404."""

    def test_list_releases(self) -> None:
        self.mock_db.execute.return_value = [
            {'release': _release_row(version='1.0.0', id='a')},
            {'release': _release_row(version='1.1.0', id='b')},
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['version'], '1.0.0')
        self.assertEqual(data[0]['project_id'], PROJECT_ID)

    def test_get_release_success(self) -> None:
        self.mock_db.execute.return_value = [{'release': _release_row()}]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/1.2.3'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['version'], '1.2.3')

    def test_get_release_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/9.9.9'))
        self.assertEqual(response.status_code, 404)


class PatchReleaseTestCase(_ReleasesTestBase):
    """PATCH /releases/{version}"""

    def test_patch_title(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [{'release': _release_row(title='Updated')}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                self._url('/1.2.3'),
                json=[
                    {'op': 'replace', 'path': '/title', 'value': 'Updated'},
                ],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['title'], 'Updated')

    def test_patch_description_and_links(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [
                {
                    'release': _release_row(
                        description='New desc',
                        links=json.dumps(
                            [
                                {
                                    'type': 'github_release',
                                    'url': 'https://example.com/',
                                    'label': None,
                                }
                            ]
                        ),
                    )
                }
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                self._url('/1.2.3'),
                json=[
                    {
                        'op': 'replace',
                        'path': '/description',
                        'value': 'New desc',
                    },
                    {
                        'op': 'replace',
                        'path': '/links',
                        'value': [
                            {
                                'type': 'github_release',
                                'url': 'https://example.com/',
                            }
                        ],
                    },
                ],
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['description'], 'New desc')
        self.assertEqual(len(body['links']), 1)

    def test_patch_title_to_empty_string(self) -> None:
        """Explicit empty-string patches of ``title`` must persist."""
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [{'release': _release_row(title='')}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                self._url('/1.2.3'),
                json=[
                    {'op': 'replace', 'path': '/title', 'value': ''},
                ],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['title'], '')
        # Confirm the SET clause received the empty string, not the old
        # title — i.e. the fix for truthiness-vs-presence is effective.
        update_call = self.mock_db.execute.await_args_list[1]
        self.assertEqual(update_call.args[1]['title'], '')

    def test_patch_readonly_version(self) -> None:
        self.mock_db.execute.side_effect = [[{'release': _release_row()}]]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                self._url('/1.2.3'),
                json=[
                    {'op': 'replace', 'path': '/version', 'value': '2.0.0'},
                ],
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('read-only', response.json()['detail'])

    def test_patch_unknown_path(self) -> None:
        self.mock_db.execute.side_effect = [[{'release': _release_row()}]]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                self._url('/1.2.3'),
                json=[
                    {'op': 'replace', 'path': '/bogus', 'value': 'x'},
                ],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                self._url('/1.2.3'),
                json=[
                    {'op': 'replace', 'path': '/title', 'value': 'x'},
                ],
            )
        self.assertEqual(response.status_code, 404)


class DeploymentEdgeTestCase(_ReleasesTestBase):
    """POST / GET deployment edges."""

    def _env(self, slug: str = 'production') -> dict[str, typing.Any]:
        return {'slug': slug, 'name': slug.title()}

    def test_record_deployment_creates_edge(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],  # _fetch_release
            # _fetch_deployment_edge: env exists, no edge
            [{'env': self._env(), 'deployments': None}],
            [{'deployments': None}],  # create_query
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url('/1.2.3/environments/production'),
                json={'status': 'pending'},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['environment']['slug'], 'production')
        self.assertEqual(len(body['deployments']), 1)
        self.assertEqual(body['deployments'][0]['status'], 'pending')
        self.assertEqual(body['current_status'], 'pending')

    def test_record_deployment_appends(self) -> None:
        existing = [
            {
                'timestamp': '2026-04-20T10:00:00+00:00',
                'status': 'pending',
                'note': None,
            }
        ]
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [
                {
                    'env': self._env(),
                    'deployments': json.dumps(existing),
                }
            ],
            [{'deployments': None}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url('/1.2.3/environments/production'),
                json={'status': 'success', 'note': 'rolled out'},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body['deployments']), 2)
        self.assertEqual(body['current_status'], 'success')

    def test_record_deployment_env_missing(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [],  # env not found
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url('/1.2.3/environments/ghost'),
                json={'status': 'pending'},
            )
        self.assertEqual(response.status_code, 422)

    def test_record_deployment_release_missing(self) -> None:
        self.mock_db.execute.side_effect = [[]]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url('/9.9.9/environments/production'),
                json={'status': 'pending'},
            )
        self.assertEqual(response.status_code, 404)

    def test_list_deployment_edges(self) -> None:
        deployments = json.dumps(
            [
                {
                    'timestamp': '2026-04-20T10:00:00+00:00',
                    'status': 'success',
                    'note': None,
                }
            ]
        )
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [
                {
                    'env': self._env('production'),
                    'deployments': deployments,
                },
                {
                    'env': self._env('staging'),
                    'deployments': deployments,
                },
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                self._url('/1.2.3/environments'),
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['current_status'], 'success')

    def test_get_single_edge_404_when_no_edge(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            # env exists but no edge
            [{'env': self._env(), 'deployments': None}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                self._url('/1.2.3/environments/production'),
            )
        self.assertEqual(response.status_code, 404)

    def test_get_single_edge_success(self) -> None:
        deployments = json.dumps(
            [
                {
                    'timestamp': '2026-04-20T10:00:00+00:00',
                    'status': 'success',
                    'note': None,
                }
            ]
        )
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [{'env': self._env(), 'deployments': deployments}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                self._url('/1.2.3/environments/production'),
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['current_status'], 'success')


class CurrentReleasesTestCase(_ReleasesTestBase):
    """GET /releases/current — latest deployment event per env."""

    @staticmethod
    def _env(
        slug: str,
        sort_order: int = 0,
    ) -> dict[str, typing.Any]:
        return {
            'slug': slug,
            'name': slug.title(),
            'sort_order': sort_order,
        }

    @staticmethod
    def _events(*specs: tuple[str, str]) -> str:
        return json.dumps(
            [
                {'timestamp': ts, 'status': status, 'note': None}
                for ts, status in specs
            ]
        )

    def test_404_when_project_missing(self) -> None:
        self.mock_db.execute.side_effect = [[]]
        response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 404)

    def test_env_with_no_deployments(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],  # _project_exists
            [
                {
                    'env': self._env('testing', sort_order=10),
                    'release': None,
                    'deployments': None,
                }
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['environment']['slug'], 'testing')
        self.assertIsNone(data[0]['release'])
        self.assertIsNone(data[0]['current_status'])
        self.assertIsNone(data[0]['last_event_at'])

    def test_latest_event_wins_across_releases(self) -> None:
        # production has been deployed v1.0.0 then v1.1.0; v1.1.0
        # event timestamp is later, so it must win.
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {
                    'env': self._env('production', sort_order=30),
                    'release': _release_row(version='1.0.0', id='r1'),
                    'deployments': self._events(
                        ('2026-04-20T10:00:00+00:00', 'success'),
                    ),
                },
                {
                    'env': self._env('production', sort_order=30),
                    'release': _release_row(version='1.1.0', id='r2'),
                    'deployments': self._events(
                        ('2026-04-22T10:00:00+00:00', 'success'),
                    ),
                },
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['release']['version'], '1.1.0')
        self.assertEqual(data[0]['current_status'], 'success')
        self.assertEqual(data[0]['last_event_at'], '2026-04-22T10:00:00Z')

    def test_rollback_surfaces_older_release(self) -> None:
        # v1.1.0 was deployed, then rolled back by re-deploying v1.0.0;
        # the latest event lives on the v1.0.0 edge so v1.0.0 wins.
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {
                    'env': self._env('production'),
                    'release': _release_row(version='1.0.0', id='r1'),
                    'deployments': self._events(
                        ('2026-04-20T10:00:00+00:00', 'success'),
                        ('2026-04-23T10:00:00+00:00', 'success'),
                    ),
                },
                {
                    'env': self._env('production'),
                    'release': _release_row(version='1.1.0', id='r2'),
                    'deployments': self._events(
                        ('2026-04-22T10:00:00+00:00', 'success'),
                        (
                            '2026-04-22T18:00:00+00:00',
                            'rolled_back',
                        ),
                    ),
                },
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data[0]['release']['version'], '1.0.0')
        self.assertEqual(data[0]['current_status'], 'success')

    def test_sorts_by_environment_sort_order(self) -> None:
        events = self._events(('2026-04-20T10:00:00+00:00', 'success'))
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {
                    'env': self._env('production', sort_order=30),
                    'release': _release_row(version='1.0.0', id='r1'),
                    'deployments': events,
                },
                {
                    'env': self._env('testing', sort_order=10),
                    'release': _release_row(version='1.0.0', id='r1'),
                    'deployments': events,
                },
                {
                    'env': self._env('staging', sort_order=20),
                    'release': _release_row(version='1.0.0', id='r1'),
                    'deployments': events,
                },
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 200)
        slugs = [row['environment']['slug'] for row in response.json()]
        self.assertEqual(slugs, ['testing', 'staging', 'production'])

    def test_undeployed_env_appears_alongside_deployed(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {
                    'env': self._env('production', sort_order=30),
                    'release': _release_row(version='1.0.0', id='r1'),
                    'deployments': self._events(
                        ('2026-04-20T10:00:00+00:00', 'success'),
                    ),
                },
                {
                    'env': self._env('testing', sort_order=10),
                    'release': None,
                    'deployments': None,
                },
            ],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        by_slug = {row['environment']['slug']: row for row in data}
        self.assertIsNone(by_slug['testing']['release'])
        self.assertEqual(by_slug['production']['release']['version'], '1.0.0')
