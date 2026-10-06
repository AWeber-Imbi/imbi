"""Tests for the agent definition endpoints."""

import datetime
import json
import typing
from unittest import mock

import psycopg.errors
from fastapi import testclient

from apps.api.tests import support
from imbi.api import models
from imbi.common import graph

BASE = '/organizations/engineering/agents'


class AgentEndpointsTestCase(support.SharedAppTestCase):
    """Test cases for agent CRUD and versions."""

    def setUp(self) -> None:
        from imbi.api.auth import permissions

        self.user = models.User(
            email='dev@example.com',
            display_name='Dev User',
            password_hash='$argon2id$hashed',
            is_active=True,
            is_admin=False,
            is_service_account=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.auth_context = permissions.AuthContext(
            user=self.user,
            session_id='test-session',
            auth_method='jwt',
            permissions={
                'agent:create',
                'agent:read',
                'agent:write',
                'agent:delete',
            },
        )

        async def mock_get_current_user() -> permissions.AuthContext:
            return self.auth_context

        self.test_app.dependency_overrides[permissions.get_current_user] = (
            mock_get_current_user
        )

        self.mock_db = mock.AsyncMock(spec=graph.Graph)
        self.test_app.dependency_overrides[graph._inject_graph] = (
            lambda: self.mock_db
        )
        patcher = mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client = testclient.TestClient(self.test_app)

    # -- Fixtures ------------------------------------------------------

    def _row(
        self,
        *,
        team: str = 'ops',
        tags: list[str] | None = None,
        latest: int = 1,
        **overrides: typing.Any,
    ) -> dict[str, typing.Any]:
        agent: dict[str, typing.Any] = {
            'id': 'agent-1',
            'name': 'Triage',
            'slug': 'triage',
            'description': None,
            'icon': None,
            'enabled': True,
            'slack_channel': '#ops',
            'prompt_ref': 'agents/triage@stable',
            'settings': json.dumps({'response_sla': '24h'}),
            'version': latest,
            'created_at': '2026-10-01T12:00:00Z',
            'updated_at': '2026-10-01T12:00:00Z',
        }
        agent.update(overrides)
        return {
            'a': agent,
            'o': {'name': 'Engineering', 'slug': 'engineering'},
            't': {'name': team.title(), 'slug': team},
            'tags': [
                {'name': s.title(), 'slug': s, 'color': '#FF0000'}
                for s in (tags or [])
            ],
            'latest': latest,
            'updated_by': 'dev@example.com',
            'last_version_at': '2026-10-01T12:00:00Z',
        }

    def _version(
        self, n: int, **snapshot: typing.Any
    ) -> dict[str, typing.Any]:
        body: dict[str, typing.Any] = {
            'name': 'Triage',
            'slug': 'triage',
            'team': 'ops',
            'tags': [],
            'slack_channel': '#ops',
            'prompt_ref': 'agents/triage@stable',
            'settings': {'response_sla': '24h'},
        }
        body.update(snapshot)
        return {
            'v': {
                'id': f'v{n}',
                'agent_id': 'agent-1',
                'n': n,
                'summary': f'note {n}',
                'snapshot': json.dumps(body),
                'created_by': 'dev@example.com',
                'created_at': '2026-10-01T12:00:00Z',
            }
        }

    def _queries(self) -> list[str]:
        return [c.args[0] for c in self.mock_db.execute.await_args_list]

    def _version_writes(self) -> list[dict[str, typing.Any]]:
        return [
            c.args[1]
            for c in self.mock_db.execute.await_args_list
            if 'CREATE (v:AgentVersion' in c.args[0]
        ]

    # -- Create --------------------------------------------------------

    def test_create_writes_version_one(self) -> None:
        # team, tags, slug check, create, attach tags, version, fetch
        self.mock_db.execute.side_effect = [
            [{'team_id': 'team-1'}],
            [{'tag_slug': 'red', 'found': True}],
            [],
            [{'id': 'agent-1'}],
            [{'attached': 1}],
            [{'n': 1}],
            [self._row(tags=['red'])],
        ]
        response = self.client.post(
            BASE + '/',
            json={
                'name': 'Triage',
                'slug': 'triage',
                'team': 'ops',
                'tags': ['red', 'red'],
                'slack_channel': '#ops',
                'prompt_ref': 'agents/triage@stable',
                'settings': {'response_sla': '24h'},
                'version_summary': 'First cut',
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body['version'], 1)
        self.assertEqual(body['team'], {'name': 'Ops', 'slug': 'ops'})
        self.assertEqual(
            body['tags'], [{'name': 'Red', 'slug': 'red', 'color': '#FF0000'}]
        )
        self.assertEqual(body['organization']['slug'], 'engineering')
        self.assertEqual(body['updated_by'], 'dev@example.com')
        self.assertIsNotNone(body['last_version_at'])
        self.assertEqual(body['settings']['response_sla'], '24h')
        self.assertNotIn('model', body)

        create = self.mock_db.execute.await_args_list[3].args
        self.assertIn('CREATE (a:Agent', create[0])
        self.assertEqual(create[1]['team_id'], 'team-1')
        self.assertEqual(create[1]['version'], 1)
        self.assertNotIn('version_summary', create[1])

        (version,) = self._version_writes()
        self.assertEqual(version['n'], 1)
        self.assertEqual(version['summary'], 'First cut')
        self.assertEqual(version['created_by'], 'dev@example.com')
        snapshot = json.loads(version['snapshot'])
        self.assertEqual(snapshot['team'], 'ops')
        self.assertEqual(snapshot['tags'], ['red'])
        self.assertEqual(snapshot['prompt_ref'], 'agents/triage@stable')
        for key in ('enabled', 'id', 'created_at', 'model', 'params'):
            self.assertNotIn(key, snapshot)

    def test_create_slug_conflict(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'team_id': 'team-1'}],
            [{'id': 'other'}],
        ]
        response = self.client.post(
            BASE + '/', json={'name': 'T', 'slug': 'triage', 'team': 'ops'}
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])

    def test_create_unknown_team(self) -> None:
        self.mock_db.execute.return_value = [{'team_id': None}]
        response = self.client.post(
            BASE + '/', json={'name': 'T', 'slug': 't', 'team': 'ghost'}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn('ghost', response.json()['detail'])

    def test_create_unknown_org(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.post(
            BASE + '/', json={'name': 'T', 'slug': 't', 'team': 'ops'}
        )
        self.assertEqual(response.status_code, 404)

    def test_create_unknown_tag(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'team_id': 'team-1'}],
            [
                {'tag_slug': 'red', 'found': True},
                {'tag_slug': 'ghost', 'found': False},
            ],
        ]
        response = self.client.post(
            BASE + '/',
            json={
                'name': 'T',
                'slug': 't',
                'team': 'ops',
                'tags': ['red', 'ghost'],
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn('ghost', response.json()['detail'])

    def test_create_rejects_invalid_input(self) -> None:
        cases: list[dict[str, typing.Any]] = [
            {'name': 'T', 'slug': 't'},
            {'name': 'T', 'slug': 't', 'team': 'ops', 'prompt_ref': 'x y'},
            {
                'name': 'T',
                'slug': 't',
                'team': 'ops',
                'settings': {'response_sla': '1w'},
            },
            {'name': '', 'slug': 't', 'team': 'ops'},
        ]
        for body in cases:
            with self.subTest(body=body):
                response = self.client.post(BASE + '/', json=body)
                self.assertEqual(response.status_code, 422)
        self.mock_db.execute.assert_not_awaited()

    def test_create_requires_permission(self) -> None:
        self.auth_context.permissions = {'agent:read'}
        response = self.client.post(
            BASE + '/', json={'name': 'T', 'slug': 't', 'team': 'ops'}
        )
        self.assertEqual(response.status_code, 403)
        self.mock_db.execute.assert_not_awaited()

    def test_read_requires_permission(self) -> None:
        self.auth_context.permissions = set()
        self.assertEqual(self.client.get(BASE + '/').status_code, 403)
        self.assertEqual(self.client.delete(BASE + '/triage').status_code, 403)
        self.mock_db.execute.assert_not_awaited()

    # -- Read ----------------------------------------------------------

    def test_list_sorted_by_name(self) -> None:
        self.mock_db.execute.return_value = [
            self._row(name='Zeta', slug='zeta'),
            self._row(name='alpha', slug='alpha'),
        ]
        response = self.client.get(BASE + '/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [a['slug'] for a in response.json()], ['alpha', 'zeta']
        )

    def test_get(self) -> None:
        self.mock_db.execute.return_value = [self._row(tags=['b', 'a'])]
        response = self.client.get(BASE + '/triage')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([t['slug'] for t in body['tags']], ['a', 'b'])
        self.assertEqual(body['prompt_ref'], 'agents/triage@stable')

    def test_get_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        self.assertEqual(self.client.get(BASE + '/nope').status_code, 404)

    # -- Update --------------------------------------------------------

    def test_put_change_writes_new_version(self) -> None:
        # fetch, version, set, fetch
        self.mock_db.execute.side_effect = [
            [self._row(latest=3)],
            [{'n': 4}],
            [{'slug': 'triage'}],
            [self._row(latest=4, slack_channel='#triage')],
        ]
        response = self.client.put(
            BASE + '/triage',
            json={'slack_channel': '#triage', 'version_summary': 'Move'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['version'], 4)
        (version,) = self._version_writes()
        self.assertEqual(version['n'], 4)
        self.assertEqual(version['summary'], 'Move')
        snapshot = json.loads(version['snapshot'])
        self.assertEqual(snapshot['slack_channel'], '#triage')
        set_params = self.mock_db.execute.await_args_list[2].args[1]
        self.assertEqual(set_params['version'], 4)
        self.assertEqual(set_params['slack_channel'], '#triage')

    def test_put_no_change_writes_nothing(self) -> None:
        self.mock_db.execute.return_value = [self._row()]
        response = self.client.put(
            BASE + '/triage',
            json={
                'name': 'Triage',
                'settings': {'response_sla': '24h'},
                'version_summary': 'ignored',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.mock_db.execute.await_count, 1)
        self.assertEqual(self._version_writes(), [])

    def test_put_enabled_only_writes_no_version(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row()],
            [{'slug': 'triage'}],
            [self._row(enabled=False)],
        ]
        response = self.client.put(BASE + '/triage', json={'enabled': False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['enabled'])
        self.assertEqual(self._version_writes(), [])
        set_params = self.mock_db.execute.await_args_list[1].args[1]
        self.assertEqual(
            set(set_params), {'enabled', 'updated_at', 'agent_id'}
        )

    def test_put_team_and_tags_change(self) -> None:
        # fetch, team, tags, version, team x2, tags x2, set, fetch
        self.mock_db.execute.side_effect = [
            [self._row(tags=['red'])],
            [{'team_id': 'team-2'}],
            [{'tag_slug': 'blue', 'found': True}],
            [{'n': 2}],
            [{'removed': 1}],
            [{'team_id': 'team-2'}],
            [{'removed': 1}],
            [{'attached': 1}],
            [{'slug': 'triage'}],
            [self._row(team='dev', tags=['blue'], latest=2)],
        ]
        response = self.client.put(
            BASE + '/triage', json={'team': 'dev', 'tags': ['blue']}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['team']['slug'], 'dev')
        snapshot = json.loads(self._version_writes()[0]['snapshot'])
        self.assertEqual(snapshot['team'], 'dev')
        self.assertEqual(snapshot['tags'], ['blue'])

    def test_put_unknown_team(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row()],
            [{'team_id': None}],
        ]
        response = self.client.put(BASE + '/triage', json={'team': 'ghost'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self._version_writes(), [])

    def test_put_slug_conflict(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row()],
            [{'id': 'other'}],
        ]
        response = self.client.put(BASE + '/triage', json={'slug': 'taken'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._version_writes(), [])

    def test_put_concurrent_version_conflict(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row()],
            psycopg.errors.UniqueViolation(),
        ]
        response = self.client.put(BASE + '/triage', json={'name': 'New'})
        self.assertEqual(response.status_code, 409)
        # The agent itself is not changed after the failed version.
        self.assertEqual(self.mock_db.execute.await_count, 2)

    def test_put_null_name_rejected(self) -> None:
        self.mock_db.execute.return_value = [self._row()]
        response = self.client.put(BASE + '/triage', json={'name': None})
        self.assertEqual(response.status_code, 422)

    def test_put_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.put(BASE + '/nope', json={'name': 'X'})
        self.assertEqual(response.status_code, 404)

    # -- Patch ---------------------------------------------------------

    def test_patch_change_writes_new_version(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row()],
            [{'n': 2}],
            [{'slug': 'triage'}],
            [self._row(latest=2, prompt_ref='agents/triage@canary')],
        ]
        response = self.client.patch(
            BASE + '/triage',
            json=[
                {
                    'op': 'replace',
                    'path': '/prompt_ref',
                    'value': 'agents/triage@canary',
                },
                {
                    'op': 'replace',
                    'path': '/version_summary',
                    'value': 'Canary',
                },
            ],
        )
        self.assertEqual(response.status_code, 200, response.text)
        (version,) = self._version_writes()
        self.assertEqual(version['n'], 2)
        self.assertEqual(version['summary'], 'Canary')

    def test_patch_enabled_only_writes_no_version(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row()],
            [{'slug': 'triage'}],
            [self._row(enabled=False)],
        ]
        response = self.client.patch(
            BASE + '/triage',
            json=[{'op': 'replace', 'path': '/enabled', 'value': False}],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._version_writes(), [])

    def test_patch_no_change_writes_nothing(self) -> None:
        self.mock_db.execute.return_value = [self._row()]
        response = self.client.patch(
            BASE + '/triage',
            json=[{'op': 'replace', 'path': '/name', 'value': 'Triage'}],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.mock_db.execute.await_count, 1)

    def test_patch_invalid_values_rejected(self) -> None:
        for op in (
            {'op': 'replace', 'path': '/name', 'value': ''},
            {'op': 'replace', 'path': '/prompt_ref', 'value': 'bad ref'},
            {'op': 'replace', 'path': '/settings/response_sla', 'value': 1},
        ):
            with self.subTest(op=op):
                self.mock_db.execute.reset_mock()
                self.mock_db.execute.return_value = [self._row()]
                response = self.client.patch(BASE + '/triage', json=[op])
                self.assertEqual(response.status_code, 400)

    def test_patch_readonly_path_rejected(self) -> None:
        self.mock_db.execute.return_value = [self._row()]
        response = self.client.patch(
            BASE + '/triage',
            json=[{'op': 'replace', 'path': '/version', 'value': 9}],
        )
        self.assertEqual(response.status_code, 400)

    # -- Delete --------------------------------------------------------

    def test_delete_removes_versions_then_agent(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'id': 'agent-1'}],
            [],
            [{'deleted': 1}],
        ]
        response = self.client.delete(BASE + '/triage')
        self.assertEqual(response.status_code, 204)
        queries = self._queries()
        self.assertIn('AgentVersion', queries[1])
        self.assertIn('DETACH DELETE v', queries[1])
        self.assertIn('DETACH DELETE a', queries[2])
        for call in self.mock_db.execute.await_args_list[1:]:
            self.assertEqual(call.args[1], {'id': 'agent-1'})

    def test_delete_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        self.assertEqual(self.client.delete(BASE + '/nope').status_code, 404)

    # -- Versions ------------------------------------------------------

    def test_list_versions_newest_first(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row(latest=3)],
            [self._version(1), self._version(3), self._version(2)],
        ]
        response = self.client.get(BASE + '/triage/versions')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([v['n'] for v in body], [3, 2, 1])
        self.assertEqual(body[0]['snapshot']['team'], 'ops')

    def test_get_version(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row()],
            [self._version(1)],
        ]
        response = self.client.get(BASE + '/triage/versions/1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['summary'], 'note 1')

    def test_get_version_not_found(self) -> None:
        self.mock_db.execute.side_effect = [[self._row()], []]
        response = self.client.get(BASE + '/triage/versions/9')
        self.assertEqual(response.status_code, 404)

    def test_restore_writes_new_version(self) -> None:
        # fetch, version, version write, set, fetch
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, slack_channel='#new')],
            [self._version(1)],
            [{'n': 4}],
            [{'slug': 'triage'}],
            [self._row(latest=4)],
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['version'], 4)
        (version,) = self._version_writes()
        self.assertEqual(version['n'], 4)
        self.assertEqual(version['summary'], 'Restored v1')
        self.assertEqual(
            json.loads(version['snapshot'])['slack_channel'], '#ops'
        )
        set_params = self.mock_db.execute.await_args_list[3].args[1]
        self.assertEqual(set_params['slack_channel'], '#ops')
        self.assertTrue(set_params['enabled'])

    def test_restore_same_config_writes_nothing(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row(latest=2)],
            [self._version(1)],
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._version_writes(), [])

    def test_restore_missing_team(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row(latest=2)],
            [self._version(1, team='gone')],
            [{'team_id': None}],
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self._version_writes(), [])

    def test_restore_requires_write(self) -> None:
        self.auth_context.permissions = {'agent:read'}
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 403)
