import json
import unittest.mock

import celpy.celparser
import httpx
import jsonpointer
import pydantic

from imbi_gateway import actions
from tests import helpers

_TOKEN = 'test-token'  # noqa: S105


class UpdateProjectTests(helpers.TestCase):
    async def test_single_rule_builds_correct_patch(self) -> None:
        body = {'repo': {'name': 'my-repo'}}
        spec = '[{"path": "/name", "from": "/repo/name"}]'
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'patch_project',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ) as mock_patch,
        ):
            await actions.update_project('myorg', 'proj-1', body, None, spec)

        mock_patch.assert_called_once_with(
            'myorg',
            'proj-1',
            [{'op': 'replace', 'path': '/name', 'value': 'my-repo'}],
        )

    async def test_multiple_rules_produce_multiple_operations(self) -> None:
        body = {'a': 1, 'b': 2}
        spec = '[{"path": "/x", "from": "/a"}, {"path": "/y", "from": "/b"}]'
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'patch_project',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ) as mock_patch,
        ):
            await actions.update_project('org', 'proj', body, None, spec)

        mock_patch.assert_called_once_with(
            'org',
            'proj',
            [
                {'op': 'replace', 'path': '/x', 'value': 1},
                {'op': 'replace', 'path': '/y', 'value': 2},
            ],
        )

    async def test_empty_rules_still_calls_patch(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'patch_project',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ) as mock_patch,
        ):
            await actions.update_project('org', 'proj', {}, None, '[]')

        mock_patch.assert_called_once_with('org', 'proj', [])

    async def test_invalid_update_spec_raises_validation_error(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self.assertRaises(pydantic.ValidationError),
        ):
            await actions.update_project('org', 'proj', {}, None, 'not-json')

    async def test_missing_pointer_in_body_raises(self) -> None:
        body = {'foo': 'bar'}
        spec = '[{"path": "/x", "from": "/does/not/exist"}]'
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self.assertRaises(jsonpointer.JsonPointerException),
        ):
            await actions.update_project('org', 'proj', body, None, spec)


class ImbiClientPatchProjectTests(helpers.TestCase):
    async def test_url_is_constructed_from_org_and_project(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'patch',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ) as mock_patch,
        ):
            async with actions.ImbiClient() as client:
                await client.patch_project('myorg', 'proj-42', [])

        mock_patch.assert_called_once_with(
            '/organizations/myorg/projects/proj-42', json=[]
        )

    async def test_error_response_logs_warning(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'patch',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(422, json={'detail': 'invalid'}),
            ),
            self.assertLogs('imbi_gateway.actions', level='WARNING') as cm,
        ):
            async with actions.ImbiClient() as client:
                response = await client.patch_project('org', 'proj', [])

        self.assertEqual(422, response.status_code)
        self.assertTrue(any('Failed to patch' in line for line in cm.output))

    async def test_error_response_with_non_json_body_logs_content(
        self,
    ) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'patch',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(
                    500, content=b'Internal Server Error'
                ),
            ),
            self.assertLogs('imbi_gateway.actions', level='WARNING') as cm,
        ):
            async with actions.ImbiClient() as client:
                response = await client.patch_project('org', 'proj', [])

        self.assertEqual(500, response.status_code)
        self.assertTrue(any('Failed to patch' in line for line in cm.output))

    async def test_success_response_does_not_log_warning(self) -> None:
        ops = [{'op': 'replace', 'path': '/name', 'value': 'x'}]
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'patch',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ),
        ):
            async with actions.ImbiClient() as client:
                response = await client.patch_project('org', 'proj', ops)

        self.assertEqual(200, response.status_code)


_DEPLOYMENT_BODY: dict[str, object] = {
    'deployment': {
        'ref': 'v1.2.3',
        'sha': 'abcdef1234567890',
        'description': 'Deployed v1.2.3 to production',
        'url': 'https://api.github.com/repos/o/r/deployments/42',
        'environment': 'production',
        'creator': {'id': 12345},
    }
}

_STATUS_BODY: dict[str, object] = {
    'deployment': {
        'ref': 'v1.2.3',
        'url': 'https://api.github.com/repos/o/r/deployments/42',
        'environment': 'production',
    },
    'deployment_status': {'state': 'success', 'environment': 'production'},
}

_CREATE_RELEASE_CONFIG = (
    '{"title_selector": "/deployment/ref",'
    ' "version_expression": "deployment.ref"}'
)
_DEPLOYMENT_EVENT_CONFIG = (
    '{"environment_selector": "/deployment_status/environment",'
    ' "version_expression": "deployment.ref",'
    ' "status_selector": "/deployment_status/state"}'
)


