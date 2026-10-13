"""Tests for the runtime secret routes and the secret fencer (ADR 0022).

These run against the live Postgres that ``root:services`` boots, with
the fake provider. The runner holds the chain of ``T-1``; the grant
lets its agent use ``secret://production/github/token``.
"""

import typing
import uuid
from unittest import mock

from apps.api.tests.endpoints import test_harness
from apps.api.tests.secret_support import MATERIAL
from imbi.api import secret_broker
from imbi.api.agent_tasks import store as task_store
from imbi.api.harness import sweeper
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
