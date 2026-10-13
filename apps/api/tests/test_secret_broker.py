"""Tests for the secrets broker resolution service (ADR 0022, P1).

These run against the live Postgres that ``root:services`` boots, with
the fake provider and captured audit events.
"""

import asyncio
import base64
import logging
import pickle
import unittest
import uuid
from unittest import mock

import orjson

from apps.api.tests import secret_support
from apps.api.tests.secret_support import MATERIAL
from imbi.api.secret_broker import broker, providers, store
from imbi.common.auth import encryption


class ReferenceTestCase(unittest.TestCase):
    def test_parse(self) -> None:
        ref = broker.parse_reference('secret://production/github/token')
        self.assertEqual(
            (ref.scope, ref.path, ref.field),
            ('production', 'github/token', None),
        )
        ref = broker.parse_reference('secret://staging/pg/app_1#Pass-word')
        self.assertEqual(ref.field, 'Pass-word')
        self.assertEqual(ref.binding, 'secret://staging/pg/app_1')
        self.assertEqual(str(ref), 'secret://staging/pg/app_1#Pass-word')

    def test_only_canonical_form(self) -> None:
        for value in (
            'secret://Production/github/token',
            'secret://production/github/token/',
            'secret://production//token',
            'secret://production/github/../token',
            'secret://production/git hub',
            'secret://production/github/token?x=1',
            'secret://production/github%2Ftoken',
            'secret://production/github/token\n',
            'secret://production',
            'secret:/production/github',
            'SECRET://production/github',
            'secret://production/github#',
            'secret://production/github#a#b',
            'secret://production/' + 'a' * 600,
            ' secret://production/github',
        ):
            with self.subTest(value=value):
                with self.assertRaises(providers.BrokerError) as ctx:
                    broker.parse_reference(value)
                self.assertEqual(
                    ctx.exception.code, 'invalid_secret_reference'
                )

    def test_binding_reference_has_no_field(self) -> None:
        with self.assertRaises(providers.BrokerError):
            broker.parse_reference('secret://a/b#c', field=False)

    def test_delivery_targets(self) -> None:
        good = [
            ('environment', 'GH_TOKEN', 'GH_TOKEN'),
            ('file', 'token.txt', 'token.txt'),
            ('file_descriptor', '3', '3'),
            ('stdin', None, None),
            ('stdin', '', None),
        ]
        for mode, target, expected in good:
            with self.subTest(mode=mode, target=target):
                self.assertEqual(broker.check_delivery(mode, target), expected)
        bad = [
            ('environment', 'PATH'),
            ('environment', 'LD_PRELOAD'),
            ('environment', 'DYLD_INSERT_LIBRARIES'),
            ('environment', 'HTTPS_PROXY'),
            ('environment', 'NO_PROXY'),
            ('environment', 'GIT_SSH_COMMAND'),
            ('environment', 'GIT_CONFIG_GLOBAL'),
            ('environment', 'PYTHONHOME'),
            ('environment', 'NODE_EXTRA_CA_CERTS'),
            ('environment', 'JAVA_TOOL_OPTIONS'),
            ('environment', 'JDK_JAVA_OPTIONS'),
            ('environment', 'BASH_FUNC_X'),
            ('environment', 'GCONV_PATH'),
            ('environment', 'SSL_CERT_FILE'),
            ('environment', 'REQUESTS_CA_BUNDLE'),
            ('environment', 'CURL_CA_BUNDLE'),
            ('environment', '_LEADING'),
            ('environment', '_JAVA_OPTIONS'),
            ('environment', 'SSH_ASKPASS'),
            ('environment', 'SSH_AUTH_SOCK'),
            ('environment', 'GIT_ASKPASS'),
            ('environment', 'EDITOR'),
            ('environment', 'VISUAL'),
            ('environment', 'PAGER'),
            ('environment', 'PERL5LIB'),
            ('environment', 'RUBYLIB'),
            ('environment', 'PYTHONWARNINGS'),
            ('environment', 'gh_token'),
            ('environment', None),
            ('file', '../token'),
            ('file', '/etc/passwd'),
            ('file', '.hidden'),
            ('file_descriptor', '2'),
            ('file_descriptor', '256'),
            ('file_descriptor', '٣'),
            ('stdin', 'X'),
            ('argument', 'X'),
        ]
        for mode, target in bad:
            with self.subTest(mode=mode, target=target):
                with self.assertRaises(providers.BrokerError) as ctx:
                    broker.check_delivery(mode, target)
                self.assertEqual(
                    ctx.exception.code, 'delivery_mode_not_allowed'
                )

    def test_sensitive_types_have_no_readable_repr(self) -> None:
        material = providers.Material(MATERIAL.encode(), lease_id='lease')
        self.assertNotIn(MATERIAL, repr(material))
        self.assertNotIn(MATERIAL, str(material))
        self.assertNotIn('lease', repr(material))
        with self.assertRaises(TypeError):
            pickle.dumps(material)
        created = broker.Created(
            uuid.uuid4(),
            'imh_secret',
            'active',
            mock.sentinel.at,  # pyright: ignore[reportArgumentType]
            'stdin',
            None,
        )
        self.assertNotIn('imh_secret', repr(created))
        request = broker.MaterializeRequest(
            'imh_secret', 'nonce-x', uuid.uuid4(), 'a', None, 'p'
        )
        self.assertNotIn('imh_secret', repr(request))
        self.assertNotIn('nonce-x', repr(request))