class CreateReleaseTests(helpers.TestCase):
    async def test_happy_path_includes_user_id(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(201),
            ) as mock_create,
        ):
            await actions.create_release(
                'org',
                'proj',
                _DEPLOYMENT_BODY,
                'alice@example.com',
                _CREATE_RELEASE_CONFIG,
            )

        mock_create.assert_called_once()
        org_arg, proj_arg, body_arg = mock_create.call_args.args
        self.assertEqual('org', org_arg)
        self.assertEqual('proj', proj_arg)
        self.assertEqual('v1.2.3', body_arg['version'])
        self.assertEqual('v1.2.3', body_arg['title'])
        self.assertEqual('alice@example.com', body_arg['created_by'])
        self.assertNotIn('links', body_arg)

    async def test_no_user_omits_created_by(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(201),
            ) as mock_create,
        ):
            await actions.create_release(
                'org', 'proj', _DEPLOYMENT_BODY, None, _CREATE_RELEASE_CONFIG
            )

        body_arg = mock_create.call_args.args[2]
        self.assertNotIn('created_by', body_arg)

    async def test_title_selector_used(self) -> None:
        config = (
            '{"title_selector": "/deployment/description",'
            ' "version_expression": "deployment.ref"}'
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(201),
            ) as mock_create,
        ):
            await actions.create_release(
                'org', 'proj', _DEPLOYMENT_BODY, None, config
            )

        body_arg = mock_create.call_args.args[2]
        self.assertEqual('Deployed v1.2.3 to production', body_arg['title'])
        self.assertEqual('v1.2.3', body_arg['version'])

    async def test_version_expression_evaluated(self) -> None:
        # Same shape as the feature-file example (ref when it looks
        # like a semver tag, otherwise fall back to the sha) but using
        # `[.]` character classes since `\.` would require a four-deep
        # escape stack through Python -> JSON -> CEL.
        config = json.dumps(
            {
                'title_selector': '/deployment/ref',
                'version_expression': (
                    'deployment.ref.matches('
                    "'^[0-9]+[.][0-9]+[.][0-9]+$'"
                    ') ? deployment.ref'
                    " : 'sha-' + deployment.sha"
                ),
            }
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(201),
            ) as mock_create,
        ):
            # Branch-style ref -> takes the fallback expression.
            await actions.create_release(
                'org',
                'proj',
                {'deployment': {'ref': 'feature/x', 'sha': 'abcdef1234'}},
                None,
                config,
            )
            self.assertEqual(
                'sha-abcdef1234', mock_create.call_args.args[2]['version']
            )

            # Semver-style ref -> takes the deployment.ref branch.
            await actions.create_release(
                'org',
                'proj',
                {'deployment': {'ref': '1.2.3', 'sha': 'abcdef1234'}},
                None,
                config,
            )
            self.assertEqual('1.2.3', mock_create.call_args.args[2]['version'])

    async def test_substring_function_available(self) -> None:
        # `substring(s, start, end)` for trimming a git sha to its
        # short form. Same call also works as the method form
        # `s.substring(start, end)`.
        config = json.dumps(
            {
                'title_selector': '/deployment/ref',
                'version_expression': 'substring(deployment.sha, 0, 7)',
            }
        )
        method_config = json.dumps(
            {
                'title_selector': '/deployment/ref',
                'version_expression': 'deployment.sha.substring(0, 7)',
            }
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(201),
            ) as mock_create,
        ):
            await actions.create_release(
                'org',
                'proj',
                {'deployment': {'ref': 'main', 'sha': 'abcdef1234567890'}},
                None,
                config,
            )
            self.assertEqual(
                'abcdef1', mock_create.call_args.args[2]['version']
            )

            await actions.create_release(
                'org',
                'proj',
                {'deployment': {'ref': 'main', 'sha': 'abcdef1234567890'}},
                None,
                method_config,
            )
            self.assertEqual(
                'abcdef1', mock_create.call_args.args[2]['version']
            )

    async def test_substring_with_only_start(self) -> None:
        config = json.dumps(
            {
                'title_selector': '/deployment/ref',
                'version_expression': 'deployment.sha.substring(8)',
            }
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(201),
            ) as mock_create,
        ):
            await actions.create_release(
                'org',
                'proj',
                {'deployment': {'ref': 'main', 'sha': 'abcdef1234567890'}},
                None,
                config,
            )
            self.assertEqual(
                '34567890', mock_create.call_args.args[2]['version']
            )

    async def test_invalid_handler_config_raises_validation_error(
        self,
    ) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self.assertRaises(pydantic.ValidationError),
        ):
            await actions.create_release(
                'org', 'proj', _DEPLOYMENT_BODY, None, '{}'
            )

    async def test_invalid_version_expression_propagates(self) -> None:
        config = (
            '{"title_selector": "/deployment/ref",'
            ' "version_expression": "this is not valid CEL"}'
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self.assertRaises(celpy.celparser.CELParseError),
        ):
            await actions.create_release(
                'org', 'proj', _DEPLOYMENT_BODY, None, config
            )

    async def test_409_is_treated_as_idempotent(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(409, json={'detail': 'exists'}),
            ),
            self.assertLogs('imbi_gateway.actions', level='DEBUG') as cm,
        ):
            # No exception expected — already exists is the steady state.
            await actions.create_release(
                'org', 'proj', _DEPLOYMENT_BODY, None, _CREATE_RELEASE_CONFIG
            )

        self.assertTrue(any('already exists' in line for line in cm.output))


