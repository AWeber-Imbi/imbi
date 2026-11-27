"""Tests for the credential of an MCP server from a secret binding."""

import dataclasses

import orjson

from apps.api.tests import secret_support
from imbi.api.secret_broker import broker, providers, store

REFERENCE = 'secret://production/mcp/token'
SERVER = broker.McpServerTarget(
    id='srv-1', url='https://mcp.example.com/', token_url=None
)


class McpCredentialTestCase(secret_support.SecretCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.mcp_binding = await self.add_binding(
            reference=REFERENCE,
            mcp_server_usage={'servers': [broker.mcp_usage_entry(SERVER)]},
        )

    async def refused(
        self,
        reference: str = REFERENCE,
        server: broker.McpServerTarget = SERVER,
        org: str = '',
    ) -> str:
        with self.assertRaises(providers.BrokerError) as ctx:
            await self.broker.mcp_credential(
                org or self.org, reference, server, actor='svc'
            )
        return ctx.exception.reason or ctx.exception.code

    async def test_listed_server_gets_the_value(self) -> None:
        material = await self.broker.mcp_credential(
            self.org, REFERENCE, SERVER, actor='svc'
        )
        self.assertEqual(material.value, secret_support.MATERIAL.encode())
        event = next(
            e for e in await self.audit_events() if e.reason == 'mcp_server'
        )
        self.assertEqual(event.type, 'secret_materialized')
        self.assertEqual(event.purpose, broker.MCP_PURPOSE)
        self.assertEqual(event.actor, 'svc')

    async def test_a_moved_server_is_refused_until_saved_again(self) -> None:
        moved_url = broker.McpServerTarget(
            id='srv-1', url='https://attacker.example/', token_url=None
        )
        moved_token = broker.McpServerTarget(
            id='srv-1',
            url=SERVER.url,
            token_url='https://attacker.example/token',
        )
        # The same place, but a secret that goes elsewhere or in the clear.
        other_use = dataclasses.replace(SERVER, auth_type='static')
        no_tls = dataclasses.replace(SERVER, verify_ssl=False)
        for server in (moved_url, moved_token, other_use, no_tls):
            with self.subTest(server=server):
                self.assertEqual(
                    await self.refused(server=server), 'mcp_server_moved'
                )
        # A binding writer saves the binding again at the new place.
        await self.store.update(
            'bindings',
            self.org,
            self.mcp_binding['id'],
            {
                'mcp_server_usage': {
                    'servers': [broker.mcp_usage_entry(moved_token)]
                }
            },
        )
        material = await self.broker.mcp_credential(
            self.org, REFERENCE, moved_token
        )
        self.assertEqual(material.value, secret_support.MATERIAL.encode())

    async def test_refusals(self) -> None:
        other = broker.McpServerTarget(id='srv-2', url=SERVER.url)
        self.assertEqual(
            await self.refused(server=other), 'mcp_server_not_listed'
        )
        # A binding with no MCP server list.
        self.assertEqual(
            await self.refused('secret://production/github/token'),
            'mcp_server_not_listed',
        )
        # Another organization has no such binding.
        self.assertEqual(
            await self.refused(org='another-org'), 'secret_binding_not_found'
        )
        await self.store.update(
            'bindings', self.org, self.mcp_binding['id'], {'enabled': False}
        )
        self.assertEqual(await self.refused(), 'secret_binding_disabled')
        await self.store.update(
            'bindings',
            self.org,
            self.mcp_binding['id'],
            {'enabled': True, 'credential_class': 'dynamic'},
        )
        self.assertEqual(await self.refused(), 'dynamic_mcp_binding')
        denied = [
            e
            for e in await self.audit_events()
            if e.type == 'secret_resolution_denied'
        ]
        self.assertIn('mcp_server_not_listed', {e.reason for e in denied})
        self.assertTrue(all(e.actor == 'svc' for e in denied))

    async def test_disabled_provider_records_a_denial(self) -> None:
        await self.store.update(
            'providers', self.org, self.provider['id'], {'enabled': False}
        )
        self.assertEqual(await self.refused(), 'secret_provider_disabled')
        event = next(
            e
            for e in await self.audit_events()
            if e.type == 'secret_resolution_denied'
        )
        self.assertEqual(event.actor, 'svc')
        self.assertEqual(event.purpose, broker.MCP_PURPOSE)
        self.assertEqual(event.binding_id, str(self.mcp_binding['id']))

    async def test_a_field_list_limits_the_value(self) -> None:
        await self.store.update(
            'bindings',
            self.org,
            self.mcp_binding['id'],
            {'locator': {'key': 'json'}, 'allowed_fields': ['token']},
        )
        material = await self.broker.mcp_credential(
            self.org, REFERENCE, SERVER, actor='svc'
        )
        self.assertEqual(
            orjson.loads(material.value), {'token': secret_support.MATERIAL}
        )

    async def test_cannot_be_granted_to_a_task(self) -> None:
        with self.assertRaises(store.ProviderKeyBinding):
            await self.store.update(
                'grants',
                self.org,
                self.grant['id'],
                {'binding_ids': [self.mcp_binding['id']]},
            )
        # A grant from before the store refused this still gets nothing.
        async with self.pool.connection() as conn:
            await conn.execute(
                'UPDATE secrets.grants SET binding_ids = %s WHERE id = %s',
                ([self.mcp_binding['id']], self.grant['id']),
            )
        with self.assertRaises(providers.BrokerError) as ctx:
            await self.broker.create_resolution(
                self.context(), self.request(reference=REFERENCE)
            )
        self.assertEqual(ctx.exception.reason, 'mcp_server_binding')
