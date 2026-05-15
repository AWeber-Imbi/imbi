import unittest

import httpx
import pytest
import respx

from imbi_plugin_sonarqube import client


class FetchComponentMeasuresTests(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_happy_path_returns_json(self) -> None:
        route = respx.get(
            'https://sonarqube.example.com/api/measures/component'
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    'component': {
                        'key': 'proj-1',
                        'measures': [
                            {'metric': 'coverage', 'value': '85.0'},
                            {'metric': 'ncloc', 'value': '1234'},
                        ],
                    }
                },
            )
        )
        result = await client.fetch_component_measures(
            base_url='https://sonarqube.example.com/',
            api_token='token-abc',
            component='proj-1',
            metric_keys=['coverage', 'ncloc'],
        )
        self.assertEqual('proj-1', result['component']['key'])
        self.assertTrue(route.called)
        request = route.calls.last.request
        self.assertEqual(
            'coverage,ncloc', request.url.params.get('metricKeys')
        )
        self.assertEqual('proj-1', request.url.params.get('component'))
        self.assertEqual(
            'Bearer token-abc', request.headers.get('Authorization')
        )

    @respx.mock
    async def test_strips_trailing_slash_from_base_url(self) -> None:
        respx.get('https://sonarqube.example.com/api/measures/component').mock(
            return_value=httpx.Response(200, json={'component': {}})
        )
        await client.fetch_component_measures(
            base_url='https://sonarqube.example.com/',
            api_token='token-abc',
            component='proj-1',
            metric_keys=['coverage'],
        )

    @respx.mock
    async def test_non_2xx_raises(self) -> None:
        respx.get('https://sonarqube.example.com/api/measures/component').mock(
            return_value=httpx.Response(500, text='oops')
        )
        with pytest.raises(client.SonarqubeClientError) as captured:
            await client.fetch_component_measures(
                base_url='https://sonarqube.example.com',
                api_token='t',
                component='c',
                metric_keys=['coverage'],
            )
        self.assertIn('status 500', str(captured.value))

    @respx.mock
    async def test_transport_error_raises(self) -> None:
        respx.get('https://sonarqube.example.com/api/measures/component').mock(
            side_effect=httpx.ConnectError('refused')
        )
        with pytest.raises(client.SonarqubeClientError) as captured:
            await client.fetch_component_measures(
                base_url='https://sonarqube.example.com',
                api_token='t',
                component='c',
                metric_keys=['coverage'],
            )
        self.assertIn('SonarQube request failed', str(captured.value))

    @respx.mock
    async def test_non_json_response_raises(self) -> None:
        respx.get('https://sonarqube.example.com/api/measures/component').mock(
            return_value=httpx.Response(200, text='not-json')
        )
        with pytest.raises(client.SonarqubeClientError):
            await client.fetch_component_measures(
                base_url='https://sonarqube.example.com',
                api_token='t',
                component='c',
                metric_keys=['coverage'],
            )
