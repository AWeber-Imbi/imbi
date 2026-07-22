"""Tests for release CRUD and deployment-edge endpoints."""

import datetime
import json
import typing
from unittest import mock

import fastapi.testclient

from imbi.api import models
from imbi.common import graph
from tests.api import support

PROJECT_ID = 'proj123nanoid'
RELEASE_ID = 'rel456nanoid'
ORG = 'engineering'


DEFAULT_COMMITTISH = 'abc1234'


def _release_row(**overrides: typing.Any) -> dict[str, typing.Any]:
    data: dict[str, typing.Any] = {
        'id': RELEASE_ID,
        'tag': '1.2.3',
        'committish': DEFAULT_COMMITTISH,
        'title': 'Initial release',
        'description': None,
        'links': json.dumps([]),
        'created_by': 'alice@example.com',
        'created_at': '2026-04-20T12:00:00+00:00',
        'updated_at': '2026-04-20T12:00:00+00:00',
    }
    data.update(overrides)
    return data


class _ReleasesTestBase(support.SharedAppTestCase):
    """Shared setup mounting release endpoints with admin auth."""

    permissions_granted: typing.ClassVar[set[str]] = {
        'project:read',
        'project:write',
    }

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

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            _current_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = lambda: (
            self.mock_db
        )
        # The create path enriches a tagged, note-less release from the
        # remote release body; that resolves the deployment capability and
        # makes its own DB/HTTP calls. Neutralize it here so create-logic
        # tests exercise only the create query sequence; the enrichment
        # itself is covered by a dedicated test.
        self._notes_patch = mock.patch(
            'imbi.api.endpoints.project_deployments'
            '.fetch_release_notes_for_tag',
            new=mock.AsyncMock(return_value=None),
        )
        self._notes_patch.start()
        self.addCleanup(self._notes_patch.stop)
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
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.releases.nanoid.generate',
                return_value=RELEASE_ID,
            ),
        ):
            response = self.client.post(
                self._url('/'),
                json={
                    'tag': '1.2.3',
                    'committish': DEFAULT_COMMITTISH,
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
        self.assertEqual(body['tag'], '1.2.3')
        self.assertEqual(body['committish'], DEFAULT_COMMITTISH)
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
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.releases.nanoid.generate',
                return_value=RELEASE_ID,
            ),
        ):
            response = self.client.post(
                self._url('/'),
                json={
                    'tag': '1.2.3',
                    'committish': DEFAULT_COMMITTISH,
                    'title': 'Initial release',
                    'created_by': 'deploy-bot',
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['created_by'], 'deploy-bot')

    def test_create_enriches_notes_from_remote_release(self) -> None:
        # A release created from a deployment webhook (tag present, no
        # description) is enriched with the remote release body so the
        # UI's release history shows the "What's Changed" markdown.
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],  # project_exists
            [],  # version uniqueness check
            [{'release': _release_row()}],  # create
        ]
        notes = "## What's Changed\n- Fixed the breadcrumb"
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.releases.nanoid.generate',
                return_value=RELEASE_ID,
            ),
            mock.patch(
                'imbi.api.endpoints.project_deployments'
                '.fetch_release_notes_for_tag',
                new=mock.AsyncMock(return_value=notes),
            ) as enrich,
        ):
            response = self.client.post(
                self._url('/'),
                json={
                    'tag': '3.23.4',
                    'committish': DEFAULT_COMMITTISH,
                    'title': 'Deploy 3.23.4',
                },
            )
        self.assertEqual(response.status_code, 201, response.text)
        enrich.assert_awaited_once()
        self.assertEqual(enrich.await_args.kwargs['tag'], '3.23.4')
        # The fetched body is what gets persisted as the node description.
        create_params = self.mock_db.execute.call_args_list[2].args[1]
        self.assertEqual(create_params['description'], notes)

    def test_create_does_not_enrich_when_description_supplied(self) -> None:
        # An explicit description is authoritative; no remote lookup runs.
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [],
            [{'release': _release_row()}],
        ]
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.releases.nanoid.generate',
                return_value=RELEASE_ID,
            ),
            mock.patch(
                'imbi.api.endpoints.project_deployments'
                '.fetch_release_notes_for_tag',
                new=mock.AsyncMock(return_value='ignored'),
            ) as enrich,
        ):
            response = self.client.post(
                self._url('/'),
                json={
                    'tag': '3.23.4',
                    'committish': DEFAULT_COMMITTISH,
                    'title': 'Deploy 3.23.4',
                    'description': 'Author-supplied notes',
                },
            )
        self.assertEqual(response.status_code, 201, response.text)
        enrich.assert_not_awaited()
        create_params = self.mock_db.execute.call_args_list[2].args[1]
        self.assertEqual(create_params['description'], 'Author-supplied notes')

    def test_create_project_not_found(self) -> None:
        self.mock_db.execute.side_effect = [[]]  # project_exists -> no rows
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url('/'),
                json={
                    'tag': '1.0.0',
                    'committish': DEFAULT_COMMITTISH,
                    'title': 'x',
                },
            )
        self.assertEqual(response.status_code, 404)

    def test_create_duplicate_version_same_project(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [{'id': RELEASE_ID}],  # duplicate
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url('/'),
                json={
                    'tag': '1.2.3',
                    'committish': DEFAULT_COMMITTISH,
                    'title': 'x',
                },
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
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.releases.nanoid.generate',
                return_value=RELEASE_ID,
            ),
        ):
            response = self.client.post(
                self._url('/'),
                json={
                    'tag': '1.2.3',
                    'committish': DEFAULT_COMMITTISH,
                    'title': 'x',
                },
            )
        self.assertEqual(response.status_code, 201)

    def test_create_two_releases_commitish_then_semver(self) -> None:
        """Create commitish-only + tagged releases for one project."""
        self.mock_db.execute.side_effect = [
            # First create: commitish-only
            [{'id': PROJECT_ID}],
            [],
            [
                {
                    'release': _release_row(
                        tag=None,
                        committish='214e932',
                        id='rel-commitish',
                    )
                }
            ],
            # Second create: tagged
            [{'id': PROJECT_ID}],
            [],
            [
                {
                    'release': _release_row(
                        tag='2.2.0',
                        committish=DEFAULT_COMMITTISH,
                        id='rel-semver',
                    )
                }
            ],
        ]
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.releases.nanoid.generate',
                side_effect=['rel-commitish', 'rel-semver'],
            ),
        ):
            first = self.client.post(
                self._url('/'),
                json={'committish': '214e932', 'title': 'commitish build'},
            )
            second = self.client.post(
                self._url('/'),
                json={
                    'tag': '2.2.0',
                    'committish': DEFAULT_COMMITTISH,
                    'title': 'semver release',
                },
            )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()['tag'], None)
        self.assertEqual(first.json()['committish'], '214e932')
        self.assertEqual(first.json()['id'], 'rel-commitish')

        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()['tag'], '2.2.0')
        self.assertEqual(second.json()['committish'], DEFAULT_COMMITTISH)
        self.assertEqual(second.json()['id'], 'rel-semver')


