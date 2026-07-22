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


class SearchProjectTests(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_returns_matching_component(self) -> None:
        route = respx.get(
            'https://sonarqube.example.com/api/projects/search'
        ).mock(
            return_value=httpx.Response(
                200,
                json={'components': [{'key': 'team:demo', 'name': 'demo'}]},
            )
        )
        result = await client.search_project(
            base_url='https://sonarqube.example.com/',
            api_token='t',
            key='team:demo',
        )
        assert result is not None
        self.assertEqual('team:demo', result['key'])
        self.assertEqual(
            'team:demo', route.calls.last.request.url.params.get('projects')
        )

    @respx.mock
    async def test_returns_none_when_absent(self) -> None:
        respx.get('https://sonarqube.example.com/api/projects/search').mock(
            return_value=httpx.Response(200, json={'components': []})
        )
        result = await client.search_project(
            base_url='https://sonarqube.example.com',
            api_token='t',
            key='team:demo',
        )
        self.assertIsNone(result)

    @respx.mock
    async def test_ignores_non_exact_key(self) -> None:
        respx.get('https://sonarqube.example.com/api/projects/search').mock(
            return_value=httpx.Response(
                200, json={'components': [{'key': 'team:demo-other'}]}
            )
        )
        result = await client.search_project(
            base_url='https://sonarqube.example.com',
            api_token='t',
            key='team:demo',
        )
        self.assertIsNone(result)

    @respx.mock
    async def test_non_2xx_raises(self) -> None:
        respx.get('https://sonarqube.example.com/api/projects/search').mock(
            return_value=httpx.Response(401, text='bad token')
        )
        with pytest.raises(client.SonarqubeClientError):
            await client.search_project(
                base_url='https://sonarqube.example.com',
                api_token='t',
                key='team:demo',
            )

    @respx.mock
    async def test_transport_error_raises(self) -> None:
        respx.get('https://sonarqube.example.com/api/projects/search').mock(
            side_effect=httpx.ConnectError('refused')
        )
        with pytest.raises(client.SonarqubeClientError):
            await client.search_project(
                base_url='https://sonarqube.example.com',
                api_token='t',
                key='team:demo',
            )

    @respx.mock
    async def test_non_json_raises(self) -> None:
        respx.get('https://sonarqube.example.com/api/projects/search').mock(
            return_value=httpx.Response(200, text='not-json')
        )
        with pytest.raises(client.SonarqubeClientError):
            await client.search_project(
                base_url='https://sonarqube.example.com',
                api_token='t',
                key='team:demo',
            )


class CreateProjectTests(unittest.IsolatedAsyncioTestCase):
    @respx.mock
    async def test_creates_and_returns_project(self) -> None:
        route = respx.post(
            'https://sonarqube.example.com/api/projects/create'
        ).mock(
            return_value=httpx.Response(
                200, json={'project': {'key': 'team:demo', 'name': 'demo'}}
            )
        )
        result = await client.create_project(
            base_url='https://sonarqube.example.com/',
            api_token='t',
            key='team:demo',
            name='demo',
        )
        self.assertEqual('team:demo', result['key'])
        params = route.calls.last.request.url.params
        self.assertEqual('team:demo', params.get('project'))
        self.assertEqual('demo', params.get('name'))

    @respx.mock
    async def test_missing_project_object_returns_empty(self) -> None:
        respx.post('https://sonarqube.example.com/api/projects/create').mock(
            return_value=httpx.Response(200, json={})
        )
        result = await client.create_project(
            base_url='https://sonarqube.example.com',
            api_token='t',
            key='team:demo',
            name='demo',
        )
        self.assertEqual({}, result)

    @respx.mock
    async def test_non_2xx_raises(self) -> None:
        respx.post('https://sonarqube.example.com/api/projects/create').mock(
            return_value=httpx.Response(400, text='duplicate key')
        )
        with pytest.raises(client.SonarqubeClientError):
            await client.create_project(
                base_url='https://sonarqube.example.com',
                api_token='t',
                key='team:demo',
                name='demo',
            )

    @respx.mock
    async def test_transport_error_raises(self) -> None:
        respx.post('https://sonarqube.example.com/api/projects/create').mock(
            side_effect=httpx.ConnectError('refused')
        )
        with pytest.raises(client.SonarqubeClientError):
            await client.create_project(
                base_url='https://sonarqube.example.com',
                api_token='t',
                key='team:demo',
                name='demo',
            )

    @respx.mock
    async def test_non_json_raises(self) -> None:
        respx.post('https://sonarqube.example.com/api/projects/create').mock(
            return_value=httpx.Response(200, text='not-json')
        )
        with pytest.raises(client.SonarqubeClientError):
            await client.create_project(
                base_url='https://sonarqube.example.com',
                api_token='t',
                key='team:demo',
                name='demo',
            )
