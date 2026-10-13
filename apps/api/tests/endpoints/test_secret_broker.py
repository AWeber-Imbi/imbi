"""Tests for the secrets broker management endpoints (ADR 0022, P1).

These run against the live Postgres that ``root:services`` boots: the
graph for the organization and its member, and the ``secrets`` schema.
Each test makes its own organization.
"""

import datetime
import typing
import uuid
from unittest import mock

import httpx

from apps.api.tests import secret_support, support
from imbi.api import models, secret_broker
from imbi.api.auth import permissions
from imbi.api.secret_broker import audit
from imbi.common import graph

ALL_PERMISSIONS = frozenset(
    {
        'secret_provider:read',
        'secret_provider:write',
        'secret_binding:read',
        'secret_binding:write',
        'secret_grant:read',
        'secret_grant:write',
        'secret_resolution:read',
        'secret_resolution:manage',
        'secret_audit:read',
    }
)


class SecretEndpointTestCase(
    secret_support.SecretCase, support.SharedAppAsyncTestCase
):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.email = f'admin-{self.org}@example.com'
        await graph.initialize()
        self.graph = graph.Graph()
        await self.graph.open()
        await self.graph.execute(
            """
            CREATE (o:Organization {{id: {org}, slug: {org}, name: {org}}})
            CREATE (u:User {{id: {email}, email: {email},
                             display_name: 'Admin', is_active: true}})
            CREATE (u)-[:MEMBER_OF {{role: 'admin'}}]->(o)
            RETURN o.id AS id
            """,
            {'org': self.org, 'email': self.email},
            ['id'],
        )
        self.permissions = set(ALL_PERMISSIONS)
        user = models.User(
            id=self.email,
            email=self.email,
            display_name='Admin',
            is_active=True,
            is_admin=False,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        async def current_user() -> permissions.AuthContext:
            return permissions.AuthContext(
                user=user,
                session_id='test-session',
                auth_method='jwt',
                permissions=set(self.permissions),
            )

        overrides = self.test_app.dependency_overrides
        overrides[permissions.get_current_user] = current_user
        overrides[graph._inject_graph] = lambda: self.graph
        overrides[secret_broker._inject_store] = lambda: self.store
        overrides[secret_broker.get_broker] = lambda: self.broker
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.test_app),
            base_url='http://test',
        )
        self.base = f'/organizations/{self.org}'

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        await self.graph.execute(
            'MATCH (n) WHERE n.id IN {ids} DETACH DELETE n RETURN 1 AS ok',
            {'ids': [self.org, self.email]},
            ['ok'],
        )
        await self.graph.close()
        await super().asyncTearDown()

    async def _post(
        self, path: str, body: typing.Any = None
    ) -> httpx.Response:
        return await self.client.post(self.base + path, json=body)

    async def test_provider_crud(self) -> None:
        response = await self._post(
            '/secret-providers/',
            {
                'name': 'aws-prod',
                'type': 'aws_secrets_manager',
                'config': {
                    'region': 'us-east-1',
                    'role_arn': 'arn:aws:iam::123456789012:role/x',
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        provider = response.json()
        self.assertIn('static_retrieval', provider['capabilities'])
        self.assertNotIn('dynamic_issuance', provider['capabilities'])
        self.assertEqual(self.events[-1].type, 'secret_provider_created')
        self.assertEqual(self.events[-1].actor, self.email)

        response = await self._post(
            '/secret-providers/',
            {
                'name': 'aws-keys',
                'type': 'aws_secrets_manager',
                'config': {
                    'region': 'us-east-1',
                    'aws_secret_access_key': 'AKIA-should-not-echo',
                },
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('AKIA-should-not-echo', response.text)
        response = await self._post(
            '/secret-providers/', {'name': 'v', 'type': 'vault'}
        )
        self.assertEqual(response.status_code, 422)
        response = await self._post(
            '/secret-providers/', {'name': 'aws-prod', 'type': 'fake'}
        )
        self.assertEqual(response.status_code, 409)

        url = f'/secret-providers/{provider["id"]}'
        response = await self.client.patch(
            self.base + url, json={'enabled': False}
        )
        self.assertFalse(response.json()['enabled'])
        response = await self.client.get(self.base + '/secret-providers/')
        self.assertEqual(
            {p['name'] for p in response.json()}, {'fake', 'aws-prod'}
        )
        response = await self.client.get(self.base + '/secret-providers/types')
        self.assertEqual(
            {t['type'] for t in response.json()},
            {'fake', 'aws_secrets_manager'},
        )
        response = await self.client.delete(self.base + url)
        self.assertEqual(response.status_code, 204)

    async def test_provider_test(self) -> None:
        response = await self._post(
            f'/secret-providers/{self.provider["id"]}/test'
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'healthy')
        self.assertEqual(self.events[-1].type, 'secret_provider_tested')
        response = await self.client.get(
            self.base + f'/secret-providers/{self.provider["id"]}'
        )
        self.assertEqual(response.json()['health_status'], 'healthy')

    async def test_binding_rules(self) -> None:
        body: dict[str, typing.Any] = {
            'reference': 'secret://production/pg/app',
            'provider_id': str(self.provider['id']),
            'credential_class': 'rotated',
            'locator': {'key': 'json'},
            'allowed_fields': ['token'],
            'allowed_delivery_modes': ['stdin'],
        }
        response = await self._post('/secret-bindings/', body)
        self.assertEqual(response.status_code, 201, response.text)
        binding = response.json()
        response = await self._post('/secret-bindings/', body)
        self.assertEqual(response.status_code, 409)
        for change in (
            {'reference': 'secret://production/pg/app#token'},
            {'reference': 'secret://Production/pg'},
            {'locator': {'key': 'x', 'arn': 'y'}},
            {'provider_id': str(uuid.uuid4())},
            {'allowed_delivery_modes': ['argument']},
            {'max_ttl_seconds': 7200},
        ):
            with self.subTest(change=change):
                response = await self._post(
                    '/secret-bindings/',
                    body | {'reference': 'secret://a/b'} | change,
                )
                self.assertEqual(response.status_code, 422, response.text)
        response = await self._post(
            f'/secret-bindings/{binding["id"]}/validate'
        )
        self.assertEqual(
            response.json(),
            {'valid': True, 'reason': None, 'metadata': {'exists': True}},
        )
        response = await self.client.patch(
            self.base + f'/secret-bindings/{binding["id"]}',
            json={'max_ttl_seconds': 60},
        )
        self.assertEqual(response.json()['max_ttl_seconds'], 60)

    async def test_dynamic_binding_needs_the_capability(self) -> None:
        response = await self._post(
            '/secret-providers/',
            {
                'name': 'aws',
                'type': 'aws_secrets_manager',
                'config': {
                    'region': 'us-east-1',
                    'role_arn': 'arn:aws:iam::123456789012:role/x',
                },
            },
        )
        response = await self._post(
            '/secret-bindings/',
            {
                'reference': 'secret://production/x',
                'provider_id': response.json()['id'],
                'credential_class': 'dynamic',
                'locator': {'secret_id': 'x'},
                'allowed_delivery_modes': ['stdin'],
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn('dynamic_issuance', response.text)

    async def test_deletion_rules(self) -> None:
        response = await self.client.delete(
            self.base + f'/secret-providers/{self.provider["id"]}'
        )
        self.assertEqual(response.status_code, 409)
        binding_url = self.base + f'/secret-bindings/{self.binding["id"]}'
        response = await self.client.delete(binding_url)
        self.assertEqual(response.status_code, 409)
        self.assertIn('grant', response.text)
        created = await self.broker.create_resolution(
            self.context(), self.request()
        )
        response = await self.client.delete(
            self.base + f'/secret-grants/{self.grant["id"]}'
        )
        self.assertEqual(response.status_code, 204)
        response = await self.client.delete(binding_url)
        self.assertEqual(response.status_code, 409)
        self.assertIn('active resolution', response.text)
        await self.broker.release(
            created.resolution_id, reason='done', actor='test'
        )
        response = await self.client.delete(binding_url)
        self.assertEqual(response.status_code, 204)
        response = await self.client.delete(
            self.base + f'/secret-providers/{self.provider["id"]}'
        )
        self.assertEqual(response.status_code, 204)

    async def test_grants_and_evaluate(self) -> None:
        body = {
            'agent_ids': ['agent-x'],
            'binding_ids': [str(uuid.uuid4())],
            'purposes': ['checkout'],
            'delivery_modes': ['stdin'],
        }
        response = await self._post('/secret-grants/', body)
        self.assertEqual(response.status_code, 422)
        response = await self._post(
            '/secret-grants/',
            body | {'binding_ids': [str(self.binding['id'])]},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['project_ids'], [])

        request = {
            'agent_id': self.agent,
            'project_id': self.project,
            'reference': 'secret://production/github/token',
            'purpose': 'github_write',
            'delivery_mode': 'environment',
            'delivery_target': 'GH_TOKEN',
        }
        response = await self._post('/secret-grants/evaluate', request)
        self.assertEqual(
            response.json(),
            {
                'allowed': True,
                'error': None,
                'reason': None,
                'grant_id': str(self.grant['id']),
                'binding_id': str(self.binding['id']),
            },
        )
        response = await self._post(
            '/secret-grants/evaluate', request | {'agent_id': 'nobody'}
        )
        self.assertEqual(
            (response.json()['allowed'], response.json()['error']),
            (False, 'secret_access_denied'),
        )
        response = await self._post(
            '/secret-grants/evaluate', request | {'reference': 'bad'}
        )
        self.assertEqual(response.json()['error'], 'invalid_secret_reference')

    async def test_resolutions_never_show_handles_or_lease_ids(self) -> None:
        await self.store.update(
            'bindings',
            self.org,
            self.binding['id'],
            {'credential_class': 'dynamic'},
        )
        created = await self.broker.create_resolution(
            self.context(), self.request()
        )
        await self.broker.materialize(
            self.executor(), self.materialize_request(created.handle)
        )
        row = await self.broker.get(created.resolution_id)
        assert row is not None
        responses = [
            await self.client.get(self.base + '/secret-resolutions/'),
            await self.client.get(
                self.base + f'/secret-resolutions/{created.resolution_id}'
            ),
            await self.client.get(
                self.base + '/secret-resolutions/',
                params={'state': 'active', 'task_id': str(self.task_id)},
            ),
        ]
        for response in responses:
            self.assertEqual(response.status_code, 200, response.text)
            for value in (
                created.handle,
                row['lease_id'],
                secret_support.MATERIAL,
            ):
                self.assertNotIn(value, response.text)
            for key in ('handle', 'handle_hash', 'lease_id'):
                self.assertNotIn(f'"{key}"', response.text)
        detail = responses[1].json()
        self.assertEqual(detail['materialization_count'], 1)
        self.assertEqual(
            detail['provider_lease'],
            {
                'present': True,
                'revocation_state': 'pending',
                'revocation_reason': None,
                'revocation_attempted_at': None,
            },
        )

        url = self.base + f'/secret-resolutions/{created.resolution_id}'
        response = await self.client.post(url + '/release')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['state'], 'released')
        self.assertEqual(
            response.json()['provider_lease']['revocation_state'], 'succeeded'
        )
        self.assertEqual(
            response.json()['release_reason'], 'released_by_operator'
        )
        response = await self.client.post(url + '/revoke-provider-lease')
        self.assertEqual(response.status_code, 200)

        static = await self.broker.create_resolution(
            self.context(), self.request()
        )
        await self.store.update(
            'bindings',
            self.org,
            self.binding['id'],
            {'credential_class': 'static'},
        )
        response = await self.client.post(
            self.base
            + f'/secret-resolutions/{static.resolution_id}'
            + '/revoke-provider-lease'
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['detail']['error'], 'provider_lease_not_revocable'
        )
        response = await self.client.post(
            self.base + f'/secret-resolutions/{uuid.uuid4()}/release'
        )
        self.assertEqual(response.status_code, 404)

    async def test_other_organizations_are_invisible(self) -> None:
        other_org = f'other-{uuid.uuid4().hex[:8]}'
        row = await self.store.create(
            'providers',
            other_org,
            {'name': 'x', 'type': 'fake', 'created_by': 'test'},
        )
        try:
            response = await self.client.get(
                self.base + f'/secret-providers/{row["id"]}'
            )
            self.assertEqual(response.status_code, 404)
            response = await self.client.delete(
                self.base + f'/secret-providers/{row["id"]}'
            )
            self.assertEqual(response.status_code, 404)
        finally:
            await self.store.delete('providers', other_org, row['id'])

    async def test_permissions(self) -> None:
        self.permissions = {'secret_provider:read'}
        checks = [
            ('get', '/secret-providers/'),
            ('post', '/secret-providers/'),
            ('get', '/secret-bindings/'),
            ('get', '/secret-grants/'),
            ('post', '/secret-grants/evaluate'),
            ('get', '/secret-resolutions/'),
            ('post', f'/secret-resolutions/{uuid.uuid4()}/release'),
            ('get', '/secret-audit-events/'),
        ]
        expected = [200, 403, 403, 403, 403, 403, 403, 403]
        found = [
            (
                await self.client.request(
                    method,
                    self.base + path,
                    json={'name': 'x', 'type': 'fake'}
                    if method == 'post'
                    else None,
                )
            ).status_code
            for method, path in checks
        ]
        self.assertEqual(found, expected)

    async def test_non_member_is_refused(self) -> None:
        await self.graph.execute(
            'MATCH (u:User {{email: {email}}})-[m:MEMBER_OF]->()'
            ' DELETE m RETURN 1 AS ok',
            {'email': self.email},
            ['ok'],
        )
        response = await self.client.get(self.base + '/secret-providers/')
        self.assertEqual(response.status_code, 403)

    async def test_audit_events(self) -> None:
        event = audit.Event(
            organization_id=self.org, type='secret_materialized'
        )
        with mock.patch.object(
            audit.clickhouse,
            'query',
            mock.AsyncMock(return_value=[event.model_dump()]),
        ) as query:
            response = await self.client.get(
                self.base + '/secret-audit-events/',
                params={'type': 'secret_materialized', 'limit': 5},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()[0]['event_id'], event.event_id)
        params = query.call_args.args[1]
        self.assertEqual(params['organization_id'], self.org)
        self.assertEqual(params['type'], 'secret_materialized')
        self.assertEqual(params['limit'], 5)
        with mock.patch.object(
            audit.clickhouse, 'query', mock.AsyncMock(side_effect=OSError)
        ):
            response = await self.client.get(
                self.base + '/secret-audit-events/'
            )
        self.assertEqual(response.status_code, 503)
