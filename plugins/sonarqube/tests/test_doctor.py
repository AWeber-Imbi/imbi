"""Tests for the SonarQube project-doctor analysis capability."""

import unittest

import httpx
import respx

from imbi.common.plugins.base import (
    AnalysisResultItem,
    PluginContext,
    ServiceConnection,
)
from imbi.common.plugins.errors import PluginRemediationNotSupported
from imbi.plugins.sonarqube.doctor import (
    _RECONCILE_EDGE,
    _REPAIR_EDGE,
    SonarQubeDoctor,
)

_SLUG = 'sonarqube'
_URL = 'https://sonarqube.example.com'
_KEY = 'platform:demo'
_CREDS = {'api_token': 't'}
_CANONICAL = f'{_URL}/api/components/show?component=platform%3Ademo'
_DASHBOARD = f'{_URL}/dashboard?id=platform%3Ademo'
_LINK_KEY = 'sonarqube'
_SEARCH = f'{_URL}/api/projects/search'
_CREATE = f'{_URL}/api/projects/create'


def _conn(
    *, identifier: str = _KEY, canonical: str | None = _CANONICAL
) -> ServiceConnection:
    return ServiceConnection(
        integration_slug=_SLUG, identifier=identifier, canonical_url=canonical
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
        else {'service_url': _URL},
        service_connections=connections or [],
        project_links=links or {},
    )


def _by_slug(
    items: list[AnalysisResultItem],
) -> dict[str, AnalysisResultItem]:
    return {i.slug: i for i in items}


def _components(*keys: str) -> httpx.Response:
    return httpx.Response(
        200, json={'components': [{'key': k, 'name': k} for k in keys]}
    )


class AnalyzeTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_warns_without_integration_binding(self) -> None:
        results = await SonarQubeDoctor().analyze(
            _ctx(integration_slug=None), _CREDS
        )
        self.assertEqual(results[0].slug, 'exists-in')
        self.assertEqual(results[0].status, 'warn')

    async def test_warns_without_service_url(self) -> None:
        results = await SonarQubeDoctor().analyze(_ctx(options={}), _CREDS)
        self.assertEqual(results[0].slug, 'service-url')

    async def test_warns_without_token(self) -> None:
        results = await SonarQubeDoctor().analyze(_ctx(), {})
        self.assertEqual(results[0].slug, 'api-token')
        self.assertIn('squ_', results[0].description)

    @respx.mock
    async def _forbidden_description(self, token: str) -> str:
        respx.get(_SEARCH).mock(return_value=httpx.Response(403))
        results = await SonarQubeDoctor().analyze(
            _ctx(connections=[_conn()]), {'api_token': token}
        )
        finding = _by_slug(results)['component']
        self.assertEqual(finding.status, 'warn')
        self.assertIn('status 403', finding.description)
        return finding.description

    async def test_forbidden_analysis_token_says_replace_it(self) -> None:
        # The prefix makes the cause certain, so the finding names it
        # rather than hedging: no permission grant can fix this one.
        for prefix in ('sqa_', 'sqp_'):
            with self.subTest(prefix=prefix):
                desc = await self._forbidden_description(f'{prefix}abc')
                self.assertIn('is an analysis token', desc)
                self.assertIn('squ_', desc)
                self.assertNotIn('Browse', desc)

    async def test_forbidden_user_token_points_at_permissions(self) -> None:
        # Telling someone holding a squ_ token to swap token types sends
        # them in circles -- a refused user token is a rights problem.
        desc = await self._forbidden_description('squ_abc')
        self.assertIn('Browse', desc)
        self.assertNotIn('replace it', desc)

    async def test_forbidden_unprefixed_token_covers_both(self) -> None:
        # Tokens predating SonarQube's prefixes tell us nothing, so the
        # finding has to offer both causes.
        desc = await self._forbidden_description('legacy-token')
        self.assertIn('analysis token', desc)
        self.assertIn('Browse', desc)

    @respx.mock
    async def test_other_errors_omit_token_hint(self) -> None:
        respx.get(_SEARCH).mock(return_value=httpx.Response(500))
        ctx = _ctx(connections=[_conn()])
        results = await SonarQubeDoctor().analyze(ctx, _CREDS)
        finding = _by_slug(results)['component']
        self.assertIn('status 500', finding.description)
        self.assertNotIn('analysis token', finding.description)
        self.assertNotIn('Browse', finding.description)

    async def test_warns_without_derivable_key(self) -> None:
        results = await SonarQubeDoctor().analyze(_ctx(team_slug=None), _CREDS)
        self.assertEqual(results[0].slug, 'exists-in')
        self.assertEqual(results[0].status, 'warn')

    @respx.mock
    async def test_edge_present_all_pass(self) -> None:
        respx.get(_SEARCH).mock(return_value=_components(_KEY))
        ctx = _ctx(connections=[_conn()], links={_LINK_KEY: _DASHBOARD})
        results = await SonarQubeDoctor().analyze(ctx, _CREDS)
        by_slug = _by_slug(results)
        self.assertEqual(by_slug['component'].status, 'pass')
        self.assertEqual(by_slug['canonical-url'].status, 'pass')
        self.assertEqual(by_slug['dashboard-link'].status, 'pass')

    @respx.mock
    async def test_edge_present_component_missing_offers_create(self) -> None:
        respx.get(_SEARCH).mock(return_value=_components())
        ctx = _ctx(connections=[_conn()])
        results = await SonarQubeDoctor().analyze(ctx, _CREDS)
        finding = _by_slug(results)['component']
        self.assertEqual(finding.status, 'fail')
        assert finding.remediation is not None
        self.assertTrue(finding.remediation.destructive)

    @respx.mock
    async def test_edge_present_canonical_and_link_drift(self) -> None:
        respx.get(_SEARCH).mock(return_value=_components(_KEY))
        ctx = _ctx(
            connections=[_conn(canonical='https://old/url')],
            links={_LINK_KEY: 'https://old/dash'},
        )
        results = await SonarQubeDoctor().analyze(ctx, _CREDS)
        by_slug = _by_slug(results)
        self.assertEqual(by_slug['canonical-url'].status, 'fail')
        self.assertEqual(by_slug['dashboard-link'].status, 'fail')

    @respx.mock
    async def test_no_edge_component_found(self) -> None:
        respx.get(_SEARCH).mock(return_value=_components(_KEY))
        results = await SonarQubeDoctor().analyze(_ctx(), _CREDS)
        finding = _by_slug(results)['exists-in']
        self.assertEqual(finding.status, 'warn')
        assert finding.remediation is not None
        self.assertFalse(finding.remediation.destructive)

    @respx.mock
    async def test_no_edge_component_absent_offers_create(self) -> None:
        respx.get(_SEARCH).mock(return_value=_components())
        results = await SonarQubeDoctor().analyze(_ctx(), _CREDS)
        finding = _by_slug(results)['exists-in']
        self.assertEqual(finding.status, 'fail')
        assert finding.remediation is not None
        self.assertTrue(finding.remediation.destructive)

    @respx.mock
    async def test_unreachable_degrades_to_warn(self) -> None:
        respx.get(_SEARCH).mock(return_value=httpx.Response(401, text='no'))
        results = await SonarQubeDoctor().analyze(_ctx(), _CREDS)
        self.assertEqual(_by_slug(results)['component'].status, 'warn')


class RemediateTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_id_raises(self) -> None:
        with self.assertRaises(PluginRemediationNotSupported):
            await SonarQubeDoctor().remediate(_ctx(), _CREDS, 'nope')

    async def test_no_integration_slug_failed(self) -> None:
        result = await SonarQubeDoctor().remediate(
            _ctx(integration_slug=None), _CREDS, _REPAIR_EDGE
        )
        self.assertEqual(result.status, 'failed')

    async def test_no_service_url_failed(self) -> None:
        result = await SonarQubeDoctor().remediate(
            _ctx(options={}), _CREDS, _REPAIR_EDGE
        )
        self.assertEqual(result.status, 'failed')

    async def test_no_token_failed(self) -> None:
        result = await SonarQubeDoctor().remediate(_ctx(), {}, _REPAIR_EDGE)
        self.assertEqual(result.status, 'failed')

    async def test_no_key_failed(self) -> None:
        result = await SonarQubeDoctor().remediate(
            _ctx(team_slug=None), _CREDS, _REPAIR_EDGE
        )
        self.assertEqual(result.status, 'failed')

    @respx.mock
    async def test_edge_matches_is_noop(self) -> None:
        respx.get(_SEARCH).mock(return_value=_components(_KEY))
        ctx = _ctx(connections=[_conn()], links={_LINK_KEY: _DASHBOARD})
        result = await SonarQubeDoctor().remediate(ctx, _CREDS, _REPAIR_EDGE)
        self.assertEqual(result.status, 'noop')
        self.assertIsNone(ctx.service_writeback)

    @respx.mock
    async def test_edge_drift_is_fixed(self) -> None:
        respx.get(_SEARCH).mock(return_value=_components(_KEY))
        ctx = _ctx(connections=[_conn(canonical='https://old')], links={})
        result = await SonarQubeDoctor().remediate(ctx, _CREDS, _REPAIR_EDGE)
        self.assertEqual(result.status, 'fixed')
        assert ctx.service_writeback is not None
        self.assertEqual(ctx.service_writeback.identifier, _KEY)
        self.assertEqual(ctx.service_writeback.canonical_url, _CANONICAL)
        self.assertEqual(
            ctx.service_writeback.dashboard_links[_LINK_KEY], _DASHBOARD
        )

    @respx.mock
    async def test_no_edge_found_links(self) -> None:
        respx.get(_SEARCH).mock(return_value=_components(_KEY))
        ctx = _ctx()
        result = await SonarQubeDoctor().remediate(ctx, _CREDS, _REPAIR_EDGE)
        self.assertEqual(result.status, 'fixed')
        assert ctx.service_writeback is not None
        self.assertEqual(ctx.service_writeback.identifier, _KEY)

    @respx.mock
    async def test_no_component_creates_project(self) -> None:
        respx.get(_SEARCH).mock(return_value=_components())
        create = respx.post(_CREATE).mock(
            return_value=httpx.Response(
                200, json={'project': {'key': _KEY, 'name': 'demo'}}
            )
        )
        ctx = _ctx()
        result = await SonarQubeDoctor().remediate(ctx, _CREDS, _REPAIR_EDGE)
        self.assertEqual(result.status, 'fixed')
        self.assertTrue(create.called)
        assert ctx.service_writeback is not None
        self.assertEqual(ctx.service_writeback.identifier, _KEY)

    @respx.mock
    async def test_reconcile_missing_component_fails_without_create(
        self,
    ) -> None:
        search = respx.get(_SEARCH).mock(return_value=_components())
        create = respx.post(_CREATE)
        ctx = _ctx(connections=[_conn()], links={_LINK_KEY: _DASHBOARD})
        result = await SonarQubeDoctor().remediate(
            ctx, _CREDS, _RECONCILE_EDGE
        )
        self.assertEqual(result.status, 'failed')
        self.assertTrue(search.called)
        self.assertFalse(create.called)
        self.assertIsNone(ctx.service_writeback)

    @respx.mock
    async def test_client_error_failed(self) -> None:
        respx.get(_SEARCH).mock(return_value=httpx.Response(401, text='no'))
        result = await SonarQubeDoctor().remediate(
            _ctx(), _CREDS, _REPAIR_EDGE
        )
        self.assertEqual(result.status, 'failed')
