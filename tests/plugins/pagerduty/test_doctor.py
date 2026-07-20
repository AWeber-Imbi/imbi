"""Tests for the PagerDuty project-doctor analysis capability."""

import unittest

import httpx
import respx
from imbi_common.plugins.base import (
    AnalysisResultItem,
    PluginContext,
    ServiceConnection,
)
from imbi_common.plugins.errors import PluginRemediationNotSupported

from imbi_plugin_pagerduty.doctor import _REPAIR_EDGE, PagerDutyDoctor

_SLUG = 'pagerduty'
_CREDS = {'api_key': 'k'}
_SVC_ID = 'PSVC1'
_HTML = 'https://acme.pagerduty.com/service-directory/PSVC1'
_CANONICAL = f'https://api.pagerduty.com/services/{_SVC_ID}'
_SERVICE = {'id': _SVC_ID, 'html_url': _HTML, 'name': 'demo'}
_LINK_KEY = 'pagerduty-service'


def _conn() -> ServiceConnection:
    return ServiceConnection(
        integration_slug=_SLUG, identifier=_SVC_ID, canonical_url=_CANONICAL
    )


def _ctx(
    *,
    integration_slug: str | None = _SLUG,
    connections: list[ServiceConnection] | None = None,
    links: dict[str, str] | None = None,
    options: dict[str, object] | None = None,
    team_slug: str | None = 'platform',
) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug='demo',
        org_slug='org',
        team_slug=team_slug,
        integration_slug=integration_slug,
        integration_options=options
        if options is not None
        else {'team_escalation_policy_mapping': {'platform': 'POLICY1'}},
        service_connections=connections or [],
        project_links=links or {},
    )


def _by_slug(
    items: list[AnalysisResultItem],
) -> dict[str, AnalysisResultItem]:
    return {i.slug: i for i in items}


class AnalyzeTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_warns_without_integration_binding(self) -> None:
        results = await PagerDutyDoctor().analyze(
            _ctx(integration_slug=None), _CREDS
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].slug, 'exists-in')
        self.assertEqual(results[0].status, 'warn')

    async def test_missing_api_key_warns(self) -> None:
        results = await PagerDutyDoctor().analyze(_ctx(), {})
        by_slug = _by_slug(results)
        self.assertEqual(by_slug['service'].status, 'warn')
        self.assertEqual(by_slug['escalation-policy'].status, 'pass')

    async def test_no_policy_mapping_warns(self) -> None:
        ctx = _ctx(
            options={'team_escalation_policy_mapping': {}},
            connections=[_conn()],
        )
        with respx.mock:
            respx.get(f'https://api.pagerduty.com/services/{_SVC_ID}').mock(
                return_value=httpx.Response(200, json={'service': _SERVICE})
            )
            results = await PagerDutyDoctor().analyze(ctx, _CREDS)
        self.assertEqual(_by_slug(results)['escalation-policy'].status, 'warn')

    @respx.mock
    async def test_edge_present_all_pass(self) -> None:
        respx.get(f'https://api.pagerduty.com/services/{_SVC_ID}').mock(
            return_value=httpx.Response(200, json={'service': _SERVICE})
        )
        ctx = _ctx(connections=[_conn()], links={_LINK_KEY: _HTML})
        results = await PagerDutyDoctor().analyze(ctx, _CREDS)
        by_slug = _by_slug(results)
        self.assertEqual(by_slug['service'].status, 'pass')
        self.assertEqual(by_slug['canonical-url'].status, 'pass')
        self.assertEqual(by_slug['dashboard-link'].status, 'pass')

    @respx.mock
    async def test_edge_present_service_404_offers_create(self) -> None:
        respx.get(f'https://api.pagerduty.com/services/{_SVC_ID}').mock(
            return_value=httpx.Response(404, json={'error': 'no'})
        )
        ctx = _ctx(connections=[_conn()])
        results = await PagerDutyDoctor().analyze(ctx, _CREDS)
        finding = _by_slug(results)['service']
        self.assertEqual(finding.status, 'fail')
        assert finding.remediation is not None
        self.assertEqual(finding.remediation.id, _REPAIR_EDGE)
        self.assertTrue(finding.remediation.destructive)

    @respx.mock
    async def test_edge_present_unexpected_status_warns(self) -> None:
        respx.get(f'https://api.pagerduty.com/services/{_SVC_ID}').mock(
            return_value=httpx.Response(500)
        )
        ctx = _ctx(connections=[_conn()])
        results = await PagerDutyDoctor().analyze(ctx, _CREDS)
        self.assertEqual(_by_slug(results)['service'].status, 'warn')

    @respx.mock
    async def test_edge_canonical_and_link_drift(self) -> None:
        respx.get(f'https://api.pagerduty.com/services/{_SVC_ID}').mock(
            return_value=httpx.Response(200, json={'service': _SERVICE})
        )
        conn = ServiceConnection(
            integration_slug=_SLUG,
            identifier=_SVC_ID,
            canonical_url='https://api.pagerduty.com/services/WRONG',
        )
        ctx = _ctx(connections=[conn], links={_LINK_KEY: 'https://old/url'})
        results = await PagerDutyDoctor().analyze(ctx, _CREDS)
        by_slug = _by_slug(results)
        self.assertEqual(by_slug['canonical-url'].status, 'fail')
        self.assertEqual(by_slug['dashboard-link'].status, 'fail')

    @respx.mock
    async def test_edge_present_bad_body_warns(self) -> None:
        respx.get(f'https://api.pagerduty.com/services/{_SVC_ID}').mock(
            return_value=httpx.Response(200, json={'nope': 1})
        )
        ctx = _ctx(connections=[_conn()])
        results = await PagerDutyDoctor().analyze(ctx, _CREDS)
        self.assertEqual(_by_slug(results)['service'].status, 'warn')

    @respx.mock
    async def test_no_edge_service_found_by_name(self) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(
                200, json={'services': [{**_SERVICE, 'name': 'demo'}]}
            )
        )
        results = await PagerDutyDoctor().analyze(_ctx(), _CREDS)
        finding = _by_slug(results)['exists-in']
        self.assertEqual(finding.status, 'warn')
        assert finding.remediation is not None
        self.assertFalse(finding.remediation.destructive)

    @respx.mock
    async def test_no_edge_not_found_offers_create(self) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(200, json={'services': []})
        )
        results = await PagerDutyDoctor().analyze(_ctx(), _CREDS)
        finding = _by_slug(results)['exists-in']
        self.assertEqual(finding.status, 'fail')
        assert finding.remediation is not None
        self.assertTrue(finding.remediation.destructive)

    @respx.mock
    async def test_no_edge_not_found_no_policy_no_offer(self) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(200, json={'services': []})
        )
        ctx = _ctx(options={'team_escalation_policy_mapping': {}})
        results = await PagerDutyDoctor().analyze(ctx, _CREDS)
        finding = _by_slug(results)['exists-in']
        self.assertEqual(finding.status, 'fail')
        self.assertIsNone(finding.remediation)

    @respx.mock
    async def test_auth_failure_degrades_to_warn(self) -> None:
        respx.get(f'https://api.pagerduty.com/services/{_SVC_ID}').mock(
            return_value=httpx.Response(401, json={'error': 'bad key'})
        )
        ctx = _ctx(connections=[_conn()])
        results = await PagerDutyDoctor().analyze(ctx, _CREDS)
        self.assertEqual(_by_slug(results)['service'].status, 'warn')


class RemediateTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_id_raises(self) -> None:
        with self.assertRaises(PluginRemediationNotSupported):
            await PagerDutyDoctor().remediate(_ctx(), _CREDS, 'nope')

    async def test_no_integration_slug_failed(self) -> None:
        result = await PagerDutyDoctor().remediate(
            _ctx(integration_slug=None), _CREDS, _REPAIR_EDGE
        )
        self.assertEqual(result.status, 'failed')

    async def test_missing_api_key_failed(self) -> None:
        result = await PagerDutyDoctor().remediate(_ctx(), {}, _REPAIR_EDGE)
        self.assertEqual(result.status, 'failed')

    @respx.mock
    async def test_edge_matches_is_noop(self) -> None:
        respx.get(f'https://api.pagerduty.com/services/{_SVC_ID}').mock(
            return_value=httpx.Response(200, json={'service': _SERVICE})
        )
        ctx = _ctx(connections=[_conn()], links={_LINK_KEY: _HTML})
        result = await PagerDutyDoctor().remediate(ctx, _CREDS, _REPAIR_EDGE)
        self.assertEqual(result.status, 'noop')
        self.assertIsNone(ctx.service_writeback)

    @respx.mock
    async def test_edge_drift_is_fixed(self) -> None:
        respx.get(f'https://api.pagerduty.com/services/{_SVC_ID}').mock(
            return_value=httpx.Response(200, json={'service': _SERVICE})
        )
        ctx = _ctx(connections=[_conn()], links={})
        result = await PagerDutyDoctor().remediate(ctx, _CREDS, _REPAIR_EDGE)
        self.assertEqual(result.status, 'fixed')
        assert ctx.service_writeback is not None
        self.assertEqual(ctx.service_writeback.identifier, _SVC_ID)
        self.assertEqual(
            ctx.service_writeback.dashboard_links[_LINK_KEY], _HTML
        )

    @respx.mock
    async def test_stale_edge_falls_back_to_name_search(self) -> None:
        respx.get(f'https://api.pagerduty.com/services/{_SVC_ID}').mock(
            return_value=httpx.Response(404, json={'error': 'no'})
        )
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(
                200, json={'services': [{**_SERVICE, 'name': 'demo'}]}
            )
        )
        ctx = _ctx(connections=[_conn()])
        result = await PagerDutyDoctor().remediate(ctx, _CREDS, _REPAIR_EDGE)
        self.assertEqual(result.status, 'fixed')
        assert ctx.service_writeback is not None
        self.assertEqual(ctx.service_writeback.identifier, _SVC_ID)

    @respx.mock
    async def test_edge_unexpected_status_failed(self) -> None:
        respx.get(f'https://api.pagerduty.com/services/{_SVC_ID}').mock(
            return_value=httpx.Response(500)
        )
        ctx = _ctx(connections=[_conn()])
        result = await PagerDutyDoctor().remediate(ctx, _CREDS, _REPAIR_EDGE)
        self.assertEqual(result.status, 'failed')

    @respx.mock
    async def test_no_edge_creates_service(self) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(200, json={'services': []})
        )
        create = respx.post('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(201, json={'service': _SERVICE})
        )
        ctx = _ctx()
        result = await PagerDutyDoctor().remediate(ctx, _CREDS, _REPAIR_EDGE)
        self.assertEqual(result.status, 'fixed')
        self.assertTrue(create.called)
        assert ctx.service_writeback is not None
        self.assertEqual(ctx.service_writeback.identifier, _SVC_ID)

    @respx.mock
    async def test_no_edge_no_policy_failed(self) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(200, json={'services': []})
        )
        ctx = _ctx(options={'team_escalation_policy_mapping': {}})
        result = await PagerDutyDoctor().remediate(ctx, _CREDS, _REPAIR_EDGE)
        self.assertEqual(result.status, 'failed')

    @respx.mock
    async def test_auth_failure_failed(self) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(401, json={'error': 'bad'})
        )
        result = await PagerDutyDoctor().remediate(
            _ctx(), _CREDS, _REPAIR_EDGE
        )
        self.assertEqual(result.status, 'failed')

    @respx.mock
    async def test_rate_limited_failed(self) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(429, headers={'ratelimit-reset': '1'})
        )
        result = await PagerDutyDoctor().remediate(
            _ctx(), _CREDS, _REPAIR_EDGE
        )
        self.assertEqual(result.status, 'failed')
