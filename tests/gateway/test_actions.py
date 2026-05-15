import json
import unittest.mock

import celpy.celparser
import httpx
import jsonpointer
import pydantic
from imbi_common.plugins import base as plugin_base

from imbi_gateway import actions
from tests import helpers

_TOKEN = 'test-token'  # noqa: S105


def _ctx(
    *,
    org_slug: str = 'org',
    project_id: str = 'proj',
    project_slug: str = 'proj',
    user_id: str | None = None,
) -> plugin_base.PluginContext:
    return plugin_base.PluginContext(
        org_slug=org_slug,
        project_id=project_id,
        project_slug=project_slug,
        actor_user_id=user_id,
    )


class UpdateProjectTests(helpers.TestCase):
    async def test_single_rule_builds_correct_patch(self) -> None:
        body = {'repo': {'name': 'my-repo'}}
        config = actions.UpdateProjectConfig.model_validate_json(
            '[{"path": "/name", "from": "/repo/name"}]'
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'patch_project',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ) as mock_patch,
        ):
            await actions.update_project(
                ctx=_ctx(org_slug='myorg', project_id='proj-1'),
                credentials={},
                external_identifier='',
                action_config=config,
                payload=body,
            )

        mock_patch.assert_called_once_with(
            'myorg',
            'proj-1',
            [{'op': 'add', 'path': '/name', 'value': 'my-repo'}],
        )

    async def test_multiple_rules_produce_multiple_operations(self) -> None:
        body = {'a': 1, 'b': 2}
        config = actions.UpdateProjectConfig.model_validate_json(
            '[{"path": "/x", "from": "/a"}, {"path": "/y", "from": "/b"}]'
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'patch_project',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ) as mock_patch,
        ):
            await actions.update_project(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload=body,
            )

        mock_patch.assert_called_once_with(
            'org',
            'proj',
            [
                {'op': 'add', 'path': '/x', 'value': 1},
                {'op': 'add', 'path': '/y', 'value': 2},
            ],
        )

    async def test_empty_rules_still_calls_patch(self) -> None:
        config = actions.UpdateProjectConfig.model_validate_json('[]')
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'patch_project',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ) as mock_patch,
        ):
            await actions.update_project(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload={},
            )

        mock_patch.assert_called_once_with('org', 'proj', [])

    async def test_missing_pointer_in_body_raises(self) -> None:
        body = {'foo': 'bar'}
        config = actions.UpdateProjectConfig.model_validate_json(
            '[{"path": "/x", "from": "/does/not/exist"}]'
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self.assertRaises(jsonpointer.JsonPointerException),
        ):
            await actions.update_project(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload=body,
            )


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

def _create_release_config(
    raw: str = (
        '{"title_selector": "/deployment/ref",'
        ' "committish_expression": "substring(deployment.sha, 0, 7)",'
        ' "version_expression": "deployment.ref"}'
    ),
) -> actions.CreateReleaseConfig:
    return actions.CreateReleaseConfig.model_validate_json(raw)


