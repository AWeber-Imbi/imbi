import json
import typing
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
        'sha': 'abcdef1234567890',
        'url': 'https://api.github.com/repos/o/r/deployments/42',
        'environment': 'production',
    },
    'deployment_status': {'state': 'success', 'environment': 'production'},
}

_RELEASE_ID = 'rel-nanoid-abc'


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
        ' "committish_expression": "substring(deployment.sha, 0, 7)",'
        ' "version_expression": "deployment.ref",'
        ' "status_selector": "/deployment_status/state"}'
    ),
) -> actions.AddDeploymentEventConfig:
    return actions.AddDeploymentEventConfig.model_validate_json(raw)


def _patch_list_releases(
    releases: list[dict[str, object]] | None = None,
) -> typing.Any:  # noqa: ANN401 — unittest.mock._patch is private
    """Patch ``ImbiClient.list_releases`` to return ``releases``.

    Defaults to a single release with ``id == _RELEASE_ID`` so most
    tests get the happy-path lookup for free.
    """
    return unittest.mock.patch.object(
        actions.ImbiClient,
        'list_releases',
        new_callable=unittest.mock.AsyncMock,
        return_value=releases
        if releases is not None
        else [{'id': _RELEASE_ID}],
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

    async def test_committish_expression_is_required(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            _create_release_config(
                '{"title_selector": "/deployment/ref",'
                ' "version_expression": "deployment.ref"}'
            )

    async def test_omits_tag_when_version_expression_absent(self) -> None:
        config = _create_release_config(
            '{"title_selector": "/deployment/ref",'
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
        self.assertNotIn('tag', body_arg)
        self.assertEqual('abcdef1', body_arg['committish'])

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
                cfg
                | {'committish_expression': 'substring(deployment.sha, 0, 7)'}
            )
        )
        method_config = _create_release_config(
            json.dumps(
                cfg
                | {'committish_expression': 'deployment.sha.substring(0, 7)'}
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
            self.assertEqual(
                'abcdef1', mock_create.call_args.args[2]['committish']
            )

            await actions.create_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=method_config,
                payload={
                    'deployment': {'ref': 'main', 'sha': 'abcdef1234567890'}
                },
            )
            self.assertEqual(
                'abcdef1', mock_create.call_args.args[2]['committish']
            )

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
            self.assertEqual(
                '34567890', mock_create.call_args.args[2]['committish']
            )

    async def test_null_version_expression_omits_tag(self) -> None:
        config = _create_release_config(
            json.dumps(
                {
                    'title_selector': '/deployment/ref',
                    'version_expression': (
                        "deployment.ref.matches('^[0-9]+[.][0-9]+[.][0-9]+$')"
                        ' ? deployment.ref : null'
                    ),
                    'committish_expression': 'substring(deployment.sha, 0, 7)',
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

        mock_create.assert_called_once()
        body_arg = mock_create.call_args.args[2]
        self.assertNotIn('tag', body_arg)
        self.assertEqual('abcdef1', body_arg['committish'])

    async def test_null_committish_expression_skips_release(self) -> None:
        config = _create_release_config(
            json.dumps(
                {
                    'title_selector': '/deployment/ref',
                    'version_expression': 'deployment.ref',
                    'committish_expression': (
                        "deployment.sha != '' ? deployment.sha : null"
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
            self.assertLogs('imbi_gateway.actions', level='WARNING') as cm,
        ):
            await actions.create_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload={'deployment': {'ref': 'v1.2.3', 'sha': ''}},
            )

        mock_create.assert_not_called()
        self.assertTrue(
            any(
                'committish expression evaluated to null' in line
                for line in cm.output
            )
        )

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
            _patch_list_releases() as mock_list,
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

        mock_list.assert_called_once_with(
            'org', 'proj', committish='abcdef1', tag='v1.2.3'
        )
        mock_record.assert_called_once_with(
            'org', 'proj', _RELEASE_ID, 'production', {'status': 'success'}
        )

    async def test_committish_expression_is_required(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            _deployment_event_config(
                '{"environment_selector": "/deployment_status/environment",'
                ' "version_expression": "deployment.ref",'
                ' "status_selector": "/deployment_status/state"}'
            )

    async def test_lookup_uses_committish_only_when_version_absent(
        self,
    ) -> None:
        config = _deployment_event_config(
            json.dumps(
                {
                    'environment_selector': '/deployment_status/environment',
                    'committish_expression': 'substring(deployment.sha, 0, 7)',
                    'status_selector': '/deployment_status/state',
                }
            )
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            _patch_list_releases() as mock_list,
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

        mock_list.assert_called_once_with(
            'org', 'proj', committish='abcdef1', tag=None
        )
        mock_record.assert_called_once()

    async def test_lookup_drops_tag_when_version_expression_yields_null(
        self,
    ) -> None:
        config = _deployment_event_config(
            json.dumps(
                {
                    'environment_selector': '/deployment_status/environment',
                    'committish_expression': 'substring(deployment.sha, 0, 7)',
                    'version_expression': (
                        "deployment.ref.matches('^[0-9]+[.][0-9]+[.][0-9]+$')"
                        ' ? deployment.ref : null'
                    ),
                    'status_selector': '/deployment_status/state',
                }
            )
        )
        payload = {
            **_STATUS_BODY,
            'deployment': {
                **typing.cast('dict[str, object]', _STATUS_BODY['deployment']),
                'ref': 'main',
            },
        }
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            _patch_list_releases() as mock_list,
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
                payload=payload,
            )

        mock_list.assert_called_once_with(
            'org', 'proj', committish='abcdef1', tag=None
        )
        mock_record.assert_called_once()

    async def test_null_committish_expression_skips_event(self) -> None:
        config = _deployment_event_config(
            json.dumps(
                {
                    'environment_selector': '/deployment_status/environment',
                    'committish_expression': (
                        "deployment.sha != '' ? deployment.sha : null"
                    ),
                    'status_selector': '/deployment_status/state',
                }
            )
        )
        payload = {
            **_STATUS_BODY,
            'deployment': {
                **typing.cast('dict[str, object]', _STATUS_BODY['deployment']),
                'sha': '',
            },
        }
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            _patch_list_releases() as mock_list,
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
                action_config=config,
                payload=payload,
            )

        mock_list.assert_not_called()
        mock_record.assert_not_called()
        self.assertTrue(
            any(
                'committish expression evaluated to null' in line
                for line in cm.output
            )
        )

    async def test_no_matching_release_warns_and_skips(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            _patch_list_releases([]),
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
                payload=_STATUS_BODY,
            )

        mock_record.assert_not_called()
        self.assertTrue(
            any('No release matches' in line for line in cm.output)
        )

    async def test_note_selector_emits_note(self) -> None:
        config = _deployment_event_config(
            json.dumps(
                {
                    'environment_selector': '/deployment_status/environment',
                    'committish_expression': 'substring(deployment.sha, 0, 7)',
                    'version_expression': 'deployment.ref',
                    'status_selector': '/deployment_status/state',
                    'note_selector': '/deployment/url',
                }
            )
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            _patch_list_releases(),
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
            _patch_list_releases(),
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
            _patch_list_releases() as mock_list,
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

        mock_list.assert_not_called()
        mock_record.assert_not_called()
        self.assertTrue(
            any('Unmapped' in line and 'frobbed' in line for line in cm.output)
        )

    async def test_release_missing_logs_warning(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            _patch_list_releases(),
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
                    'o', 'p', _RELEASE_ID, 'prod', {'status': 'success'}
                )

        mock_post.assert_called_once_with(
            f'/organizations/o/projects/p/releases/{_RELEASE_ID}'
            f'/environments/prod',
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


class ImbiClientListReleasesTests(helpers.TestCase):
    async def test_url_and_no_filters(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'get',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200, json=[{'id': _RELEASE_ID}]),
            ) as mock_get,
        ):
            async with actions.ImbiClient() as client:
                releases = await client.list_releases('org', 'proj')

        mock_get.assert_called_once_with(
            '/organizations/org/projects/proj/releases/', params={}
        )
        self.assertEqual([{'id': _RELEASE_ID}], releases)

    async def test_passes_committish_and_tag(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'get',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200, json=[]),
            ) as mock_get,
        ):
            async with actions.ImbiClient() as client:
                await client.list_releases(
                    'org', 'proj', committish='abcdef1', tag='v1.2.3'
                )

        mock_get.assert_called_once_with(
            '/organizations/org/projects/proj/releases/',
            params={'committish': 'abcdef1', 'tag': 'v1.2.3'},
        )

    async def test_error_logs_warning_and_returns_empty(self) -> None:
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
                releases = await client.list_releases('org', 'proj')

        self.assertEqual([], releases)
        self.assertTrue(
            any('Failed to list releases' in line for line in cm.output)
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
            _patch_list_releases(),
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


def _sbom_envelope(
    version: str = '1.2.3', *, sbom: dict[str, typing.Any] | None = None
) -> dict[str, typing.Any]:
    """Build a fake webhook envelope wrapping a CycloneDX document."""
    return {
        'repository': 'org/repo',
        'version': version,
        'sbom': sbom
        or {
            'bomFormat': 'CycloneDX',
            'specVersion': '1.7',
            'version': 1,
            'components': [],
        },
    }


class IngestSbomConfigTests(helpers.TestCase):
    """Pydantic validation of the handler-config JSON."""

    def test_minimal_config(self) -> None:
        config = actions.IngestSbomConfig.model_validate_json(
            '{"version_expression": "version"}'
        )
        self.assertEqual(config.version_expression, 'version')
        # Empty pointer defaults to the entire payload.
        self.assertEqual(str(config.sbom_selector), '')

    def test_sbom_selector_pointer(self) -> None:
        config = actions.IngestSbomConfig.model_validate_json(
            '{"version_expression": "version", "sbom_selector": "/sbom"}'
        )
        self.assertEqual(str(config.sbom_selector), '/sbom')

    def test_missing_required_version_expression(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            actions.IngestSbomConfig.model_validate_json('{}')


class IngestSbomTests(helpers.TestCase):
    """Behavior of ``actions.ingest_sbom`` end-to-end (mocking the API)."""

    def _config(self, sbom_pointer: str = '/sbom') -> actions.IngestSbomConfig:
        return actions.IngestSbomConfig.model_validate_json(
            json.dumps(
                {
                    'version_expression': 'version',
                    'sbom_selector': sbom_pointer,
                }
            )
        )

    async def test_resolves_release_then_puts_sbom(self) -> None:
        envelope = _sbom_envelope(version='2.0.0')
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                return_value=[{'id': 'rel-1', 'tag': '2.0.0'}],
            ) as mock_list,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(204),
            ) as mock_put,
        ):
            await actions.ingest_sbom(
                ctx=_ctx(org_slug='myorg', project_id='proj-1'),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                payload=envelope,
            )

        mock_list.assert_awaited_once_with('myorg', 'proj-1', tag='2.0.0')
        mock_put.assert_awaited_once_with(
            'myorg', 'proj-1', 'rel-1', envelope['sbom']
        )

    async def test_drops_sbom_when_release_missing(self) -> None:
        envelope = _sbom_envelope()
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                return_value=[],
            ) as mock_list,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_put,
        ):
            await actions.ingest_sbom(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                payload=envelope,
            )

        mock_list.assert_awaited_once()
        mock_put.assert_not_awaited()

    async def test_does_not_raise_on_api_error(self) -> None:
        # The action should NOT propagate non-2xx — the gateway is a
        # forwarder, and the API is responsible for surfacing the
        # detail. Mirrors the existing add_deployment_event behavior.
        envelope = _sbom_envelope()
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                return_value=[{'id': 'rel-1'}],
            ) as mock_list,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(
                    415, text='Unsupported spec version'
                ),
            ) as mock_put,
        ):
            await actions.ingest_sbom(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                payload=envelope,
            )
        mock_list.assert_awaited_once()
        mock_put.assert_awaited_once()

    async def test_skips_when_sbom_is_not_an_object(self) -> None:
        envelope = {'version': '1.0.0', 'sbom': 'not a dict'}
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_list,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_put,
        ):
            await actions.ingest_sbom(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                payload=envelope,
            )

        mock_list.assert_not_awaited()
        mock_put.assert_not_awaited()

    async def test_drops_when_sbom_selector_misses(self) -> None:
        # A malformed/mismatched payload (selector points at a missing
        # path) must warn and drop rather than bubble the
        # JsonPointerException up to the dispatcher.
        envelope = {'version': '1.0.0'}
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_list,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_put,
        ):
            await actions.ingest_sbom(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                payload=envelope,
            )

        mock_list.assert_not_awaited()
        mock_put.assert_not_awaited()

    async def test_conditional_version_expression_main_uses_short_sha(
        self,
    ) -> None:
        # The driving GitHub-Actions use case: deploys from ``main``
        # ship as short-SHA-tagged images (matching the deployment
        # image tag), while deploys from a release branch / tag ship
        # under that ref's name. The CEL ternary captures both.
        envelope: dict[str, typing.Any] = {
            'ref_name': 'main',
            'sha': 'deadbeef1234567890deadbeef1234567890dead',
            'sbom': {
                'bomFormat': 'CycloneDX',
                'specVersion': '1.7',
                'version': 1,
                'components': [],
            },
        }
        config = actions.IngestSbomConfig.model_validate_json(
            json.dumps(
                {
                    'version_expression': (
                        'ref_name == "main" ? substring(sha, 0, 7) : ref_name'
                    ),
                    'sbom_selector': '/sbom',
                }
            )
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                return_value=[{'id': 'rel-1', 'tag': 'deadbee'}],
            ) as mock_list,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(204),
            ),
        ):
            await actions.ingest_sbom(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload=envelope,
            )

        mock_list.assert_awaited_once_with('org', 'proj', tag='deadbee')

    async def test_conditional_version_expression_branch_uses_ref_name(
        self,
    ) -> None:
        # Same config, the non-main branch arm — the SBoM lands
        # under ``release/2.0.x`` rather than the short SHA.
        envelope: dict[str, typing.Any] = {
            'ref_name': 'release/2.0.x',
            'sha': 'deadbeef1234567890deadbeef1234567890dead',
            'sbom': {
                'bomFormat': 'CycloneDX',
                'specVersion': '1.7',
                'version': 1,
                'components': [],
            },
        }
        config = actions.IngestSbomConfig.model_validate_json(
            json.dumps(
                {
                    'version_expression': (
                        'ref_name == "main" ? substring(sha, 0, 7) : ref_name'
                    ),
                    'sbom_selector': '/sbom',
                }
            )
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                return_value=[{'id': 'rel-1'}],
            ) as mock_list,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(204),
            ),
        ):
            await actions.ingest_sbom(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload=envelope,
            )

        mock_list.assert_awaited_once_with('org', 'proj', tag='release/2.0.x')

    async def test_drops_when_version_expression_evaluates_null(self) -> None:
        # CEL ``null`` (e.g. a field that doesn't exist with the ?
        # navigation operator) means we have no release identity and
        # must not call list_releases.
        envelope = {'ref_name': None, 'sbom': {'specVersion': '1.7'}}
        config = actions.IngestSbomConfig.model_validate_json(
            json.dumps(
                {'version_expression': 'ref_name', 'sbom_selector': '/sbom'}
            )
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_list,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_put,
        ):
            await actions.ingest_sbom(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                payload=envelope,
            )

        mock_list.assert_not_awaited()
        mock_put.assert_not_awaited()


