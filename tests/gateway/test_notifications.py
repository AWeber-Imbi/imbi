import json
import typing
import unittest.mock

import celpy
import fastapi
import httpx
import nanoid
import pydantic
from cryptography import fernet
from imbi_common import clickhouse, graph
from imbi_common.auth.encryption import TokenEncryption
from imbi_common.graph import (
    _inject_graph,  # pyright: ignore[reportPrivateUsage]
)
from imbi_common.plugins import base as plugin_base
from imbi_common.plugins import registry as plugin_registry

import imbi_gateway.app
from imbi_gateway import actions, notifications
from tests import helpers

if typing.TYPE_CHECKING:
    from collections import abc

_TOKEN = 'test-token'  # noqa: S105

#: Captures ``run_action`` invocations across tests.
ACTION_CALLS: list[dict[str, object]] = []


async def stub_action(
    *,
    ctx: plugin_base.PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: 'StubActionConfig',
    event: object,
) -> None:
    ACTION_CALLS.append(
        {
            'ctx': ctx,
            'credentials': credentials,
            'external_identifier': external_identifier,
            'action_config': action_config,
            'event': event,
        }
    )


async def raising_action(
    *,
    ctx: plugin_base.PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: 'StubActionConfig',
    event: object,
) -> None:
    del ctx, credentials, external_identifier, action_config, event
    raise RuntimeError('test error')


class StubActionConfig(pydantic.BaseModel):
    label: str = 'default'


class StubNoCredsPlugin(plugin_base.WebhookActionPlugin):
    """Stub registered for tests that need a no-credentials plugin."""

    manifest = plugin_base.PluginManifest(
        slug='stub-nocreds',
        name='Stub (no credentials)',
        plugin_type='webhook',
        credentials=[],
    )

    @classmethod
    def actions(cls) -> list[plugin_base.ActionDescriptor]:
        return [
            plugin_base.ActionDescriptor(
                name='do_thing',
                label='Do Thing',
                callable=typing.cast(
                    'typing.Any', 'tests.test_notifications:stub_action'
                ),
                config_model=typing.cast(
                    'typing.Any', 'tests.test_notifications:StubActionConfig'
                ),
            ),
            plugin_base.ActionDescriptor(
                name='boom',
                label='Boom',
                callable=typing.cast(
                    'typing.Any', 'tests.test_notifications:raising_action'
                ),
                config_model=typing.cast(
                    'typing.Any', 'tests.test_notifications:StubActionConfig'
                ),
            ),
        ]


class StubWithCredsPlugin(plugin_base.WebhookActionPlugin):
    """Stub registered for tests that exercise credential resolution."""

    manifest = plugin_base.PluginManifest(
        slug='stub-creds',
        name='Stub (with credentials)',
        plugin_type='webhook',
        credentials=[
            plugin_base.CredentialField(name='api_token', label='API Token')
        ],
    )

    @classmethod
    def actions(cls) -> list[plugin_base.ActionDescriptor]:
        return [
            plugin_base.ActionDescriptor(
                name='do_thing',
                label='Do Thing',
                callable=typing.cast(
                    'typing.Any', 'tests.test_notifications:stub_action'
                ),
                config_model=typing.cast(
                    'typing.Any', 'tests.test_notifications:StubActionConfig'
                ),
            )
        ]


