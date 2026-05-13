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
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
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

    def test_create_two_releases_commitish_then_semver(self) -> None:
        """Create both a commitish and a semver release for one project.

        ``version_format`` is fixed at process start, so this test does
        not flip it mid-run.
        """
        self.mock_db.execute.side_effect = [
            # First create: 214e932
            [{'id': PROJECT_ID}],
            [],
            [{'release': _release_row(version='214e932', id='rel-commitish')}],
            # Second create: 2.2.0
            [{'id': PROJECT_ID}],
            [],
            [{'release': _release_row(version='2.2.0', id='rel-semver')}],
        ]
        with (
            mock.patch(
                'imbi_common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi_api.endpoints.releases.nanoid.generate',
                side_effect=['rel-commitish', 'rel-semver'],
            ),
        ):
            first = self.client.post(
                self._url('/'),
                json={'version': '214e932', 'title': 'commitish build'},
            )
            second = self.client.post(
                self._url('/'),
                json={'version': '2.2.0', 'title': 'semver release'},
            )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()['version'], '214e932')
        self.assertEqual(first.json()['id'], 'rel-commitish')

        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()['version'], '2.2.0')
        self.assertEqual(second.json()['id'], 'rel-semver')


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


class AppendDeploymentEventDedupeTestCase(_ReleasesTestBase):
    """Direct coverage for ``append_deployment_event`` dedupe semantics."""

    def _call(
        self,
        existing: list[dict[str, typing.Any]],
        *,
        external_run_id: str | None,
        status: str = 'success',
        note: str | None = None,
    ) -> typing.Any:
        import asyncio

        from imbi_api.endpoints.releases import append_deployment_event

        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [
                {
                    'env': {'slug': 'production', 'name': 'Production'},
                    'deployments': json.dumps(existing) if existing else None,
                }
            ],
            [{'deployments': None}],  # only consumed by append / set path
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            return asyncio.run(
                append_deployment_event(
                    self.mock_db,
                    org_slug=ORG,
                    project_id=PROJECT_ID,
                    version='1.2.3',
                    env_slug='production',
                    status=typing.cast(typing.Any, status),
                    note=note,
                    external_run_id=external_run_id,
                    external_run_url='https://gh/runs/42',
                )
            )

    def test_same_run_id_same_status_is_no_op(self) -> None:
        existing = [
            {
                'timestamp': '2026-05-13T14:00:00+00:00',
                'status': 'success',
                'note': None,
                'external_run_id': '42',
                'external_run_url': 'https://gh/runs/42',
            }
        ]
        edge, outcome = self._call(
            existing, external_run_id='42', status='success'
        )
        self.assertEqual(outcome, 'noop')
        self.assertEqual(len(edge.deployments), 1)
        # Only the two read queries fired; the SET branch must not run.
        self.assertEqual(self.mock_db.execute.await_count, 2)

    def test_same_run_id_status_change_updates_in_place(self) -> None:
        existing = [
            {
                'timestamp': '2026-05-13T14:00:00+00:00',
                'status': 'in_progress',
                'note': None,
                'external_run_id': '42',
                'external_run_url': 'https://gh/runs/42',
            }
        ]
        edge, outcome = self._call(
            existing, external_run_id='42', status='success'
        )
        self.assertEqual(outcome, 'updated')
        self.assertEqual(len(edge.deployments), 1)
        self.assertEqual(edge.deployments[0].status, 'success')
        self.assertEqual(edge.current_status, 'success')

    def test_different_run_id_still_appends(self) -> None:
        existing = [
            {
                'timestamp': '2026-05-13T14:00:00+00:00',
                'status': 'success',
                'note': None,
                'external_run_id': '41',
                'external_run_url': None,
            }
        ]
        edge, outcome = self._call(
            existing, external_run_id='42', status='success'
        )
        self.assertEqual(outcome, 'appended')
        self.assertEqual(len(edge.deployments), 2)
        self.assertEqual(edge.deployments[-1].external_run_id, '42')

    def test_no_external_run_id_keeps_append_only_semantics(self) -> None:
        existing = [
            {
                'timestamp': '2026-05-13T14:00:00+00:00',
                'status': 'success',
                'note': None,
                'external_run_id': None,
                'external_run_url': None,
            }
        ]
        # Both have no external_run_id, so the pre-dedupe deploy / promote
        # flow remains append-only.
        edge, outcome = self._call(
            existing, external_run_id=None, status='success'
        )
        self.assertEqual(outcome, 'appended')
        self.assertEqual(len(edge.deployments), 2)


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