class CreateResolutionTestCase(secret_support.SecretCase):
    async def _denied(
        self,
        code: str,
        context: broker.ResolutionContext | None = None,
        request: broker.ResolutionRequest | None = None,
    ) -> providers.BrokerError:
        with self.assertRaises(providers.BrokerError) as ctx:
            await self.broker.create_resolution(
                context or self.context(), request or self.request()
            )
        self.assertEqual(ctx.exception.code, code, ctx.exception.reason)
        self.assertEqual(self.events[-1].type, 'secret_resolution_denied')
        self.assertEqual(self.events[-1].result, 'denied')
        return ctx.exception

    async def test_allowed(self) -> None:
        created = await self.broker.create_resolution(
            self.context(), self.request()
        )
        self.assertTrue(created.handle.startswith('imh_'))
        # 32 random bytes, URL-safe base64 without padding.
        self.assertEqual(len(created.handle), 4 + 43)
        self.assertEqual(created.state, 'active')
        row = await self.broker.get(created.resolution_id)
        assert row is not None
        self.assertEqual(row['grant_id'], self.grant['id'])
        self.assertEqual(row['runner_id'], self.runner)
        self.assertNotEqual(row['handle_hash'], created.handle.encode())
        self.assertEqual(len(row['handle_hash']), 32)
        self.assertEqual(self.events[-1].type, 'secret_resolution_allowed')

    async def test_missing_context_is_denied(self) -> None:
        for change in ({'agent_id': ''}, {'runner_id': ''}):
            with self.subTest(change=change):
                error = await self._denied(
                    'secret_access_denied', self.context(**change)
                )
                self.assertEqual(error.reason, 'missing_context')

    async def test_context_must_match_task(self) -> None:
        for change in (
            {'agent_id': 'other-agent'},
            {'project_id': 'other-project'},
            {'project_id': None},
            {'organization_id': 'other-org'},
            {'task_id': uuid.uuid4()},
        ):
            with self.subTest(change=change):
                await self._denied(
                    'resolution_context_mismatch', self.context(**change)
                )

    async def test_closed_task_is_denied(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_runtime.tasks SET status = 'closed'"
                ' WHERE id = %s',
                (self.task_id,),
            )
        await self._denied('secret_access_denied')

    async def test_exact_grant_match(self) -> None:
        other_agent_task = await self.add_task(agent='agent-other')
        await self._denied(
            'secret_access_denied',
            self.context(agent_id='agent-other', task_id=other_agent_task),
        )
        no_project_task = await self.add_task(project=None)
        await self._denied(
            'secret_access_denied',
            self.context(project_id=None, task_id=no_project_task),
        )
        await self._denied(
            'secret_access_denied', request=self.request(purpose='deploy')
        )
        # A grant without project ids allows a task without a project.
        await self.add_grant(
            [self.binding['id']], agent_ids=['agent-other'], project_ids=[]
        )
        await self.broker.create_resolution(
            self.context(agent_id='agent-other', task_id=other_agent_task),
            self.request(),
        )

    async def test_two_grants_are_ambiguous(self) -> None:
        await self.add_grant([self.binding['id']])
        error = await self._denied('secret_access_denied')
        self.assertEqual(error.reason, 'ambiguous_grants')

    async def test_unknown_reference_and_bad_syntax(self) -> None:
        await self._denied(
            'secret_binding_not_found',
            request=self.request(reference='secret://production/nothing'),
        )
        await self._denied(
            'invalid_secret_reference',
            request=self.request(reference='secret://Production/x'),
        )
        await self._denied(
            'secret_access_denied', request=self.request(purpose='Bad')
        )

    async def test_field_allowlist(self) -> None:
        binding = await self.add_binding(
            reference='secret://production/github/app',
            locator={'key': 'json'},
            allowed_fields=['token'],
        )
        await self.store.update(
            'grants',
            self.org,
            self.grant['id'],
            {'binding_ids': [self.binding['id'], binding['id']]},
        )
        await self._denied(
            'secret_field_not_allowed',
            request=self.request(reference='secret://production/github/app'),
        )
        await self._denied(
            'secret_field_not_allowed',
            request=self.request(
                reference='secret://production/github/app#user'
            ),
        )
        await self._denied(
            'secret_field_not_allowed',
            request=self.request(
                reference='secret://production/github/token#token'
            ),
        )
        created = await self.broker.create_resolution(
            self.context(),
            self.request(reference='secret://production/github/app#token'),
        )
        result = await self.broker.materialize(
            self.executor(), self.materialize_request(created.handle)
        )
        self.assertEqual(result.material, MATERIAL)

    async def test_binding_pins_delivery_targets(self) -> None:
        await self.store.update(
            'bindings',
            self.org,
            self.binding['id'],
            {'allowed_delivery_targets': ['GITHUB_TOKEN']},
        )
        error = await self._denied('delivery_mode_not_allowed')
        self.assertEqual(error.reason, 'target_not_allowed')
        created = await self.broker.create_resolution(
            self.context(), self.request(delivery_target='GITHUB_TOKEN')
        )
        # stdin has no target, so the list does not apply to it.
        await self.broker.create_resolution(
            self.context(),
            self.request(delivery_mode='stdin', delivery_target=None),
        )
        # A list changed after create invalidates the unused handle.
        await self.store.update(
            'bindings',
            self.org,
            self.binding['id'],
            {'allowed_delivery_targets': ['OTHER']},
        )
        with self.assertRaises(providers.BrokerError):
            await self.broker.materialize(
                self.executor(), self.materialize_request(created.handle)
            )
        # The denylist applies even to a pinned name.
        await self.store.update(
            'bindings',
            self.org,
            self.binding['id'],
            {'allowed_delivery_targets': ['LD_PRELOAD']},
        )
        await self._denied(
            'delivery_mode_not_allowed',
            request=self.request(delivery_target='LD_PRELOAD'),
        )

    async def test_delivery_mode_and_ttl_limits(self) -> None:
        await self._denied(
            'delivery_mode_not_allowed',
            request=self.request(delivery_mode='file', delivery_target='t'),
        )
        await self._denied(
            'delivery_mode_not_allowed',
            request=self.request(delivery_target='PATH'),
        )
        await self.store.update(
            'grants', self.org, self.grant['id'], {'max_ttl_seconds': 60}
        )
        await self._denied(
            'requested_ttl_too_large', request=self.request(ttl_seconds=61)
        )
        await self._denied(
            'requested_ttl_too_large', request=self.request(ttl_seconds=901)
        )
        await self._denied(
            'requested_ttl_too_large', request=self.request(ttl_seconds=0)
        )
        await self.store.update(
            'grants',
            self.org,
            self.grant['id'],
            {'delivery_modes': ['stdin']},
        )
        await self._denied('secret_access_denied')

    async def test_provider_of_another_organization(self) -> None:
        other_org = f'other-{uuid.uuid4().hex[:8]}'
        other = await self.store.create(
            'providers',
            other_org,
            {'name': 'x', 'type': 'fake', 'created_by': 'test'},
        )
        try:
            with self.assertRaises(store.UnknownProvider):
                await self.add_binding(
                    reference='secret://production/other',
                    provider_id=other['id'],
                )
            with self.assertRaises(store.UnknownProvider):
                await self.store.update(
                    'bindings',
                    self.org,
                    self.binding['id'],
                    {'provider_id': other['id']},
                )
            # A row written around the store: the broker still reads
            # providers of the binding's own organization only.
            async with self.pool.connection() as conn:
                await conn.execute(
                    'UPDATE secrets.bindings SET provider_id = %s'
                    ' WHERE id = %s',
                    (other['id'], self.binding['id']),
                )
            await self._denied('secret_provider_disabled')
        finally:
            async with self.pool.connection() as conn:
                await conn.execute(
                    'UPDATE secrets.bindings SET provider_id = %s'
                    ' WHERE id = %s',
                    (self.provider['id'], self.binding['id']),
                )
            await self.store.delete('providers', other_org, other['id'])

    async def test_capability_enforcement(self) -> None:
        aws = await self.store.create(
            'providers',
            self.org,
            {
                'name': 'aws',
                'type': 'aws_secrets_manager',
                'config': {'region': 'us-east-1'},
                'capabilities': [],
                'created_by': 'test',
            },
        )
        # The endpoints refuse this binding; written directly here.
        binding = await self.add_binding(
            reference='secret://production/dynamic',
            provider_id=aws['id'],
            credential_class='dynamic',
            locator={'secret_id': 'x'},
        )
        await self.add_grant([binding['id']])
        error = await self._denied(
            'operation_not_supported',
            request=self.request(reference='secret://production/dynamic'),
        )
        self.assertEqual(error.reason, 'missing_dynamic_issuance')
        with self.assertRaises(providers.BrokerError) as ctx:
            await providers.PROVIDERS['aws_secrets_manager'].revoke({}, 'x')
        self.assertEqual(ctx.exception.code, 'provider_lease_not_revocable')

    async def test_disabled_resources_deny_new_resolutions(self) -> None:
        for table, row, code in (
            ('providers', self.provider, 'secret_provider_disabled'),
            ('bindings', self.binding, 'secret_binding_disabled'),
            ('grants', self.grant, 'secret_access_denied'),
        ):
            with self.subTest(table=table):
                await self.store.update(
                    table, self.org, row['id'], {'enabled': False}
                )
                await self._denied(code)
                await self.store.update(
                    table, self.org, row['id'], {'enabled': True}
                )

    async def test_idempotency_key_rotates_the_handle(self) -> None:
        request = self.request(idempotency_key='key-1')
        first = await self.broker.create_resolution(self.context(), request)
        second = await self.broker.create_resolution(self.context(), request)
        self.assertEqual(first.resolution_id, second.resolution_id)
        self.assertNotEqual(first.handle, second.handle)
        with self.assertRaises(providers.BrokerError) as ctx:
            await self.broker.materialize(
                self.executor(), self.materialize_request(first.handle)
            )
        self.assertEqual(ctx.exception.code, 'resolution_not_found')
        await self.broker.materialize(
            self.executor(), self.materialize_request(second.handle)
        )
        await self._denied('resolution_already_used', request=request)
        await self._denied(
            'resolution_context_mismatch',
            request=self.request(idempotency_key='key-1', ttl_seconds=60),
        )

    async def test_concurrent_idempotent_creates(self) -> None:
        request = self.request(idempotency_key='key-2')
        created = await asyncio.gather(
            *(
                self.broker.create_resolution(self.context(), request)
                for _ in range(5)
            )
        )
        self.assertEqual(len({c.resolution_id for c in created}), 1)


