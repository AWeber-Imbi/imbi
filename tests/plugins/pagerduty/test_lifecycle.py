"""Tests for the PagerDuty lifecycle plugin."""

import os
import typing
import unittest
import unittest.mock

import httpx
import respx
from cryptography import fernet
from imbi_common.auth.encryption import TokenEncryption
from imbi_common.plugins.base import PluginContext

from imbi_plugin_pagerduty.lifecycle import PagerDutyLifecycle

_CREDS = {'api_key': 'k'}
_SERVICE = {
    'id': 'PSVC1',
    'html_url': 'https://acme.pagerduty.com/service-directory/PSVC1',
}
_LINK = {'pagerduty-service': _SERVICE['html_url']}


def _ctx(
    *,
    options: dict[str, object] | None = None,
    team_slug: str | None = 'platform',
    previous_team_slug: str | None = None,
    links: dict[str, str] | None = None,
) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug='demo',
        org_slug='org',
        team_slug=team_slug,
        previous_team_slug=previous_team_slug,
        integration_options=options
        if options is not None
        else {'team_escalation_policy_mapping': {'platform': 'POLICY1'}},
        project_links=links or {},
    )


class _EncryptionTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        key = fernet.Fernet.generate_key().decode()
        patcher = unittest.mock.patch.dict(
            os.environ, {'IMBI_AUTH_ENCRYPTION_KEY': key}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        TokenEncryption.reset_instance()
        self.addCleanup(TokenEncryption.reset_instance)


class CreateTestCase(_EncryptionTestCase):
    @respx.mock
    async def test_creates_service_and_subscription(self) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(200, json={'services': []})
        )
        respx.post('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(201, json={'service': _SERVICE})
        )
        respx.post('https://api.pagerduty.com/webhook_subscriptions').mock(
            return_value=httpx.Response(
                201,
                json={
                    'webhook_subscription': {
                        'id': 'PSUB1',
                        'delivery_method': {'secret': 'whsecret'},
                    }
                },
            )
        )
        ctx = _ctx(
            options={
                'team_escalation_policy_mapping': {'platform': 'POLICY1'},
                'gateway_webhook_url': 'https://gw/notifications/wh1',
            }
        )
        result = await PagerDutyLifecycle().on_project_created(ctx, _CREDS)
        self.assertEqual(result.status, 'ok')
        assert ctx.service_writeback is not None
        self.assertEqual(ctx.service_writeback.identifier, 'PSVC1')
        self.assertEqual(
            ctx.service_writeback.dashboard_links['pagerduty-service'],
            _SERVICE['html_url'],
        )
        enc = ctx.service_writeback.webhook_secret_enc
        assert enc is not None
        self.assertEqual(
            TokenEncryption.get_instance().decrypt(enc), 'whsecret'
        )

    @respx.mock
    async def test_skipped_when_no_policy(self) -> None:
        ctx = _ctx(options={'team_escalation_policy_mapping': {}})
        result = await PagerDutyLifecycle().on_project_created(ctx, _CREDS)
        self.assertEqual(result.status, 'skipped')
        self.assertIsNone(ctx.service_writeback)

    @respx.mock
    async def test_adopts_existing_service(self) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(
                200, json={'services': [{**_SERVICE, 'name': 'demo'}]}
            )
        )
        ctx = _ctx()
        result = await PagerDutyLifecycle().on_project_created(ctx, _CREDS)
        self.assertEqual(result.status, 'skipped')
        assert ctx.service_writeback is not None
        self.assertEqual(ctx.service_writeback.identifier, 'PSVC1')

    @respx.mock
    async def test_create_without_gateway_url_skips_subscription(
        self,
    ) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(200, json={'services': []})
        )
        respx.post('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(201, json={'service': _SERVICE})
        )
        sub = respx.post(
            'https://api.pagerduty.com/webhook_subscriptions'
        ).mock(return_value=httpx.Response(201, json={}))
        ctx = _ctx()
        result = await PagerDutyLifecycle().on_project_created(ctx, _CREDS)
        self.assertEqual(result.status, 'ok')
        self.assertFalse(sub.called)
        assert ctx.service_writeback is not None
        self.assertIsNone(ctx.service_writeback.webhook_secret_enc)


class UpdateTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_updates_existing_service(self) -> None:
        route = respx.put('https://api.pagerduty.com/services/PSVC1').mock(
            return_value=httpx.Response(200, json={'service': _SERVICE})
        )
        ctx = _ctx(links=_LINK)
        result = await PagerDutyLifecycle().on_project_updated(ctx, _CREDS)
        self.assertEqual(result.status, 'ok')
        self.assertTrue(route.called)
        assert ctx.service_writeback is not None
        self.assertEqual(ctx.service_writeback.identifier, 'PSVC1')


class DeleteTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_deletes_subscription_and_service(self) -> None:
        respx.get('https://api.pagerduty.com/webhook_subscriptions').mock(
            return_value=httpx.Response(
                200,
                json={
                    'webhook_subscriptions': [
                        {
                            'id': 'PSUB1',
                            'filter': {
                                'type': 'service_reference',
                                'id': 'PSVC1',
                            },
                        }
                    ]
                },
            )
        )
        del_sub = respx.delete(
            'https://api.pagerduty.com/webhook_subscriptions/PSUB1'
        ).mock(return_value=httpx.Response(204))
        del_svc = respx.delete(
            'https://api.pagerduty.com/services/PSVC1'
        ).mock(return_value=httpx.Response(204))
        ctx = _ctx(links=_LINK)
        result = await PagerDutyLifecycle().on_project_deleted(ctx, _CREDS)
        self.assertEqual(result.status, 'ok')
        self.assertTrue(del_sub.called)
        self.assertTrue(del_svc.called)
        assert ctx.service_writeback is not None
        self.assertTrue(ctx.service_writeback.remove)

    @respx.mock
    async def test_missing_service_404_skipped(self) -> None:
        respx.get('https://api.pagerduty.com/webhook_subscriptions').mock(
            return_value=httpx.Response(
                200, json={'webhook_subscriptions': []}
            )
        )
        respx.delete('https://api.pagerduty.com/services/PSVC1').mock(
            return_value=httpx.Response(404, json={'error': 'not found'})
        )
        ctx = _ctx(links=_LINK)
        result = await PagerDutyLifecycle().on_project_deleted(ctx, _CREDS)
        self.assertEqual(result.status, 'skipped')


class RelocateTestCase(unittest.IsolatedAsyncioTestCase):
    _MAPPING: typing.ClassVar[dict[str, object]] = {
        'team_escalation_policy_mapping': {
            'platform': 'NEW',
            'old-team': 'OLD',
        }
    }

    @respx.mock
    async def test_repoints_escalation_policy(self) -> None:
        route = respx.put('https://api.pagerduty.com/services/PSVC1').mock(
            return_value=httpx.Response(200, json={'service': _SERVICE})
        )
        ctx = _ctx(
            options=self._MAPPING,
            team_slug='platform',
            previous_team_slug='old-team',
            links=_LINK,
        )
        result = await PagerDutyLifecycle().on_project_relocated(ctx, _CREDS)
        self.assertEqual(result.status, 'ok')
        self.assertTrue(route.called)

    async def test_noop_when_policy_unchanged(self) -> None:
        ctx = _ctx(
            options=self._MAPPING,
            team_slug='platform',
            previous_team_slug='platform',
            links=_LINK,
        )
        result = await PagerDutyLifecycle().on_project_relocated(ctx, _CREDS)
        self.assertEqual(result.status, 'skipped')


class MiscTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_archived_skipped(self) -> None:
        result = await PagerDutyLifecycle().on_project_archived(_ctx(), _CREDS)
        self.assertEqual(result.status, 'skipped')

    async def test_resolve_relocation_target(self) -> None:
        target = await PagerDutyLifecycle().resolve_relocation_target(
            _ctx(), _CREDS
        )
        assert target is not None
        self.assertEqual(target.link_key, 'pagerduty-service')
        self.assertEqual(target.identifier, 'POLICY1/demo')

    async def test_resolve_relocation_target_none_without_policy(
        self,
    ) -> None:
        ctx = _ctx(options={'team_escalation_policy_mapping': {}})
        target = await PagerDutyLifecycle().resolve_relocation_target(
            ctx, _CREDS
        )
        self.assertIsNone(target)