class CurrentReleasesHydrationTestCase(_ReleasesTestBase):
    """GET /releases/current — deployment-plugin hydration pass.

    Exercises the optional ``_hydrate_release_train`` step that asks the
    project's bound deployment plugin for live workflow run status (for
    in-flight events with an ``external_run_id``) and aggregate CI
    check-runs status (for each env's currently-deployed version).
    """

    @staticmethod
    def _env(slug: str, sort_order: int = 0) -> dict[str, typing.Any]:
        return {
            'slug': slug,
            'name': slug.title(),
            'sort_order': sort_order,
        }

    @staticmethod
    def _events_with_run(
        ts: str,
        status: str,
        run_id: str | None = None,
        run_url: str | None = None,
    ) -> str:
        entry: dict[str, typing.Any] = {
            'timestamp': ts,
            'status': status,
            'note': None,
        }
        if run_id is not None:
            entry['external_run_id'] = run_id
        if run_url is not None:
            entry['external_run_url'] = run_url
        return json.dumps([entry])

    def _patch_plugin_resolution(
        self,
        *,
        get_deployment_status: mock.AsyncMock | None = None,
        get_check_status: mock.AsyncMock | None = None,
    ) -> tuple[mock.AsyncMock, mock.AsyncMock]:
        """Return (run_mock, ci_mock) bound to a stub plugin handler."""
        run_mock = get_deployment_status or mock.AsyncMock(
            return_value=mock.MagicMock(
                status='in_progress',
                run_id='42',
                run_url=None,
            )
        )
        ci_mock = get_check_status or mock.AsyncMock(return_value='unknown')

        class _Handler:
            get_deployment_status = run_mock
            get_check_status = ci_mock

        resolved = mock.MagicMock()
        resolved.entry.handler_cls = lambda: _Handler()
        resolved.options = {}

        async def _resolve_and_context(
            db: typing.Any, org_slug: str, project_id: str, auth: typing.Any
        ) -> tuple[typing.Any, typing.Any, dict[str, str]]:
            del db, org_slug, project_id, auth
            return resolved, mock.MagicMock(), {'access_token': 'x'}

        self._patcher = mock.patch(
            'imbi_api.endpoints.project_deployments._resolve_and_context',
            new=_resolve_and_context,
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        return run_mock, ci_mock

    def test_hydration_skipped_when_no_plugin_bound(self) -> None:
        # Three db.execute calls: project_exists, deployments query,
        # then the plugin-resolution query (returns no rows → 404 →
        # hydration skipped).  No fields populated by hydration.
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {
                    'env': self._env('production', sort_order=30),
                    'release': _release_row(version='1.0.0', id='r1'),
                    'deployments': self._events_with_run(
                        '2026-04-20T10:00:00+00:00', 'success'
                    ),
                },
            ],
            [],  # resolve_plugin → no plugin → HTTPException(404)
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 200)
        body = response.json()[0]
        self.assertIsNone(body['ci_status'])
        self.assertIsNone(body['external_run_url'])

    def test_in_flight_run_promoted_to_terminal(self) -> None:
        run_mock = mock.AsyncMock(
            return_value=mock.MagicMock(
                status='success',
                run_id='42',
                run_url='https://gh/runs/42',
            )
        )
        ci_mock = mock.AsyncMock(return_value='pass')
        self._patch_plugin_resolution(
            get_deployment_status=run_mock,
            get_check_status=ci_mock,
        )
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {
                    'env': self._env('production', sort_order=30),
                    'release': _release_row(version='1.0.0', id='r1'),
                    'deployments': self._events_with_run(
                        '2026-04-20T10:00:00+00:00',
                        'in_progress',
                        run_id='42',
                        run_url='https://gh/runs/42',
                    ),
                },
            ],
            # The persistence path does additional db.execute calls
            # (re-fetch release, edge MATCH, SET).  Provide enough
            # truthy results so append_deployment_event can land.
            [{'release': _release_row(version='1.0.0', id='r1')}],
            [{'env': self._env('production'), 'deployments': None}],
            [{'deployments': '[]'}],
        ]
        with mock.patch(
            'imbi_common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 200)
        body = response.json()[0]
        self.assertEqual(body['current_status'], 'success')
        self.assertEqual(body['ci_status'], 'pass')
        self.assertEqual(body['external_run_url'], 'https://gh/runs/42')
        run_mock.assert_awaited_once()
        ci_mock.assert_awaited_once()

    def test_unknown_ci_status_returns_null(self) -> None:
        self._patch_plugin_resolution(
            get_check_status=mock.AsyncMock(return_value='unknown'),
        )
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {
                    'env': self._env('production', sort_order=30),
                    'release': _release_row(version='1.0.0', id='r1'),
                    'deployments': self._events_with_run(
                        '2026-04-20T10:00:00+00:00', 'success'
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
        body = response.json()[0]
        self.assertIsNone(body['ci_status'])

    def test_plugin_call_failure_does_not_break_response(self) -> None:
        run_mock = mock.AsyncMock(
            side_effect=RuntimeError('plugin boom'),
        )
        ci_mock = mock.AsyncMock(side_effect=RuntimeError('ci boom'))
        self._patch_plugin_resolution(
            get_deployment_status=run_mock,
            get_check_status=ci_mock,
        )
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {
                    'env': self._env('production', sort_order=30),
                    'release': _release_row(version='1.0.0', id='r1'),
                    'deployments': self._events_with_run(
                        '2026-04-20T10:00:00+00:00',
                        'in_progress',
                        run_id='42',
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
        body = response.json()[0]
        # Status untouched (still in_progress); ci_status null.
        self.assertEqual(body['current_status'], 'in_progress')
        self.assertIsNone(body['ci_status'])