class MaterializeTestCase(secret_support.SecretCase):
    async def _create(self, **changes: object) -> broker.Created:
        return await self.broker.create_resolution(
            self.context(), self.request(**changes)
        )

    async def _refused(
        self, code: str, request: broker.MaterializeRequest, runner: str = ''
    ) -> None:
        with self.assertRaises(providers.BrokerError) as ctx:
            await self.broker.materialize(self.executor(runner), request)
        self.assertEqual(ctx.exception.code, code, ctx.exception.reason)

    async def test_materialize_once(self) -> None:
        created = await self._create()
        result = await self.broker.materialize(
            self.executor(), self.materialize_request(created.handle)
        )
        self.assertEqual(result.encoding, 'utf8')
        self.assertEqual(result.material, MATERIAL)
        self.assertEqual(result.delivery_target, 'GH_TOKEN')
        self.assertEqual(result.body()['delivery']['mode'], 'environment')
        self.assertNotIn(MATERIAL, repr(result))
        with self.assertRaises(TypeError):
            pickle.dumps(result)
        await self._refused(
            'resolution_already_used', self.materialize_request(created.handle)
        )
        self.assertEqual(
            [e.type for e in self.events[-2:]],
            ['secret_materialized', 'secret_materialized'],
        )
        self.assertEqual(self.events[-1].result, 'denied')
        self.assertEqual(
            broker.NO_STORE_HEADERS,
            {
                'Cache-Control': 'no-store',
                'Pragma': 'no-cache',
                'X-Content-Type-Options': 'nosniff',
            },
        )

    async def test_binary_material_is_base64(self) -> None:
        self.fake.values['plain'] = b'\xff\x00secret'
        created = await self._create()
        result = await self.broker.materialize(
            self.executor(), self.materialize_request(created.handle)
        )
        self.assertEqual(result.encoding, 'base64')
        self.assertEqual(base64.b64decode(result.material), b'\xff\x00secret')

    async def test_single_use_under_concurrency(self) -> None:
        created = await self._create()
        results = await asyncio.gather(
            *(
                self.broker.materialize(
                    self.executor(), self.materialize_request(created.handle)
                )
                for _ in range(10)
            ),
            return_exceptions=True,
        )
        ok = [r for r in results if isinstance(r, broker.Materialization)]
        failed = [r for r in results if isinstance(r, providers.BrokerError)]
        self.assertEqual(len(ok), 1)
        self.assertEqual(len(failed), 9)
        self.assertEqual({e.code for e in failed}, {'resolution_already_used'})
        row = await self.broker.get(created.resolution_id)
        assert row is not None
        self.assertEqual(row['materialization_count'], 1)

    async def test_nonce_replay(self) -> None:
        created = await self._create()
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE secrets.resolutions SET materialization_limit = 3'
                ' WHERE id = %s',
                (created.resolution_id,),
            )
        request = self.materialize_request(created.handle, nonce='n-1')
        await self.broker.materialize(self.executor(), request)
        with self.assertRaises(providers.BrokerError) as ctx:
            await self.broker.materialize(self.executor(), request)
        self.assertEqual(ctx.exception.reason, 'nonce_replay')
        await self.broker.materialize(
            self.executor(),
            self.materialize_request(created.handle, nonce='n-2'),
        )

    async def test_context_mismatch(self) -> None:
        created = await self._create()
        await self._refused(
            'resolution_context_mismatch',
            self.materialize_request(created.handle),
            runner='runner-other',
        )
        for change in (
            {'task_id': uuid.uuid4()},
            {'agent_id': 'other'},
            {'project_id': None},
            {'purpose': 'checkout'},
        ):
            with self.subTest(change=change):
                await self._refused(
                    'resolution_context_mismatch',
                    self.materialize_request(created.handle, **change),
                )
        # The refusals used nothing: the right context still works.
        await self.broker.materialize(
            self.executor(), self.materialize_request(created.handle)
        )

    async def test_disabled_resources_invalidate_unused_handles(self) -> None:
        for table, row, code in (
            ('providers', self.provider, 'secret_provider_disabled'),
            ('bindings', self.binding, 'secret_binding_disabled'),
            ('grants', self.grant, 'secret_access_denied'),
        ):
            with self.subTest(table=table):
                created = await self._create()
                await self.store.update(
                    table, self.org, row['id'], {'enabled': False}
                )
                await self._refused(
                    code, self.materialize_request(created.handle)
                )
                await self.store.update(
                    table, self.org, row['id'], {'enabled': True}
                )
                await self.broker.materialize(
                    self.executor(), self.materialize_request(created.handle)
                )

    async def test_task_is_checked_again_at_materialize(self) -> None:
        for column, value in (
            ('status', 'closed'),
            ('agent_id', 'other-agent'),
            ('project_id', 'other-project'),
            ('organization_id', 'other-org'),
        ):
            with self.subTest(column=column):
                created = await self._create()
                async with self.pool.connection() as conn:
                    row = await conn.execute(
                        f'SELECT {column} FROM agent_runtime.tasks'
                        ' WHERE id = %s',
                        (self.task_id,),
                    )
                    before = (await row.fetchone() or [None])[0]
                    await conn.execute(
                        f'UPDATE agent_runtime.tasks SET {column} = %s'
                        ' WHERE id = %s',
                        (value, self.task_id),
                    )
                with self.assertRaises(providers.BrokerError) as ctx:
                    await self.broker.materialize(
                        self.executor(),
                        self.materialize_request(created.handle),
                    )
                self.assertIn(
                    ctx.exception.code,
                    {'secret_access_denied', 'resolution_context_mismatch'},
                )
                async with self.pool.connection() as conn:
                    await conn.execute(
                        f'UPDATE agent_runtime.tasks SET {column} = %s'
                        ' WHERE id = %s',
                        (before, self.task_id),
                    )
                # The refusal used nothing: the handle still works.
                await self.broker.materialize(
                    self.executor(), self.materialize_request(created.handle)
                )

    async def test_sweep_releases_resolutions_of_closed_tasks(self) -> None:
        created = await self._create()
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_runtime.tasks SET status = 'closed'"
                ' WHERE id = %s',
                (self.task_id,),
            )
        await self.broker.sweep()
        row = await self.broker.get(created.resolution_id)
        assert row is not None
        self.assertEqual(
            (row['state'], row['release_reason'], row['handle_hash']),
            ('released', 'task_closed', None),
        )
        self.assertIn(
            'secret_resolution_released', [e.type for e in self.events]
        )

    async def test_deleted_grant_invalidates_handle(self) -> None:
        created = await self._create()
        await self.store.delete('grants', self.org, self.grant['id'])
        await self._refused(
            'secret_access_denied', self.materialize_request(created.handle)
        )

    async def test_expiry(self) -> None:
        created = await self._create()
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE secrets.resolutions'
                " SET expires_at = NOW() - INTERVAL '1 second'"
                ' WHERE id = %s',
                (created.resolution_id,),
            )
        await self._refused(
            'resolution_expired', self.materialize_request(created.handle)
        )
        self.assertGreaterEqual(await self.broker.sweep(), 1)
        row = await self.broker.get(created.resolution_id)
        assert row is not None
        self.assertEqual(row['state'], 'expired')
        self.assertIsNone(row['handle_hash'])
        self.assertIn(
            'secret_resolution_expired', [e.type for e in self.events]
        )
        await self._refused(
            'resolution_not_found', self.materialize_request(created.handle)
        )

    async def test_provider_failure_marks_failed(self) -> None:
        self.fake.unavailable = True
        created = await self._create()
        await self._refused(
            'secret_provider_unavailable',
            self.materialize_request(created.handle),
        )
        row = await self.broker.get(created.resolution_id)
        assert row is not None
        self.assertEqual(row['state'], 'failed')
        self.assertEqual(self.events[-1].result, 'failed')


