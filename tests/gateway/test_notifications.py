import typing

import httpx
import nanoid
from imbi_common import graph
from imbi_common.graph import (
    _inject_graph,  # pyright: ignore[reportPrivateUsage]
)

import imbi_gateway.app
from tests import helpers

if typing.TYPE_CHECKING:
    from collections import abc

HANDLER_CALLS: list[tuple[str, str, object, str]] = []


async def stub_handler(
    org_slug: str, project_id: str, body: object, config: str
) -> None:
    HANDLER_CALLS.append((org_slug, project_id, body, config))


class ProcessNotificationTests(helpers.TestCase):
    async def asyncSetUp(self) -> None:
        HANDLER_CALLS.clear()

        self.org_id = nanoid.generate()
        self.org_slug = f'org-{self.org_id[:8]}'
        self.webhook_id = nanoid.generate()
        self.tps_id = nanoid.generate()
        self.proj_id = nanoid.generate()
        self.ext_id = f'ext-{nanoid.generate()[:8]}'
        self.rule_ids: list[str] = []

        self.g = graph.Graph()
        await self.g.open()

        self.app = imbi_gateway.app.create_app()

        async def _override_graph() -> abc.AsyncIterator[graph.Graph]:
            yield self.g

        self.app.dependency_overrides[_inject_graph] = _override_graph

        ts = '2024-01-01T00:00:00+00:00'

        await self.g.execute(
            'CREATE (n:Organization {{id: {id}, slug: {slug},'
            ' name: {name}, created_at: {ts}}}) RETURN n',
            {
                'id': self.org_id,
                'slug': self.org_slug,
                'name': 'Test Org',
                'ts': ts,
            },
            ['n'],
        )
        await self.g.execute(
            'CREATE (n:Webhook {{id: {id}, slug: {slug},'
            ' name: {name}, created_at: {ts}}}) RETURN n',
            {
                'id': self.webhook_id,
                'slug': f'wh-{self.webhook_id[:8]}',
                'name': 'Test Webhook',
                'ts': ts,
            },
            ['n'],
        )
        await self.g.execute(
            'MATCH (w:Webhook {{id: {wid}}}), (o:Organization {{id: {oid}}})'
            ' CREATE (w)-[:BELONGS_TO]->(o) RETURN w',
            {'wid': self.webhook_id, 'oid': self.org_id},
            ['w'],
        )
        await self.g.execute(
            'CREATE (n:ThirdPartyService {{id: {id}, slug: {slug},'
            ' name: {name}, created_at: {ts}}}) RETURN n',
            {
                'id': self.tps_id,
                'slug': f'tps-{self.tps_id[:8]}',
                'name': 'Test Service',
                'ts': ts,
            },
            ['n'],
        )
        await self.g.execute(
            'MATCH (tps:ThirdPartyService {{id: {tid}}}),'
            ' (o:Organization {{id: {oid}}})'
            ' CREATE (tps)-[:BELONGS_TO]->(o) RETURN tps',
            {'tid': self.tps_id, 'oid': self.org_id},
            ['tps'],
        )
        await self.g.execute(
            'MATCH (w:Webhook {{id: {wid}}}),'
            ' (tps:ThirdPartyService {{id: {tid}}})'
            ' CREATE (w)-[:IMPLEMENTED_BY'
            ' {{identifier_selector: {sel}}}]->(tps)'
            ' RETURN w',
            {'wid': self.webhook_id, 'tid': self.tps_id, 'sel': '/repo/id'},
            ['w'],
        )
        await self.g.execute(
            'CREATE (n:Project {{id: {id}, slug: {slug},'
            ' name: {name}, created_at: {ts}}}) RETURN n',
            {
                'id': self.proj_id,
                'slug': f'proj-{self.proj_id[:8]}',
                'name': 'Test Project',
                'ts': ts,
            },
            ['n'],
        )
        await self.g.execute(
            'MATCH (p:Project {{id: {pid}}}),'
            ' (tps:ThirdPartyService {{id: {tid}}})'
            ' CREATE (p)-[:EXISTS_IN {{identifier: {ext_id}}}]->(tps)'
            ' RETURN p',
            {'pid': self.proj_id, 'tid': self.tps_id, 'ext_id': self.ext_id},
            ['p'],
        )

    async def asyncTearDown(self) -> None:
        for rule_id in self.rule_ids:
            await self.g.execute(
                'MATCH (n:WebhookRule {{id: {id}}})'
                ' DETACH DELETE n RETURN 1 AS r',
                {'id': rule_id},
                ['r'],
            )
        for label, node_id in [
            ('Project', self.proj_id),
            ('ThirdPartyService', self.tps_id),
            ('Webhook', self.webhook_id),
            ('Organization', self.org_id),
        ]:
            await self.g.execute(
                f'MATCH (n:{label} {{{{id: {{id}}}}}})'
                ' DETACH DELETE n RETURN 1 AS r',
                {'id': node_id},
                ['r'],
            )
        await self.g.close()

    async def _add_rule(
        self,
        *,
        handler: str = 'tests.test_notifications.stub_handler',
        filter_expression: str = 'true',
        ordinal: int = 1,
        handler_config: str = '{}',
    ) -> str:
        rule_id = nanoid.generate()
        self.rule_ids.append(rule_id)
        await self.g.execute(
            'CREATE (r:WebhookRule {{id: {id}, ordinal: {ord},'
            ' handler: {handler}, handler_config: {cfg},'
            ' filter_expression: {expr}}}) RETURN r',
            {
                'id': rule_id,
                'ord': ordinal,
                'handler': handler,
                'cfg': handler_config,
                'expr': filter_expression,
            },
            ['r'],
        )
        await self.g.execute(
            'MATCH (r:WebhookRule {{id: {rid}}}),'
            ' (w:Webhook {{id: {wid}}})'
            ' CREATE (r)-[:ACTIONS]->(w) RETURN r',
            {'rid': rule_id, 'wid': self.webhook_id},
            ['r'],
        )
        return rule_id

    async def _post(self, webhook_id: str, body: object) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url='http://test'
        ) as client:
            return await client.post(f'/notifications/{webhook_id}', json=body)

    async def test_no_webhook_found(self) -> None:
        with self.assertLogs(
            'imbi_gateway.notifications', level='WARNING'
        ) as cm:
            response = await self._post(nanoid.generate(), {})
        self.assertEqual(200, response.status_code)
        self.assertEqual([], HANDLER_CALLS)
        self.assertTrue(any('No records found' in line for line in cm.output))

    async def test_no_rules_empty_collect(self) -> None:
        # Confirms collect() returns [] not None when no WebhookRule
        # nodes exist
        body = {'repo': {'id': self.ext_id}}
        response = await self._post(self.webhook_id, body)
        self.assertEqual(200, response.status_code)
        self.assertEqual([], HANDLER_CALLS)

    async def test_no_service_global_webhook_not_implemented(self) -> None:
        # Remove the IMPLEMENTED_BY edge by using a webhook with no TPS link
        no_tps_webhook_id = nanoid.generate()
        ts = '2024-01-01T00:00:00+00:00'
        await self.g.execute(
            'CREATE (n:Webhook {{id: {id}, slug: {slug},'
            ' name: {name}, created_at: {ts}}}) RETURN n',
            {
                'id': no_tps_webhook_id,
                'slug': f'wh-{no_tps_webhook_id[:8]}',
                'name': 'No-TPS Webhook',
                'ts': ts,
            },
            ['n'],
        )
        await self.g.execute(
            'MATCH (w:Webhook {{id: {wid}}}),'
            ' (o:Organization {{id: {oid}}})'
            ' CREATE (w)-[:BELONGS_TO]->(o) RETURN w',
            {'wid': no_tps_webhook_id, 'oid': self.org_id},
            ['w'],
        )
        try:
            with self.assertLogs(
                'imbi_gateway.notifications', level='WARNING'
            ) as cm:
                response = await self._post(no_tps_webhook_id, {})
            self.assertEqual(200, response.status_code)
            self.assertEqual([], HANDLER_CALLS)
            self.assertTrue(
                any('Global webhooks' in line for line in cm.output)
            )
        finally:
            await self.g.execute(
                'MATCH (n:Webhook {{id: {id}}}) DETACH DELETE n RETURN 1 AS r',
                {'id': no_tps_webhook_id},
                ['r'],
            )

    async def test_all_conditions_false_no_handler_called(self) -> None:
        await self._add_rule(filter_expression='false')
        body = {'repo': {'id': self.ext_id}}
        with self.assertLogs('imbi_gateway.notifications', level='INFO') as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(200, response.status_code)
        self.assertEqual([], HANDLER_CALLS)
        self.assertTrue(any('no filter matches' in line for line in cm.output))

    async def test_handler_called_when_condition_matches(self) -> None:
        await self._add_rule(filter_expression='true')
        body = {'repo': {'id': self.ext_id}}
        response = await self._post(self.webhook_id, body)
        self.assertEqual(200, response.status_code)
        self.assertEqual(1, len(HANDLER_CALLS))
        org_slug, project_id, received_body, _ = HANDLER_CALLS[0]
        self.assertEqual(self.org_slug, org_slug)
        self.assertEqual(self.proj_id, project_id)
        self.assertEqual(body, received_body)

    async def test_project_not_found_for_external_id(self) -> None:
        await self._add_rule(filter_expression='true')
        body = {'repo': {'id': 'no-such-external-id'}}
        with self.assertLogs(
            'imbi_gateway.notifications', level='WARNING'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(200, response.status_code)
        self.assertEqual([], HANDLER_CALLS)
        self.assertTrue(any('no project found' in line for line in cm.output))

    async def test_invalid_rule_handler_logs_error(self) -> None:
        await self._add_rule(handler='does.not.exist.handler')
        body = {'repo': {'id': self.ext_id}}
        with self.assertLogs(
            'imbi_gateway.notifications', level='ERROR'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(200, response.status_code)
        self.assertEqual([], HANDLER_CALLS)
        self.assertTrue(
            any('failed to deserialize rules' in line for line in cm.output)
        )
