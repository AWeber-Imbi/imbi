"""Tests for the agent definition endpoints."""

import datetime
import json
import typing
from unittest import mock

import psycopg.errors
from fastapi import testclient

from apps.api.tests import support
from apps.api.tests.endpoints import test_prompts
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

    def _batch(self) -> list[typing.Any]:
        """Return the statements of the one transactional write."""
        self.mock_db._execute_batch.assert_awaited_once()
        return list(self.mock_db._execute_batch.await_args.args[0])

    def _version_writes(self) -> list[dict[str, typing.Any]]:
        writes = [
            (c.args[0], c.args[1])
            for c in self.mock_db.execute.await_args_list
        ]
        for c in self.mock_db._execute_batch.await_args_list:
            writes += [(s.cypher, s.params) for s in c.args[0]]
        return [
            params
            for cypher, params in writes
            if 'CREATE (v:AgentVersion' in cypher
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
                'prompt_version': 2,
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
        self.assertEqual(create[1]['prompt_version'], 2)
        self.assertNotIn('version_summary', create[1])

        (version,) = self._version_writes()
        self.assertEqual(version['n'], 1)
        self.assertEqual(version['summary'], 'First cut')
        self.assertEqual(version['created_by'], 'dev@example.com')
        snapshot = json.loads(version['snapshot'])
        self.assertEqual(snapshot['team'], 'ops')
        self.assertEqual(snapshot['tags'], ['red'])
        self.assertEqual(snapshot['prompt_ref'], 'agents/triage@stable')
        self.assertEqual(snapshot['prompt_version'], 2)
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

    def test_create_copies_org_id(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'team_id': 'team-1'}],
            [],
            [{'id': 'agent-1'}],
            [{'n': 1}],
            [self._row()],
        ]
        response = self.client.post(
            BASE + '/', json={'name': 'T', 'slug': 'triage', 'team': 'ops'}
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertIn('SET a.org_id = o.id', self._queries()[2])

    def test_create_concurrent_slug_conflict(self) -> None:
        # The slug check passes, then the unique index stops the create.
        self.mock_db.execute.side_effect = [
            [{'team_id': 'team-1'}],
            [],
            psycopg.errors.UniqueViolation(),
        ]
        response = self.client.post(
            BASE + '/', json={'name': 'T', 'slug': 'triage', 'team': 'ops'}
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])
        self.assertEqual(self._version_writes(), [])

    def test_create_removes_agent_when_version_fails(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'team_id': 'team-1'}],
            [],
            [{'id': 'agent-1'}],
            RuntimeError('version write failed'),
            [],
            [{'deleted': 1}],
        ]
        with self.assertRaises(RuntimeError):
            self.client.post(
                BASE + '/',
                json={'name': 'T', 'slug': 'triage', 'team': 'ops'},
            )
        queries = self._queries()
        self.assertIn('DETACH DELETE v', queries[4])
        self.assertIn('DETACH DELETE a', queries[5])
        agent_id = self.mock_db.execute.await_args_list[2].args[1]['id']
        self.assertEqual(
            self.mock_db.execute.await_args_list[5].args[1], {'id': agent_id}
        )

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
        # fetch, batch (version, set), fetch
        self.mock_db.execute.side_effect = [
            [self._row(latest=3)],
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
        statements = self._batch()
        self.assertEqual(len(statements), 2)
        set_params = statements[1].params
        self.assertEqual(set_params['version'], 4)
        self.assertEqual(set_params['slack_channel'], '#triage')

    def test_put_prompt_version_writes_new_version(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, prompt_version=4)],
            [self._row(latest=4, prompt_version=5)],
        ]
        response = self.client.put(
            BASE + '/triage', json={'prompt_version': 5}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['prompt_version'], 5)
        (version,) = self._version_writes()
        self.assertEqual(json.loads(version['snapshot'])['prompt_version'], 5)
        self.assertEqual(self._batch()[1].params['prompt_version'], 5)

    def test_put_same_prompt_version_writes_nothing(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, prompt_version=4)],
        ]
        response = self.client.put(
            BASE + '/triage', json={'prompt_version': 4}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.mock_db._execute_batch.assert_not_awaited()

    def test_put_rejects_zero_prompt_version(self) -> None:
        response = self.client.put(
            BASE + '/triage', json={'prompt_version': 0}
        )
        self.assertEqual(response.status_code, 422)

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
            [self._row(enabled=False)],
        ]
        response = self.client.put(BASE + '/triage', json={'enabled': False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['enabled'])
        self.assertEqual(self._version_writes(), [])
        (set_stmt,) = self._batch()
        set_params = set_stmt.params
        self.assertEqual(
            set(set_params), {'enabled', 'updated_at', 'agent_id'}
        )

    def test_put_team_and_tags_change(self) -> None:
        # fetch, team, tags, batch (version, team x2, tags x2, set), fetch
        self.mock_db.execute.side_effect = [
            [self._row(tags=['red'])],
            [{'team_id': 'team-2'}],
            [{'tag_slug': 'blue', 'found': True}],
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
        # The version, the edges, and the properties are one
        # transaction, so a failed edge write keeps the old state.
        statements = self._batch()
        self.assertEqual(len(statements), 6)
        self.assertIn('CREATE (v:AgentVersion', statements[0].cypher)
        self.assertIn('OWNED_BY', statements[1].cypher)
        self.assertEqual(statements[2].params['team_id'], 'team-2')
        self.assertIn('TAGGED_WITH', statements[3].cypher)
        self.assertEqual(statements[4].params['tag_slugs'], ['blue'])
        self.assertIn('SET', statements[5].cypher)

    def test_put_deleted_agent_is_not_found(self) -> None:
        # fetch, batch (matches nothing), fetch (agent is gone)
        self.mock_db.execute.side_effect = [[self._row()], []]
        response = self.client.put(BASE + '/triage', json={'name': 'New'})
        self.assertEqual(response.status_code, 404)
        self.mock_db._execute_batch.assert_awaited_once()

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
        self.mock_db.execute.side_effect = [[self._row()]]
        self.mock_db._execute_batch.side_effect = (
            psycopg.errors.UniqueViolation()
        )
        response = self.client.put(BASE + '/triage', json={'name': 'New'})
        self.assertEqual(response.status_code, 409)
        self.assertIn('Version 2', response.json()['detail'])
        # The transaction rolls back, and nothing else is written.
        self.assertEqual(self.mock_db.execute.await_count, 1)

    def test_put_concurrent_slug_conflict(self) -> None:
        # fetch, slug check, batch (unique violation)
        self.mock_db.execute.side_effect = [[self._row(tags=['red'])], []]
        self.mock_db._execute_batch.side_effect = (
            psycopg.errors.UniqueViolation()
        )
        response = self.client.put(
            BASE + '/triage', json={'slug': 'taken', 'tags': []}
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.json()['detail'])
        # The transaction rolls back, so no clean-up write is needed.
        self.assertEqual(self.mock_db.execute.await_count, 2)

    def test_put_write_failure_propagates(self) -> None:
        self.mock_db.execute.side_effect = [[self._row()]]
        self.mock_db._execute_batch.side_effect = psycopg.errors.InternalError(
            'Entity failed to be updated'
        )
        with self.assertRaises(psycopg.errors.InternalError):
            self.client.put(BASE + '/triage', json={'name': 'New'})
        # The transaction rolls back, so no clean-up write is needed.
        self.assertEqual(self.mock_db.execute.await_count, 1)

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
        self.mock_db.execute.return_value = [{'id': 'agent-1'}]
        response = self.client.delete(BASE + '/triage')
        self.assertEqual(response.status_code, 204)
        # Both deletes run in one transaction.
        self.assertEqual(self.mock_db.execute.await_count, 1)
        self.mock_db._execute_batch.assert_awaited_once()
        statements = self.mock_db._execute_batch.await_args.args[0]
        self.assertEqual(len(statements), 2)
        self.assertIn('AgentVersion', statements[0].cypher)
        self.assertIn('DETACH DELETE v', statements[0].cypher)
        self.assertIn('DETACH DELETE a', statements[1].cypher)
        for stmt in statements:
            self.assertEqual(stmt.params, {'id': 'agent-1'})

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
        # fetch, version, batch (version write, set), fetch
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, slack_channel='#new')],
            [self._version(1)],
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
        set_params = self._batch()[1].params
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

    # -- Restore with the prompt ---------------------------------------

    def _prompt(self, stable: int) -> list[dict[str, typing.Any]]:
        return test_prompts.prompt_row(
            latest=6,
            namespace='agents',
            slug='triage',
            labels=json.dumps([test_prompts.label('stable', stable)]),
        )

    def _allow_promote(self) -> None:
        self.auth_context.permissions = {
            *self.auth_context.permissions,
            'prompt:promote',
        }

    def test_restore_moves_prompt_label(self) -> None:
        self._allow_promote()
        # fetch, version, prompt, prompt version, batch, fetch
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, slack_channel='#new', prompt_version=5)],
            [self._version(1, prompt_version=4)],
            self._prompt(stable=5),
            test_prompts.version_row(4),
            [self._row(latest=4, prompt_version=4)],
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['prompt_version'], 4)
        label_move, version_write, agent_set = self._batch()
        self.assertTrue(label_move.expect_rows)
        self.assertEqual(label_move.params['id'], 'prm-1')
        (label,) = json.loads(label_move.params['labels'])
        self.assertEqual(label['name'], 'stable')
        self.assertEqual(label['version'], 4)
        self.assertEqual(label['updated_by'], 'dev@example.com')
        self.assertIn('CREATE (v:AgentVersion', version_write.cypher)
        self.assertEqual(
            json.loads(version_write.params['snapshot'])['prompt_version'], 4
        )
        self.assertEqual(agent_set.params['prompt_version'], 4)

    def test_restore_moves_named_label(self) -> None:
        self._allow_promote()
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, prompt_version=5)],
            [
                self._version(
                    1, prompt_ref='agents/triage@beta', prompt_version=4
                )
            ],
            self._prompt(stable=5),
            test_prompts.version_row(4),
            [self._row(latest=4, prompt_version=4)],
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 200, response.text)
        labels = json.loads(self._batch()[0].params['labels'])
        self.assertEqual(
            sorted((lb['name'], lb['version']) for lb in labels),
            [('beta', 4), ('stable', 5)],
        )

    def test_restore_label_only_when_config_is_same(self) -> None:
        self._allow_promote()
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, prompt_version=4)],
            [self._version(1, prompt_version=4)],
            self._prompt(stable=5),
            test_prompts.version_row(4),
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 200, response.text)
        (label_move,) = self._batch()
        self.assertTrue(label_move.expect_rows)
        self.assertEqual(self._version_writes(), [])

    def test_restore_label_already_at_version(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, slack_channel='#new', prompt_version=4)],
            [self._version(1, prompt_version=4)],
            self._prompt(stable=4),
            test_prompts.version_row(4),
            [self._row(latest=4, prompt_version=4)],
        ]
        # No prompt:promote is needed when the label does not move.
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self._batch()), 2)

    def test_restore_pinned_ref_moves_no_label(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, slack_channel='#new')],
            [self._version(1, prompt_ref='agents/triage@3', prompt_version=3)],
            [self._row(latest=4)],
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self._batch()), 2)

    def test_restore_missing_prompt_version_conflicts(self) -> None:
        self._allow_promote()
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, slack_channel='#new', prompt_version=5)],
            [self._version(1, prompt_version=4)],
            self._prompt(stable=5),
            [],
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('no version 4', response.json()['detail'])
        self.mock_db._execute_batch.assert_not_awaited()

    def test_restore_missing_prompt_conflicts(self) -> None:
        self._allow_promote()
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, slack_channel='#new', prompt_version=5)],
            [self._version(1, prompt_version=4)],
            [],
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 409, response.text)
        self.mock_db._execute_batch.assert_not_awaited()

    def test_restore_label_move_requires_promote(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, slack_channel='#new', prompt_version=5)],
            [self._version(1, prompt_version=4)],
            self._prompt(stable=5),
            test_prompts.version_row(4),
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 403, response.text)
        self.mock_db._execute_batch.assert_not_awaited()

    def test_restore_prompt_changed_conflicts(self) -> None:
        self._allow_promote()
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, slack_channel='#new', prompt_version=5)],
            [self._version(1, prompt_version=4)],
            self._prompt(stable=5),
            test_prompts.version_row(4),
        ]
        self.mock_db._execute_batch.side_effect = (
            graph.StatementMatchedNothing('labels')
        )
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('prompt changed', response.json()['detail'])

    def test_restore_shared_prompt_conflicts(self) -> None:
        # The agent uses the shared prompt now, but it is not in the
        # agents namespace, so a restore must not move its label.
        self._allow_promote()
        ref = 'imbi-assistant/system@stable'
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, prompt_ref=ref, prompt_version=5)],
            [self._version(1, prompt_ref=ref, prompt_version=4)],
            self._prompt(stable=5),
            test_prompts.version_row(4),
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('imbi-assistant/system', response.json()['detail'])
        self.mock_db._execute_batch.assert_not_awaited()
        self.assertEqual(self._version_writes(), [])

    def test_restore_other_agent_prompt_conflicts(self) -> None:
        self._allow_promote()
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, prompt_version=5)],
            [
                self._version(
                    1, prompt_ref='agents/other@stable', prompt_version=4
                )
            ],
            self._prompt(stable=5),
            test_prompts.version_row(4),
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('agents/other', response.json()['detail'])
        self.mock_db._execute_batch.assert_not_awaited()
        self.assertEqual(self._version_writes(), [])

    def test_restore_agent_without_prompt_conflicts(self) -> None:
        self._allow_promote()
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, prompt_ref=None)],
            [self._version(1, prompt_version=4)],
            self._prompt(stable=5),
            test_prompts.version_row(4),
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 409, response.text)
        self.mock_db._execute_batch.assert_not_awaited()

    def test_restore_shared_prompt_label_in_place(self) -> None:
        # No label moves, so the restore of the rest goes on.
        ref = 'imbi-assistant/system@stable'
        self.mock_db.execute.side_effect = [
            [
                self._row(
                    latest=3,
                    slack_channel='#new',
                    prompt_ref=ref,
                    prompt_version=4,
                )
            ],
            [self._version(1, prompt_ref=ref, prompt_version=4)],
            self._prompt(stable=4),
            test_prompts.version_row(4),
            [self._row(latest=4, prompt_ref=ref, prompt_version=4)],
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self._batch()), 2)

    def test_restore_moves_label_with_other_selector(self) -> None:
        # The same prompt with another label is the agent's own prompt.
        self._allow_promote()
        self.mock_db.execute.side_effect = [
            [
                self._row(
                    latest=3, prompt_ref='agents/triage@beta', prompt_version=5
                )
            ],
            [self._version(1, prompt_version=4)],
            self._prompt(stable=5),
            test_prompts.version_row(4),
            [self._row(latest=4, prompt_version=4)],
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 200, response.text)
        (label,) = json.loads(self._batch()[0].params['labels'])
        self.assertEqual((label['name'], label['version']), ('stable', 4))

    # -- Tools ---------------------------------------------------------

    _TOOLS: typing.ClassVar[dict[str, typing.Any]] = {
        'github.read_file': {},
        'imbi.update_project': {
            'approval': True,
            'environments': ['staging', 'production'],
            'rate_limit': {'count': 6, 'per': 'hour'},
        },
    }

    _STORED_TOOLS: typing.ClassVar[dict[str, typing.Any]] = {
        'github.read_file': {
            'approval': False,
            'environments': None,
            'rate_limit': None,
        },
        'imbi.update_project': {
            'approval': True,
            'environments': ['production', 'staging'],
            'rate_limit': {'count': 6, 'per': 'hour'},
        },
    }

    def _env_rows(self, **found: bool) -> list[dict[str, typing.Any]]:
        return [{'env_slug': s, 'found': f} for s, f in found.items()]

    def test_get_returns_tools(self) -> None:
        self.mock_db.execute.return_value = [
            self._row(tools=json.dumps(self._STORED_TOOLS))
        ]
        body = self.client.get(BASE + '/triage').json()
        self.assertEqual(body['tools'], self._STORED_TOOLS)

    def test_get_agent_without_tools(self) -> None:
        self.mock_db.execute.return_value = [self._row()]
        self.assertEqual(self.client.get(BASE + '/triage').json()['tools'], {})

    def test_create_with_tools(self) -> None:
        # team, environments, slug check, create, version, fetch
        self.mock_db.execute.side_effect = [
            [{'team_id': 'team-1'}],
            self._env_rows(production=True, staging=True),
            [],
            [{'id': 'agent-1'}],
            [{'n': 1}],
            [self._row(tools=json.dumps(self._STORED_TOOLS))],
        ]
        response = self.client.post(
            BASE + '/',
            json={
                'name': 'Triage',
                'slug': 'triage',
                'team': 'ops',
                'tools': self._TOOLS,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        env_query = self.mock_db.execute.await_args_list[1].args
        self.assertEqual(env_query[1]['slugs'], ['production', 'staging'])
        create = self.mock_db.execute.await_args_list[3].args
        self.assertEqual(json.loads(create[1]['tools']), self._STORED_TOOLS)
        (version,) = self._version_writes()
        snapshot = json.loads(version['snapshot'])
        self.assertEqual(snapshot['tools'], self._STORED_TOOLS)

    def test_create_unknown_environment(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'team_id': 'team-1'}],
            self._env_rows(production=True, staging=False),
        ]
        response = self.client.post(
            BASE + '/',
            json={
                'name': 'T',
                'slug': 't',
                'team': 'ops',
                'tools': self._TOOLS,
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn('staging', response.json()['detail'])
        self.assertEqual(self._version_writes(), [])

    def test_create_rejects_invalid_tools(self) -> None:
        for tools in (
            {'no_server': {}},
            {'github.read_file': {'environments': []}},
            {'github.read_file': {'rate_limit': {'count': 0, 'per': 'day'}}},
            {'github.read_file': {'rate_limit': {'count': 1, 'per': 'week'}}},
        ):
            with self.subTest(tools=tools):
                response = self.client.post(
                    BASE + '/',
                    json={
                        'name': 'T',
                        'slug': 't',
                        'team': 'ops',
                        'tools': tools,
                    },
                )
                self.assertEqual(response.status_code, 422)
        self.mock_db.execute.assert_not_awaited()

    def test_tool_keys_are_not_checked(self) -> None:
        # A tool without environments needs no query. The key does not
        # have to be in the catalog.
        self.mock_db.execute.side_effect = [
            [self._row(latest=2)],
            [self._row(latest=3)],
        ]
        response = self.client.put(
            BASE + '/triage', json={'tools': {'offline.some_tool': {}}}
        )
        self.assertEqual(response.status_code, 200, response.text)
        (version,) = self._version_writes()
        self.assertEqual(
            list(json.loads(version['snapshot'])['tools']),
            ['offline.some_tool'],
        )

    def test_put_tools_writes_new_version(self) -> None:
        # fetch, environments, batch (version, set), fetch
        self.mock_db.execute.side_effect = [
            [self._row(latest=2)],
            self._env_rows(production=True, staging=True),
            [self._row(latest=3, tools=json.dumps(self._STORED_TOOLS))],
        ]
        response = self.client.put(
            BASE + '/triage',
            json={'tools': self._TOOLS, 'version_summary': 'Changed tools'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['tools'], self._STORED_TOOLS)
        (version,) = self._version_writes()
        self.assertEqual(version['summary'], 'Changed tools')
        self.assertEqual(
            json.loads(version['snapshot'])['tools'], self._STORED_TOOLS
        )
        set_params = self._batch()[1].params
        self.assertEqual(json.loads(set_params['tools']), self._STORED_TOOLS)

    def test_put_same_tools_writes_nothing(self) -> None:
        self.mock_db.execute.return_value = [
            self._row(tools=json.dumps(self._STORED_TOOLS))
        ]
        response = self.client.put(
            BASE + '/triage', json={'tools': self._TOOLS}
        )
        self.assertEqual(response.status_code, 200, response.text)
        # No environment query and no write.
        self.assertEqual(self.mock_db.execute.await_count, 1)
        self.mock_db._execute_batch.assert_not_awaited()

    def test_put_unknown_environment(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row()],
            self._env_rows(production=False, staging=True),
        ]
        response = self.client.put(
            BASE + '/triage', json={'tools': self._TOOLS}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn('production', response.json()['detail'])
        self.mock_db._execute_batch.assert_not_awaited()

    def test_patch_tool(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row(tools=json.dumps(self._STORED_TOOLS))],
            self._env_rows(production=True, staging=True),
            [self._row(latest=2)],
        ]
        response = self.client.patch(
            BASE + '/triage',
            json=[
                {
                    'op': 'replace',
                    'path': '/tools/imbi.update_project/approval',
                    'value': False,
                },
                {'op': 'remove', 'path': '/tools/github.read_file'},
            ],
        )
        self.assertEqual(response.status_code, 200, response.text)
        tools = json.loads(self._version_writes()[0]['snapshot'])['tools']
        self.assertEqual(list(tools), ['imbi.update_project'])
        self.assertFalse(tools['imbi.update_project']['approval'])

    def test_restore_restores_tools(self) -> None:
        # fetch, version, environments, batch, fetch
        self.mock_db.execute.side_effect = [
            [self._row(latest=3)],
            [self._version(1, tools=self._STORED_TOOLS)],
            self._env_rows(production=True, staging=True),
            [self._row(latest=4)],
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 200, response.text)
        set_params = self._batch()[1].params
        self.assertEqual(json.loads(set_params['tools']), self._STORED_TOOLS)

    def test_restore_old_version_clears_tools(self) -> None:
        # Version 1 was written before tools existed.
        self.mock_db.execute.side_effect = [
            [self._row(latest=3, tools=json.dumps(self._STORED_TOOLS))],
            [self._version(1)],
            [self._row(latest=4)],
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(json.loads(self._batch()[1].params['tools']), {})

    def test_restore_missing_environment(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row(latest=3)],
            [self._version(1, tools=self._STORED_TOOLS)],
            self._env_rows(production=False, staging=True),
        ]
        response = self.client.post(BASE + '/triage/versions/1/restore')
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self._version_writes(), [])

    def test_version_snapshot_has_tools(self) -> None:
        self.mock_db.execute.side_effect = [
            [self._row()],
            [self._version(2, tools=self._STORED_TOOLS)],
        ]
        body = self.client.get(BASE + '/triage/versions/2').json()
        self.assertEqual(body['snapshot']['tools'], self._STORED_TOOLS)

    # -- Tool catalog --------------------------------------------------

    def test_tool_catalog(self) -> None:
        from imbi.api import agent_tools, scoring

        valkey_client = mock.AsyncMock()
        self.test_app.dependency_overrides[scoring._inject_optional_client] = (
            lambda: valkey_client
        )
        self.addCleanup(
            self.test_app.dependency_overrides.pop,
            scoring._inject_optional_client,
        )
        catalog = agent_tools.AgentToolCatalog(
            groups=[
                agent_tools.AgentToolGroup(
                    server=agent_tools.AgentToolServer(
                        slug='sentry', name='Sentry', transport='mcp/http'
                    ),
                    error='Timed out after 10s',
                )
            ],
            generated_at=datetime.datetime(2026, 10, 6, tzinfo=datetime.UTC),
        )
        with mock.patch.object(
            agent_tools, 'get_catalog', return_value=catalog
        ) as get_catalog:
            response = self.client.get(BASE + '/tool-catalog?refresh=true')
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['groups'][0]['server']['slug'], 'sentry')
        self.assertEqual(body['groups'][0]['tools'], [])
        self.assertEqual(body['groups'][0]['error'], 'Timed out after 10s')
        args = get_catalog.await_args
        self.assertIs(args.args[0], self.mock_db)
        self.assertIs(args.args[1], valkey_client)
        self.assertTrue(args.kwargs['refresh'])
        # The OpenAPI document of this app is the source of Imbi tools.
        self.assertIn('paths', args.args[2]())

    def test_tool_catalog_requires_read(self) -> None:
        self.auth_context.permissions = set()
        response = self.client.get(BASE + '/tool-catalog')
        self.assertEqual(response.status_code, 403)