class ListGetReleaseTestCase(_ReleasesTestBase):
    """GET list / get single / 404."""

    def test_list_releases(self) -> None:
        self.mock_db.execute.return_value = [
            {'release': _release_row(tag='1.0.0', id='a')},
            {'release': _release_row(tag='1.1.0', id='b')},
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['tag'], '1.0.0')
        self.assertEqual(data[0]['project_id'], PROJECT_ID)
        passed_params = self.mock_db.execute.await_args_list[0].args[1]
        self.assertIsNone(passed_params['committish'])
        self.assertIsNone(passed_params['tag'])

    def test_list_releases_filter_by_committish(self) -> None:
        self.mock_db.execute.return_value = [
            {'release': _release_row(committish=DEFAULT_COMMITTISH)},
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                self._url('/'),
                params={'committish': DEFAULT_COMMITTISH},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        passed_params = self.mock_db.execute.await_args_list[0].args[1]
        self.assertEqual(passed_params['committish'], DEFAULT_COMMITTISH)
        self.assertIsNone(passed_params['tag'])

    def test_list_releases_filter_by_tag(self) -> None:
        self.mock_db.execute.return_value = [
            {'release': _release_row(tag='1.2.3')},
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                self._url('/'),
                params={'tag': '1.2.3'},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        passed_params = self.mock_db.execute.await_args_list[0].args[1]
        self.assertEqual(passed_params['tag'], '1.2.3')
        self.assertIsNone(passed_params['committish'])

    def test_list_releases_filter_by_both(self) -> None:
        self.mock_db.execute.return_value = [
            {
                'release': _release_row(
                    committish=DEFAULT_COMMITTISH, tag='1.2.3'
                )
            },
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                self._url('/'),
                params={'committish': DEFAULT_COMMITTISH, 'tag': '1.2.3'},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        passed_params = self.mock_db.execute.await_args_list[0].args[1]
        self.assertEqual(passed_params['committish'], DEFAULT_COMMITTISH)
        self.assertEqual(passed_params['tag'], '1.2.3')

    def test_list_releases_filter_no_matches(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.get(
            self._url('/'),
            params={'committish': 'deadbee'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_get_release_success(self) -> None:
        self.mock_db.execute.return_value = [{'release': _release_row()}]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url(f'/{RELEASE_ID}'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['tag'], '1.2.3')

    def test_get_release_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/missing-id'))
        self.assertEqual(response.status_code, 404)


class PatchReleaseTestCase(_ReleasesTestBase):
    """PATCH /releases/{release_id}"""

    def test_patch_title(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [],  # _conflict_query — no collision
            [{'release': _release_row(title='Updated')}],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                self._url(f'/{RELEASE_ID}'),
                json=[
                    {'op': 'replace', 'path': '/title', 'value': 'Updated'},
                ],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['title'], 'Updated')

    def test_patch_description_and_links(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [],  # _conflict_query — no collision
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
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                self._url(f'/{RELEASE_ID}'),
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
            [],  # _conflict_query — no collision
            [{'release': _release_row(title='')}],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                self._url(f'/{RELEASE_ID}'),
                json=[
                    {'op': 'replace', 'path': '/title', 'value': ''},
                ],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['title'], '')
        # Confirm the SET clause received the empty string, not the old
        # title — i.e. the fix for truthiness-vs-presence is effective.
        # Index 2 = [fetch_release, conflict_query, update_query].
        update_call = self.mock_db.execute.await_args_list[2]
        self.assertEqual(update_call.args[1]['title'], '')

    def test_patch_readonly_committish(self) -> None:
        self.mock_db.execute.side_effect = [[{'release': _release_row()}]]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                self._url(f'/{RELEASE_ID}'),
                json=[
                    {
                        'op': 'replace',
                        'path': '/committish',
                        'value': 'deadbee',
                    },
                ],
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('read-only', response.json()['detail'])

    def test_patch_unknown_path(self) -> None:
        self.mock_db.execute.side_effect = [[{'release': _release_row()}]]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                self._url(f'/{RELEASE_ID}'),
                json=[
                    {'op': 'replace', 'path': '/bogus', 'value': 'x'},
                ],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                self._url(f'/{RELEASE_ID}'),
                json=[
                    {'op': 'replace', 'path': '/title', 'value': 'x'},
                ],
            )
        self.assertEqual(response.status_code, 404)

    def test_patch_tag_collision_returns_409(self) -> None:
        """Tagging a release with another release's ``(committish, tag)``
        pair must 409 rather than silently creating an ambiguous pair."""
        self.mock_db.execute.side_effect = [
            [{'release': _release_row(tag=None)}],
            # _conflict_query: another release on this SHA already has
            # the target tag.
            [{'id': 'other-release-id'}],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.patch(
                self._url(f'/{RELEASE_ID}'),
                json=[
                    {'op': 'replace', 'path': '/tag', 'value': 'v1.2.3'},
                ],
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])


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
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url(f'/{RELEASE_ID}/environments/production'),
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
            [{'current_release': RELEASE_ID}],  # current_release write
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url(f'/{RELEASE_ID}/environments/production'),
                json={'status': 'success', 'note': 'rolled out'},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body['deployments']), 2)
        self.assertEqual(body['current_status'], 'success')

    def test_record_deployment_enqueues_rescore(self) -> None:
        # Recording an event must trigger a score recompute, since a
        # DeploymentStatusPolicy can score the project on its status.
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [{'env': self._env(), 'deployments': None}],
            [{'deployments': None}],
        ]
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.releases.score_queue.enqueue_recompute',
                new=mock.AsyncMock(return_value=True),
            ) as enqueue,
        ):
            response = self.client.post(
                self._url(f'/{RELEASE_ID}/environments/production'),
                json={'status': 'failed'},
            )
        self.assertEqual(response.status_code, 200)
        enqueue.assert_awaited_once()
        self.assertEqual(
            enqueue.await_args.args[1:],
            (PROJECT_ID, 'deployment_status_change'),
        )

    def test_record_deployment_env_missing(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [],  # env not found
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url(f'/{RELEASE_ID}/environments/ghost'),
                json={'status': 'pending'},
            )
        self.assertEqual(response.status_code, 422)

    def test_record_deployment_release_missing(self) -> None:
        self.mock_db.execute.side_effect = [[]]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url('/missing-id/environments/production'),
                json={'status': 'pending'},
            )
        self.assertEqual(response.status_code, 404)

    def test_record_deployment_closes_opslog_on_terminal_status(
        self,
    ) -> None:
        # When external_run_id + a terminal status arrive together,
        # complete_opslog_entry should be called to close the ops-log row.
        existing = [
            {
                'timestamp': '2026-04-20T10:00:00+00:00',
                'status': 'in_progress',
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
            [{'current_release': RELEASE_ID}],  # current_release write
        ]
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.releases.complete_opslog_entry',
                new_callable=mock.AsyncMock,
                return_value=True,
            ) as mock_close,
        ):
            response = self.client.post(
                self._url(f'/{RELEASE_ID}/environments/production'),
                json={'status': 'success', 'external_run_id': 'run-42'},
            )
        self.assertEqual(response.status_code, 200)
        mock_close.assert_awaited_once()
        args = mock_close.call_args
        self.assertEqual(args.args[0], 'run-42')

    def test_record_deployment_skips_opslog_for_non_terminal_status(
        self,
    ) -> None:
        # complete_opslog_entry must NOT be called for non-terminal statuses
        # even when external_run_id is present.
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [{'env': self._env(), 'deployments': None}],
            [{'deployments': None}],
        ]
        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            mock.patch(
                'imbi.api.endpoints.releases.complete_opslog_entry',
                new_callable=mock.AsyncMock,
                return_value=True,
            ) as mock_close,
        ):
            response = self.client.post(
                self._url(f'/{RELEASE_ID}/environments/production'),
                json={'status': 'in_progress', 'external_run_id': 'run-42'},
            )
        self.assertEqual(response.status_code, 200)
        mock_close.assert_not_called()

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
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                self._url(f'/{RELEASE_ID}/environments'),
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
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                self._url(f'/{RELEASE_ID}/environments/production'),
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
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                self._url(f'/{RELEASE_ID}/environments/production'),
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['current_status'], 'success')

    def _current_release_calls(self) -> list[typing.Any]:
        # The current_release write is the only query that MERGEs the
        # DEPLOYED_IN edge and sets current_release.
        return [
            call
            for call in self.mock_db.execute.await_args_list
            if 'DEPLOYED_IN' in call.args[0]
            and 'current_release' in call.args[0]
        ]

    def test_record_deployment_success_sets_current_release(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [{'env': self._env(), 'deployments': None}],
            [{'deployments': None}],  # create edge
            [{'current_release': RELEASE_ID}],  # current_release write
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url(f'/{RELEASE_ID}/environments/production'),
                json={'status': 'success'},
            )
        self.assertEqual(response.status_code, 200)
        calls = self._current_release_calls()
        self.assertEqual(len(calls), 1)
        params = calls[0].args[1]
        self.assertEqual(params['release_id'], RELEASE_ID)
        self.assertEqual(params['project_id'], PROJECT_ID)
        self.assertEqual(params['env_slug'], 'production')
        self.assertEqual(params['org_slug'], ORG)
        # Timestamp is normalized to UTC so the stored-string comparison
        # in the newer-only guard is chronologically correct.
        self.assertTrue(params['ts'].endswith('+00:00'))
        # The write is guarded so out-of-order replays cannot regress it.
        self.assertIn('current_release_at', calls[0].args[0])

    def test_record_deployment_non_success_skips_current_release(
        self,
    ) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [{'env': self._env(), 'deployments': None}],
            [{'deployments': None}],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.post(
                self._url(f'/{RELEASE_ID}/environments/production'),
                json={'status': 'in_progress'},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._current_release_calls(), [])

    def test_record_deployment_current_release_empty_logs_warning(
        self,
    ) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [{'env': self._env(), 'deployments': None}],
            [{'deployments': None}],  # create edge
            [],  # current_release write matched nothing
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            with self.assertLogs(
                'imbi.api.endpoints.releases', level='WARNING'
            ) as logs:
                response = self.client.post(
                    self._url(f'/{RELEASE_ID}/environments/production'),
                    json={'status': 'success'},
                )
        # The deployment write still succeeds; only the pointer is skipped.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self._current_release_calls()), 1)
        self.assertTrue(
            any('current_release update skipped' in m for m in logs.output)
        )