class AddDeploymentEventTests(helpers.TestCase):
    async def test_status_mapping(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'record_deployment',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ) as mock_record,
        ):
            await actions.add_deployment_event(
                'org', 'proj', _STATUS_BODY, None, _DEPLOYMENT_EVENT_CONFIG
            )

        mock_record.assert_called_once_with(
            'org', 'proj', 'v1.2.3', 'production', {'status': 'success'}
        )

    async def test_note_selector_emits_note(self) -> None:
        config = json.dumps(
            {
                'environment_selector': '/deployment_status/environment',
                'version_expression': 'deployment.ref',
                'status_selector': '/deployment_status/state',
                'note_selector': '/deployment/url',
            }
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'record_deployment',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ) as mock_record,
        ):
            await actions.add_deployment_event(
                'org', 'proj', _STATUS_BODY, None, config
            )

        event_body = mock_record.call_args.args[4]
        self.assertEqual(
            'https://api.github.com/repos/o/r/deployments/42',
            event_body['note'],
        )

    async def test_failure_state_maps_to_failed(self) -> None:
        body = {
            **_STATUS_BODY,
            'deployment_status': {
                'state': 'failure',
                'environment': 'production',
            },
        }
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'record_deployment',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ) as mock_record,
        ):
            await actions.add_deployment_event(
                'org', 'proj', body, None, _DEPLOYMENT_EVENT_CONFIG
            )

        self.assertEqual('failed', mock_record.call_args.args[4]['status'])

    async def test_unknown_state_skipped(self) -> None:
        body = {
            **_STATUS_BODY,
            'deployment_status': {
                'state': 'frobbed',
                'environment': 'production',
            },
        }
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'record_deployment',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_record,
            self.assertLogs('imbi_gateway.actions', level='WARNING') as cm,
        ):
            await actions.add_deployment_event(
                'org', 'proj', body, None, _DEPLOYMENT_EVENT_CONFIG
            )

        mock_record.assert_not_called()
        self.assertTrue(
            any('Unmapped' in line and 'frobbed' in line for line in cm.output)
        )

    async def test_release_missing_logs_warning(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'record_deployment',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(404, json={'detail': 'missing'}),
            ),
            self.assertLogs('imbi_gateway.actions', level='WARNING') as cm,
        ):
            await actions.add_deployment_event(
                'org', 'proj', _STATUS_BODY, None, _DEPLOYMENT_EVENT_CONFIG
            )

        self.assertTrue(
            any('Release' in line and 'missing' in line for line in cm.output)
        )

    async def test_invalid_handler_config_raises_validation_error(
        self,
    ) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self.assertRaises(pydantic.ValidationError),
        ):
            await actions.add_deployment_event(
                'org', 'proj', _STATUS_BODY, None, '{}'
            )


class ImbiClientFindUserByIdentityTests(helpers.TestCase):
    async def test_url_and_params_returns_email(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'get',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(
                    200, json={'email': 'alice@example.com'}
                ),
            ) as mock_get,
        ):
            async with actions.ImbiClient() as client:
                result = await client.find_user_by_identity('github', 's-1')

        mock_get.assert_called_once_with(
            '/users/by-identity',
            params={'plugin_slug': 'github', 'subject': 's-1'},
        )
        self.assertEqual('alice@example.com', result)

    async def test_404_returns_none(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'get',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(404),
            ),
        ):
            async with actions.ImbiClient() as client:
                result = await client.find_user_by_identity('github', 's-1')

        self.assertIsNone(result)

    async def test_other_error_logs_and_returns_none(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'get',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(500, content=b'boom'),
            ),
            self.assertLogs('imbi_gateway.actions', level='WARNING') as cm,
        ):
            async with actions.ImbiClient() as client:
                result = await client.find_user_by_identity('github', 's-1')

        self.assertIsNone(result)
        self.assertTrue(
            any('Failed to look up user' in line for line in cm.output)
        )

    async def test_missing_email_returns_none(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'get',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200, json={'id': 1}),
            ),
        ):
            async with actions.ImbiClient() as client:
                result = await client.find_user_by_identity('github', 's-1')

        self.assertIsNone(result)

    async def test_null_email_returns_none(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'get',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200, json={'email': None}),
            ),
        ):
            async with actions.ImbiClient() as client:
                result = await client.find_user_by_identity('github', 's-1')

        self.assertIsNone(result)