def _deployment_event_config(
    raw: str = (
        '{"environment_selector": "/deployment_status/environment",'
        ' "version_expression": "deployment.ref",'
        ' "status_selector": "/deployment_status/state"}'
    ),
) -> actions.AddDeploymentEventConfig:
    return actions.AddDeploymentEventConfig.model_validate_json(raw)


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
                ctx=_ctx(user_id='alice@example.com'),
                credentials={},
                external_identifier='',
                action_config=_create_release_config(),
                payload=_DEPLOYMENT_BODY,
            )

        mock_create.assert_called_once()
        org_arg, proj_arg, body_arg = mock_create.call_args.args
        self.assertEqual('org', org_arg)
        self.assertEqual('proj', proj_arg)
        self.assertEqual('v1.2.3', body_arg['tag'])
        self.assertEqual('abcdef1', body_arg['committish'])
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
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_create_release_config(),
                payload=_DEPLOYMENT_BODY,
            )

        body_arg = mock_create.call_args.args[2]
        self.assertNotIn('created_by', body_arg)

    async def test_title_selector_used(self) -> None:
        config = _create_release_config(
            '{"title_selector": "/deployment/description",'
            ' "version_expression": "deployment.ref",'
            ' "committish_expression": "substring(deployment.sha, 0, 7)"}'
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
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload=_DEPLOYMENT_BODY,
            )

        body_arg = mock_create.call_args.args[2]
        self.assertEqual('Deployed v1.2.3 to production', body_arg['title'])
        self.assertEqual('v1.2.3', body_arg['tag'])

    async def test_version_expression_evaluated(self) -> None:
        config = _create_release_config(
            json.dumps(
                {
                    'title_selector': '/deployment/ref',
                    'committish_expression': 'deployment.sha',
                    'version_expression': (
                        'deployment.ref.matches('
                        "'^[0-9]+[.][0-9]+[.][0-9]+$'"
                        ') ? deployment.ref'
                        " : 'sha-' + deployment.sha"
                    ),
                }
            )
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
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload={
                    'deployment': {'ref': 'feature/x', 'sha': 'abcdef1234'}
                },
            )
            self.assertEqual(
                'sha-abcdef1234', mock_create.call_args.args[2]['tag']
            )

            await actions.create_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload={'deployment': {'ref': '1.2.3', 'sha': 'abcdef1234'}},
            )
            self.assertEqual('1.2.3', mock_create.call_args.args[2]['tag'])

    async def test_substring_function_available(self) -> None:
        cfg = {
            'title_selector': '/deployment/ref',
            'version_expression': 'deployment.ref',
        }
        config = _create_release_config(
            json.dumps(
                cfg | {
                    'committish_expression': 'substring(deployment.sha, 0, 7)',
                }
            )
        )
        method_config = _create_release_config(
            json.dumps(
                cfg | {
                    'committish_expression': 'deployment.sha.substring(0, 7)',
                }
            )
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
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload={
                    'deployment': {'ref': 'main', 'sha': 'abcdef1234567890'}
                },
            )
            self.assertEqual('abcdef1', mock_create.call_args.args[2]['committish'])

            await actions.create_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=method_config,
                payload={
                    'deployment': {'ref': 'main', 'sha': 'abcdef1234567890'}
                },
            )
            self.assertEqual('abcdef1', mock_create.call_args.args[2]['committish'])

    async def test_substring_with_only_start(self) -> None:
        config = _create_release_config(
            json.dumps(
                {
                    'title_selector': '/deployment/ref',
                    'committish_expression': 'deployment.sha.substring(8)',
                    'version_expression': 'deployment.ref',
                }
            )
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
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload={
                    'deployment': {'ref': 'main', 'sha': 'abcdef1234567890'}
                },
            )
            self.assertEqual('34567890', mock_create.call_args.args[2]['committish'])

    async def test_invalid_version_expression_propagates(self) -> None:
        config = _create_release_config(
            '{"title_selector": "/deployment/ref",'
            ' "version_expression": "this is not valid CEL",'
            ' "committish_expression": "substring(deployment.sha, 0, 7)"}'
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self.assertRaises(celpy.celparser.CELParseError),
        ):
            await actions.create_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload=_DEPLOYMENT_BODY,
            )

    async def test_invalid_committish_expression_propagates(self) -> None:
        config = _create_release_config(
            '{"title_selector": "/deployment/ref",'
            ' "version_expression": "deployment.ref",'
            ' "committish_expression": "this is not valid CEL"}'
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self.assertRaises(celpy.celparser.CELParseError),
        ):
            await actions.create_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload=_DEPLOYMENT_BODY,
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
            await actions.create_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_create_release_config(),
                payload=_DEPLOYMENT_BODY,
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
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_deployment_event_config(),
                payload=_STATUS_BODY,
            )

        mock_record.assert_called_once_with(
            'org', 'proj', 'v1.2.3', 'production', {'status': 'success'}
        )

    async def test_note_selector_emits_note(self) -> None:
        config = _deployment_event_config(
            json.dumps(
                {
                    'environment_selector': '/deployment_status/environment',
                    'version_expression': 'deployment.ref',
                    'status_selector': '/deployment_status/state',
                    'note_selector': '/deployment/url',
                }
            )
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
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload=_STATUS_BODY,
            )

        event_body = mock_record.call_args.args[4]
        self.assertEqual(
            'https://api.github.com/repos/o/r/deployments/42',
            event_body['note'],
        )

    async def test_failure_state_maps_to_failed(self) -> None:
        payload = {
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
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_deployment_event_config(),
                payload=payload,
            )

        self.assertEqual('failed', mock_record.call_args.args[4]['status'])

    async def test_unknown_state_skipped(self) -> None:
        payload = {
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
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_deployment_event_config(),
                payload=payload,
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
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_deployment_event_config(),
                payload=_STATUS_BODY,
            )

        self.assertTrue(
            any('Release' in line and 'missing' in line for line in cm.output)
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
                await client.create_release('myorg', 'proj-42', {'tag': 'v1'})

        mock_post.assert_called_once_with(
            '/organizations/myorg/projects/proj-42/releases/',
            json={'tag': 'v1'},
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
        payload = {
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
                ctx=_ctx(org_slug='o', project_id='p'),
                credentials={},
                external_identifier='',
                action_config=_deployment_event_config(),
                payload=payload,
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
