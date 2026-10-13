"""Tests for the runtime secret routes and the secret fencer (ADR 0022).

These run against the live Postgres that ``root:services`` boots, with
the fake provider. The runner holds the chain of ``T-1``; the grant
lets its agent use ``secret://production/github/token``.
"""

import logging
import typing
import uuid
from unittest import mock

import httpx

from apps.api.tests.endpoints import test_harness
from apps.api.tests.secret_support import MATERIAL
from imbi.api import secret_broker
from imbi.api.agent_tasks import store as task_store
from imbi.api.auth import permissions
from imbi.api.endpoints import harness as harness_api
from imbi.api.harness import auth as harness_auth
from imbi.api.harness import sweeper, tokens
from imbi.api.secret_broker import broker, providers, store

REFERENCE = 'secret://production/github/token'


class SecretRunnerTestCase(test_harness.RunnerTestCase):
    """Fixtures: a claimed chain, a fake provider, a binding, a grant."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await secret_broker.initialize()
        self.broker = broker.Broker(self.pool)
        self.secrets = store.SecretStore(self.pool)
        self.test_app.dependency_overrides[secret_broker.get_broker] = (
            lambda: self.broker
        )
        self.addAsyncCleanup(self._cleanup_secrets)
        # The app lifespan registers these; the tests have no lifespan.
        task_store.register_close_hook(self.broker.release_task_resolutions)
        self.addCleanup(
            task_store.unregister_close_hook,
            self.broker.release_task_resolutions,
        )
        patcher = mock.patch.object(broker.log, 'publish', mock.AsyncMock())
        patcher.start()
        self.addCleanup(patcher.stop)

        fake = providers.PROVIDERS['fake']
        assert isinstance(fake, providers.FakeProvider)
        self.fake = fake
        fake.values = {'plain': MATERIAL.encode()}
        fake.leases = set()
        fake.revoked = []
        fake.fail_revoke = False
        fake.unavailable = False
        provider = await self.secrets.create(
            'providers',
            self.org,
            {
                'name': 'fake',
                'type': 'fake',
                'config': {},
                'capabilities': sorted(fake.capabilities),
                'created_by': 'test',
            },
        )
        self.binding = await self.secrets.create(
            'bindings',
            self.org,
            {
                'reference': REFERENCE,
                'provider_id': provider['id'],
                # Dynamic: the fake provider issues a lease to revoke.
                'credential_class': 'dynamic',
                'locator': {'key': 'plain'},
                'allowed_delivery_modes': ['environment'],
                'max_ttl_seconds': 900,
                'created_by': 'test',
            },
        )
        await self.secrets.create(
            'grants',
            self.org,
            {
                'agent_ids': [self.agent_id],
                'binding_ids': [self.binding['id']],
                'purposes': ['github_write'],
                'delivery_modes': ['environment'],
                'max_ttl_seconds': 900,
                'created_by': 'test',
            },
        )
        self.runner = await self.register()
        claim = await self.claim(self.runner)
        assert claim is not None
        self.token: str = claim['agent_token']
        self.chain_id: str = claim['chain_id']

    async def _cleanup_secrets(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                'DELETE FROM secrets.audit_outbox'
                " WHERE event->>'organization_id' = %s",
                (self.org,),
            )
            for table in ('resolutions', 'grants', 'bindings', 'providers'):
                await conn.execute(
                    f'DELETE FROM secrets.{table} WHERE organization_id = %s',
                    (self.org,),
                )

    def context(self, **changes: typing.Any) -> broker.ResolutionContext:
        values: dict[str, typing.Any] = {
            'organization_id': self.org,
            'agent_id': self.agent_id,
            'project_id': None,
            'task_id': uuid.UUID(self.task['id']),
            'runner_id': self.runner['runner_id'],
        } | changes
        return broker.ResolutionContext(**values)

    async def resolve(self) -> broker.Created:
        """Create a resolution for ``T-1`` through the broker."""
        return await self.broker.create_resolution(
            self.context(),
            broker.ResolutionRequest(
                reference=REFERENCE,
                purpose='github_write',
                ttl_seconds=300,
                delivery_mode='environment',
                delivery_target='GH_TOKEN',
            ),
        )

    async def materialize(self, created: broker.Created) -> None:
        await self.broker.materialize(
            broker.ExecutorContext(self.runner['runner_id']),
            broker.MaterializeRequest(
                handle=created.handle,
                nonce=uuid.uuid4().hex,
                task_id=uuid.UUID(self.task['id']),
                agent_id=self.agent_id,
                project_id=None,
                purpose='github_write',
            ),
        )

    async def resolution(self, created: broker.Created) -> store.Row:
        row = await self.broker.get(created.resolution_id)
        assert row is not None
        return row


class FencerTests(SecretRunnerTestCase):
    async def test_chain_requeues_only_after_release(self) -> None:
        sweeper.register_fencer(self.broker.release_runner_resolutions)
        self.addCleanup(
            sweeper.unregister_fencer, self.broker.release_runner_resolutions
        )
        created = await self.resolve()
        await self.materialize(created)
        self.assertEqual(
            (await self.resolution(created))['revocation_state'], 'pending'
        )
        # The provider cannot revoke the lease yet.
        self.fake.fail_revoke = True
        await self.expire(self.runner)
        await sweeper.sweep_once(self.harness)
        await self.end_grace(self.chain_id)
        await sweeper.sweep_once(self.harness)
        chain = await self.harness.chain(uuid.UUID(self.chain_id))
        assert chain is not None
        self.assertEqual(chain['state'], 'stuck')
        row = await self.resolution(created)
        self.assertEqual(
            (row['state'], row['revocation_state']), ('released', 'failed')
        )
        self.assertNotIn(
            'attempt_marker', [e['type'] for e in await self.events()]
        )
        # The revocation works now: the chain goes back to the queue.
        self.fake.fail_revoke = False
        await sweeper.sweep_once(self.harness)
        chain = await self.harness.chain(uuid.UUID(self.chain_id))
        assert chain is not None
        self.assertEqual(chain['state'], 'queued')
        self.assertEqual(
            (await self.resolution(created))['revocation_state'], 'succeeded'
        )
        self.assertEqual(self.fake.leases, set())


class CloseTests(SecretRunnerTestCase):
    async def test_close_releases_at_once(self) -> None:
        created = await self.resolve()
        await self.materialize(created)
        response = await self.as_agent(
            self.token, 'POST', 'T-1/outcome', {'outcome': 'done_acted'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        # No sweep ran: the close hook released it and revoked the lease.
        row = await self.resolution(created)
        self.assertEqual(
            (row['state'], row['release_reason'], row['revocation_state']),
            ('released', 'task_closed', 'succeeded'),
        )
        self.assertEqual(self.fake.leases, set())
        events = [
            e for e in await self.events() if e['type'] == 'secret.resolution'
        ]
        self.assertEqual(
            [e['payload']['action'] for e in events],
            ['created', 'materialized', 'released'],
        )

    async def test_failing_hook_does_not_fail_the_close(self) -> None:
        created = await self.resolve()
        with mock.patch.object(
            broker, '_release_events', side_effect=RuntimeError('down')
        ):
            response = await self.as_agent(
                self.token, 'POST', 'T-1/outcome', {'outcome': 'done_acted'}
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.task_row())['status'], 'closed')
        self.assertEqual((await self.resolution(created))['state'], 'active')
        # The sweep releases what the hook left open.
        await self.broker.sweep()
        self.assertEqual((await self.resolution(created))['state'], 'released')


class RouteTests(SecretRunnerTestCase):
    async def create(
        self,
        token: str | None = None,
        short_id: str = 'T-1',
        headers: dict[str, str] | None = None,
        **body: typing.Any,
    ) -> httpx.Response:
        payload: dict[str, typing.Any] = {
            'short_id': short_id,
            'reference': REFERENCE,
            'purpose': 'github_write',
            'ttl_seconds': 300,
            'delivery': {'mode': 'environment', 'target': 'GH_TOKEN'},
        } | body
        return await self.client.post(
            '/harness/secret-resolutions',
            json=payload,
            headers={'Authorization': f'Bearer {token or self.token}'}
            | (headers or {}),
        )

    async def created(self, **kwargs: typing.Any) -> dict[str, typing.Any]:
        response = await self.create(**kwargs)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def materialize_route(
        self,
        handle: str,
        credential: str | None = None,
        **changes: typing.Any,
    ) -> httpx.Response:
        payload: dict[str, typing.Any] = {
            'handle': handle,
            'nonce': uuid.uuid4().hex,
            'task_id': self.task['id'],
            'agent_id': self.agent_id,
            'project_id': None,
            'purpose': 'github_write',
        } | changes
        return await self.client.post(
            '/harness/executor/secret-materializations',
            json=payload,
            headers={
                'Authorization': 'Bearer '
                + (credential or self.runner['executor_token'])
            },
        )

    async def release_route(
        self, resolution_id: str, credential: str | None = None
    ) -> httpx.Response:
        return await self.client.post(
            f'/harness/executor/secret-resolutions/{resolution_id}/release',
            headers={
                'Authorization': 'Bearer '
                + (credential or self.runner['executor_token'])
            },
        )

    def assert_no_store(self, response: httpx.Response) -> None:
        for name, value in broker.NO_STORE_HEADERS.items():
            self.assertEqual(response.headers.get(name), value)

    async def test_create_materialize_release(self) -> None:
        # Context in the body is ignored: it comes from the token.
        response = await self.create(
            organization_id=self.other_org,
            agent_id='someone-else',
            runner_id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assert_no_store(response)
        created = response.json()
        self.assertTrue(created['handle'].startswith('imh_'))
        self.assertEqual(
            created['delivery'], {'mode': 'environment', 'target': 'GH_TOKEN'}
        )
        row = await self.broker.get(uuid.UUID(created['resolution_id']))
        assert row is not None
        self.assertEqual(
            (
                row['organization_id'],
                row['agent_id'],
                str(row['task_id']),
                row['runner_id'],
            ),
            (
                self.org,
                self.agent_id,
                self.task['id'],
                self.runner['runner_id'],
            ),
        )

        response = await self.materialize_route(created['handle'])
        self.assertEqual(response.status_code, 200, response.text)
        self.assert_no_store(response)
        body = response.json()
        self.assertEqual(
            (body['encoding'], body['material']), ('utf8', MATERIAL)
        )
        self.assertEqual(body['resolution_id'], created['resolution_id'])

        response = await self.release_route(created['resolution_id'])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                'resolution_id': created['resolution_id'],
                'state': 'released',
                'revocation_state': 'succeeded',
            },
        )
        # Idempotent.
        response = await self.release_route(created['resolution_id'])
        self.assertEqual(response.status_code, 200, response.text)

    async def test_idempotency_key_rotates_the_handle(self) -> None:
        key = {'Idempotency-Key': 'checkout-1'}
        first = await self.created(headers=key)
        second = await self.created(headers=key)
        self.assertEqual(first['resolution_id'], second['resolution_id'])
        self.assertNotEqual(first['handle'], second['handle'])
        response = await self.materialize_route(first['handle'])
        self.assertEqual(response.status_code, 404, response.text)
        response = await self.materialize_route(second['handle'])
        self.assertEqual(response.status_code, 200, response.text)

    async def test_denial_uses_the_error_envelope(self) -> None:
        response = await self.create(purpose='deploy')
        self.assertEqual(response.status_code, 403, response.text)
        self.assert_no_store(response)
        self.assertEqual(
            response.json()['detail']['error'], 'secret_access_denied'
        )

    async def test_agent_token_cannot_materialize_or_release(self) -> None:
        created = await self.created()
        for credential in (self.token, self.runner['runner_token']):
            response = await self.materialize_route(
                created['handle'], credential
            )
            self.assertEqual(response.status_code, 401, response.text)
            self.assertEqual(
                response.json()['detail']['error'],
                'invalid_executor_credential',
            )
            response = await self.release_route(
                created['resolution_id'], credential
            )
            self.assertEqual(response.status_code, 401, response.text)
        # The handle is still unused.
        response = await self.materialize_route(created['handle'])
        self.assertEqual(response.status_code, 200, response.text)

    async def test_executor_credential_cannot_manage_policy(self) -> None:
        overrides = self.test_app.dependency_overrides
        del overrides[permissions.get_current_user]
        del overrides[harness_auth.harness_caller]
        created = await self.created()
        auth = {'Authorization': f'Bearer {self.runner["executor_token"]}'}
        base = f'/organizations/{self.org}'
        for method, path, body in (
            ('GET', f'{base}/secret-providers/', None),
            ('GET', f'{base}/secret-bindings/', None),
            (
                'PATCH',
                f'{base}/secret-bindings/{self.binding["id"]}',
                {'enabled': False},
            ),
            ('GET', f'{base}/secret-grants/', None),
            ('GET', f'{base}/secret-resolutions/', None),
            (
                'POST',
                f'{base}/secret-resolutions/{created["resolution_id"]}'
                '/release',
                None,
            ),
            ('POST', '/harness/secret-resolutions', {}),
        ):
            with self.subTest(method=method, path=path):
                response = await self.client.request(
                    method, path, json=body, headers=auth
                )
                self.assertEqual(response.status_code, 401, response.text)
        row = await self.broker.get(uuid.UUID(created['resolution_id']))
        assert row is not None
        self.assertEqual(row['state'], 'active')

    async def test_another_chain_is_refused(self) -> None:
        self.act_as_user()
        await self.create_task()
        self.act_as(self.account)
        other_runner = await self.register()
        other = await self.claim(other_runner)
        assert other is not None
        self.assertEqual(other['task']['short_id'], 'T-2')
        response = await self.create(short_id='T-2')
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()['detail']['error'], 'chain_forbidden')
        # A resolution of the other runner: this executor cannot use it.
        theirs = await self.created(token=other['agent_token'], short_id='T-2')
        response = await self.materialize_route(
            theirs['handle'], task_id=other['task']['id']
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'resolution_context_mismatch'
        )
        response = await self.release_route(theirs['resolution_id'])
        self.assertEqual(response.status_code, 404, response.text)
        # The handle still works for its own executor.
        response = await self.materialize_route(
            theirs['handle'],
            other_runner['executor_token'],
            task_id=other['task']['id'],
        )
        self.assertEqual(response.status_code, 200, response.text)

    async def test_another_organization_is_refused(self) -> None:
        # A token of this chain attempt, but for another organization.
        forged, _ = tokens.mint_agent_token(
            self.account.slug,
            tokens.AgentGrant(
                chain_id=uuid.UUID(self.chain_id),
                attempt=1,
                runner_id=uuid.UUID(self.runner['runner_id']),
                organization_id=self.other_org,
            ),
        )
        response = await self.create(token=forged)
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json()['detail']['error'], 'stale_attempt')

    async def test_another_agent_is_refused(self) -> None:
        helper_id = await self.make_agent('helper', name='Helper')
        await self.make_version({'subagents': [{'agent_id': helper_id}]})
        response = await self.client.post(
            '/harness/tasks/T-1/children',
            json={
                'agent_slug': 'helper',
                'title': 'Help',
                'description': 'Help out.',
            },
            headers={'Authorization': f'Bearer {self.token}'},
        )
        self.assertEqual(response.status_code, 201, response.text)
        child = response.json()
        response = await self.create(short_id=child['short_id'])
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail']['error'], 'agent_task_forbidden'
        )
        # The executor must name the context of the resolution.
        created = await self.created()
        for changes in (
            {'agent_id': helper_id},
            {'task_id': child['id']},
            {'purpose': 'deploy'},
        ):
            with self.subTest(changes=changes):
                response = await self.materialize_route(
                    created['handle'], **changes
                )
                self.assertEqual(response.status_code, 403, response.text)

    async def test_stale_attempt_is_refused(self) -> None:
        created = await self.created()
        await self.expire(self.runner)
        await sweeper.sweep_once(self.harness)
        response = await self.create()
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json()['detail']['error'], 'stale_attempt')
        # The executor credential of a fenced runner stops at once.
        response = await self.materialize_route(created['handle'])
        self.assertEqual(response.status_code, 401, response.text)
        response = await self.release_route(created['resolution_id'])
        self.assertEqual(response.status_code, 401, response.text)

    async def test_materialize_logs_no_material(self) -> None:
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger('imbi').debug('capture start')
            created = await self.created()
            nonce = uuid.uuid4().hex
            ok = await self.materialize_route(created['handle'], nonce=nonce)
            replay = await self.materialize_route(
                created['handle'], nonce=nonce
            )
            unknown = await self.materialize_route('imh_' + 'x' * 43)
            self.fake.unavailable = True
            failing = await self.created()
            unavailable = await self.materialize_route(failing['handle'])
            self.fake.unavailable = False
            crashing = await self.created()
            with mock.patch.object(
                self.fake,
                'resolve',
                side_effect=RuntimeError(f'boom {MATERIAL}'),
            ):
                crashed = await self.materialize_route(crashing['handle'])
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()['material'], MATERIAL)
        secrets = (
            MATERIAL,
            nonce,
            created['handle'],
            failing['handle'],
            crashing['handle'],
        )
        for response, status in (
            (replay, 409),
            (unknown, 404),
            (unavailable, 503),
            (crashed, 502),
        ):
            with self.subTest(status=status):
                self.assertEqual(response.status_code, status, response.text)
                self.assert_no_store(response)
                for value in secrets:
                    self.assertNotIn(value, response.text)
        text = '\n'.join(logs.output)
        for value in secrets:
            self.assertNotIn(value, text)
        # The request model keeps the handle and nonce out of its repr.
        model = harness_api.SecretMaterializationCreate(
            handle=created['handle'],
            nonce=nonce,
            task_id=uuid.UUID(self.task['id']),
            agent_id=self.agent_id,
            purpose='github_write',
        )
        for value in (created['handle'], nonce):
            self.assertNotIn(value, repr(model))
            self.assertNotIn(value, str(model.model_dump()))