class LeaseTestCase(secret_support.SecretCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.store.update(
            'bindings',
            self.org,
            self.binding['id'],
            {'credential_class': 'dynamic'},
        )

    async def _materialized(self) -> uuid.UUID:
        created = await self.broker.create_resolution(
            self.context(), self.request()
        )
        result = await self.broker.materialize(
            self.executor(), self.materialize_request(created.handle)
        )
        self.assertIsNotNone(result.credential_expires_at)
        return created.resolution_id

    async def test_release_revokes_the_lease(self) -> None:
        resolution_id = await self._materialized()
        row = await self.broker.get(resolution_id)
        assert row is not None
        self.assertEqual(row['revocation_state'], 'pending')
        lease_id = encryption.decrypt_token(row['lease_id'])
        self.assertIn(lease_id, self.fake.leases)
        self.assertNotIn(lease_id, row['lease_id'])
        released = await self.broker.release(
            resolution_id, reason='child_exited', actor='runner:x'
        )
        self.assertEqual(released['state'], 'released')
        self.assertEqual(released['revocation_state'], 'succeeded')
        self.assertEqual(self.fake.revoked, [lease_id])
        types = [e.type for e in self.events]
        self.assertIn('secret_resolution_released', types)
        self.assertIn('secret_lease_revoked', types)
        # Idempotent: a second release changes nothing.
        again = await self.broker.release(
            resolution_id, reason='again', actor='runner:x'
        )
        self.assertEqual(again['release_reason'], 'child_exited')
        self.assertEqual(self.fake.revoked, [lease_id])

    async def test_failed_revocation_stays_visible(self) -> None:
        resolution_id = await self._materialized()
        self.fake.fail_revoke = True
        released = await self.broker.release(
            resolution_id, reason='child_exited', actor='runner:x'
        )
        self.assertEqual(released['state'], 'released')
        self.assertEqual(released['revocation_state'], 'failed')
        self.assertEqual(
            self.events[-1].type, 'secret_lease_revocation_failed'
        )
        with self.assertRaises(providers.BrokerError) as ctx:
            await self.broker.revoke_provider_lease(
                self.org, resolution_id, 'admin'
            )
        self.assertEqual(ctx.exception.code, 'provider_revocation_failed')
        self.fake.fail_revoke = False
        row = await self.broker.revoke_provider_lease(
            self.org, resolution_id, 'admin'
        )
        self.assertEqual(row['revocation_state'], 'succeeded')

    async def test_sweeps_revoke_an_expired_lease_once(self) -> None:
        resolution_id = await self._materialized()
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE secrets.resolutions'
                " SET expires_at = NOW() - INTERVAL '5 minutes'"
                ' WHERE id = %s',
                (resolution_id,),
            )
        # Two replicas sweep at the same time, then one sweeps again.
        await asyncio.gather(self.broker.sweep(), self.broker.sweep())
        await self.broker.sweep()
        self.assertEqual(len(self.fake.revoked), 1)
        row = await self.broker.get(resolution_id)
        assert row is not None
        self.assertEqual(
            (row['state'], row['revocation_state']), ('expired', 'succeeded')
        )

    async def test_release_runner_resolutions(self) -> None:
        resolution_id = await self._materialized()
        unused = await self.broker.create_resolution(
            self.context(), self.request()
        )
        self.fake.fail_revoke = True
        self.assertFalse(
            await self.broker.release_runner_resolutions(self.runner)
        )
        for rid in (resolution_id, unused.resolution_id):
            row = await self.broker.get(rid)
            assert row is not None
            self.assertEqual(row['state'], 'released')
            self.assertEqual(row['release_reason'], 'runner_fenced')
        self.fake.fail_revoke = False
        self.assertTrue(
            await self.broker.release_runner_resolutions(self.runner)
        )
        with self.assertRaises(providers.BrokerError):
            await self.broker.materialize(
                self.executor(), self.materialize_request(unused.handle)
            )

    async def test_fencing_during_a_slow_provider_call(self) -> None:
        created = await self.broker.create_resolution(
            self.context(), self.request()
        )
        started = asyncio.Event()
        proceed = asyncio.Event()
        resolve = self.fake.resolve

        async def slow(*args: object, **kwargs: object) -> providers.Material:
            started.set()
            await proceed.wait()
            return await resolve(*args, **kwargs)  # type: ignore[arg-type]

        with mock.patch.object(self.fake, 'resolve', slow):
            call = asyncio.create_task(
                self.broker.materialize(
                    self.executor(), self.materialize_request(created.handle)
                )
            )
            await started.wait()
            # In flight: the chain must stay fenced.
            self.assertFalse(
                await self.broker.release_runner_resolutions(self.runner)
            )
            proceed.set()
            with self.assertRaises(providers.BrokerError) as ctx:
                await call
        self.assertEqual(ctx.exception.reason, 'resolution_released')
        # The lease issued after the release is revoked, and no row
        # keeps it.
        self.assertEqual(len(self.fake.revoked), 1)
        self.assertEqual(self.fake.leases, set())
        row = await self.broker.get(created.resolution_id)
        assert row is not None
        self.assertEqual(row['state'], 'released')
        self.assertIsNone(row['lease_id'])
        self.assertIsNone(row['materializing_since'])
        self.assertTrue(
            await self.broker.release_runner_resolutions(self.runner)
        )

    async def test_unsaved_lease_is_revoked_at_once(self) -> None:
        created = await self.broker.create_resolution(
            self.context(), self.request()
        )
        with (
            mock.patch.object(
                encryption, 'encrypt_token', side_effect=RuntimeError
            ),
            self.assertRaises(providers.BrokerError) as ctx,
        ):
            await self.broker.materialize(
                self.executor(), self.materialize_request(created.handle)
            )
        self.assertEqual(ctx.exception.reason, 'lease_not_saved')
        self.assertEqual(len(self.fake.revoked), 1)
        self.assertEqual(self.fake.leases, set())


