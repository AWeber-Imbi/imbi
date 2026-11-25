"""Tests for the Grafana plugin: manifest, signature, lifecycle, doctor."""

import unittest

import imbi.plugins.grafana
from imbi.common.plugins.base import PluginContext, ServiceConnection
from imbi.plugins.grafana import doctor, lifecycle, links, plugin

_BASE = 'https://grafana.example.com'
_RULES = (
    f'{_BASE}/api/prometheus/grafana/api/v1/rules?matcher=%7B%22name%22'
    '%3A%22service%22%2C%22value%22%3A%22demo-p1%22%2C%22isRegex%22%3Afalse'
    '%2C%22isEqual%22%3Atrue%7D'
)
_LIST = f'{_BASE}/alerting/list?search=label%3Aservice%3Ddemo-p1'


def _ctx(
    *,
    connected: bool = False,
    identifier: str = 'demo-p1',
    verified: bool = True,
    links_: dict[str, str] | None = None,
    options: dict[str, object] | None = None,
) -> PluginContext:
    return PluginContext(
        project_id='p1',
        project_slug='demo',
        project_name='Demo',
        org_slug='org',
        integration_slug='grafana',
        integration_options=(
            {'service_url': _BASE + '/'} if options is None else options
        ),
        service_connections=[
            ServiceConnection(
                integration_slug='grafana',
                identifier=identifier,
                canonical_url=links.canonical_url(
                    _BASE, 'service', identifier
                ),
                verified_identifier=identifier if verified else None,
            )
        ]
        if connected
        else [],
        project_links=(
            links_
            if links_ is not None
            else (
                {'grafana': links.dashboard_url(_BASE, 'service', identifier)}
                if connected
                else {}
            )
        ),
    )


class ManifestTestCase(unittest.TestCase):
    def test_manifest(self) -> None:
        manifest = imbi.plugins.grafana.PLUGIN.manifest
        self.assertEqual('grafana', manifest.slug)
        self.assertEqual('api_token', manifest.auth_type)
        self.assertEqual(['api_token'], [c.name for c in manifest.credentials])
        self.assertFalse(manifest.credentials[0].required)
        self.assertFalse(manifest.shareable_service_identifier)
        self.assertEqual(
            ['service_url', 'label'], [o.name for o in manifest.options]
        )
        self.assertEqual(
            ['lifecycle', 'webhook-actions', 'analysis', 'workflow-steps'],
            [c.kind for c in manifest.capabilities],
        )
        capability = manifest.get_capability('webhook-actions')
        assert capability is not None
        self.assertIs(capability.handler, plugin.GrafanaWebhookActions)
        capability = manifest.get_capability('lifecycle')
        assert capability is not None
        self.assertIs(capability.handler, lifecycle.GrafanaLifecycle)
        self.assertTrue(capability.hints['supports_lifecycle_sync'])
        capability = manifest.get_capability('analysis')
        assert capability is not None
        self.assertIs(capability.handler, doctor.GrafanaDoctor)

    def test_version(self) -> None:
        self.assertTrue(imbi.plugins.grafana.version)


class WebhookActionsTestCase(unittest.TestCase):
    def test_actions_empty(self) -> None:
        self.assertEqual(plugin.GrafanaWebhookActions.actions(), [])

    def test_instantiable(self) -> None:
        self.assertIsInstance(
            plugin.GrafanaWebhookActions(), plugin.GrafanaWebhookActions
        )

    def test_signature_is_hmac_hex_body(self) -> None:
        signature = plugin.GrafanaWebhookActions.signature()
        self.assertEqual(
            (
                signature.header,
                signature.prefix,
                signature.secret,
                signature.scheme,
            ),
            ('x-grafana-alerting-signature', '', 'webhook', 'hmac-hex'),
        )