class ImbiClientCreateReleaseTests(helpers.TestCase):
    async def test_url_is_constructed_from_org_and_project(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'post',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(201),
            ) as mock_post,
        ):
            async with actions.ImbiClient() as client:
                await client.create_release(
                    'myorg', 'proj-42', {'version': 'v1'}
                )

        mock_post.assert_called_once_with(
            '/organizations/myorg/projects/proj-42/releases/',
            json={'version': 'v1'},
        )

    async def test_409_response_does_not_log_warning(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'post',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(409, json={'detail': 'exists'}),
            ),
            self.assertNoLogs('imbi_gateway.actions', level='WARNING'),
        ):
            async with actions.ImbiClient() as client:
                response = await client.create_release('o', 'p', {})

        self.assertEqual(409, response.status_code)

    async def test_other_error_logs_warning(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'post',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(500, content=b'boom'),
            ),
            self.assertLogs('imbi_gateway.actions', level='WARNING') as cm,
        ):
            async with actions.ImbiClient() as client:
                response = await client.create_release('o', 'p', {})

        self.assertEqual(500, response.status_code)
        self.assertTrue(
            any('Failed to create release' in line for line in cm.output)
        )


class ImbiClientRecordDeploymentTests(helpers.TestCase):
    async def test_url_is_constructed(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'post',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ) as mock_post,
        ):
            async with actions.ImbiClient() as client:
                await client.record_deployment(
                    'o', 'p', 'v1.2.3', 'prod', {'status': 'success'}
                )

        mock_post.assert_called_once_with(
            '/organizations/o/projects/p/releases/v1.2.3/environments/prod',
            json={'status': 'success'},
        )

    async def test_404_response_does_not_log_warning(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'post',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(404),
            ),
            self.assertNoLogs('imbi_gateway.actions', level='WARNING'),
        ):
            async with actions.ImbiClient() as client:
                response = await client.record_deployment(
                    'o', 'p', 'v1', 'prod', {}
                )

        self.assertEqual(404, response.status_code)

    async def test_other_error_logs_warning(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'post',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(500, content=b'boom'),
            ),
            self.assertLogs('imbi_gateway.actions', level='WARNING') as cm,
        ):
            async with actions.ImbiClient() as client:
                response = await client.record_deployment(
                    'o', 'p', 'v1', 'prod', {}
                )

        self.assertEqual(500, response.status_code)
        self.assertTrue(
            any('Failed to record deployment' in line for line in cm.output)
        )


class StatusMapTests(helpers.TestCase):
    """Verify every GitHub deployment_status state mapping."""

    async def _capture_status(self, github_state: str) -> str:
        body = {
            **_STATUS_BODY,
            'deployment_status': {
                'state': github_state,
                'environment': 'production',
            },
        }
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'record_deployment',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ) as mock_record,
        ):
            await actions.add_deployment_event(
                'o', 'p', body, None, _DEPLOYMENT_EVENT_CONFIG
            )
        return str(mock_record.call_args.args[4]['status'])

    async def test_all_known_states(self) -> None:
        cases = {
            'queued': 'pending',
            'pending': 'pending',
            'in_progress': 'in_progress',
            'success': 'success',
            'failure': 'failed',
            'error': 'failed',
            'inactive': 'rolled_back',
        }
        for github_state, imbi_status in cases.items():
            with self.subTest(state=github_state):
                self.assertEqual(
                    imbi_status, await self._capture_status(github_state)
                )


JsonPointerAdapter = pydantic.TypeAdapter[actions.JsonPointer](
    actions.JsonPointer
)


class JsonPointerTests(helpers.TestCase):
    def test_json_pointer_parsing(self) -> None:
        ptr = jsonpointer.JsonPointer('/target')
        self.assertIs(ptr, JsonPointerAdapter.validate_python(ptr))
        self.assertEqual(ptr, JsonPointerAdapter.validate_python('/target'))
        with self.assertRaises(ValueError):
            JsonPointerAdapter.validate_python('../relative-is-unsupported')
        with self.assertRaises(ValueError):
            JsonPointerAdapter.validate_python(42)

    def test_serialization(self) -> None:
        ptr = JsonPointerAdapter.validate_python('/target')
        self.assertEqual(b'"/target"', JsonPointerAdapter.dump_json(ptr))
        self.assertEqual(
            jsonpointer.JsonPointer('/target'),
            JsonPointerAdapter.dump_python(ptr),
        )
        self.assertEqual(
            {'type': 'string', 'format': 'json-pointer'},
            JsonPointerAdapter.json_schema(),
        )
