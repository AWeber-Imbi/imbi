"""Tests for PagerDuty service resolution."""

import unittest

import httpx
import respx
from imbi_common.plugins.base import PluginContext

from imbi_plugin_pagerduty import _client, _services

_CREDS = {'api_key': 'k'}


def _ctx(
    *,
    project_slug: str = 'demo',
    previous_project_slug: str | None = None,
    links: dict[str, str] | None = None,
) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug=project_slug,
        org_slug='org',
        previous_project_slug=previous_project_slug,
        project_links=links or {},
    )


class ServiceIdFromLinkTestCase(unittest.TestCase):
    def test_parses_last_segment(self) -> None:
        links = {
            'pagerduty-service': (
                'https://acme.pagerduty.com/service-directory/PSVC1'
            )
        }
        self.assertEqual(_services.service_id_from_link(links), 'PSVC1')

    def test_missing_link_returns_none(self) -> None:
        self.assertIsNone(_services.service_id_from_link({}))


class ResolveServiceIdTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_prefers_link(self) -> None:
        ctx = _ctx(
            links={'pagerduty-service': 'https://acme.pagerduty.com/s/PLINK'}
        )
        async with _client.client(_CREDS) as client:
            self.assertEqual(
                await _services.resolve_service_id(client, ctx), 'PLINK'
            )

    @respx.mock
    async def test_falls_back_to_name(self) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(
                200, json={'services': [{'id': 'PNAME', 'name': 'demo'}]}
            )
        )
        async with _client.client(_CREDS) as client:
            self.assertEqual(
                await _services.resolve_service_id(client, _ctx()), 'PNAME'
            )

    @respx.mock
    async def test_falls_back_to_previous_slug(self) -> None:
        def _by_query(request: httpx.Request) -> httpx.Response:
            query = request.url.params.get('query')
            if query == 'old-name':
                return httpx.Response(
                    200,
                    json={'services': [{'id': 'POLD', 'name': 'old-name'}]},
                )
            return httpx.Response(200, json={'services': []})

        respx.get('https://api.pagerduty.com/services').mock(
            side_effect=_by_query
        )
        ctx = _ctx(project_slug='new-name', previous_project_slug='old-name')
        async with _client.client(_CREDS) as client:
            self.assertEqual(
                await _services.resolve_service_id(client, ctx), 'POLD'
            )

    @respx.mock
    async def test_no_match_returns_none(self) -> None:
        respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(200, json={'services': []})
        )
        async with _client.client(_CREDS) as client:
            self.assertIsNone(
                await _services.resolve_service_id(client, _ctx())
            )
