import os
import unittest
import unittest.mock

import httpx
import respx

from imbi.common.plugins import base as plugin_base
from imbi.plugins.sonarqube import actions

_SAMPLE_RESPONSE: dict[str, object] = {
    'component': {
        'key': 'proj-1',
        'measures': [
            {'metric': 'coverage', 'value': '85.0'},
            {'metric': 'ncloc', 'value': '1234'},
        ],
    }
}

_HANDLER_CONFIG_JSON = (
    '[{"metric": "coverage", "path": "/test_coverage"},'
    ' {"metric": "ncloc",    "path": "/lines_of_code"}]'
)


def _config(raw: str = _HANDLER_CONFIG_JSON) -> actions.MetricMappings:
    return actions.MetricMappings.model_validate_json(raw)


def _ctx(
    *,
    service_endpoint: str | None = 'https://sonarqube.example.com',
) -> plugin_base.PluginContext:
    integration_options: dict[str, object] = {}
    if service_endpoint is not None:
        integration_options['service_url'] = service_endpoint
    return plugin_base.PluginContext(
        org_slug='org',
        project_id='proj',
        project_slug='proj',
        integration_slug='sonarqube',
        integration_options=integration_options,
    )


_DEFAULT_CREDS = {'api_token': 'token-abc'}


class UpdateProjectFromWebhookTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._env = unittest.mock.patch.dict(
            os.environ,
            {
                'ACTIONS_IMBI_TOKEN': 'imbi-token',
                'ACTIONS_IMBI_URL': 'http://imbi-api.example.com',
            },
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    @respx.mock
    async def test_happy_path_patches_all_metrics(self) -> None:
        respx.get('https://sonarqube.example.com/api/measures/component').mock(
            return_value=httpx.Response(200, json=_SAMPLE_RESPONSE)
        )
        patch_route = respx.patch(
            'http://imbi-api.example.com/organizations/org/projects/proj'
        ).mock(return_value=httpx.Response(204))
        await actions.update_project_from_webhook(
            ctx=_ctx(),
            credentials=_DEFAULT_CREDS,
            external_identifier='proj-1',
            action_config=_config(),
            event={},
        )
        self.assertTrue(patch_route.called)
        sent = patch_route.calls.last.request.content
        self.assertIn(b'"path":"/test_coverage"', sent)
        self.assertIn(b'"value":"85.0"', sent)
        self.assertIn(b'"path":"/lines_of_code"', sent)
        self.assertIn(b'"value":"1234"', sent)

    @respx.mock
    async def test_missing_api_token_skips_with_warning(self) -> None:
        with self.assertLogs('imbi.plugins.sonarqube.actions') as cm:
            await actions.update_project_from_webhook(
                ctx=_ctx(),
                credentials={},
                external_identifier='proj-1',
                action_config=_config(),
                event={},
            )
        self.assertEqual(0, respx.calls.call_count)
        self.assertTrue(any('api_token' in line for line in cm.output))

    @respx.mock
    async def test_missing_service_endpoint_skips(self) -> None:
        with self.assertLogs('imbi.plugins.sonarqube.actions'):
            await actions.update_project_from_webhook(
                ctx=_ctx(service_endpoint=None),
                credentials=_DEFAULT_CREDS,
                external_identifier='proj-1',
                action_config=_config(),
                event={},
            )
        self.assertEqual(0, respx.calls.call_count)

    @respx.mock
    async def test_missing_metric_in_response_skips_that_op(self) -> None:
        partial: dict[str, object] = {
            'component': {
                'key': 'proj-1',
                'measures': [
                    {'metric': 'coverage', 'value': '85.0'},
                ],
            }
        }
        respx.get('https://sonarqube.example.com/api/measures/component').mock(
            return_value=httpx.Response(200, json=partial)
        )
        patch_route = respx.patch(
            'http://imbi-api.example.com/organizations/org/projects/proj'
        ).mock(return_value=httpx.Response(204))
        with self.assertLogs(
            'imbi.plugins.sonarqube.actions', level='WARNING'
        ) as cm:
            await actions.update_project_from_webhook(
                ctx=_ctx(),
                credentials=_DEFAULT_CREDS,
                external_identifier='proj-1',
                action_config=_config(),
                event={},
            )
        self.assertTrue(patch_route.called)
        sent = patch_route.calls.last.request.content
        self.assertIn(b'/test_coverage', sent)
        self.assertNotIn(b'/lines_of_code', sent)
        self.assertTrue(
            any('measure' in line and 'ncloc' in line for line in cm.output)
        )

    @respx.mock
    async def test_no_metrics_match_skips_patch(self) -> None:
        empty: dict[str, object] = {
            'component': {'key': 'proj-1', 'measures': []}
        }
        respx.get('https://sonarqube.example.com/api/measures/component').mock(
            return_value=httpx.Response(200, json=empty)
        )
        patch_route = respx.patch(
            'http://imbi-api.example.com/organizations/org/projects/proj'
        ).mock(return_value=httpx.Response(204))
        await actions.update_project_from_webhook(
            ctx=_ctx(),
            credentials=_DEFAULT_CREDS,
            external_identifier='proj-1',
            action_config=_config(),
            event={},
        )
        self.assertFalse(patch_route.called)

    @respx.mock
    async def test_sonarqube_client_error_swallowed(self) -> None:
        respx.get('https://sonarqube.example.com/api/measures/component').mock(
            return_value=httpx.Response(500, text='boom')
        )
        patch_route = respx.patch(
            'http://imbi-api.example.com/organizations/org/projects/proj'
        ).mock(return_value=httpx.Response(204))
        with self.assertLogs('imbi.plugins.sonarqube.actions', level='ERROR'):
            await actions.update_project_from_webhook(
                ctx=_ctx(),
                credentials=_DEFAULT_CREDS,
                external_identifier='proj-1',
                action_config=_config(),
                event={},
            )
        self.assertFalse(patch_route.called)

    async def test_empty_mappings_short_circuits(self) -> None:
        with self.assertLogs('imbi.plugins.sonarqube.actions', level='DEBUG'):
            await actions.update_project_from_webhook(
                ctx=_ctx(),
                credentials=_DEFAULT_CREDS,
                external_identifier='proj-1',
                action_config=_config('[]'),
                event={},
            )
        self.assertEqual(0, respx.calls.call_count)

    @respx.mock
    async def test_imbi_patch_failure_is_logged(self) -> None:
        respx.get('https://sonarqube.example.com/api/measures/component').mock(
            return_value=httpx.Response(200, json=_SAMPLE_RESPONSE)
        )
        respx.patch(
            'http://imbi-api.example.com/organizations/org/projects/proj'
        ).mock(return_value=httpx.Response(500, text='kaboom'))
        with self.assertLogs(
            'imbi.plugins.sonarqube.actions', level='WARNING'
        ) as cm:
            await actions.update_project_from_webhook(
                ctx=_ctx(),
                credentials=_DEFAULT_CREDS,
                external_identifier='proj-1',
                action_config=_config(),
                event={},
            )
        self.assertTrue(any('Failed to patch' in line for line in cm.output))