class AppendDeploymentEventDedupeTestCase(_ReleasesTestBase):
    """Direct coverage for ``append_deployment_event`` dedupe semantics."""

    def _call(
        self,
        existing: list[dict[str, typing.Any]],
        *,
        external_run_id: str | None,
        status: str = 'success',
        note: str | None = None,
        performed_by: str | None = None,
    ) -> typing.Any:
        import asyncio

        from imbi.api.endpoints.releases import append_deployment_event

        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [
                {
                    'env': {'slug': 'production', 'name': 'Production'},
                    'deployments': json.dumps(existing) if existing else None,
                }
            ],
            [{'deployments': None}],  # only consumed by append / set path
            # only consumed by the current_release write on success writes
            [{'current_release': RELEASE_ID}],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            return asyncio.run(
                append_deployment_event(
                    self.mock_db,
                    org_slug=ORG,
                    project_id=PROJECT_ID,
                    release_id=RELEASE_ID,
                    env_slug='production',
                    status=typing.cast('typing.Any', status),
                    note=note,
                    external_run_id=external_run_id,
                    external_run_url='https://gh/runs/42',
                    performed_by=performed_by,
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

    def test_performed_by_change_refreshes_in_place(self) -> None:
        """A new ``performed_by`` for the same run triggers a refresh.

        Resync replaying a deployment after a plugin upgrade can now
        supply a creator login it didn't have before; the dedupe path
        must treat that as a change so the edge picks up the new
        attribution rather than no-op'ing on identical-looking rows.
        """
        existing = [
            {
                'timestamp': '2026-05-13T14:00:00+00:00',
                'status': 'success',
                'note': None,
                'external_run_id': '42',
                'external_run_url': 'https://gh/runs/42',
                'performed_by': None,
            }
        ]
        edge, outcome = self._call(
            existing,
            external_run_id='42',
            status='success',
            performed_by='octocat',
        )
        self.assertEqual(outcome, 'updated')
        self.assertEqual(edge.deployments[0].performed_by, 'octocat')

    def _current_release_calls(self) -> list[typing.Any]:
        return [
            call
            for call in self.mock_db.execute.await_args_list
            if 'DEPLOYED_IN' in call.args[0]
            and 'current_release' in call.args[0]
        ]

    def test_success_append_records_current_release(self) -> None:
        _edge, outcome = self._call([], external_run_id=None, status='success')
        self.assertEqual(outcome, 'appended')
        calls = self._current_release_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[1]['release_id'], RELEASE_ID)

    def test_non_success_append_skips_current_release(self) -> None:
        _edge, outcome = self._call([], external_run_id=None, status='failed')
        self.assertEqual(outcome, 'appended')
        self.assertEqual(self._current_release_calls(), [])

    def test_performed_by_match_is_no_op(self) -> None:
        existing = [
            {
                'timestamp': '2026-05-13T14:00:00+00:00',
                'status': 'success',
                'note': None,
                'external_run_id': '42',
                'external_run_url': 'https://gh/runs/42',
                'performed_by': 'octocat',
            }
        ]
        edge, outcome = self._call(
            existing,
            external_run_id='42',
            status='success',
            performed_by='octocat',
        )
        self.assertEqual(outcome, 'noop')
        self.assertEqual(edge.deployments[0].performed_by, 'octocat')


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
            'imbi.common.graph.parse_agtype',
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
                    'release': _release_row(tag='1.0.0', id='r1'),
                    'deployments': self._events(
                        ('2026-04-20T10:00:00+00:00', 'success'),
                    ),
                },
                {
                    'env': self._env('production', sort_order=30),
                    'release': _release_row(tag='1.1.0', id='r2'),
                    'deployments': self._events(
                        ('2026-04-22T10:00:00+00:00', 'success'),
                    ),
                },
            ],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['release']['tag'], '1.1.0')
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
                    'release': _release_row(tag='1.0.0', id='r1'),
                    'deployments': self._events(
                        ('2026-04-20T10:00:00+00:00', 'success'),
                        ('2026-04-23T10:00:00+00:00', 'success'),
                    ),
                },
                {
                    'env': self._env('production'),
                    'release': _release_row(tag='1.1.0', id='r2'),
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
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data[0]['release']['tag'], '1.0.0')
        self.assertEqual(data[0]['current_status'], 'success')

    def test_sorts_by_environment_sort_order(self) -> None:
        events = self._events(('2026-04-20T10:00:00+00:00', 'success'))
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {
                    'env': self._env('production', sort_order=30),
                    'release': _release_row(tag='1.0.0', id='r1'),
                    'deployments': events,
                },
                {
                    'env': self._env('testing', sort_order=10),
                    'release': _release_row(tag='1.0.0', id='r1'),
                    'deployments': events,
                },
                {
                    'env': self._env('staging', sort_order=20),
                    'release': _release_row(tag='1.0.0', id='r1'),
                    'deployments': events,
                },
            ],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
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
                    'release': _release_row(tag='1.0.0', id='r1'),
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
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        by_slug = {row['environment']['slug']: row for row in data}
        self.assertIsNone(by_slug['testing']['release'])
        self.assertEqual(by_slug['production']['release']['tag'], '1.0.0')

    def test_performed_by_email_resolves_to_display_name(self) -> None:
        """An email ``performed_by`` that matches an Imbi user surfaces
        the user's display name and a linkable email."""
        deployments = json.dumps(
            [
                {
                    'timestamp': '2026-04-22T10:00:00+00:00',
                    'status': 'success',
                    'note': None,
                    'performed_by': 'kevin@example.com',
                }
            ]
        )
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {
                    'env': self._env('production'),
                    'release': _release_row(tag='1.0.0', id='r1'),
                    'deployments': deployments,
                }
            ],
        ]
        kevin = models.User(
            email='kevin@example.com',
            display_name='Kevin Vance',
            is_active=True,
            is_admin=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        with (
            mock.patch(
                'imbi.api.endpoints.releases._users_by_email',
                new=mock.AsyncMock(return_value={'kevin@example.com': kevin}),
            ),
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
        ):
            response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 200, response.text)
        row = response.json()[0]
        self.assertEqual(row['performed_by'], 'Kevin Vance')
        self.assertEqual(row['performed_by_email'], 'kevin@example.com')

    def test_performed_by_login_without_imbi_user_is_not_linkable(
        self,
    ) -> None:
        """A raw remote login stays as-is with no linkable email."""
        deployments = json.dumps(
            [
                {
                    'timestamp': '2026-04-22T10:00:00+00:00',
                    'status': 'success',
                    'note': None,
                    'performed_by': 'octocat',
                }
            ]
        )
        self.mock_db.execute.side_effect = [
            [{'id': PROJECT_ID}],
            [
                {
                    'env': self._env('production'),
                    'release': _release_row(tag='1.0.0', id='r1'),
                    'deployments': deployments,
                }
            ],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 200, response.text)
        row = response.json()[0]
        self.assertEqual(row['performed_by'], 'octocat')
        self.assertIsNone(row['performed_by_email'])


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
        resolved.capability_cls = lambda: _Handler()
        resolved.integration_options = {}
        resolved.capability_options = {}

        async def _resolve_and_context(
            db: typing.Any, org_slug: str, project_id: str, auth: typing.Any
        ) -> tuple[typing.Any, typing.Any, dict[str, str]]:
            del db, org_slug, project_id, auth
            return resolved, mock.MagicMock(), {'access_token': 'x'}

        self._patcher = mock.patch(
            'imbi.api.endpoints.project_deployments._resolve_and_context',
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
                    'release': _release_row(tag='1.0.0', id='r1'),
                    'deployments': self._events_with_run(
                        '2026-04-20T10:00:00+00:00', 'success'
                    ),
                },
            ],
            [],  # resolve_plugin → no plugin → HTTPException(404)
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
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
                    'release': _release_row(tag='1.0.0', id='r1'),
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
            [{'release': _release_row(tag='1.0.0', id='r1')}],
            [{'env': self._env('production'), 'deployments': None}],
            [{'deployments': '[]'}],
            [{'current_release': 'r1'}],  # current_release write on success
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
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
                    'release': _release_row(tag='1.0.0', id='r1'),
                    'deployments': self._events_with_run(
                        '2026-04-20T10:00:00+00:00', 'success'
                    ),
                },
            ],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
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
                    'release': _release_row(tag='1.0.0', id='r1'),
                    'deployments': self._events_with_run(
                        '2026-04-20T10:00:00+00:00',
                        'in_progress',
                        run_id='42',
                    ),
                },
            ],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(self._url('/current'))
        self.assertEqual(response.status_code, 200)
        body = response.json()[0]
        # Status untouched (still in_progress); ci_status null.
        self.assertEqual(body['current_status'], 'in_progress')
        self.assertIsNone(body['ci_status'])