class IngestSbomAutoCreateTests(helpers.TestCase):
    """Behaviour of ``ingest_sbom`` when ``committish_expression`` is set."""

    def _config(
        self, *, title_selector: str | None = None
    ) -> actions.IngestSbomConfig:
        config: dict[str, str] = {
            'version_expression': 'version',
            'sbom_selector': '/sbom',
            'committish_expression': 'committish',
        }
        if title_selector is not None:
            config['title_selector'] = title_selector
        return actions.IngestSbomConfig.model_validate_json(json.dumps(config))

    def _envelope(
        self,
        *,
        committish: str | None = 'abc1234567890def',
        title: str | None = None,
        version: str = '1.2.3',
    ) -> dict[str, typing.Any]:
        envelope = _sbom_envelope(version=version)
        if committish is not None:
            envelope['committish'] = committish
        if title is not None:
            envelope['title'] = title
        return envelope

    async def test_creates_release_when_committish_resolves(self) -> None:
        envelope = self._envelope()
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                return_value=[],
            ) as mock_list,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(201, json={'id': 'rel-new'}),
            ) as mock_create,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(204),
            ) as mock_put,
        ):
            await actions.ingest_sbom(
                ctx=_ctx(org_slug='myorg', project_id='proj-1'),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                payload=envelope,
            )

        mock_list.assert_awaited_once_with('myorg', 'proj-1', tag='1.2.3')
        mock_create.assert_awaited_once_with(
            'myorg',
            'proj-1',
            {
                'committish': 'abc1234',
                'title': 'Release 1.2.3',
                'tag': '1.2.3',
            },
        )
        mock_put.assert_awaited_once_with(
            'myorg', 'proj-1', 'rel-new', envelope['sbom']
        )

    async def test_lowercases_and_truncates_committish(self) -> None:
        # Producers commonly emit the full 40-char SHA from
        # ``$GITHUB_SHA`` — the gateway is responsible for trimming it
        # to the 7-char short SHA the API requires.
        envelope = self._envelope(
            committish='ABCDEF1234567890ABCDEF1234567890ABCDEF12'
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                return_value=[],
            ),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(201, json={'id': 'rel-1'}),
            ) as mock_create,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(204),
            ),
        ):
            await actions.ingest_sbom(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                payload=envelope,
            )

        body = mock_create.call_args.args[2]
        self.assertEqual(body['committish'], 'abcdef1')

    async def test_uses_title_selector_when_present(self) -> None:
        envelope = self._envelope(title='2026.05.26 build')
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                return_value=[],
            ),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(201, json={'id': 'rel-1'}),
            ) as mock_create,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(204),
            ),
        ):
            await actions.ingest_sbom(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(title_selector='/title'),
                payload=envelope,
            )

        self.assertEqual(
            mock_create.call_args.args[2]['title'], '2026.05.26 build'
        )

    async def test_drops_when_committish_is_not_short_hex(self) -> None:
        # ``Release.committish`` is contracted to ^[0-9a-f]{7}$. A
        # producer that sends e.g. a branch name like "main" or a
        # short-but-non-hex value must drop, not generate a 4xx from
        # the API.
        envelope = self._envelope(committish='main')
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                return_value=[],
            ),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_create,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_put,
        ):
            await actions.ingest_sbom(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                payload=envelope,
            )

        mock_create.assert_not_awaited()
        mock_put.assert_not_awaited()

    async def test_drops_when_committish_expression_cannot_resolve(
        self,
    ) -> None:
        # The envelope helper omits the field when ``committish`` is
        # ``None`` — so the CEL ``"committish"`` raises CELEvalError
        # for an undeclared reference rather than evaluating to null.
        # The auto-create branch must treat both as "can't resolve"
        # and drop, not 500.
        envelope = self._envelope(committish=None)
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                return_value=[],
            ),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_create,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_put,
        ):
            await actions.ingest_sbom(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                payload=envelope,
            )

        mock_create.assert_not_awaited()
        mock_put.assert_not_awaited()

    async def test_handles_409_by_refetching(self) -> None:
        # Two webhook deliveries land in parallel: list_releases is
        # empty on both, the first wins create_release with 201 and
        # the second loses with 409. The losing run must re-list and
        # PUT against the winning release id rather than dropping.
        envelope = self._envelope()
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                side_effect=[[], [{'id': 'rel-winning'}]],
            ),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(409, text='exists'),
            ),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(204),
            ) as mock_put,
        ):
            await actions.ingest_sbom(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                payload=envelope,
            )

        mock_put.assert_awaited_once_with(
            'org', 'proj', 'rel-winning', envelope['sbom']
        )

    async def test_drops_on_create_release_error(self) -> None:
        envelope = self._envelope()
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                return_value=[],
            ),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'create_release',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(422, text='invalid committish'),
            ),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put_sbom',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_put,
        ):
            await actions.ingest_sbom(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                payload=envelope,
            )

        mock_put.assert_not_awaited()


class ImbiClientPutSbomTests(helpers.TestCase):
    """``ImbiClient.put_sbom`` URL/auth correctness."""

    async def test_url_includes_release_id(self) -> None:
        sbom_doc = {'bomFormat': 'CycloneDX', 'specVersion': '1.7'}
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(204),
            ) as mock_put,
        ):
            async with actions.ImbiClient() as client:
                response = await client.put_sbom(
                    'myorg', 'proj-1', 'rel-1', sbom_doc
                )

        self.assertEqual(response.status_code, 204)
        mock_put.assert_awaited_once_with(
            '/organizations/myorg/projects/proj-1/releases/rel-1/sbom',
            json=sbom_doc,
        )

    async def test_error_response_logs_warning(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'put',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(415, text='Unsupported'),
            ),
            self.assertLogs('imbi_gateway.actions', level='WARNING') as cm,
        ):
            async with actions.ImbiClient() as client:
                response = await client.put_sbom(
                    'org',
                    'proj',
                    'rel',
                    {'bomFormat': 'CycloneDX', 'specVersion': '1.5'},
                )

        self.assertEqual(response.status_code, 415)
        self.assertTrue(
            any('Failed to put SBoM' in line for line in cm.output)
        )
