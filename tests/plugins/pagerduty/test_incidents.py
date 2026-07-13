"""Tests for the PagerDuty incidents capability."""

import datetime
import unittest

import httpx
import respx
from imbi_common.plugins.base import PluginContext

from imbi_plugin_pagerduty.incidents import PagerDutyIncidents

_CREDS = {'api_key': 'k'}
_LINKED = {
    'pagerduty-service': 'https://acme.pagerduty.com/service-directory/PSVC1'
}


def _ctx(links: dict[str, str] | None = None) -> PluginContext:
    return PluginContext(
        project_id='p',
        project_slug='demo',
        org_slug='org',
        project_links=links if links is not None else _LINKED,
    )


def _window() -> tuple[datetime.datetime, datetime.datetime]:
    end = datetime.datetime(2026, 6, 8, tzinfo=datetime.UTC)
    return end - datetime.timedelta(days=7), end


class ListIncidentsTestCase(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_happy_path(self) -> None:
        route = respx.get('https://api.pagerduty.com/incidents').mock(
            return_value=httpx.Response(
                200,
                json={
                    'incidents': [
                        {
                            'id': 'PINC1',
                            'title': 'boom',
                            'status': 'triggered',
                            'created_at': '2026-06-02T00:00:00Z',
                            'html_url': 'https://x/PINC1',
                        }
                    ],
                    'more': False,
                    'total': 1,
                },
            )
        )
        start, end = _window()
        result = await PagerDutyIncidents().list_incidents(
            _ctx(), _CREDS, start_time=start, end_time=end
        )
        self.assertEqual(len(result.incidents), 1)
        self.assertEqual(result.incidents[0].id, 'PINC1')
        self.assertIsNone(result.next_cursor)
        self.assertEqual(result.total, 1)
        # service id from the link was used for the query
        request = route.calls.last.request
        self.assertIn('service_ids%5B%5D=PSVC1', str(request.url))

    @respx.mock
    async def test_pagination_sets_next_cursor(self) -> None:
        respx.get('https://api.pagerduty.com/incidents').mock(
            return_value=httpx.Response(
                200, json={'incidents': [], 'more': True, 'total': 200}
            )
        )
        start, end = _window()
        result = await PagerDutyIncidents().list_incidents(
            _ctx(), _CREDS, start_time=start, end_time=end, limit=100
        )
        self.assertEqual(result.next_cursor, '100')

    @respx.mock
    async def test_status_filter_forwarded(self) -> None:
        route = respx.get('https://api.pagerduty.com/incidents').mock(
            return_value=httpx.Response(200, json={'incidents': []})
        )
        start, end = _window()
        await PagerDutyIncidents().list_incidents(
            _ctx(),
            _CREDS,
            start_time=start,
            end_time=end,
            statuses=['triggered', 'acknowledged'],
        )
        url = str(route.calls.last.request.url)
        self.assertIn('statuses%5B%5D=triggered', url)
        self.assertIn('statuses%5B%5D=acknowledged', url)

    @respx.mock
    async def test_no_service_returns_empty(self) -> None:
        # No link and no name match -> empty result, no /incidents call.
        services = respx.get('https://api.pagerduty.com/services').mock(
            return_value=httpx.Response(200, json={'services': []})
        )
        incidents = respx.get('https://api.pagerduty.com/incidents').mock(
            return_value=httpx.Response(200, json={'incidents': []})
        )
        start, end = _window()
        result = await PagerDutyIncidents().list_incidents(
            _ctx(links={}), _CREDS, start_time=start, end_time=end
        )
        self.assertEqual(result.incidents, [])
        self.assertTrue(services.called)
        self.assertFalse(incidents.called)