class NoLeakTestCase(secret_support.SecretCase):
    async def test_no_material_or_handle_in_logs_rows_or_audit(self) -> None:
        await self.store.update(
            'bindings',
            self.org,
            self.binding['id'],
            {'credential_class': 'dynamic'},
        )
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger('imbi').debug('capture start')
            created = await self.broker.create_resolution(
                self.context(), self.request(idempotency_key='k')
            )
            result = await self.broker.materialize(
                self.executor(), self.materialize_request(created.handle)
            )
            self.fake.fail_revoke = True
            await self.broker.release(
                created.resolution_id, reason='done', actor='runner:x'
            )
            self.fake.unavailable = True
            failing = await self.broker.create_resolution(
                self.context(), self.request()
            )
            with self.assertRaises(providers.BrokerError):
                await self.broker.materialize(
                    self.executor(), self.materialize_request(failing.handle)
                )
            # A provider bug whose message holds the value: logged by
            # type only.
            self.fake.unavailable = False
            crashing = await self.broker.create_resolution(
                self.context(), self.request()
            )
            with (
                mock.patch.object(
                    self.fake,
                    'resolve',
                    side_effect=RuntimeError(f'boom {MATERIAL}'),
                ),
                self.assertRaises(providers.BrokerError) as ctx,
            ):
                await self.broker.materialize(
                    self.executor(), self.materialize_request(crashing.handle)
                )
            self.assertIsNone(ctx.exception.__cause__)
            self.assertNotIn(MATERIAL, str(ctx.exception))
        self.assertIn('Provider fake failed: RuntimeError', logs.output[-1])
        self.assertEqual(result.material, MATERIAL)
        row = await self.broker.get(created.resolution_id)
        assert row is not None
        lease_id = encryption.decrypt_token(row['lease_id'])
        secrets = (MATERIAL, created.handle, failing.handle, lease_id)

        text = '\n'.join(logs.output)
        for value in secrets:
            self.assertNotIn(value, text)

        async with self.pool.connection() as conn:
            cur = await conn.execute(
                'SELECT row_to_json(r)::TEXT FROM secrets.resolutions AS r'
                ' WHERE organization_id = %s'
                ' UNION ALL SELECT row_to_json(n)::TEXT'
                ' FROM secrets.nonces AS n JOIN secrets.resolutions AS r'
                ' ON r.id = n.resolution_id WHERE r.organization_id = %s'
                ' UNION ALL SELECT row_to_json(b)::TEXT'
                ' FROM secrets.bindings AS b WHERE organization_id = %s'
                ' UNION ALL SELECT row_to_json(p)::TEXT'
                ' FROM secrets.providers AS p WHERE organization_id = %s',
                (self.org,) * 4,
            )
            stored = '\n'.join(r[0] for r in await cur.fetchall())
        for value in secrets:
            self.assertNotIn(value, stored)

        published = orjson.dumps(
            [e.model_dump(mode='json') for e in self.events]
        ).decode()
        for value in secrets:
            self.assertNotIn(value, published)