class LinksTestCase(unittest.TestCase):
    def test_writeback(self) -> None:
        wb = links.writeback(_ctx(), 'demo-p1')
        self.assertEqual('demo-p1', wb.identifier)
        self.assertEqual(_RULES, wb.canonical_url)
        self.assertEqual({'grafana': _LIST}, wb.dashboard_links)

    def test_custom_label(self) -> None:
        ctx = _ctx(options={'service_url': _BASE, 'label': 'app'})
        wb = links.writeback(ctx, 'demo-p1')
        self.assertIn('%22name%22%3A%22app%22', wb.canonical_url)
        self.assertIn('label%3Aapp%3Ddemo-p1', wb.dashboard_links['grafana'])

    def test_missing_url_raises(self) -> None:
        with self.assertRaises(links.GrafanaConfigError):
            links.base_url(_ctx(options={}))
        with self.assertRaises(links.GrafanaConfigError):
            links.base_url(_ctx(options={'service_url': 'grafana.local'}))

    def test_two_integrations_keep_their_own_links(self) -> None:
        eu_base = 'https://grafana-eu.example.com'
        eu_list = links.dashboard_url(eu_base, 'service', 'demo-p1')
        both = {'grafana': _LIST, 'grafana-eu': eu_list}
        us = _ctx(connected=True, links_=both)
        eu = us.model_copy(
            update={
                'integration_slug': 'grafana-eu',
                'integration_options': {'service_url': eu_base},
                'service_connections': [
                    ServiceConnection(
                        integration_slug='grafana-eu',
                        identifier='demo-p1',
                        canonical_url=links.canonical_url(
                            eu_base, 'service', 'demo-p1'
                        ),
                        verified_identifier='demo-p1',
                    )
                ],
            }
        )
        us_wb = links.writeback(us, 'demo-p1')
        eu_wb = links.writeback(eu, 'demo-p1')
        self.assertEqual({'grafana': _LIST}, us_wb.dashboard_links)
        self.assertEqual({'grafana-eu': eu_list}, eu_wb.dashboard_links)
        self.assertTrue(links.matches(us, us_wb))
        self.assertTrue(links.matches(eu, eu_wb))

    def test_identifier_prefers_edge(self) -> None:
        self.assertEqual('demo-p1', links.identifier(_ctx()))
        self.assertEqual(
            'legacy',
            links.identifier(_ctx(connected=True, identifier='legacy')),
        )


class LifecycleTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_created_writes_edge(self) -> None:
        ctx = _ctx()
        result = await lifecycle.GrafanaLifecycle().on_project_created(ctx, {})
        self.assertEqual('ok', result.status)
        assert ctx.service_writeback is not None
        self.assertEqual('demo-p1', ctx.service_writeback.identifier)
        self.assertEqual(_RULES, ctx.service_writeback.canonical_url)
        self.assertEqual(
            {'grafana': _LIST}, ctx.service_writeback.dashboard_links
        )
        self.assertFalse(ctx.service_writeback.remove)

    async def test_updated_is_noop_when_linked(self) -> None:
        ctx = _ctx(connected=True)
        result = await lifecycle.GrafanaLifecycle().on_project_updated(ctx, {})
        self.assertEqual('skipped', result.status)
        self.assertIsNone(ctx.service_writeback)

    async def test_updated_keeps_existing_identifier(self) -> None:
        ctx = _ctx(connected=True, identifier='legacy', links_={})
        result = await lifecycle.GrafanaLifecycle().on_project_updated(ctx, {})
        self.assertEqual('ok', result.status)
        assert ctx.service_writeback is not None
        self.assertEqual('legacy', ctx.service_writeback.identifier)

    async def test_deleted_removes_edge(self) -> None:
        ctx = _ctx(connected=True)
        result = await lifecycle.GrafanaLifecycle().on_project_deleted(ctx, {})
        self.assertEqual('ok', result.status)
        assert ctx.service_writeback is not None
        self.assertTrue(ctx.service_writeback.remove)
        self.assertEqual('demo-p1', ctx.service_writeback.identifier)

    async def test_deleted_without_edge_skips(self) -> None:
        ctx = _ctx()
        result = await lifecycle.GrafanaLifecycle().on_project_deleted(ctx, {})
        self.assertEqual('skipped', result.status)
        self.assertIsNone(ctx.service_writeback)

    async def test_archived_skips(self) -> None:
        result = await lifecycle.GrafanaLifecycle().on_project_archived(
            _ctx(), {}
        )
        self.assertEqual('skipped', result.status)

    async def test_missing_url_fails(self) -> None:
        ctx = _ctx(options={})
        result = await lifecycle.GrafanaLifecycle().on_project_created(ctx, {})
        self.assertEqual('failed', result.status)
        self.assertIsNone(ctx.service_writeback)
        result = await lifecycle.GrafanaLifecycle().on_project_deleted(
            _ctx(connected=True, options={}), {}
        )
        self.assertEqual('failed', result.status)


class DoctorTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_unbound(self) -> None:
        ctx = _ctx()
        ctx.integration_slug = None
        items = await doctor.GrafanaDoctor().analyze(ctx, {})
        self.assertEqual(['warn'], [i.status for i in items])

    async def test_missing_url_warns(self) -> None:
        items = await doctor.GrafanaDoctor().analyze(_ctx(options={}), {})
        self.assertEqual(['warn'], [i.status for i in items])
        self.assertIsNone(items[0].remediation)

    async def test_linked_passes(self) -> None:
        items = {
            i.slug: i
            for i in await doctor.GrafanaDoctor().analyze(
                _ctx(connected=True), {}
            )
        }
        self.assertEqual('pass', items['exists-in'].status)
        self.assertEqual('pass', items['identifier'].status)

    async def test_unlinked_fails_with_offer(self) -> None:
        items = {
            i.slug: i for i in await doctor.GrafanaDoctor().analyze(_ctx(), {})
        }
        self.assertEqual('fail', items['exists-in'].status)
        assert items['exists-in'].remediation is not None
        self.assertEqual('link-project', items['exists-in'].remediation.id)
        self.assertTrue(items['exists-in'].remediation.destructive)
        self.assertFalse(items['exists-in'].remediation.sweepable)

    async def test_unverified_or_stale_link_warns(self) -> None:
        for ctx in (
            _ctx(connected=True, verified=False),
            _ctx(connected=True, links_={}),
        ):
            items = {
                i.slug: i
                for i in await doctor.GrafanaDoctor().analyze(ctx, {})
            }
            self.assertEqual('warn', items['exists-in'].status)
            assert items['exists-in'].remediation is not None
            self.assertEqual('link-project', items['exists-in'].remediation.id)

    async def test_identifier_differs_from_default(self) -> None:
        items = {
            i.slug: i
            for i in await doctor.GrafanaDoctor().analyze(
                _ctx(connected=True, identifier='legacy'), {}
            )
        }
        self.assertEqual('pass', items['exists-in'].status)
        self.assertEqual('warn', items['identifier'].status)
        assert items['identifier'].remediation is not None
        self.assertEqual(
            'use-project-value', items['identifier'].remediation.id
        )

    async def test_remediate_link(self) -> None:
        ctx = _ctx()
        result = await doctor.GrafanaDoctor().remediate(
            ctx, {}, 'link-project'
        )
        self.assertEqual('fixed', result.status)
        assert ctx.service_writeback is not None
        self.assertEqual('demo-p1', ctx.service_writeback.identifier)

    async def test_remediate_link_noop(self) -> None:
        ctx = _ctx(connected=True)
        result = await doctor.GrafanaDoctor().remediate(
            ctx, {}, 'link-project'
        )
        self.assertEqual('noop', result.status)
        self.assertIsNone(ctx.service_writeback)

    async def test_remediate_use_default(self) -> None:
        ctx = _ctx(connected=True, identifier='legacy')
        result = await doctor.GrafanaDoctor().remediate(
            ctx, {}, 'use-project-value'
        )
        self.assertEqual('fixed', result.status)
        assert ctx.service_writeback is not None
        self.assertEqual('demo-p1', ctx.service_writeback.identifier)

    async def test_remediate_missing_url_fails(self) -> None:
        result = await doctor.GrafanaDoctor().remediate(
            _ctx(options={}), {}, 'link-project'
        )
        self.assertEqual('failed', result.status)

    async def test_remediate_unknown_raises(self) -> None:
        from imbi.common.plugins.errors import (
            PluginRemediationNotSupported,
        )

        with self.assertRaises(PluginRemediationNotSupported):
            await doctor.GrafanaDoctor().remediate(_ctx(), {}, 'nope')