class StubIdentityPlugin(plugin_base.IdentityPlugin):
    """Stub identity plugin used to satisfy registry filtering in tests."""

    manifest = plugin_base.PluginManifest(
        slug='stub-identity', name='Stub Identity', plugin_type='identity'
    )

    async def authorization_request(
        self,
        ctx: plugin_base.PluginContext,
        credentials: dict[str, str],
        redirect_uri: str,
        scopes: list[str] | None = None,
    ) -> plugin_base.AuthorizationRequest:
        del ctx, credentials, redirect_uri, scopes
        raise NotImplementedError

    async def exchange_code(
        self,
        ctx: plugin_base.PluginContext,
        credentials: dict[str, str],
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> tuple[plugin_base.IdentityProfile, plugin_base.IdentityCredentials]:
        del ctx, credentials, code, redirect_uri, code_verifier
        raise NotImplementedError

    async def refresh(
        self,
        ctx: plugin_base.PluginContext,
        credentials: dict[str, str],
        refresh_token: str,
    ) -> plugin_base.IdentityCredentials:
        del ctx, credentials, refresh_token
        raise NotImplementedError


#: Identity-typed slugs registered for tests that exercise the user
#: resolution path. ``_resolve_user_id`` filters candidate plugin slugs
#: through the registry, so every slug referenced as an identity plugin
#: must be installed with ``plugin_type='identity'`` for the existing
#: behavior to be reachable from tests.
_IDENTITY_PLUGIN_SLUGS = ('github', 'gitlab', 'stub-identity')


def _install_stub_plugins() -> None:
    """Pre-populate the registry with stub plugins used across tests."""
    _registry: dict[str, plugin_registry.RegistryEntry] = (
        plugin_registry._registry  # pyright: ignore[reportPrivateUsage]
    )
    for cls in (StubNoCredsPlugin, StubWithCredsPlugin):
        _registry[cls.manifest.slug] = plugin_registry.RegistryEntry(
            handler_cls=cls,
            manifest=cls.manifest,
            package_name='tests',
            package_version='0.0.0',
        )
    for slug in _IDENTITY_PLUGIN_SLUGS:
        _registry[slug] = plugin_registry.RegistryEntry(
            handler_cls=StubIdentityPlugin,
            manifest=plugin_base.PluginManifest(
                slug=slug, name=f'Stub {slug}', plugin_type='identity'
            ),
            package_name='tests',
            package_version='0.0.0',
        )


def _uninstall_stub_plugins() -> None:
    _registry: dict[str, plugin_registry.RegistryEntry] = (
        plugin_registry._registry  # pyright: ignore[reportPrivateUsage]
    )
    for slug in ('stub-nocreds', 'stub-creds', *_IDENTITY_PLUGIN_SLUGS):
        _registry.pop(slug, None)


class WebhookRuleUnitTests(helpers.TestCase):
    _VALID_RULE: typing.ClassVar[dict[str, object]] = {
        'handler': 'stub-nocreds#do_thing',
        'ordinal': 1,
        'handler_config': '{}',
        'filter_expression': 'true',
    }

    def test_valid_handler_exposes_slug_and_action(self) -> None:
        rule = notifications.WebhookRule.model_validate(self._VALID_RULE)
        self.assertEqual('stub-nocreds', rule.plugin_slug)
        self.assertEqual('do_thing', rule.action_name)

    def test_handler_without_separator_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            notifications.WebhookRule.model_validate(
                {**self._VALID_RULE, 'handler': 'no-separator'}
            )

    def test_handler_with_empty_slug_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            notifications.WebhookRule.model_validate(
                {**self._VALID_RULE, 'handler': '#do_thing'}
            )

    def test_handler_with_empty_action_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            notifications.WebhookRule.model_validate(
                {**self._VALID_RULE, 'handler': 'stub-nocreds#'}
            )

    def test_handler_dotted_path_rejected(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            notifications.WebhookRule.model_validate(
                {
                    **self._VALID_RULE,
                    'handler': 'imbi_gateway.actions:update_project',
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
        ACTION_CALLS.clear()

        self.org_id = nanoid.generate()
        self.org_slug = f'org-{self.org_id[:8]}'
        self.webhook_id = nanoid.generate()
        self.tps_slug = f'tps-{nanoid.generate()[:8]}'
        self.proj_id = nanoid.generate()
        self.ext_id = f'ext-{nanoid.generate()[:8]}'
        self.rule_ids: list[str] = []
        self.plugin_ids: list[str] = []
        self.extra_project_ids: list[str] = []

        self.g = graph.Graph()
        await self.g.open()

        # create_app() calls plugin_registry.load_plugins() which wipes
        # the registry, so the stub plugins must be installed *after*
        # the app has been built.
        self.app = imbi_gateway.app.create_app()
        _install_stub_plugins()

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
            'CREATE (n:ThirdPartyService {{slug: {slug},'
            ' name: {name}, created_at: {ts}}}) RETURN n',
            {'slug': self.tps_slug, 'name': 'Test Service', 'ts': ts},
            ['n'],
        )
        await self.g.execute(
            'MATCH (tps:ThirdPartyService {{slug: {tslug}}}),'
            ' (o:Organization {{id: {oid}}})'
            ' CREATE (tps)-[:BELONGS_TO]->(o) RETURN tps',
            {'tslug': self.tps_slug, 'oid': self.org_id},
            ['tps'],
        )
        await self.g.execute(
            'MATCH (w:Webhook {{id: {wid}}}),'
            ' (tps:ThirdPartyService {{slug: {tslug}}})'
            ' CREATE (w)-[:IMPLEMENTED_BY'
            ' {{identifier_selector: {sel}}}]->(tps)'
            ' RETURN w',
            {
                'wid': self.webhook_id,
                'tslug': self.tps_slug,
                'sel': '/repo/id',
            },
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
            ' (tps:ThirdPartyService {{slug: {tslug}}})'
            ' CREATE (p)-[:EXISTS_IN {{identifier: {ext_id}}}]->(tps)'
            ' RETURN p',
            {
                'pid': self.proj_id,
                'tslug': self.tps_slug,
                'ext_id': self.ext_id,
            },
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
        for plugin_id in self.plugin_ids:
            await self.g.execute(
                'MATCH (n:Plugin {{id: {id}}}) DETACH DELETE n RETURN 1 AS r',
                {'id': plugin_id},
                ['r'],
            )
        for project_id in self.extra_project_ids:
            await self.g.execute(
                'MATCH (n:Project {{id: {id}}}) DETACH DELETE n RETURN 1 AS r',
                {'id': project_id},
                ['r'],
            )
        await self.g.execute(
            'MATCH (n:ThirdPartyService {{slug: {slug}}})'
            ' DETACH DELETE n RETURN 1 AS r',
            {'slug': self.tps_slug},
            ['r'],
        )
        for label, node_id in [
            ('Project', self.proj_id),
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
        _uninstall_stub_plugins()

    async def _add_rule(
        self,
        *,
        handler: str = 'stub-nocreds#do_thing',
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

    async def _attach_plugin(
        self,
        slug: str,
        *,
        plugin_configuration: str | None = None,
        options: dict[str, typing.Any] | None = None,
    ) -> str:
        plugin_id = nanoid.generate()
        self.plugin_ids.append(plugin_id)
        ts = '2024-01-01T00:00:00+00:00'
        if plugin_configuration is None:
            await self.g.execute(
                'CREATE (p:Plugin {{id: {id}, plugin_slug: {slug},'
                ' label: {slug}, created_at: {ts}}}) RETURN p',
                {'id': plugin_id, 'slug': slug, 'ts': ts},
                ['p'],
            )
        else:
            await self.g.execute(
                'CREATE (p:Plugin {{id: {id}, plugin_slug: {slug},'
                ' label: {slug}, created_at: {ts},'
                ' plugin_configuration: {cfg}}}) RETURN p',
                {
                    'id': plugin_id,
                    'slug': slug,
                    'ts': ts,
                    'cfg': plugin_configuration,
                },
                ['p'],
            )
        if options is not None:
            await self.g.execute(
                'MATCH (p:Plugin {{id: {id}}}) SET p.options = {opts}'
                ' RETURN p',
                {'id': plugin_id, 'opts': options},
                ['p'],
            )
        await self.g.execute(
            'MATCH (p:Plugin {{id: {pid}}}),'
            ' (tps:ThirdPartyService {{slug: {tslug}}})'
            ' CREATE (tps)-[:HAS_PLUGIN]->(p) RETURN p',
            {'pid': plugin_id, 'tslug': self.tps_slug},
            ['p'],
        )
        return plugin_id

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

    async def _create_extra_project(self) -> str:
        project_id = nanoid.generate()
        self.extra_project_ids.append(project_id)
        ts = '2024-01-01T00:00:00+00:00'
        await self.g.execute(
            'CREATE (n:Project {{id: {id}, slug: {slug},'
            ' name: {name}, created_at: {ts}}}) RETURN n',
            {
                'id': project_id,
                'slug': f'proj-{project_id[:8]}',
                'name': 'Second Project',
                'ts': ts,
            },
            ['n'],
        )
        await self.g.execute(
            'MATCH (p:Project {{id: {pid}}}),'
            ' (tps:ThirdPartyService {{slug: {tslug}}})'
            ' CREATE (p)-[:EXISTS_IN {{identifier: {ext_id}}}]->(tps)'
            ' RETURN p',
            {'pid': project_id, 'tslug': self.tps_slug, 'ext_id': self.ext_id},
            ['p'],
        )
        return project_id

    async def test_no_webhook_found(self) -> None:
        with self.assertLogs(
            'imbi_gateway.notifications', level='WARNING'
        ) as cm:
            response = await self._post(nanoid.generate(), {})
        self.assertEqual(204, response.status_code)
        self.assertEqual([], ACTION_CALLS)
        self.assertTrue(any('No records found' in line for line in cm.output))

    async def test_no_rules_empty_collect(self) -> None:
        body = {'repo': {'id': self.ext_id}}
        response = await self._post(self.webhook_id, body)
        self.assertEqual(204, response.status_code)
        self.assertEqual([], ACTION_CALLS)

    async def test_no_service_global_webhook_not_implemented(self) -> None:
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
            self.assertEqual([], ACTION_CALLS)
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
        self.assertEqual([], ACTION_CALLS)
        self.assertTrue(any('no filter matches' in line for line in cm.output))

    async def test_handler_called_when_condition_matches(self) -> None:
        await self._add_rule(filter_expression='true')
        body = {'repo': {'id': self.ext_id}}
        response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        self.assertEqual(1, len(ACTION_CALLS))
        call = ACTION_CALLS[0]
        ctx = typing.cast('plugin_base.PluginContext', call['ctx'])
        self.assertEqual(self.org_slug, ctx.org_slug)
        self.assertEqual(self.proj_id, ctx.project_id)
        self.assertEqual(f'proj-{self.proj_id[:8]}', ctx.project_slug)
        event = typing.cast('dict[str, typing.Any]', call['event'])
        self.assertEqual(body, event['payload'])
        self.assertEqual({}, call['credentials'])
        self.assertEqual(self.ext_id, call['external_identifier'])
        self.assertIsNone(ctx.actor_user_id)

    async def test_filter_matches_on_request_header(self) -> None:
        await self._add_rule(
            filter_expression='metadata.headers["x-github-event"] == "push"'
        )
        body = {'repo': {'id': self.ext_id}}
        response = await self._post(
            self.webhook_id, body, headers={'X-GitHub-Event': 'push'}
        )
        self.assertEqual(202, response.status_code)
        self.assertEqual(1, len(ACTION_CALLS))

    async def test_filter_skips_on_non_matching_header(self) -> None:
        await self._add_rule(
            filter_expression='metadata.headers["x-github-event"] == "push"'
        )
        body = {'repo': {'id': self.ext_id}}
        response = await self._post(
            self.webhook_id, body, headers={'X-GitHub-Event': 'deployment'}
        )
        self.assertEqual(204, response.status_code)
        self.assertEqual([], ACTION_CALLS)

    async def test_filter_matches_on_resolved_event_type(self) -> None:
        await self._set_implemented_by(event_type_selector='x-github-event')
        await self._add_rule(filter_expression='type == "push"')
        body = {'repo': {'id': self.ext_id}}
        response = await self._post(
            self.webhook_id, body, headers={'X-GitHub-Event': 'push'}
        )
        self.assertEqual(202, response.status_code)
        self.assertEqual(1, len(ACTION_CALLS))

    async def test_filter_matches_on_payload_field(self) -> None:
        await self._add_rule(filter_expression='payload.action == "opened"')
        body = {'repo': {'id': self.ext_id}, 'action': 'opened'}
        response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        self.assertEqual(1, len(ACTION_CALLS))

    async def test_connected_plugin_options_reach_context(self) -> None:
        with self.override_environment(
            IMBI_AUTH_ENCRYPTION_KEY=fernet.Fernet.generate_key().decode()
        ):
            TokenEncryption.reset_instance()
            try:
                encrypted = TokenEncryption.get_instance().encrypt(
                    json.dumps({'api_token': 's3cret'})
                )
                await self._attach_plugin(
                    'stub-creds',
                    plugin_configuration=encrypted,
                    options={'host': 'example.ghe.com', 'flavor': 'ghec'},
                )
                await self._add_rule(handler='stub-creds#do_thing')
                body = {'repo': {'id': self.ext_id}}
                response = await self._post(self.webhook_id, body)
                self.assertEqual(202, response.status_code)
                self.assertEqual(1, len(ACTION_CALLS))
                ctx = typing.cast(
                    'plugin_base.PluginContext', ACTION_CALLS[0]['ctx']
                )
                by_slug = {sp.slug: sp for sp in ctx.service_plugins}
                self.assertIn('stub-creds', by_slug)
                self.assertEqual(
                    {'host': 'example.ghe.com', 'flavor': 'ghec'},
                    by_slug['stub-creds'].options,
                )
                # The non-secret options surface, never the credential blob.
                for sp in ctx.service_plugins:
                    self.assertNotIn('plugin_configuration', sp.options)
                    self.assertNotIn('api_token', sp.options)
            finally:
                TokenEncryption.reset_instance()

    async def test_handler_called_for_each_matching_project(self) -> None:
        await self._add_rule(filter_expression='true')
        second_proj_id = await self._create_extra_project()
        body = {'repo': {'id': self.ext_id}}
        response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        self.assertEqual(2, len(ACTION_CALLS))
        project_ids = {
            typing.cast('plugin_base.PluginContext', call['ctx']).project_id
            for call in ACTION_CALLS
        }
        self.assertEqual({self.proj_id, second_proj_id}, project_ids)

    async def test_project_not_found_for_external_id(self) -> None:
        await self._add_rule(filter_expression='true')
        body = {'repo': {'id': 'no-such-external-id'}}
        with self.assertLogs(
            'imbi_gateway.notifications', level='WARNING'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(204, response.status_code)
        self.assertEqual([], ACTION_CALLS)
        self.assertTrue(any('no project found' in line for line in cm.output))

    async def test_unknown_plugin_slug_logs_error_and_skips(self) -> None:
        await self._add_rule(handler='no-such-plugin#do_thing')
        body = {'repo': {'id': self.ext_id}}
        with self.assertLogs(
            'imbi_gateway.notifications', level='ERROR'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        # Dispatcher logs and skips the rule; events were recorded so 202.
        self.assertEqual(202, response.status_code)
        self.assertEqual([], ACTION_CALLS)
        self.assertTrue(any('Unknown plugin' in line for line in cm.output))

    async def test_unknown_action_name_logs_error_and_skips(self) -> None:
        await self._add_rule(handler='stub-nocreds#missing_action')
        body = {'repo': {'id': self.ext_id}}
        with self.assertLogs(
            'imbi_gateway.notifications', level='ERROR'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        self.assertEqual([], ACTION_CALLS)
        self.assertTrue(
            any('does not expose action' in line for line in cm.output)
        )

    async def test_invalid_handler_string_fails_rule_validation(self) -> None:
        # A handler that doesn't match the `#` shape fails WebhookRule
        # validation, causing the whole batch to be skipped with an error.
        await self._add_rule(handler='does.not.exist.handler')
        body = {'repo': {'id': self.ext_id}}
        with self.assertLogs(
            'imbi_gateway.notifications', level='ERROR'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(204, response.status_code)
        self.assertEqual([], ACTION_CALLS)
        self.assertTrue(
            any('failed to deserialize rules' in line for line in cm.output)
        )

    async def test_invalid_handler_config_logs_and_skips(self) -> None:
        await self._add_rule(handler_config='not valid json')
        body = {'repo': {'id': self.ext_id}}
        with self.assertLogs(
            'imbi_gateway.notifications', level='ERROR'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        self.assertEqual([], ACTION_CALLS)
        self.assertTrue(
            any('Invalid handler_config' in line for line in cm.output)
        )

    async def test_plugin_requiring_credentials_skipped_when_unattached(
        self,
    ) -> None:
        await self._add_rule(handler='stub-creds#do_thing')
        body = {'repo': {'id': self.ext_id}}
        with self.assertLogs(
            'imbi_gateway.notifications', level='WARNING'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        self.assertEqual([], ACTION_CALLS)
        self.assertTrue(
            any(
                'requires credentials' in line and 'stub-creds' in line
                for line in cm.output
            )
        )

    async def test_plugin_actions_failure_logs_and_skips_rule(self) -> None:
        # If a plugin's ``actions()`` raises (third-party code we cannot
        # trust), the dispatcher logs and skips that rule instead of
        # aborting delivery for every sibling rule.
        def _boom(
            cls: type[StubNoCredsPlugin],
        ) -> list[plugin_base.ActionDescriptor]:
            del cls
            raise RuntimeError('boom in actions()')

        await self._add_rule(handler='stub-nocreds#do_thing')
        body = {'repo': {'id': self.ext_id}}
        with (
            unittest.mock.patch.object(
                StubNoCredsPlugin, 'actions', classmethod(_boom)
            ),
            self.assertLogs('imbi_gateway.notifications', level='ERROR') as cm,
        ):
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        self.assertEqual([], ACTION_CALLS)
        self.assertTrue(
            any(
                'raised while enumerating actions' in line
                and 'stub-nocreds' in line
                for line in cm.output
            )
        )

    async def test_plugin_skipped_when_credentials_cannot_be_loaded(
        self,
    ) -> None:
        # A plugin row whose ``plugin_configuration`` cannot be decrypted
        # is treated like an unattached plugin -- the rule is skipped
        # rather than invoked with an empty credentials dict.
        await self._attach_plugin(
            'stub-creds', plugin_configuration='not-a-valid-ciphertext'
        )
        await self._add_rule(handler='stub-creds#do_thing')
        body = {'repo': {'id': self.ext_id}}
        with self.assertLogs(
            'imbi_gateway.notifications', level='WARNING'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        self.assertEqual([], ACTION_CALLS)
        self.assertTrue(
            any(
                'none could be loaded' in line and 'stub-creds' in line
                for line in cm.output
            )
        )

    async def test_plugin_with_credentials_receives_decrypted_blob(
        self,
    ) -> None:
        with self.override_environment(
            IMBI_AUTH_ENCRYPTION_KEY=fernet.Fernet.generate_key().decode()
        ):
            TokenEncryption.reset_instance()
            try:
                encrypted = TokenEncryption.get_instance().encrypt(
                    json.dumps({'api_token': 's3cret'})
                )
                await self._attach_plugin(
                    'stub-creds', plugin_configuration=encrypted
                )
                await self._add_rule(handler='stub-creds#do_thing')
                body = {'repo': {'id': self.ext_id}}
                response = await self._post(self.webhook_id, body)
                self.assertEqual(202, response.status_code)
                self.assertEqual(1, len(ACTION_CALLS))
                self.assertEqual(
                    {'api_token': 's3cret'}, ACTION_CALLS[0]['credentials']
                )
            finally:
                TokenEncryption.reset_instance()

    async def test_identifier_pointer_not_in_body(self) -> None:
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
        await self._add_rule(filter_expression='true')
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
            ' (tps:ThirdPartyService {{slug: {tslug}}})'
            ' CREATE (w)-[:IMPLEMENTED_BY {{'
            'identifier_selector: {sel},'
            ' user_subject_selector: {uss},'
            ' identity_plugin_slug: {ips},'
            ' event_type_selector: {ets}'
            '}}]->(tps) RETURN w',
            {
                'wid': self.webhook_id,
                'tslug': self.tps_slug,
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
        self.assertEqual(1, len(ACTION_CALLS))
        ctx = typing.cast('plugin_base.PluginContext', ACTION_CALLS[0]['ctx'])
        self.assertEqual('alice@example.com', ctx.actor_user_id)

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
        ctx = typing.cast('plugin_base.PluginContext', ACTION_CALLS[0]['ctx'])
        self.assertIsNone(ctx.actor_user_id)

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
        ctx = typing.cast('plugin_base.PluginContext', ACTION_CALLS[0]['ctx'])
        self.assertIsNone(ctx.actor_user_id)

    async def test_user_subject_selector_resolves_to_empty_string(
        self,
    ) -> None:
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
        ctx = typing.cast('plugin_base.PluginContext', ACTION_CALLS[0]['ctx'])
        self.assertIsNone(ctx.actor_user_id)

    async def test_user_subject_selector_no_candidate_plugins(self) -> None:
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
        ctx = typing.cast('plugin_base.PluginContext', ACTION_CALLS[0]['ctx'])
        self.assertIsNone(ctx.actor_user_id)

    async def test_non_identity_plugin_skipped_during_user_resolution(
        self,
    ) -> None:
        """Non-identity attached plugins are not probed for users.

        The gateway used to call ``/users/by-identity`` for every plugin
        attached to the TPS, generating 404 noise for webhook /
        configuration / deployment plugins. After the refactor only
        plugins registered with ``plugin_type='identity'`` are queried.
        """
        await self._add_rule(filter_expression='true')
        await self._set_implemented_by(user_subject_selector='/sender/id')
        await self._attach_plugin('stub-nocreds')
        await self._attach_plugin('github')
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
        ctx = typing.cast('plugin_base.PluginContext', ACTION_CALLS[0]['ctx'])
        self.assertEqual('alice@example.com', ctx.actor_user_id)

    async def test_user_resolution_two_distinct_users_logs_error(self) -> None:
        await self._add_rule(filter_expression='true')
        await self._set_implemented_by(user_subject_selector='/sender/id')
        ts = '2024-01-01T00:00:00+00:00'
        plugin_ids = [nanoid.generate(), nanoid.generate()]
        self.plugin_ids.extend(plugin_ids)
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
                ' (tps:ThirdPartyService {{slug: {tslug}}})'
                ' CREATE (tps)-[:HAS_PLUGIN]->(p) RETURN p',
                {'pid': plugin_id, 'tslug': self.tps_slug},
                ['p'],
            )

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
            self.assertLogs('imbi_gateway.notifications', level='ERROR') as cm,
        ):
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        ctx = typing.cast('plugin_base.PluginContext', ACTION_CALLS[0]['ctx'])
        self.assertIsNone(ctx.actor_user_id)
        self.assertTrue(
            any('multiple Imbi users' in line for line in cm.output)
        )

    async def test_handler_exception_is_caught(self) -> None:
        await self._add_rule(handler='stub-nocreds#boom')
        body = {'repo': {'id': self.ext_id}}
        with self.assertLogs(
            'imbi_gateway.notifications', level='ERROR'
        ) as cm:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        self.assertTrue(
            any('Failure executing rule' in line for line in cm.output)
        )

    async def test_event_recorded_for_each_matching_project(self) -> None:
        await self._add_rule(filter_expression='true')
        await self._set_implemented_by(event_type_selector='x-github-event')
        second_proj_id = await self._create_extra_project()
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
        self.assertEqual(2, len(events_arg))
        self.assertEqual(
            {self.proj_id, second_proj_id},
            {ev.project_id for ev in events_arg},
        )
        for ev in events_arg:
            self.assertEqual('deployment_status', ev.type)
            self.assertEqual(body, ev.payload)
            self.assertEqual(self.webhook_id, ev.metadata['webhook_id'])
            self.assertEqual(
                'deployment_status',
                ev.metadata['headers'].get('x-github-event'),
            )

    async def test_event_recorded_when_filter_does_not_match(self) -> None:
        await self._add_rule(filter_expression='false')
        body = {'repo': {'id': self.ext_id}}
        with unittest.mock.patch.object(
            clickhouse, 'insert', new=unittest.mock.AsyncMock()
        ) as mock_insert:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(204, response.status_code)
        self.assertEqual([], ACTION_CALLS)
        mock_insert.assert_awaited_once()
        assert mock_insert.await_args is not None  # noqa: S101 - test narrowing
        table_arg, events_arg = mock_insert.await_args.args
        self.assertEqual('events', table_arg)
        self.assertEqual(1, len(events_arg))
        self.assertEqual(self.proj_id, events_arg[0].project_id)

    async def test_no_event_when_no_project_matches(self) -> None:
        await self._add_rule(filter_expression='true')
        body = {'repo': {'id': 'no-such-external-id'}}
        with unittest.mock.patch.object(
            clickhouse, 'insert', new=unittest.mock.AsyncMock()
        ) as mock_insert:
            response = await self._post(self.webhook_id, body)
        self.assertEqual(204, response.status_code)
        mock_insert.assert_not_awaited()

    async def test_access_log_context_includes_user_id_and_event(self) -> None:
        await self._add_rule(filter_expression='true')
        await self._set_implemented_by(
            user_subject_selector='/sender/id',
            identity_plugin_slug='github',
            event_type_selector='x-github-event',
        )
        body = {'repo': {'id': self.ext_id}, 'sender': {'id': 12345}}
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'find_user_by_identity',
                new=unittest.mock.AsyncMock(return_value='alice@example.com'),
            ),
            unittest.mock.patch.object(
                clickhouse, 'insert', new=unittest.mock.AsyncMock()
            ),
            self.assertLogs('imbi_common.access', level='INFO') as cm,
        ):
            response = await self._post(
                self.webhook_id,
                body,
                headers={'X-GitHub-Event': 'pull_request'},
            )
        self.assertEqual(202, response.status_code)
        access_line = cm.records[0].getMessage()
        self.assertIn('user_id:alice@example.com', access_line)
        self.assertIn('event:pull_request', access_line)

    async def test_access_log_context_omitted_when_no_user_or_event(
        self,
    ) -> None:
        await self._add_rule(filter_expression='true')
        body = {'repo': {'id': self.ext_id}}
        with (
            unittest.mock.patch.object(
                clickhouse, 'insert', new=unittest.mock.AsyncMock()
            ),
            self.assertLogs('imbi_common.access', level='INFO') as cm,
        ):
            response = await self._post(self.webhook_id, body)
        self.assertEqual(202, response.status_code)
        access_line = cm.records[0].getMessage()
        self.assertNotIn('user_id:', access_line)
        self.assertNotIn('event:', access_line)
        self.assertNotIn('(', access_line)

    async def test_access_log_context_includes_only_event_when_no_user(
        self,
    ) -> None:
        await self._add_rule(filter_expression='true')
        await self._set_implemented_by(event_type_selector='x-github-event')
        body = {'repo': {'id': self.ext_id}}
        with (
            unittest.mock.patch.object(
                clickhouse, 'insert', new=unittest.mock.AsyncMock()
            ),
            self.assertLogs('imbi_common.access', level='INFO') as cm,
        ):
            response = await self._post(
                self.webhook_id, body, headers={'X-GitHub-Event': 'ping'}
            )
        self.assertEqual(202, response.status_code)
        access_line = cm.records[0].getMessage()
        self.assertNotIn('user_id:', access_line)
        self.assertIn('event:ping', access_line)

    async def test_event_insert_failure_does_not_block_handlers(self) -> None:
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
        self.assertEqual(1, len(ACTION_CALLS))
        self.assertTrue(
            any(
                'Failed to record webhook events in ClickHouse' in line
                for line in cm.output
            )
        )


_set_access_log_context = (
    notifications._set_access_log_context  # pyright: ignore[reportPrivateUsage]
)


class SetAccessLogContextUnitTests(helpers.TestCase):
    """Unit tests for the `_set_access_log_context` helper."""

    def _make_request(
        self, initial: dict[str, str] | None = None
    ) -> fastapi.Request:
        scope: dict[str, typing.Any] = {'type': 'http', 'state': {}}
        if initial is not None:
            scope['state']['imbi_common_access_log'] = initial
        return fastapi.Request(scope)

    def test_sets_both_values_when_state_is_empty(self) -> None:
        request = self._make_request()
        _set_access_log_context(request, user_id='alice', event='ping')
        self.assertEqual(
            {'user_id': 'alice', 'event': 'ping'},
            request.state.imbi_common_access_log,
        )

    def test_merges_with_existing_context(self) -> None:
        request = self._make_request({'request_id': 'r-1'})
        _set_access_log_context(request, user_id='alice', event='ping')
        self.assertEqual(
            {'request_id': 'r-1', 'user_id': 'alice', 'event': 'ping'},
            request.state.imbi_common_access_log,
        )

    def test_existing_key_is_overwritten(self) -> None:
        request = self._make_request({'event': 'stale'})
        _set_access_log_context(request, user_id=None, event='fresh')
        self.assertEqual(
            {'event': 'fresh'}, request.state.imbi_common_access_log
        )

    def test_no_updates_leaves_state_untouched(self) -> None:
        request = self._make_request({'request_id': 'r-1'})
        _set_access_log_context(request, user_id=None, event='')
        self.assertEqual(
            {'request_id': 'r-1'}, request.state.imbi_common_access_log
        )

    def test_skips_empty_user_and_event(self) -> None:
        request = self._make_request()
        _set_access_log_context(request, user_id=None, event='')
        self.assertFalse(hasattr(request.state, 'imbi_common_access_log'))


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


_sanitize_utf8 = (
    notifications._sanitize_utf8  # pyright: ignore[reportPrivateUsage]
)
_extract_json_body = (
    notifications._extract_json_body  # pyright: ignore[reportPrivateUsage]
)


class _FakeBodyRequest:
    """Minimal stand-in exposing the ``body()`` coroutine."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    async def body(self) -> bytes:
        return self._raw


class Utf8SanitizationTests(helpers.TestCase):
    def test_replaces_lone_surrogate_in_string(self) -> None:
        cleaned = typing.cast('str', _sanitize_utf8('hi \ud83d there'))
        cleaned.encode('utf-8')  # must not raise
        self.assertNotIn('\ud83d', cleaned)

    def test_recurses_dicts_lists_and_keys(self) -> None:
        payload = {
            'msg': 'a\ud800b',
            'nested': [{'k\ud801': 'v\ud802'}],
            'count': 3,
            'flag': True,
            'none': None,
        }
        cleaned = typing.cast('dict[str, typing.Any]', _sanitize_utf8(payload))
        json.dumps(cleaned).encode('utf-8')  # whole tree now encodable
        self.assertEqual(3, cleaned['count'])
        self.assertIs(True, cleaned['flag'])
        self.assertIsNone(cleaned['none'])
        inner_key = next(iter(cleaned['nested'][0]))
        inner_key.encode('utf-8')
        self.assertNotIn('\ud801', inner_key)

    def test_scalars_pass_through(self) -> None:
        self.assertEqual(42, _sanitize_utf8(42))
        self.assertIsNone(_sanitize_utf8(None))

    async def test_extract_body_accepts_non_utf8_bytes(self) -> None:
        # cp1252 smart quote 0x92 is invalid UTF-8; lenient decode keeps
        # the request from 422ing and the value is stored as clean UTF-8.
        raw = (
            json.dumps({'msg': 'X'})
            .encode('utf-8')
            .replace(b'X', b'hi\x92there')
        )
        request = typing.cast('fastapi.Request', _FakeBodyRequest(raw))
        body = await _extract_json_body(request)
        json.dumps(body).encode('utf-8')  # encodable
        self.assertIsInstance(body, dict)

    async def test_extract_body_invalid_json_still_422(self) -> None:
        request = typing.cast('fastapi.Request', _FakeBodyRequest(b'not json'))
        with self.assertRaises(fastapi.HTTPException) as ctx:
            await _extract_json_body(request)
        self.assertEqual(422, ctx.exception.status_code)


_make_user_resolver = (
    notifications._make_user_resolver  # pyright: ignore[reportPrivateUsage]
)


class MakeUserResolverUnitTests(helpers.TestCase):
    """Coverage for the ``PluginContext.resolve_user_by_identity`` factory.

    The factory builds the coroutine an action (e.g. commit-sync author
    attribution) uses to map an identity subject to an Imbi user email,
    reusing the same identity-plugin filtering and multi-match handling as
    the gateway's own delivery-actor resolution.
    """

    def test_no_identity_plugins_returns_none(self) -> None:
        with unittest.mock.patch.object(
            notifications, '_filter_to_identity_plugins', return_value=[]
        ):
            self.assertIsNone(_make_user_resolver(['stub-nocreds']))

    async def test_resolves_subject_to_email(self) -> None:
        with (
            unittest.mock.patch.object(
                notifications,
                '_filter_to_identity_plugins',
                return_value=['github'],
            ),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'find_user_by_identity',
                new=unittest.mock.AsyncMock(return_value='alice@example.com'),
            ) as mock_lookup,
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
        ):
            resolver = _make_user_resolver(['github'])
            if resolver is None:
                self.fail('expected a resolver, got None')
            self.assertEqual('alice@example.com', await resolver('42'))
        mock_lookup.assert_awaited_once_with('github', '42')

    async def test_unmatched_subject_returns_none(self) -> None:
        with (
            unittest.mock.patch.object(
                notifications,
                '_filter_to_identity_plugins',
                return_value=['github'],
            ),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'find_user_by_identity',
                new=unittest.mock.AsyncMock(return_value=None),
            ),
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
        ):
            resolver = _make_user_resolver(['github'])
            if resolver is None:
                self.fail('expected a resolver, got None')
            self.assertIsNone(await resolver('99'))

    async def test_multiple_distinct_matches_logs_and_returns_none(
        self,
    ) -> None:
        with (
            unittest.mock.patch.object(
                notifications,
                '_filter_to_identity_plugins',
                return_value=['github', 'gitlab'],
            ),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'find_user_by_identity',
                new=unittest.mock.AsyncMock(
                    side_effect=['a@example.com', 'b@example.com']
                ),
            ),
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
        ):
            resolver = _make_user_resolver(['github', 'gitlab'])
            if resolver is None:
                self.fail('expected a resolver, got None')
            with self.assertLogs(notifications.LOGGER, level='ERROR'):
                self.assertIsNone(await resolver('1'))
