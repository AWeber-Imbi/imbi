"""Tests for tag CRUD endpoints."""

import datetime
import typing
import unittest
import uuid
from unittest import mock

import fastapi
import psycopg.errors
from fastapi.testclient import TestClient

from apps.api.tests import support
from imbi.api import models
from imbi.api.endpoints import tags
from imbi.common import graph


class TagEndpointsTestCase(support.SharedAppTestCase):
    """Test cases for tag CRUD endpoints."""

    def setUp(self) -> None:
        from imbi.api.auth import permissions

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
                'tag:create',
                'tag:read',
                'tag:write',
                'tag:delete',
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

        self.client = TestClient(self.test_app)

    def _tag_data(self, **overrides: typing.Any) -> dict:
        data: dict[str, typing.Any] = {
            'id': 'tag-123',
            'name': 'Runbook',
            'slug': 'runbook',
            'description': None,
            'created_at': '2026-03-17T12:00:00Z',
            'updated_at': '2026-03-17T12:00:00Z',
        }
        data.update(overrides)
        return data

    def _org_data(self) -> dict:
        return {'name': 'Engineering', 'slug': 'engineering'}

    # -- Create --------------------------------------------------------

    def test_create_success(self) -> None:
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/tags/',
                json={'name': 'Runbook'},
            )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['slug'], 'runbook')
        self.assertEqual(body['relationships']['documents']['count'], 0)

    def test_create_auto_slugifies_from_name(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(name='Post Mortem', slug='post-mortem'),
                'o': self._org_data(),
            }
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/tags/',
                json={'name': 'Post Mortem'},
            )
        self.assertEqual(response.status_code, 201)
        # second positional arg of .execute call contains the params dict
        _, args, _ = self.mock_db.execute.mock_calls[0]
        self.assertEqual(args[1]['slug'], 'post-mortem')

    def test_create_rejects_empty_name(self) -> None:
        response = self.client.post(
            '/organizations/engineering/tags/',
            json={'name': ''},
        )
        self.assertEqual(response.status_code, 422)

    def test_create_rejects_empty_slug(self) -> None:
        response = self.client.post(
            '/organizations/engineering/tags/',
            json={'name': 'Runbook', 'slug': ''},
        )
        self.assertEqual(response.status_code, 422)

    def test_create_slug_conflict(self) -> None:
        self.mock_db.execute.side_effect = psycopg.errors.UniqueViolation()
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/tags/',
                json={'name': 'Runbook', 'slug': 'runbook'},
            )
        self.assertEqual(response.status_code, 409)

    def test_create_org_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/ghost/tags/',
                json={'name': 'Runbook'},
            )
        self.assertEqual(response.status_code, 404)

    # -- List ----------------------------------------------------------

    def test_list_success(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(),
                'o': self._org_data(),
                'document_count': 4,
                'agent_count': 0,
            },
            {
                't': self._tag_data(name='Alert', slug='alert'),
                'o': self._org_data(),
                'document_count': 0,
                'agent_count': 0,
            },
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get('/organizations/engineering/tags/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['relationships']['documents']['count'], 4)

    # -- Get -----------------------------------------------------------

    def test_get_success(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(),
                'o': self._org_data(),
                'document_count': 2,
                'agent_count': 0,
            }
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/tags/runbook'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['relationships']['documents']['count'], 2
        )

    def test_get_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/tags/missing'
            )
        self.assertEqual(response.status_code, 404)

    # -- Patch ---------------------------------------------------------

    def test_patch_rename(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'t': self._tag_data(), 'o': self._org_data()}],
            [
                {
                    't': self._tag_data(name='Runbooks'),
                    'o': self._org_data(),
                    'document_count': 3,
                    'agent_count': 0,
                }
            ],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/name', 'value': 'Runbooks'}],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'Runbooks')

    def test_patch_slug_conflict(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'t': self._tag_data(), 'o': self._org_data()}],
            psycopg.errors.UniqueViolation(),
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/slug', 'value': 'alert'}],
            )
        self.assertEqual(response.status_code, 409)

    def test_patch_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.patch(
            '/organizations/engineering/tags/missing',
            json=[{'op': 'replace', 'path': '/name', 'value': 'X'}],
        )
        self.assertEqual(response.status_code, 404)

    def test_patch_readonly_path_rejected(self) -> None:
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/id', 'value': 'xxx'}],
            )
        self.assertEqual(response.status_code, 400)

    # -- Delete --------------------------------------------------------

    def test_delete_success(self) -> None:
        self.mock_db.execute.return_value = [{'t': True}]
        response = self.client.delete(
            '/organizations/engineering/tags/runbook'
        )
        self.assertEqual(response.status_code, 204)

    def test_delete_not_found(self) -> None:
        self.mock_db.execute.return_value = []
        response = self.client.delete(
            '/organizations/engineering/tags/missing'
        )
        self.assertEqual(response.status_code, 404)

    def test_patch_validation_error(self) -> None:
        """Patching /name to non-string triggers a 400 validation error."""
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/name', 'value': 123}],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_rejects_empty_name(self) -> None:
        """Patching /name to an empty string yields a 400."""
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/name', 'value': ''}],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_rejects_empty_slug(self) -> None:
        """Patching /slug to an empty string yields a 400."""
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/slug', 'value': ''}],
            )
        self.assertEqual(response.status_code, 400)

    def test_patch_concurrent_delete_returns_404(self) -> None:
        """Update returning no rows after fetch yields 404."""
        self.mock_db.execute.side_effect = [
            [{'t': self._tag_data(), 'o': self._org_data()}],
            [],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'replace', 'path': '/name', 'value': 'Runbooks'}],
            )
        self.assertEqual(response.status_code, 404)

    # -- Color ---------------------------------------------------------

    def test_create_with_color(self) -> None:
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(color='#3B82F6'), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/tags/',
                json={'name': 'Runbook', 'color': '#3B82F6'},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['color'], '#3B82F6')
        _, args, _ = self.mock_db.execute.mock_calls[0]
        self.assertEqual(args[1]['color'], '#3B82F6')

    def test_create_without_color_stores_null(self) -> None:
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.post(
                '/organizations/engineering/tags/',
                json={'name': 'Runbook'},
            )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()['color'])
        _, args, _ = self.mock_db.execute.mock_calls[0]
        self.assertIsNone(args[1]['color'])

    def test_create_rejects_invalid_color(self) -> None:
        for color in ('blue', '#3B82F', '#3B82F6AA', '3B82F6', '#GGGGGG'):
            with self.subTest(color=color):
                response = self.client.post(
                    '/organizations/engineering/tags/',
                    json={'name': 'Runbook', 'color': color},
                )
                self.assertEqual(response.status_code, 422)

    def test_get_returns_color(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(color='#abcdef'),
                'o': self._org_data(),
                'document_count': 0,
                'agent_count': 0,
            }
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/tags/runbook'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['color'], '#abcdef')

    def test_list_returns_color(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(color='#abcdef'),
                'o': self._org_data(),
                'document_count': 0,
                'agent_count': 0,
            }
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get('/organizations/engineering/tags/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['color'], '#abcdef')

    def _patch_color(
        self,
        existing: str | None,
        operation: dict[str, typing.Any],
        stored: str | None,
    ) -> typing.Any:
        self.mock_db.execute.side_effect = [
            [{'t': self._tag_data(color=existing), 'o': self._org_data()}],
            [
                {
                    't': self._tag_data(color=stored),
                    'o': self._org_data(),
                    'document_count': 0,
                    'agent_count': 0,
                }
            ],
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            return self.client.patch(
                '/organizations/engineering/tags/runbook', json=[operation]
            )

    def test_patch_sets_color(self) -> None:
        response = self._patch_color(
            None,
            {'op': 'add', 'path': '/color', 'value': '#FF0000'},
            '#FF0000',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['color'], '#FF0000')
        params = self.mock_db.execute.await_args_list[1].args[1]
        self.assertEqual(params['color'], '#FF0000')

    def test_patch_clears_color(self) -> None:
        response = self._patch_color(
            '#FF0000', {'op': 'replace', 'path': '/color', 'value': None}, None
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['color'])
        params = self.mock_db.execute.await_args_list[1].args[1]
        self.assertIsNone(params['color'])

    def test_patch_other_field_keeps_color(self) -> None:
        response = self._patch_color(
            '#FF0000',
            {'op': 'replace', 'path': '/name', 'value': 'Runbooks'},
            '#FF0000',
        )
        self.assertEqual(response.status_code, 200)
        params = self.mock_db.execute.await_args_list[1].args[1]
        self.assertEqual(params['color'], '#FF0000')

    def test_patch_rejects_invalid_color(self) -> None:
        self.mock_db.execute.return_value = [
            {'t': self._tag_data(), 'o': self._org_data()}
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.patch(
                '/organizations/engineering/tags/runbook',
                json=[{'op': 'add', 'path': '/color', 'value': 'red'}],
            )
        self.assertEqual(response.status_code, 400)

    # -- Counts --------------------------------------------------------

    def test_get_returns_agent_count(self) -> None:
        self.mock_db.execute.return_value = [
            {
                't': self._tag_data(),
                'o': self._org_data(),
                'document_count': 1,
                'agent_count': 3,
            }
        ]
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            response = self.client.get(
                '/organizations/engineering/tags/runbook'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['relationships']['agents']['count'], 3
        )

    # -- Merge ---------------------------------------------------------

    def _merge(self, target: str) -> typing.Any:
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            return self.client.post(
                '/organizations/engineering/tags/runbook/merge',
                json={'target': target},
            )

    def test_merge_into_itself(self) -> None:
        response = self._merge('runbook')
        self.assertEqual(response.status_code, 422)
        self.mock_db.execute.assert_not_awaited()

    def test_merge_unknown_tag(self) -> None:
        for found, missing in (('alert', 'runbook'), ('runbook', 'alert')):
            with self.subTest(missing=missing):
                self.mock_db.execute.reset_mock()
                self.mock_db.execute.return_value = [
                    {'slug': found, 'id': f'id-{found}'}
                ]
                response = self._merge('alert')
                self.assertEqual(response.status_code, 404)
                self.assertIn(missing, response.json()['detail'])
                self.assertEqual(self.mock_db.execute.await_count, 1)

    def test_merge_success(self) -> None:
        self.mock_db.execute.side_effect = [
            [{'slug': 'runbook', 'id': 't-1'}, {'slug': 'alert', 'id': 't-2'}],
            [],
            [
                {
                    't': self._tag_data(id='t-2', name='Alert', slug='alert'),
                    'o': self._org_data(),
                    'document_count': 2,
                    'agent_count': 1,
                }
            ],
        ]
        response = self._merge('alert')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['slug'], 'alert')


class TagGraphTestCase(unittest.IsolatedAsyncioTestCase):
    """Tag uniqueness and merge against the real graph."""

    async def asyncSetUp(self) -> None:
        suffix = uuid.uuid4().hex[:10]
        self.org = f'tags-{suffix}'
        self.ids = [self.org, f'doc-{suffix}', f'agent-{suffix}']
        await graph.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.addAsyncCleanup(self.graph.close)
        self.addAsyncCleanup(self._cleanup)
        await self._run(
            """
            CREATE (o:Organization {{id: {org}, slug: {org}}}),
                   (:Document {{id: {doc}}})-[:BELONGS_TO]->(o),
                   (:Agent {{id: {agent}}})-[:BELONGS_TO]->(o)
            RETURN 1 AS ok
            """,
            org=self.org,
            doc=self.ids[1],
            agent=self.ids[2],
        )
        self.request = mock.Mock()
        self.request.app.url_path_for.return_value = '/tags/x'

    async def _run(
        self, query: str, **params: typing.Any
    ) -> list[dict[str, typing.Any]]:
        return await self.graph.execute(query, params, ['ok'])

    async def _cleanup(self) -> None:
        await self._run(
            """
            MATCH (t:Tag)-[:BELONGS_TO]->(:Organization {{id: {org}}})
            DETACH DELETE t
            RETURN 1 AS ok
            """,
            org=self.org,
        )
        await self._run(
            'MATCH (n) WHERE n.id IN {ids} DETACH DELETE n RETURN 1 AS ok',
            ids=self.ids,
        )

    async def _create(self, slug: str) -> dict[str, typing.Any]:
        return await tags.create_tag(
            self.org,
            tags.TagCreate(name=slug),
            self.request,
            self.graph,
            mock.Mock(),
        )

    async def _tag(self, node_id: str, slug: str) -> None:
        await self._run(
            """
            MATCH (n {{id: {id}}}),
                  (t:Tag {{slug: {slug}}})
                  -[:BELONGS_TO]->(:Organization {{id: {org}}})
            CREATE (n)-[:TAGGED_WITH]->(t)
            RETURN 1 AS ok
            """,
            id=node_id,
            slug=slug,
            org=self.org,
        )

    async def test_duplicate_create_conflicts(self) -> None:
        await self._create('experiment')
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await self._create('experiment')
        self.assertEqual(ctx.exception.status_code, 409)

    async def _merge(self, source: str, target: str) -> dict[str, typing.Any]:
        return await tags.merge_tag(
            self.org,
            source,
            tags.TagMerge(target=target),
            self.request,
            self.graph,
            mock.Mock(),
        )

    async def _get(self, slug: str) -> dict[str, typing.Any]:
        return await tags.get_tag(
            self.org, slug, self.request, self.graph, mock.Mock()
        )

    async def test_unused_tag_counts_zero(self) -> None:
        await self._create('unused')
        tag = await self._get('unused')
        counts = {k: v.count for k, v in tag['relationships'].items()}
        self.assertEqual(counts, {'documents': 0, 'agents': 0})

    async def test_merge_deletes_an_unused_source(self) -> None:
        await self._create('unused')
        await self._create('target')
        await self._merge('unused', 'target')
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await self._get('unused')
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_merge_moves_edges_without_duplicates(self) -> None:
        await self._create('experiment')
        await self._create('experiments')
        doc, agent = self.ids[1], self.ids[2]
        # The document has both tags; the agent only the source.
        await self._tag(doc, 'experiment')
        await self._tag(doc, 'experiments')
        await self._tag(agent, 'experiment')

        merged = await self._merge('experiment', 'experiments')

        counts = {k: v.count for k, v in merged['relationships'].items()}
        self.assertEqual(counts, {'documents': 1, 'agents': 1})
        edges = await self._run(
            """
            MATCH (n)-[:TAGGED_WITH]->(t:Tag)
            WHERE n.id IN {ids}
            RETURN [n.id, t.slug] AS ok
            """,
            ids=[doc, agent],
        )
        self.assertCountEqual(
            [graph.parse_agtype(e['ok']) for e in edges],
            [[doc, 'experiments'], [agent, 'experiments']],
        )
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await self._get('experiment')
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == '__main__':
    unittest.main()
