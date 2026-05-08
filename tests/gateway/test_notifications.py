import typing
import unittest.mock

import celpy
import httpx
import nanoid
import pydantic
from imbi_common import clickhouse, graph
from imbi_common.graph import (
    _inject_graph,  # pyright: ignore[reportPrivateUsage]
)

import imbi_gateway.app
from imbi_gateway import actions, notifications
from tests import helpers

if typing.TYPE_CHECKING:
    from collections import abc

_TOKEN = 'test-token'  # noqa: S105

HANDLER_CALLS: list[tuple[str, str, object, str | None, str]] = []


async def stub_handler(
    org_slug: str,
    project_id: str,
    body: object,
    user_id: str | None,
    config: str,
) -> None:
    HANDLER_CALLS.append((org_slug, project_id, body, user_id, config))


def sync_stub_handler(
    org_slug: str,
    project_id: str,
    body: object,
    user_id: str | None,
    config: str,
) -> None:
    pass


async def raising_stub_handler(
    _org_slug: str,
    _project_id: str,
    _body: object,
    _user_id: str | None,
    _config: str,
) -> None:
    raise RuntimeError('test error')


class WebhookRuleUnitTests(helpers.TestCase):
    _VALID_RULE: typing.ClassVar[dict[str, object]] = {
        'handler': 'tests.test_notifications.stub_handler',
        'ordinal': 1,
        'handler_config': '{}',
        'filter_expression': 'true',
    }

    def test_sync_handler_rejected_by_validator(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            notifications.WebhookRule.model_validate(
                {
                    **self._VALID_RULE,
                    'handler': 'tests.test_notifications.sync_stub_handler',
                }
            )

    def test_evaluate_condition_cel_error_returns_none(self) -> None:
        rule = notifications.WebhookRule.model_validate(self._VALID_RULE)
        with unittest.mock.patch.object(
            celpy, 'json_to_cel', side_effect=celpy.CELEvalError('test')
        ):
            self.assertIsNone(rule.evaluate_condition({}))

    def test_evaluate_condition_unexpected_exception_returns_none(
        self,
    ) -> None:
        rule = notifications.WebhookRule.model_validate(self._VALID_RULE)
        with unittest.mock.patch.object(
            celpy, 'json_to_cel', side_effect=TypeError('unexpected')
        ):
            self.assertIsNone(rule.evaluate_condition({}))


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

    async def _post(
        self,
        webhook_id: str,
        body: object,
        *,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url='http://test'
        ) as client:
            return await client.post(
                f'/notifications/{webhook_id}', json=body, headers=headers
            )

    async def test_no_webhook_found(self) -> None:
        with self.assertLogs(
            'imbi_gateway.notifications', level='WARNING'
        ) as cm:
            response = await self._post(nanoid.generate(), {})
        self.assertEqual(204, response.status_code)
        self.assertEqual([], HANDLER_CALLS)
        self.assertTrue(any('No records found' in line for line in cm.output))

    async def test_no_rules_empty_collect(self) -> None:
        # Confirms collect() returns [] not None when no WebhookRule
        # nodes exist
        body = {'repo': {'id': self.ext_id}}
        response = await self._post(self.webhook_id, body)
        self.assertEqual(204, response.status_code)
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
            self.assertEqual(204, response.status_code)
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
        with self.assertLogs(
            'imbi_gateway.notifications', level='DEBUG'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(204, response.status_code)
        self.assertEqual([], HANDLER_CALLS)
        self.assertTrue(any('no filter matches' in line for line in cm.output))

    async def test_handler_called_when_condition_matches(self) -> None:
        await self._add_rule(filter_expression='true')
        body = {'repo': {'id': self.ext_id}}
        response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        self.assertEqual(1, len(HANDLER_CALLS))
        org_slug, project_id, received_body, user_id, _ = HANDLER_CALLS[0]
        self.assertEqual(self.org_slug, org_slug)
        self.assertEqual(self.proj_id, project_id)
        self.assertEqual(body, received_body)
        # No user_subject_selector configured on the IMPLEMENTED_BY edge
        self.assertIsNone(user_id)

    async def test_handler_called_for_each_matching_project(self) -> None:
        await self._add_rule(filter_expression='true')
        ts = '2024-01-01T00:00:00+00:00'
        second_proj_id = nanoid.generate()
        await self.g.execute(
            'CREATE (n:Project {{id: {id}, slug: {slug},'
            ' name: {name}, created_at: {ts}}}) RETURN n',
            {
                'id': second_proj_id,
                'slug': f'proj2-{second_proj_id[:8]}',
                'name': 'Second Project',
                'ts': ts,
            },
            ['n'],
        )
        await self.g.execute(
            'MATCH (p:Project {{id: {pid}}}),'
            ' (tps:ThirdPartyService {{id: {tid}}})'
            ' CREATE (p)-[:EXISTS_IN {{identifier: {ext_id}}}]->(tps)'
            ' RETURN p',
            {'pid': second_proj_id, 'tid': self.tps_id, 'ext_id': self.ext_id},
            ['p'],
        )
        try:
            body = {'repo': {'id': self.ext_id}}
            response = await self._post(self.webhook_id, body)
            self.assertEqual(202, response.status_code)
            self.assertEqual(2, len(HANDLER_CALLS))
            project_ids = {call[1] for call in HANDLER_CALLS}
            self.assertEqual({self.proj_id, second_proj_id}, project_ids)
        finally:
            await self.g.execute(
                'MATCH (n:Project {{id: {id}}}) DETACH DELETE n RETURN 1 AS r',
                {'id': second_proj_id},
                ['r'],
            )

    async def test_project_not_found_for_external_id(self) -> None:
        await self._add_rule(filter_expression='true')
        body = {'repo': {'id': 'no-such-external-id'}}
        with self.assertLogs(
            'imbi_gateway.notifications', level='WARNING'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(204, response.status_code)
        self.assertEqual([], HANDLER_CALLS)
        self.assertTrue(any('no project found' in line for line in cm.output))

    async def test_invalid_rule_handler_logs_error(self) -> None:
        await self._add_rule(handler='does.not.exist.handler')
        body = {'repo': {'id': self.ext_id}}
        with self.assertLogs(
            'imbi_gateway.notifications', level='ERROR'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(204, response.status_code)
        self.assertEqual([], HANDLER_CALLS)
        self.assertTrue(
            any('failed to deserialize rules' in line for line in cm.output)
        )

    async def test_identifier_pointer_not_in_body(self) -> None:
        # Body is missing /repo/id so JsonPointerException is raised
        with self.assertLogs(
            'imbi_gateway.notifications', level='ERROR'
        ) as cm:
            response = await self._post(self.webhook_id, {})
        self.assertEqual(204, response.status_code)
        self.assertTrue(
            any(
                'failed to select project identifier' in line
                for line in cm.output
            )
        )

    async def test_webhook_in_multiple_orgs_fails(self) -> None:
        # A second BELONGS_TO edge makes the query return 2 rows
        extra_org_id = nanoid.generate()
        ts = '2024-01-01T00:00:00+00:00'
        await self.g.execute(
            'CREATE (n:Organization {{id: {id}, slug: {slug},'
            ' name: {name}, created_at: {ts}}}) RETURN n',
            {
                'id': extra_org_id,
                'slug': f'extra-{extra_org_id[:8]}',
                'name': 'Extra Org',
                'ts': ts,
            },
            ['n'],
        )
        await self.g.execute(
            'MATCH (w:Webhook {{id: {wid}}}),'
            ' (o:Organization {{id: {oid}}})'
            ' CREATE (w)-[:BELONGS_TO]->(o) RETURN w',
            {'wid': self.webhook_id, 'oid': extra_org_id},
            ['w'],
        )
        try:
            body = {'repo': {'id': self.ext_id}}
            response = await self._post(self.webhook_id, body)
            self.assertEqual(500, response.status_code)
        finally:
            await self.g.execute(
                'MATCH (n:Organization {{id: {id}}})'
                ' DETACH DELETE n RETURN 1 AS r',
                {'id': extra_org_id},
                ['r'],
            )

    async def test_invalid_json_body_returns_unprocessable_content(
        self,
    ) -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url='http://test'
        ) as client:
            response = await client.post(
                f'/notifications/{self.webhook_id}',
                content=b'not valid json',
                headers={'content-type': 'application/json'},
            )
        self.assertEqual(422, response.status_code)

    async def _set_implemented_by(
        self,
        *,
        identifier_selector: str = '/repo/id',
        user_subject_selector: str | None = None,
        identity_plugin_slug: str | None = None,
        event_type_selector: str | None = None,
    ) -> None:
        """Replace the IMPLEMENTED_BY edge with one carrying given props."""
        await self.g.execute(
            'MATCH (w:Webhook {{id: {wid}}})-[i:IMPLEMENTED_BY]->()'
            ' DELETE i RETURN 1 AS r',
            {'wid': self.webhook_id},
            ['r'],
        )
        await self.g.execute(
            'MATCH (w:Webhook {{id: {wid}}}),'
            ' (tps:ThirdPartyService {{id: {tid}}})'
            ' CREATE (w)-[:IMPLEMENTED_BY {{'
            'identifier_selector: {sel},'
            ' user_subject_selector: {uss},'
            ' identity_plugin_slug: {ips},'
            ' event_type_selector: {ets}'
            '}}]->(tps) RETURN w',
            {
                'wid': self.webhook_id,
                'tid': self.tps_id,
                'sel': identifier_selector,
                'uss': user_subject_selector,
                'ips': identity_plugin_slug,
                'ets': event_type_selector,
            },
            ['w'],
        )

    async def test_user_subject_selector_resolves_user(self) -> None:
        await self._add_rule(filter_expression='true')
        await self._set_implemented_by(
            user_subject_selector='/sender/id', identity_plugin_slug='github'
        )
        body = {'repo': {'id': self.ext_id}, 'sender': {'id': 12345}}
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'find_user_by_identity',
                new=unittest.mock.AsyncMock(return_value='alice@example.com'),
            ) as mock_lookup,
        ):
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        mock_lookup.assert_awaited_once_with('github', '12345')
        self.assertEqual(1, len(HANDLER_CALLS))
        self.assertEqual('alice@example.com', HANDLER_CALLS[0][3])

    async def test_user_subject_selector_misses_returns_none(self) -> None:
        await self._add_rule(filter_expression='true')
        await self._set_implemented_by(
            user_subject_selector='/sender/id', identity_plugin_slug='github'
        )
        body = {'repo': {'id': self.ext_id}, 'sender': {'id': 99999}}
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'find_user_by_identity',
                new=unittest.mock.AsyncMock(return_value=None),
            ),
        ):
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        self.assertIsNone(HANDLER_CALLS[0][3])

    async def test_user_subject_selector_unresolvable_pointer(self) -> None:
        await self._add_rule(filter_expression='true')
        await self._set_implemented_by(
            user_subject_selector='/missing/path',
            identity_plugin_slug='github',
        )
        body = {'repo': {'id': self.ext_id}}
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'find_user_by_identity',
                new=unittest.mock.AsyncMock(),
            ) as mock_lookup,
            self.assertLogs('imbi_gateway.notifications', level='WARNING'),
        ):
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        mock_lookup.assert_not_awaited()
        self.assertIsNone(HANDLER_CALLS[0][3])

    async def test_user_subject_selector_resolves_to_empty_string(
        self,
    ) -> None:
        # An empty subject is treated as "no identity" — no lookup
        await self._add_rule(filter_expression='true')
        await self._set_implemented_by(
            user_subject_selector='/sender/id', identity_plugin_slug='github'
        )
        body = {'repo': {'id': self.ext_id}, 'sender': {'id': ''}}
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'find_user_by_identity',
                new=unittest.mock.AsyncMock(),
            ) as mock_lookup,
        ):
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        mock_lookup.assert_not_awaited()
        self.assertIsNone(HANDLER_CALLS[0][3])

    async def test_user_subject_selector_no_candidate_plugins(self) -> None:
        # user_subject_selector resolves, but no edge identity_plugin_slug
        # and no HAS_PLUGIN edges, so the slug list is empty and the
        # handler runs without attribution.
        await self._add_rule(filter_expression='true')
        await self._set_implemented_by(user_subject_selector='/sender/id')
        body = {'repo': {'id': self.ext_id}, 'sender': {'id': 12345}}
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'find_user_by_identity',
                new=unittest.mock.AsyncMock(),
            ) as mock_lookup,
        ):
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        mock_lookup.assert_not_awaited()
        self.assertIsNone(HANDLER_CALLS[0][3])

    async def test_user_resolution_two_distinct_users_logs_error(self) -> None:
        await self._add_rule(filter_expression='true')
        await self._set_implemented_by(user_subject_selector='/sender/id')
        # Add two identity plugins to the TPS so candidate_plugin_slugs
        # has two entries that resolve to different users.
        ts = '2024-01-01T00:00:00+00:00'
        plugin_ids = [nanoid.generate(), nanoid.generate()]
        slugs = ['github', 'gitlab']
        for plugin_id, slug in zip(plugin_ids, slugs, strict=True):
            await self.g.execute(
                'CREATE (p:Plugin {{id: {id}, plugin_slug: {slug},'
                ' label: {slug}, created_at: {ts}}}) RETURN p',
                {'id': plugin_id, 'slug': slug, 'ts': ts},
                ['p'],
            )
            await self.g.execute(
                'MATCH (p:Plugin {{id: {pid}}}),'
                ' (tps:ThirdPartyService {{id: {tid}}})'
                ' CREATE (tps)-[:HAS_PLUGIN]->(p) RETURN p',
                {'pid': plugin_id, 'tid': self.tps_id},
                ['p'],
            )

        try:
            body = {'repo': {'id': self.ext_id}, 'sender': {'id': 1}}
            with (
                self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
                unittest.mock.patch.object(
                    actions.ImbiClient,
                    'find_user_by_identity',
                    new=unittest.mock.AsyncMock(
                        side_effect=['alice@x.com', 'bob@y.com']
                    ),
                ),
                self.assertLogs(
                    'imbi_gateway.notifications', level='ERROR'
                ) as cm,
            ):
                response = await self._post(self.webhook_id, body)
            self.assertEqual(202, response.status_code)
            self.assertIsNone(HANDLER_CALLS[0][3])
            self.assertTrue(
                any('multiple Imbi users' in line for line in cm.output)
            )
        finally:
            for plugin_id in plugin_ids:
                await self.g.execute(
                    'MATCH (n:Plugin {{id: {id}}})'
                    ' DETACH DELETE n RETURN 1 AS r',
                    {'id': plugin_id},
                    ['r'],
                )

    async def test_handler_exception_is_caught(self) -> None:
        # Handler raises at dispatch time; exception logged, 202 returned
        await self._add_rule(
            handler='tests.test_notifications.raising_stub_handler'
        )
        body = {'repo': {'id': self.ext_id}}
        with self.assertLogs(
            'imbi_gateway.notifications', level='ERROR'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        self.assertTrue(any('Failure in' in line for line in cm.output))

    async def test_event_recorded_for_each_matching_project(self) -> None:
        """Each project that matches the webhook gets one events row."""
        await self._add_rule(filter_expression='true')
        await self._set_implemented_by(event_type_selector='x-github-event')
        body = {'repo': {'id': self.ext_id}, 'action': 'opened'}
        with unittest.mock.patch.object(
            clickhouse, 'insert', new=unittest.mock.AsyncMock()
        ) as mock_insert:
            response = await self._post(
                self.webhook_id,
                body,
                headers={'X-GitHub-Event': 'deployment_status'},
            )
        self.assertEqual(202, response.status_code)
        mock_insert.assert_awaited_once()
        assert mock_insert.await_args is not None  # noqa: S101 - test narrowing
        table_arg, events_arg = mock_insert.await_args.args
        self.assertEqual('events', table_arg)
        self.assertEqual(1, len(events_arg))
        ev = events_arg[0]
        self.assertEqual(self.proj_id, ev.project_id)
        self.assertEqual('deployment_status', ev.type)
        self.assertEqual(body, ev.payload)
        self.assertEqual(self.webhook_id, ev.metadata['webhook_id'])
        self.assertEqual(
            'deployment_status', ev.metadata['headers'].get('x-github-event')
        )

    async def test_no_event_when_filter_does_not_match(self) -> None:
        await self._add_rule(filter_expression='false')
        body = {'repo': {'id': self.ext_id}}
        with unittest.mock.patch.object(
            clickhouse, 'insert', new=unittest.mock.AsyncMock()
        ) as mock_insert:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(204, response.status_code)
        mock_insert.assert_not_awaited()

    async def test_no_event_when_no_project_matches(self) -> None:
        await self._add_rule(filter_expression='true')
        body = {'repo': {'id': 'no-such-external-id'}}
        with unittest.mock.patch.object(
            clickhouse, 'insert', new=unittest.mock.AsyncMock()
        ) as mock_insert:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(204, response.status_code)
        mock_insert.assert_not_awaited()

    async def test_event_insert_failure_does_not_block_handlers(self) -> None:
        """ClickHouse failures are best-effort; handler runs anyway."""
        await self._add_rule(filter_expression='true')
        body = {'repo': {'id': self.ext_id}}
        with (
            unittest.mock.patch.object(
                clickhouse,
                'insert',
                new=unittest.mock.AsyncMock(side_effect=RuntimeError('boom')),
            ),
            self.assertLogs('imbi_gateway.notifications', level='ERROR') as cm,
        ):
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        self.assertEqual(1, len(HANDLER_CALLS))
        self.assertTrue(
            any(
                'Failed to record webhook events in ClickHouse' in line
                for line in cm.output
            )
        )


_resolve_event_type = (
    notifications._resolve_event_type  # pyright: ignore[reportPrivateUsage]
)


class ResolveEventTypeUnitTests(helpers.TestCase):
    """Unit tests for the `_resolve_event_type` pure function."""

    def test_none_selector_returns_empty(self) -> None:
        self.assertEqual('', _resolve_event_type(None, {}, {}))

    def test_empty_selector_returns_empty(self) -> None:
        self.assertEqual('', _resolve_event_type('', {}, {}))

    def test_json_pointer_resolves(self) -> None:
        self.assertEqual(
            'opened', _resolve_event_type('/action', {'action': 'opened'}, {})
        )

    def test_json_pointer_miss_logs_and_returns_empty(self) -> None:
        with self.assertLogs(
            'imbi_gateway.notifications', level='WARNING'
        ) as cm:
            result = _resolve_event_type('/missing', {'action': 'opened'}, {})
        self.assertEqual('', result)
        self.assertTrue(any('failed to resolve' in line for line in cm.output))

    def test_json_pointer_resolves_to_none_returns_empty(self) -> None:
        self.assertEqual(
            '', _resolve_event_type('/action', {'action': None}, {})
        )

    def test_json_pointer_stringifies_non_string(self) -> None:
        self.assertEqual('42', _resolve_event_type('/n', {'n': 42}, {}))

    def test_header_present_uses_value(self) -> None:
        self.assertEqual(
            'deployment_status',
            _resolve_event_type(
                'x-github-event', {}, {'x-github-event': 'deployment_status'}
            ),
        )

    def test_header_absent_returns_literal_selector(self) -> None:
        # SonarQube case: no header named "SonarQube Notification" exists;
        # the selector itself is the stable label.
        self.assertEqual(
            'SonarQube Notification',
            _resolve_event_type('SonarQube Notification', {}, {}),
        )

    def test_header_empty_string_treated_as_absent(self) -> None:
        self.assertEqual(
            'x-github-event',
            _resolve_event_type('x-github-event', {}, {'x-github-event': ''}),
        )


_safe_headers = (
    notifications._safe_headers  # pyright: ignore[reportPrivateUsage]
)


class SafeHeadersUnitTests(helpers.TestCase):
    """Unit tests for the `_safe_headers` redaction helper."""

    def test_non_sensitive_headers_pass_through(self) -> None:
        self.assertEqual(
            {
                'content-type': 'application/json',
                'x-github-event': 'pull_request',
            },
            _safe_headers(
                {
                    'content-type': 'application/json',
                    'x-github-event': 'pull_request',
                }
            ),
        )

    def test_authorization_is_redacted(self) -> None:
        self.assertEqual(
            {'authorization': '[redacted]'},
            _safe_headers({'authorization': 'Bearer s3cret'}),
        )

    def test_signature_headers_are_redacted(self) -> None:
        result = _safe_headers(
            {
                'X-Hub-Signature-256': 'sha256=deadbeef',
                'X-PagerDuty-Signature': 'v1=abcd',
                'X-Sonar-Webhook-HMAC-SHA256': 'feedface',
            }
        )
        self.assertEqual(
            {
                'X-Hub-Signature-256': '[redacted]',
                'X-PagerDuty-Signature': '[redacted]',
                'X-Sonar-Webhook-HMAC-SHA256': '[redacted]',
            },
            result,
        )

    def test_redaction_is_case_insensitive(self) -> None:
        self.assertEqual(
            {'AUTHORIZATION': '[redacted]', 'Cookie': '[redacted]'},
            _safe_headers(
                {'AUTHORIZATION': 'Bearer s3cret', 'Cookie': 'sid=xyz'}
            ),
        )