def _tiny_sbom() -> dict[str, typing.Any]:
    """Return a fresh minimal CycloneDX 1.7 document."""
    return {
        'bomFormat': 'CycloneDX',
        'specVersion': '1.7',
        'version': 1,
        'components': [
            {
                'type': 'library',
                'bom-ref': 'pkg:npm/express@4.18.2',
                'name': 'express',
                'version': '4.18.2',
                'purl': 'pkg:npm/express@4.18.2',
                'licenses': [{'license': {'id': 'MIT'}}],
            }
        ],
    }


class PutReleaseSbomTestCase(_ReleasesTestBase):
    """PUT /releases/{release_id}/sbom"""

    def test_put_success_returns_204(self) -> None:
        # _fetch_release row, then CLEAR_RELEASE_COMPONENTS (no rows),
        # then UPSERT_COMPONENT_AND_LINK (one row), then identifier
        # upsert (no rows expected back).
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [],
            [{'component_id': 'comp-1'}],
            [],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                self._url(f'/{RELEASE_ID}/sbom'),
                json=_tiny_sbom(),
            )
        self.assertEqual(response.status_code, 204)
        # First execute was _fetch_release; the second was the clear
        # query — that's the load-bearing idempotence assertion.
        clear_call = self.mock_db.execute.call_args_list[1]
        self.assertIn(
            'DELETE edge',
            clear_call.args[0],
        )
        # The third call (UPSERT_COMPONENT_AND_LINK) carries the
        # edge-attribution params for ReleaseComponentEdge — the
        # tiny SBoM emits no scope and no group properties, so
        # both come through as None / "[]" rather than absent.
        upsert_call = self.mock_db.execute.call_args_list[2]
        upsert_params = upsert_call.args[1]
        self.assertIn('scope', upsert_params)
        self.assertIn('groups', upsert_params)
        self.assertIsNone(upsert_params['scope'])
        self.assertEqual(upsert_params['groups'], '[]')

    def test_put_unknown_release_returns_404(self) -> None:
        self.mock_db.execute.side_effect = [[]]
        response = self.client.put(
            self._url(f'/{RELEASE_ID}/sbom'),
            json=_tiny_sbom(),
        )
        self.assertEqual(response.status_code, 404)

    def test_put_wrong_spec_version_returns_415(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
        ]
        bad = _tiny_sbom()
        bad['specVersion'] = '1.5'
        response = self.client.put(
            self._url(f'/{RELEASE_ID}/sbom'),
            json=bad,
        )
        self.assertEqual(response.status_code, 415)

    def test_put_malformed_payload_returns_400(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
        ]
        bad = _tiny_sbom()
        bad['components'] = 'not a list'
        response = self.client.put(
            self._url(f'/{RELEASE_ID}/sbom'),
            json=bad,
        )
        self.assertEqual(response.status_code, 400)

    def test_put_idempotent_clear_runs_twice_for_two_puts(self) -> None:
        # Two PUTs in succession: each must run a CLEAR_RELEASE_COMPONENTS
        # before re-linking — that is the durable contract.
        for _ in range(2):
            self.mock_db.execute.side_effect = [
                [{'release': _release_row()}],
                [],
                [{'component_id': 'comp-1'}],
                [],
            ]
            with mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ):
                response = self.client.put(
                    self._url(f'/{RELEASE_ID}/sbom'),
                    json=_tiny_sbom(),
                )
            self.assertEqual(response.status_code, 204)
            clear_call = self.mock_db.execute.call_args_list[1]
            self.assertIn('DELETE edge', clear_call.args[0])
            self.mock_db.execute.reset_mock()

    def test_put_continues_past_per_component_failure(self) -> None:
        # Two-component SBoM where one component's upsert raises.
        # The action must log a warning for the failing component
        # and still return 204 — partial graph state is more useful
        # than an aborted ingest. The mock keys responses off the
        # Cypher template + purl_name so the parallel-gather order
        # is irrelevant.
        two_component_sbom = {
            'bomFormat': 'CycloneDX',
            'specVersion': '1.7',
            'version': 1,
            'components': [
                {
                    'type': 'library',
                    'bom-ref': 'pkg:npm/good@1.0.0',
                    'name': 'good',
                    'version': '1.0.0',
                    'purl': 'pkg:npm/good@1.0.0',
                },
                {
                    'type': 'library',
                    'bom-ref': 'pkg:npm/broken@1.0.0',
                    'name': 'broken',
                    'version': '1.0.0',
                    'purl': 'pkg:npm/broken@1.0.0',
                },
            ],
        }

        async def fake_execute(
            query: str,
            params: dict[str, typing.Any] | None = None,
            columns: list[str] | None = None,
        ) -> list[dict[str, typing.Any]]:
            del columns
            params = params or {}
            if 'MATCH (p:Project' in query and 'RETURN r' in query:
                return [{'release': _release_row()}]
            if 'DELETE edge' in query:
                return []
            if 'MERGE (c:Component' in query:
                if params['purl_name'] == 'pkg:npm/broken':
                    raise RuntimeError('simulated AGE error')
                return [{'component_id': f'comp-{params["purl_name"]}'}]
            if 'MERGE (ci:ComponentIdentifier' in query:
                return []
            raise AssertionError(f'unexpected query in mock: {query[:60]!r}')

        self.mock_db.execute.side_effect = fake_execute

        with (
            mock.patch(
                'imbi.common.graph.parse_agtype',
                side_effect=lambda x: x,
            ),
            self.assertLogs('imbi.api.sbom', level='WARNING') as cm,
        ):
            response = self.client.put(
                self._url(f'/{RELEASE_ID}/sbom'),
                json=two_component_sbom,
            )

        self.assertEqual(response.status_code, 204)
        # The failing component must show up in the logs with its
        # purl + version + release id so on-call can find it.
        failure_lines = [
            line for line in cm.output if 'pkg:npm/broken' in line
        ]
        self.assertEqual(
            len(failure_lines), 1, msg=f'logs were: {cm.output!r}'
        )
        self.assertIn('1.0.0', failure_lines[0])
        self.assertIn(RELEASE_ID, failure_lines[0])
        self.assertIn('simulated AGE error', failure_lines[0])
        # The healthy component must still have made its upsert
        # call — that's the "some data > no data" contract.
        upsert_purls = {
            call.args[1]['purl_name']
            for call in self.mock_db.execute.call_args_list
            if 'MERGE (c:Component' in call.args[0]
        }
        self.assertEqual(upsert_purls, {'pkg:npm/good', 'pkg:npm/broken'})

    def test_put_same_purl_versions_run_sequentially_in_same_bucket(
        self,
    ) -> None:
        # Regression for the AGE "Entity failed to be updated: 3"
        # conflict — two versions of the same package (sharing one
        # purl_name and therefore one Component vertex) MUST be
        # serialized in the same bucket. Across-bucket parallelism
        # is fine; within-bucket parallelism deadlocks AGE.
        multi_version_sbom = {
            'bomFormat': 'CycloneDX',
            'specVersion': '1.7',
            'version': 1,
            'components': [
                {
                    'type': 'library',
                    'bom-ref': 'pkg:npm/react-is@17.0.2',
                    'name': 'react-is',
                    'version': '17.0.2',
                    'purl': 'pkg:npm/react-is@17.0.2',
                },
                {
                    'type': 'library',
                    'bom-ref': 'pkg:npm/react-is@18.3.1',
                    'name': 'react-is',
                    'version': '18.3.1',
                    'purl': 'pkg:npm/react-is@18.3.1',
                },
                # An unrelated package in a different bucket — it
                # may interleave with the react-is bucket but
                # MUST NOT serialize *between* the two react-is
                # versions.
                {
                    'type': 'library',
                    'bom-ref': 'pkg:npm/chalk@5.0.0',
                    'name': 'chalk',
                    'version': '5.0.0',
                    'purl': 'pkg:npm/chalk@5.0.0',
                },
            ],
        }

        # Track which purl_names are mid-upsert so we can assert
        # no two tasks ever hold the same Component vertex
        # simultaneously. ``asyncio.sleep(0)`` inside the mock
        # forces a scheduler yield so any latent within-bucket
        # parallelism gets a chance to expose itself.
        in_flight: set[str] = set()
        overlapping_calls: list[str] = []

        async def fake_execute(
            query: str,
            params: dict[str, typing.Any] | None = None,
            columns: list[str] | None = None,
        ) -> list[dict[str, typing.Any]]:
            import asyncio as _asyncio

            del columns
            params = params or {}
            if 'MATCH (p:Project' in query and 'RETURN r' in query:
                return [{'release': _release_row()}]
            if 'DELETE edge' in query:
                return []
            if 'MERGE (c:Component' in query:
                purl = params['purl_name']
                if purl in in_flight:
                    overlapping_calls.append(purl)
                in_flight.add(purl)
                await _asyncio.sleep(0)
                in_flight.discard(purl)
                return [{'component_id': f'comp-{purl}'}]
            if 'MERGE (ci:ComponentIdentifier' in query:
                return []
            raise AssertionError(f'unexpected query in mock: {query[:60]!r}')

        self.mock_db.execute.side_effect = fake_execute

        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.put(
                self._url(f'/{RELEASE_ID}/sbom'),
                json=multi_version_sbom,
            )

        self.assertEqual(response.status_code, 204)
        # The load-bearing assertion: no two upserts on the same
        # Component vertex ever overlapped. Anything in
        # ``overlapping_calls`` is a regression that would
        # reproduce the AGE "Entity failed to be updated: 3"
        # error in production.
        self.assertEqual(overlapping_calls, [])
        # And both react-is versions still ended up upserted.
        upsert_purls_with_versions = sorted(
            (call.args[1]['purl_name'], call.args[1]['version'])
            for call in self.mock_db.execute.call_args_list
            if 'MERGE (c:Component' in call.args[0]
        )
        self.assertEqual(
            upsert_purls_with_versions,
            [
                ('pkg:npm/chalk', '5.0.0'),
                ('pkg:npm/react-is', '17.0.2'),
                ('pkg:npm/react-is', '18.3.1'),
            ],
        )


