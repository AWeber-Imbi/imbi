"""Tests for ``/users/me/preferences/{namespace}``.

They run against the live Postgres that ``root:services`` boots.
"""

import datetime
import uuid

import httpx

from apps.api.tests import support
from imbi.api import models, preferences
from imbi.common import graph

_URL = '/users/me/preferences/slack_home'


class UserPreferencesTestCase(support.SharedAppAsyncTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        from imbi.api.auth import permissions

        self.email = f'prefs-{uuid.uuid4().hex[:10]}@example.com'
        await graph.initialize()
        await preferences.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        self.addAsyncCleanup(self._cleanup)
        self.user = models.User(
            email=self.email,
            display_name='Prefs',
            is_active=True,
            is_admin=True,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.context = permissions.AuthContext(
            user=self.user,
            session_id='test-session',
            auth_method='jwt',
            permissions={'user:delete'},
        )

        async def current_user() -> permissions.AuthContext:
            return self.context

        overrides = self.test_app.dependency_overrides
        overrides[permissions.get_current_user] = current_user
        overrides[graph._inject_graph] = lambda: self.graph
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.test_app),
            base_url='http://test',
        )

    async def _cleanup(self) -> None:
        await self.client.aclose()
        await self.graph.locked_with_connection(
            preferences.lock_key(self.email),
            lambda _execute, conn: preferences.delete_user(conn, self.email),
        )
        await self.graph.close()

    async def _put(
        self, value: dict[str, object], version: int
    ) -> httpx.Response:
        return await self.client.put(
            _URL, json={'value': value, 'version': version}
        )

    async def test_get_before_first_write_is_404(self) -> None:
        response = await self.client.get(_URL)
        self.assertEqual(response.status_code, 404)

    async def test_create_update_and_get(self) -> None:
        response = await self._put({'max_items': 10}, 0)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['version'], 1)
        self.assertEqual(body['value']['max_items'], 10)
        self.assertEqual(
            body['value']['order'], list(preferences.DEFAULT_ORDER)
        )

        response = await self._put(
            {'sections': {'my_tickets': {'display': 'collapsed'}}}, 1
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['version'], 2)

        response = await self.client.get(_URL)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['version'], 2)
        self.assertEqual(
            body['value']['sections'],
            {'my_tickets': {'display': 'collapsed'}},
        )
        self.assertEqual(body['value']['max_items'], 5)
        self.assertIn('updated_at', body)

    async def test_stale_version_is_409(self) -> None:
        self.assertEqual((await self._put({}, 0)).status_code, 200)
        self.assertEqual((await self._put({}, 0)).status_code, 409)
        self.assertEqual((await self._put({}, 1)).status_code, 200)
        self.assertEqual((await self._put({}, 1)).status_code, 409)

    async def test_update_without_row_is_409(self) -> None:
        self.assertEqual((await self._put({}, 3)).status_code, 409)

    async def test_order_is_normalized(self) -> None:
        response = await self._put(
            {'order': ['my_projects', 'needs_attention']}, 0
        )
        self.assertEqual(response.status_code, 200, response.text)
        expected = ['my_projects', 'needs_attention'] + [
            key
            for key in preferences.DEFAULT_ORDER
            if key not in ('my_projects', 'needs_attention')
        ]
        self.assertEqual(response.json()['value']['order'], expected)
        response = await self.client.get(_URL)
        self.assertEqual(response.json()['value']['order'], expected)

    async def test_invalid_values_are_422(self) -> None:
        for value in (
            {'sections': {'needs_attention': {'display': 'hidden'}}},
            {'order': ['my_tickets', 'my_tickets']},
            {'order': ['not_a_section']},
            {'max_items': 7},
        ):
            with self.subTest(value=value):
                response = await self._put(value, 0)
                self.assertEqual(response.status_code, 422)
        self.assertEqual((await self.client.get(_URL)).status_code, 404)

    async def test_unknown_namespace_is_422(self) -> None:
        response = await self.client.get('/users/me/preferences/other')
        self.assertEqual(response.status_code, 422)

    async def test_service_account_is_403(self) -> None:
        self.context.user = None
        self.assertEqual((await self.client.get(_URL)).status_code, 403)
        self.assertEqual((await self._put({}, 0)).status_code, 403)

    async def test_user_delete_removes_rows(self) -> None:
        self.assertEqual((await self._put({}, 0)).status_code, 200)
        await self.graph.execute(
            'CREATE (u:User {{email: {email}}}) RETURN u.email AS email',
            {'email': self.email},
            ['email'],
        )
        self.context.user = self.user.model_copy(
            update={'email': 'admin@example.com'}
        )
        response = await self.client.delete(f'/users/{self.email}')
        self.assertEqual(response.status_code, 204)
        self.context.user = self.user
        self.assertEqual((await self.client.get(_URL)).status_code, 404)