class GetReleaseDependenciesTestCase(_ReleasesTestBase):
    """GET /releases/{release_id}/dependencies"""

    def test_get_empty_release_returns_empty_components(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                self._url(f'/{RELEASE_ID}/dependencies'),
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['release_id'], RELEASE_ID)
        self.assertEqual(body['components'], [])

    def test_get_unknown_release_returns_404(self) -> None:
        self.mock_db.execute.side_effect = [[]]
        response = self.client.get(
            self._url(f'/{RELEASE_ID}/dependencies'),
        )
        self.assertEqual(response.status_code, 404)

    def test_get_populated_release_returns_components(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [
                {
                    'component_id': 'comp-1',
                    'purl_name': 'pkg:npm/express',
                    'name': 'express',
                    'ecosystem': 'npm',
                    'description': None,
                    'component_release_id': 'cr-1',
                    'version': '4.18.2',
                    'license': 'MIT',
                    'supplier': 'OpenJS Foundation',
                    'hashes': '{}',
                    'scope': 'optional',
                    'groups': '["dev","test"]',
                    'identifiers': [
                        {'kind': 'purl', 'value': 'pkg:npm/express'},
                    ],
                },
            ],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                self._url(f'/{RELEASE_ID}/dependencies'),
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body['components']), 1)
        component = body['components'][0]
        self.assertEqual(component['purl_name'], 'pkg:npm/express')
        self.assertEqual(component['version'], '4.18.2')
        self.assertEqual(component['license'], 'MIT')
        self.assertEqual(component['supplier'], 'OpenJS Foundation')
        self.assertEqual(
            component['identifiers'],
            [{'kind': 'purl', 'value': 'pkg:npm/express'}],
        )
        # ReleaseComponentEdge round-trip — these are per-release
        # usage facts that the UI keys off to render scope/group
        # chips.
        self.assertEqual(component['scope'], 'optional')
        self.assertEqual(component['groups'], ['dev', 'test'])
        # AGE ``cypher()`` requires the SELECT AS column list to match
        # the RETURN clause column count. The second execute call (the
        # dependency listing) must pass the 13-column ``columns``
        # parameter — without it AGE raises a DatatypeMismatch at run
        # time even though our mock-based tests would still pass.
        list_call = self.mock_db.execute.call_args_list[1]
        self.assertEqual(
            list_call.args[2],
            [
                'component_id',
                'purl_name',
                'name',
                'ecosystem',
                'description',
                'component_release_id',
                'version',
                'license',
                'supplier',
                'hashes',
                'scope',
                'groups',
                'identifiers',
            ],
        )

    def test_get_release_with_missing_edge_attrs(self) -> None:
        """Releases ingested before scope/groups were tracked must
        still render — defaulting to null/empty rather than 500."""
        self.mock_db.execute.side_effect = [
            [{'release': _release_row()}],
            [
                {
                    'component_id': 'comp-1',
                    'purl_name': 'pkg:npm/express',
                    'name': 'express',
                    'ecosystem': 'npm',
                    'description': None,
                    'component_release_id': 'cr-1',
                    'version': '4.18.2',
                    'license': None,
                    'supplier': None,
                    'hashes': '{}',
                    'scope': None,
                    'groups': None,
                    'identifiers': [],
                },
            ],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype',
            side_effect=lambda x: x,
        ):
            response = self.client.get(
                self._url(f'/{RELEASE_ID}/dependencies'),
            )
        self.assertEqual(response.status_code, 200)
        component = response.json()['components'][0]
        self.assertIsNone(component['scope'])
        self.assertEqual(component['groups'], [])
