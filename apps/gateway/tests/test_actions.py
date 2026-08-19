import json
import typing
import unittest.mock

import celpy.celparser
import httpx
import jsonpointer
import pydantic

from apps.gateway.tests import helpers
from imbi.common.plugins import base as plugin_base
from imbi.gateway import actions

_TOKEN = 'test-token'


def _event(
    body: object,
    **overrides: typing.Any,
) -> dict[str, typing.Any]:
    """Wrap a webhook body in the event context handlers now receive."""
    return {
        'type': '',
        'integration': '',
        'attributed_to': '',
        'metadata': {'headers': {}},
        'payload': body,
        **overrides,
    }


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
            '[{"path": "/name", "from": "/payload/repo/name"}]'
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
                event=_event(body),
            )

        mock_patch.assert_called_once_with(
            'myorg',
            'proj-1',
            [{'op': 'add', 'path': '/name', 'value': 'my-repo'}],
        )

    async def test_multiple_rules_produce_multiple_operations(self) -> None:
        body = {'a': 1, 'b': 2}
        config = actions.UpdateProjectConfig.model_validate_json(
            '[{"path": "/x", "from": "/payload/a"},'
            ' {"path": "/y", "from": "/payload/b"}]'
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
                event=_event(body),
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
                event=_event({}),
            )

        mock_patch.assert_called_once_with('org', 'proj', [])

    async def test_missing_pointer_in_body_raises(self) -> None:
        body = {'foo': 'bar'}
        config = actions.UpdateProjectConfig.model_validate_json(
            '[{"path": "/x", "from": "/payload/does/not/exist"}]'
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
                event=_event(body),
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
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
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
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
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
        '{"title_selector": "/payload/deployment/ref",'
        ' "committish_expression": "substring(payload.deployment.sha, 0, 7)",'
        ' "version_expression": "payload.deployment.ref"}'
    ),
) -> actions.CreateReleaseConfig:
    return actions.CreateReleaseConfig.model_validate_json(raw)


def _deployment_event_config(
    raw: str = (
        '{"environment_selector": "/payload/deployment_status/environment",'
        ' "committish_expression": "substring(payload.deployment.sha, 0, 7)",'
        ' "version_expression": "payload.deployment.ref",'
        ' "status_selector": "/payload/deployment_status/state"}'
    ),
) -> actions.AddDeploymentEventConfig:
    return actions.AddDeploymentEventConfig.model_validate_json(raw)


def _run_selector_config() -> actions.AddDeploymentEventConfig:
    """A deployment-event config wired to both run selectors."""
    return _deployment_event_config(
        json.dumps(
            {
                'environment_selector': (
                    '/payload/deployment_status/environment'
                ),
                'committish_expression': (
                    'substring(payload.deployment.sha, 0, 7)'
                ),
                'version_expression': 'payload.deployment.ref',
                'status_selector': '/payload/deployment_status/state',
                'external_run_id_selector': '/payload/deployment/id',
                'external_run_url_selector': (
                    '/payload/deployment_status/log_url'
                ),
            }
        )
    )


def _patch_list_releases(
    releases: list[dict[str, object]] | None = None,
) -> typing.Any:
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
                event=_event(_DEPLOYMENT_BODY),
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
                event=_event(_DEPLOYMENT_BODY),
            )

        body_arg = mock_create.call_args.args[2]
        self.assertNotIn('created_by', body_arg)

    async def test_committish_expression_is_required(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            _create_release_config(
                '{"title_selector": "/payload/deployment/ref",'
                ' "version_expression": "payload.deployment.ref"}'
            )

    async def test_omits_tag_when_version_expression_absent(self) -> None:
        config = _create_release_config(
            '{"title_selector": "/payload/deployment/ref",'
            ' "committish_expression": "substring(payload.deployment.sha,'
            ' 0, 7)"}'
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
                event=_event(_DEPLOYMENT_BODY),
            )

        body_arg = mock_create.call_args.args[2]
        self.assertNotIn('tag', body_arg)
        self.assertEqual('abcdef1', body_arg['committish'])

    async def test_title_selector_used(self) -> None:
        config = _create_release_config(
            '{"title_selector": "/payload/deployment/description",'
            ' "version_expression": "payload.deployment.ref",'
            ' "committish_expression": "substring(payload.deployment.sha,'
            ' 0, 7)"}'
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
                event=_event(_DEPLOYMENT_BODY),
            )

        body_arg = mock_create.call_args.args[2]
        self.assertEqual('Deployed v1.2.3 to production', body_arg['title'])
        self.assertEqual('v1.2.3', body_arg['tag'])

    async def test_version_expression_evaluated(self) -> None:
        config = _create_release_config(
            json.dumps(
                {
                    'title_selector': '/payload/deployment/ref',
                    'committish_expression': 'payload.deployment.sha',
                    'version_expression': (
                        'payload.deployment.ref.matches('
                        "'^[0-9]+[.][0-9]+[.][0-9]+$'"
                        ') ? payload.deployment.ref'
                        " : 'sha-' + payload.deployment.sha"
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
                event=_event(
                    {'deployment': {'ref': 'feature/x', 'sha': 'abcdef1234'}}
                ),
            )
            self.assertEqual(
                'sha-abcdef1234', mock_create.call_args.args[2]['tag']
            )

            await actions.create_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                event=_event(
                    {'deployment': {'ref': '1.2.3', 'sha': 'abcdef1234'}}
                ),
            )
            self.assertEqual('1.2.3', mock_create.call_args.args[2]['tag'])

    async def test_substring_function_available(self) -> None:
        cfg = {
            'title_selector': '/payload/deployment/ref',
            'version_expression': 'payload.deployment.ref',
        }
        config = _create_release_config(
            json.dumps(
                cfg
                | {
                    'committish_expression': (
                        'substring(payload.deployment.sha, 0, 7)'
                    )
                }
            )
        )
        method_config = _create_release_config(
            json.dumps(
                cfg
                | {
                    'committish_expression': (
                        'payload.deployment.sha.substring(0, 7)'
                    )
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
                event=_event(
                    {'deployment': {'ref': 'main', 'sha': 'abcdef1234567890'}}
                ),
            )
            self.assertEqual(
                'abcdef1', mock_create.call_args.args[2]['committish']
            )

            await actions.create_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=method_config,
                event=_event(
                    {'deployment': {'ref': 'main', 'sha': 'abcdef1234567890'}}
                ),
            )
            self.assertEqual(
                'abcdef1', mock_create.call_args.args[2]['committish']
            )

    async def test_substring_with_only_start(self) -> None:
        config = _create_release_config(
            json.dumps(
                {
                    'title_selector': '/payload/deployment/ref',
                    'committish_expression': (
                        'payload.deployment.sha.substring(8)'
                    ),
                    'version_expression': 'payload.deployment.ref',
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
                event=_event(
                    {'deployment': {'ref': 'main', 'sha': 'abcdef1234567890'}}
                ),
            )
            self.assertEqual(
                '34567890', mock_create.call_args.args[2]['committish']
            )

    async def test_null_version_expression_omits_tag(self) -> None:
        config = _create_release_config(
            json.dumps(
                {
                    'title_selector': '/payload/deployment/ref',
                    'version_expression': (
                        'payload.deployment.ref.matches'
                        "('^[0-9]+[.][0-9]+[.][0-9]+$')"
                        ' ? payload.deployment.ref : null'
                    ),
                    'committish_expression': (
                        'substring(payload.deployment.sha, 0, 7)'
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
                event=_event(
                    {'deployment': {'ref': 'main', 'sha': 'abcdef1234567890'}}
                ),
            )

        mock_create.assert_called_once()
        body_arg = mock_create.call_args.args[2]
        self.assertNotIn('tag', body_arg)
        self.assertEqual('abcdef1', body_arg['committish'])

    async def test_null_committish_expression_skips_release(self) -> None:
        config = _create_release_config(
            json.dumps(
                {
                    'title_selector': '/payload/deployment/ref',
                    'version_expression': 'payload.deployment.ref',
                    'committish_expression': (
                        "payload.deployment.sha != ''"
                        ' ? payload.deployment.sha : null'
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
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
        ):
            await actions.create_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                event=_event({'deployment': {'ref': 'v1.2.3', 'sha': ''}}),
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
            '{"title_selector": "/payload/deployment/ref",'
            ' "version_expression": "this is not valid CEL",'
            ' "committish_expression": "substring(payload.deployment.sha,'
            ' 0, 7)"}'
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
                event=_event(_DEPLOYMENT_BODY),
            )

    async def test_invalid_committish_expression_propagates(self) -> None:
        config = _create_release_config(
            '{"title_selector": "/payload/deployment/ref",'
            ' "version_expression": "payload.deployment.ref",'
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
                event=_event(_DEPLOYMENT_BODY),
            )

    async def test_null_title_selector_falls_back_to_the_version(self) -> None:
        # An Imbi-created GitHub Deployment carries no ``description``;
        # stringifying that null used to title the release "None".
        config = _create_release_config(
            '{"title_selector": "/payload/deployment/description",'
            ' "version_expression": "payload.deployment.ref",'
            ' "committish_expression": "substring(payload.deployment.sha,'
            ' 0, 7)"}'
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
                event=_event(
                    {
                        'deployment': {
                            'ref': 'v1.2.3',
                            'sha': 'abcdef1234567890',
                            'description': None,
                        }
                    }
                ),
            )

        self.assertEqual(
            'Release v1.2.3', mock_create.call_args.args[2]['title']
        )

    async def test_title_selector_is_optional(self) -> None:
        config = _create_release_config(
            '{"version_expression": "payload.deployment.ref",'
            ' "committish_expression": "substring(payload.deployment.sha,'
            ' 0, 7)"}'
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
                event=_event(_DEPLOYMENT_BODY),
            )

        self.assertEqual(
            'Release v1.2.3', mock_create.call_args.args[2]['title']
        )

    async def test_title_falls_back_to_committish_without_a_tag(self) -> None:
        config = _create_release_config(
            '{"committish_expression": "substring(payload.deployment.sha,'
            ' 0, 7)"}'
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
                event=_event(_DEPLOYMENT_BODY),
            )

        self.assertEqual(
            'Release abcdef1', mock_create.call_args.args[2]['title']
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
            self.assertLogs('imbi.gateway.actions', level='DEBUG') as cm,
        ):
            await actions.create_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_create_release_config(),
                event=_event(_DEPLOYMENT_BODY),
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
                event=_event(_STATUS_BODY),
            )

        mock_list.assert_called_once_with('org', 'proj', tag='v1.2.3')
        mock_record.assert_called_once_with(
            'org', 'proj', _RELEASE_ID, 'production', {'status': 'success'}
        )

    async def test_tag_lookup_wins_over_a_drifted_committish(self) -> None:
        """The tag resolves the release even when the SHA has moved.

        ``release-tag.yaml`` tags the version-bump commit, so the SHA on
        the ``deployment_status`` payload is not the one the Release node
        carries until ``complete_promote_build`` heals it.  Pairing both
        filters dropped the event for that whole window.
        """
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                return_value=[{'id': _RELEASE_ID, 'committish': '9999999'}],
            ) as mock_list,
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
                event=_event(_STATUS_BODY),
            )

        mock_list.assert_called_once_with('org', 'proj', tag='v1.2.3')
        mock_record.assert_called_once_with(
            'org', 'proj', _RELEASE_ID, 'production', {'status': 'success'}
        )

    async def test_failed_tag_lookup_drops_instead_of_falling_back(
        self,
    ) -> None:
        """A failed tag lookup must not resolve by committish.

        ``list_releases`` returns ``None`` when the request itself
        failed, which is not the same answer as an empty list -- falling
        back would record the event against whatever node carries this
        SHA, the mis-attribution the tag-first order exists to end.
        """
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                side_effect=[None, [{'id': _RELEASE_ID}]],
            ) as mock_list,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'record_deployment',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_record,
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
        ):
            await actions.add_deployment_event(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_deployment_event_config(),
                event=_event(_STATUS_BODY),
            )

        mock_list.assert_called_once_with('org', 'proj', tag='v1.2.3')
        mock_record.assert_not_called()
        self.assertTrue(
            any('dropped rather than resolved' in line for line in cm.output)
        )

    async def test_lookup_falls_back_to_committish_when_tag_misses(
        self,
    ) -> None:
        """A tag Imbi never recorded still resolves by commit."""
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'list_releases',
                new_callable=unittest.mock.AsyncMock,
                side_effect=[[], [{'id': _RELEASE_ID}]],
            ) as mock_list,
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
                event=_event(_STATUS_BODY),
            )

        self.assertEqual(
            mock_list.await_args_list,
            [
                unittest.mock.call('org', 'proj', tag='v1.2.3'),
                unittest.mock.call('org', 'proj', committish='abcdef1'),
            ],
        )
        mock_record.assert_called_once()

    async def test_committish_expression_is_required(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            _deployment_event_config(
                '{"environment_selector":'
                ' "/payload/deployment_status/environment",'
                ' "version_expression": "payload.deployment.ref",'
                ' "status_selector": "/payload/deployment_status/state"}'
            )

    async def test_lookup_uses_committish_only_when_version_absent(
        self,
    ) -> None:
        config = _deployment_event_config(
            json.dumps(
                {
                    'environment_selector': (
                        '/payload/deployment_status/environment'
                    ),
                    'committish_expression': (
                        'substring(payload.deployment.sha, 0, 7)'
                    ),
                    'status_selector': '/payload/deployment_status/state',
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
                event=_event(_STATUS_BODY),
            )

        mock_list.assert_called_once_with('org', 'proj', committish='abcdef1')
        mock_record.assert_called_once()

    async def test_lookup_drops_tag_when_version_expression_yields_null(
        self,
    ) -> None:
        config = _deployment_event_config(
            json.dumps(
                {
                    'environment_selector': (
                        '/payload/deployment_status/environment'
                    ),
                    'committish_expression': (
                        'substring(payload.deployment.sha, 0, 7)'
                    ),
                    'version_expression': (
                        'payload.deployment.ref.matches'
                        "('^[0-9]+[.][0-9]+[.][0-9]+$')"
                        ' ? payload.deployment.ref : null'
                    ),
                    'status_selector': '/payload/deployment_status/state',
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
                event=_event(payload),
            )

        mock_list.assert_called_once_with('org', 'proj', committish='abcdef1')
        mock_record.assert_called_once()

    async def test_null_committish_expression_skips_event(self) -> None:
        config = _deployment_event_config(
            json.dumps(
                {
                    'environment_selector': (
                        '/payload/deployment_status/environment'
                    ),
                    'committish_expression': (
                        "payload.deployment.sha != ''"
                        ' ? payload.deployment.sha : null'
                    ),
                    'status_selector': '/payload/deployment_status/state',
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
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
        ):
            await actions.add_deployment_event(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                event=_event(payload),
            )

        mock_list.assert_not_called()
        mock_record.assert_not_called()
        self.assertTrue(
            any(
                'committish expression evaluated to null' in line
                for line in cm.output
            )
        )

    async def test_failed_write_is_not_counted_as_recorded(self) -> None:
        """A 5xx loses the event; the count has to say so."""
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            _patch_list_releases(),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'record_deployment',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(503),
            ),
            unittest.mock.patch.object(
                actions.metrics, 'deployment_event'
            ) as mock_metric,
        ):
            await actions.add_deployment_event(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_deployment_event_config(),
                event=_event(_STATUS_BODY),
            )
        mock_metric.assert_called_once_with('write_failed', 'proj')

    async def test_failed_unattached_write_is_counted_as_failed(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            _patch_list_releases([]),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'record_unattached_deployment',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(500),
            ),
            unittest.mock.patch.object(
                actions.metrics, 'deployment_event'
            ) as mock_metric,
        ):
            await actions.add_deployment_event(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_deployment_event_config(),
                event=_event(_STATUS_BODY),
            )
        mock_metric.assert_called_once_with('write_failed', 'proj')

    async def test_dispositions_are_counted(self) -> None:
        """Every outcome is counted, not only logged.

        A dropped event returns normally, so the activity feed records
        the handler as succeeded -- counting is the only way to see the
        loss without grepping logs.
        """
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            _patch_list_releases(),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'record_deployment',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(200),
            ),
            unittest.mock.patch.object(
                actions.metrics, 'deployment_event'
            ) as mock_metric,
        ):
            await actions.add_deployment_event(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_deployment_event_config(),
                event=_event(_STATUS_BODY),
            )
        mock_metric.assert_called_once_with('recorded', 'proj')

    async def test_unmapped_status_is_counted(self) -> None:
        body = {
            **_STATUS_BODY,
            'deployment_status': {'state': 'martian'},
        }
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.metrics, 'deployment_event'
            ) as mock_metric,
        ):
            await actions.add_deployment_event(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_deployment_event_config(),
                event=_event(body),
            )
        mock_metric.assert_called_once_with('unmapped_status', 'proj')

    async def test_no_matching_release_records_without_one(self) -> None:
        """An unresolvable release must not cost us the deployment.

        Dropping the event is how a real rollout went unrecorded
        whenever release identity drifted. It is recorded against the
        project and environment instead, carrying what failed to
        resolve so the sweeper can attach the Release later.
        """
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            _patch_list_releases([]),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'record_deployment',
                new_callable=unittest.mock.AsyncMock,
            ) as mock_record,
            unittest.mock.patch.object(
                actions.ImbiClient,
                'record_unattached_deployment',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(201, json={'deployment_id': 'd1'}),
            ) as mock_unattached,
        ):
            await actions.add_deployment_event(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_deployment_event_config(),
                event=_event(_STATUS_BODY),
            )

        mock_record.assert_not_called()
        mock_unattached.assert_called_once_with(
            'org',
            'proj',
            'production',
            {
                'status': 'success',
                'tag': 'v1.2.3',
                'committish': 'abcdef1',
            },
        )

    async def test_note_selector_emits_note(self) -> None:
        config = _deployment_event_config(
            json.dumps(
                {
                    'environment_selector': (
                        '/payload/deployment_status/environment'
                    ),
                    'committish_expression': (
                        'substring(payload.deployment.sha, 0, 7)'
                    ),
                    'version_expression': 'payload.deployment.ref',
                    'status_selector': '/payload/deployment_status/state',
                    'note_selector': '/payload/deployment/url',
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
                event=_event(_STATUS_BODY),
            )

        event_body = mock_record.call_args.args[4]
        self.assertEqual(
            'https://api.github.com/repos/o/r/deployments/42',
            event_body['note'],
        )

    async def test_run_selectors_emit_run_id_and_url(self) -> None:
        payload = {
            **_STATUS_BODY,
            'deployment': {**_STATUS_BODY['deployment'], 'id': 42},  # type: ignore[dict-item]
            'deployment_status': {
                'state': 'success',
                'environment': 'production',
                'log_url': 'https://gh/o/r/actions/runs/99',
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
                action_config=_run_selector_config(),
                event=_event(payload),
            )

        event_body = mock_record.call_args.args[4]
        self.assertEqual('42', event_body['external_run_id'])
        self.assertEqual(
            'https://gh/o/r/actions/runs/99', event_body['external_run_url']
        )

    async def test_absent_run_url_omits_the_key(self) -> None:
        # GitHub posts the first deployment_status of a rollout before
        # the workflow knows its own run URL; the key must be dropped
        # rather than sent as the literal "None".
        payload = {
            **_STATUS_BODY,
            'deployment': {**_STATUS_BODY['deployment'], 'id': 42},  # type: ignore[dict-item]
            'deployment_status': {
                'state': 'in_progress',
                'environment': 'production',
                'log_url': '',
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
                action_config=_run_selector_config(),
                event=_event(payload),
            )

        event_body = mock_record.call_args.args[4]
        self.assertNotIn('external_run_url', event_body)
        self.assertEqual('42', event_body['external_run_id'])

    async def test_missing_run_url_pointer_omits_the_key(self) -> None:
        # The pointer resolving to nothing at all (no ``log_url`` key)
        # must degrade the same way an empty one does, not raise.
        payload = {
            **_STATUS_BODY,
            'deployment': {**_STATUS_BODY['deployment'], 'id': 42},  # type: ignore[dict-item]
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
                action_config=_run_selector_config(),
                event=_event(payload),
            )

        self.assertNotIn('external_run_url', mock_record.call_args.args[4])

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
                event=_event(payload),
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
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
        ):
            await actions.add_deployment_event(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_deployment_event_config(),
                event=_event(payload),
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
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
        ):
            await actions.add_deployment_event(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=_deployment_event_config(),
                event=_event(_STATUS_BODY),
            )

        self.assertTrue(
            any('Release' in line and 'missing' in line for line in cm.output)
        )


def _status_body(state: str) -> dict[str, object]:
    """A ``deployment_status`` body reporting ``state``."""
    return {
        'deployment': {'ref': 'v1.2.3', 'sha': 'abcdef1234567890'},
        'deployment_status': {'state': state, 'environment': 'production'},
    }


_PUBLISH_CONFIG = (
    '{"version_expression": "payload.deployment.ref",'
    ' "status_selector": "/payload/deployment_status/state"}'
)


class PublishReleaseTests(helpers.TestCase):
    def _config(self, raw: str = _PUBLISH_CONFIG) -> typing.Any:
        return actions.PublishReleaseConfig.model_validate_json(raw)

    def _patch(self, response: httpx.Response) -> typing.Any:
        return unittest.mock.patch.object(
            actions.ImbiClient,
            'publish_release',
            new_callable=unittest.mock.AsyncMock,
            return_value=response,
        )

    async def test_success_publishes_the_tag(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self._patch(httpx.Response(200, json={'published': True})) as pub,
        ):
            await actions.publish_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                event=_event(_status_body('success')),
            )

        pub.assert_called_once_with('org', 'proj', 'v1.2.3', False)

    async def test_prerelease_flag_is_forwarded(self) -> None:
        config = self._config(
            '{"version_expression": "payload.deployment.ref",'
            ' "status_selector": "/payload/deployment_status/state",'
            ' "prerelease": true}'
        )
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self._patch(httpx.Response(200)) as pub,
        ):
            await actions.publish_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                event=_event(_status_body('success')),
            )

        pub.assert_called_once_with('org', 'proj', 'v1.2.3', True)

    async def test_non_success_states_do_not_publish(self) -> None:
        for state in ('failure', 'error', 'inactive', 'pending', 'queued'):
            with self.subTest(state=state):
                with (
                    self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
                    self._patch(httpx.Response(200)) as pub,
                ):
                    await actions.publish_release(
                        ctx=_ctx(),
                        credentials={},
                        external_identifier='',
                        action_config=self._config(),
                        event=_event(_status_body(state)),
                    )
                pub.assert_not_called()

    async def test_unmapped_state_does_not_publish(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self._patch(httpx.Response(200)) as pub,
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
        ):
            await actions.publish_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                event=_event(_status_body('frobbed')),
            )

        pub.assert_not_called()
        self.assertTrue(any('Unmapped' in line for line in cm.output))

    async def test_null_version_is_skipped(self) -> None:
        config = self._config(
            '{"version_expression": "payload.deployment.tag",'
            ' "status_selector": "/payload/deployment_status/state"}'
        )
        body = _status_body('success')
        typing.cast('dict[str, object]', body['deployment'])['tag'] = None
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self._patch(httpx.Response(200)) as pub,
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
        ):
            await actions.publish_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                event=_event(body),
            )

        pub.assert_not_called()
        self.assertTrue(any('evaluated to null' in line for line in cm.output))

    async def test_404_and_409_are_not_failures(self) -> None:
        for status in (404, 409):
            with self.subTest(status=status):
                with (
                    self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
                    self._patch(httpx.Response(status, json={'detail': 'no'})),
                    self.assertLogs('imbi.gateway.actions', 'INFO') as cm,
                ):
                    await actions.publish_release(
                        ctx=_ctx(),
                        credentials={},
                        external_identifier='',
                        action_config=self._config(),
                        event=_event(_status_body('success')),
                    )
                self.assertTrue(
                    any('was not published' in line for line in cm.output)
                )


_BLOCK_CONFIG = (
    '{"version_expression": "payload.deployment.ref",'
    ' "status_selector": "/payload/deployment_status/state"}'
)


class BlockReleaseTests(helpers.TestCase):
    def _config(self, raw: str = _BLOCK_CONFIG) -> typing.Any:
        return actions.BlockReleaseConfig.model_validate_json(raw)

    def _patch(self, response: httpx.Response) -> typing.Any:
        return unittest.mock.patch.object(
            actions.ImbiClient,
            'block_release',
            new_callable=unittest.mock.AsyncMock,
            return_value=response,
        )

    async def test_failure_states_block_with_a_default_reason(self) -> None:
        for state in ('failure', 'error'):
            with self.subTest(state=state):
                with (
                    self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
                    self._patch(httpx.Response(200)) as block,
                ):
                    await actions.block_release(
                        ctx=_ctx(),
                        credentials={},
                        external_identifier='',
                        action_config=self._config(),
                        event=_event(_status_body(state)),
                    )
                block.assert_called_once_with(
                    'org', 'proj', 'v1.2.3', f'Deployment reported {state}'
                )

    async def test_inactive_does_not_block(self) -> None:
        # ``inactive`` maps to ``rolled_back``: the deployment was
        # superseded by a newer one, which is the normal end of every
        # deployment's life and must never block the tag.
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self._patch(httpx.Response(200)) as block,
        ):
            await actions.block_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                event=_event(_status_body('inactive')),
            )

        block.assert_not_called()

    async def test_success_and_pending_do_not_block(self) -> None:
        for state in ('success', 'pending', 'queued', 'in_progress'):
            with self.subTest(state=state):
                with (
                    self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
                    self._patch(httpx.Response(200)) as block,
                ):
                    await actions.block_release(
                        ctx=_ctx(),
                        credentials={},
                        external_identifier='',
                        action_config=self._config(),
                        event=_event(_status_body(state)),
                    )
                block.assert_not_called()

    async def test_reason_selector_is_used(self) -> None:
        config = self._config(
            '{"version_expression": "payload.deployment.ref",'
            ' "status_selector": "/payload/deployment_status/state",'
            ' "reason_selector": "/payload/deployment_status/description"}'
        )
        body = _status_body('failure')
        status = typing.cast('dict[str, object]', body['deployment_status'])
        status['description'] = 'Migration 0042 failed'
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self._patch(httpx.Response(200)) as block,
        ):
            await actions.block_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                event=_event(body),
            )

        block.assert_called_once_with(
            'org', 'proj', 'v1.2.3', 'Migration 0042 failed'
        )

    async def test_null_reason_falls_back_to_the_state(self) -> None:
        config = self._config(
            '{"version_expression": "payload.deployment.ref",'
            ' "status_selector": "/payload/deployment_status/state",'
            ' "reason_selector": "/payload/deployment_status/description"}'
        )
        body = _status_body('failure')
        status = typing.cast('dict[str, object]', body['deployment_status'])
        status['description'] = None
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self._patch(httpx.Response(200)) as block,
        ):
            await actions.block_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                event=_event(body),
            )

        block.assert_called_once_with(
            'org', 'proj', 'v1.2.3', 'Deployment reported failure'
        )

    async def test_overlong_reason_is_truncated(self) -> None:
        config = self._config(
            '{"version_expression": "payload.deployment.ref",'
            ' "status_selector": "/payload/deployment_status/state",'
            ' "reason_selector": "/payload/deployment_status/description"}'
        )
        body = _status_body('failure')
        status = typing.cast('dict[str, object]', body['deployment_status'])
        status['description'] = 'x' * 600
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self._patch(httpx.Response(200)) as block,
        ):
            await actions.block_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=config,
                event=_event(body),
            )

        self.assertEqual(500, len(block.call_args.args[3]))

    async def test_missing_release_logs_a_warning(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self._patch(httpx.Response(404, json={'detail': 'missing'})),
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
        ):
            await actions.block_release(
                ctx=_ctx(),
                credentials={},
                external_identifier='',
                action_config=self._config(),
                event=_event(_status_body('failure')),
            )

        self.assertTrue(any('block dropped' in line for line in cm.output))


class ImbiClientPublishReleaseTests(helpers.TestCase):
    async def test_url_body_and_error_logging(self) -> None:
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
                await client.publish_release('org', 'proj', 'v1.2.3', True)

        mock_post.assert_called_once_with(
            '/organizations/org/projects/proj/deployments/releases'
            '/v1.2.3/publish',
            json={'prerelease': True},
        )

    async def test_server_error_logs_warning(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'post',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(500, text='boom'),
            ),
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
        ):
            async with actions.ImbiClient() as client:
                await client.publish_release('org', 'proj', 'v1.2.3', False)

        self.assertTrue(
            any('Failed to publish release' in line for line in cm.output)
        )

    async def test_404_and_409_do_not_log_warning(self) -> None:
        for status in (404, 409):
            with self.subTest(status=status):
                with (
                    self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
                    unittest.mock.patch.object(
                        actions.ImbiClient,
                        'post',
                        new_callable=unittest.mock.AsyncMock,
                        return_value=httpx.Response(status),
                    ),
                    self.assertNoLogs('imbi.gateway.actions', 'WARNING'),
                ):
                    async with actions.ImbiClient() as client:
                        await client.publish_release(
                            'org', 'proj', 'v1.2.3', False
                        )


class ImbiClientBlockReleaseTests(helpers.TestCase):
    async def test_url_and_body(self) -> None:
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
                await client.block_release('org', 'proj', 'v1.2.3', 'nope')

        mock_post.assert_called_once_with(
            '/organizations/org/projects/proj/deployments/releases'
            '/v1.2.3/block',
            json={'reason': 'nope'},
        )

    async def test_server_error_logs_warning(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'post',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(500, text='boom'),
            ),
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
        ):
            async with actions.ImbiClient() as client:
                await client.block_release('org', 'proj', 'v1.2.3', 'nope')

        self.assertTrue(
            any('Failed to block release' in line for line in cm.output)
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
            params={'integration_slug': 'github', 'subject': 's-1'},
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
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
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
            self.assertNoLogs('imbi.gateway.actions', level='WARNING'),
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
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
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
            self.assertNoLogs('imbi.gateway.actions', level='WARNING'),
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
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
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

    async def test_error_logs_warning_and_returns_none(self) -> None:
        """A failed request is ``None``, not an empty list.

        Callers that narrow a lookup and fall back on the empty case
        need the two apart; ``add_deployment_event`` drops the event
        rather than resolving it by committish when this returns
        ``None``.
        """
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            unittest.mock.patch.object(
                actions.ImbiClient,
                'get',
                new_callable=unittest.mock.AsyncMock,
                return_value=httpx.Response(500, content=b'boom'),
            ),
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
        ):
            async with actions.ImbiClient() as client:
                releases = await client.list_releases('org', 'proj')

        self.assertIsNone(releases)
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
                event=_event(payload),
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
            '{"version_expression": "payload.version"}'
        )
        self.assertEqual(config.version_expression, 'payload.version')
        # Empty pointer defaults to the entire event payload.
        self.assertEqual(str(config.sbom_selector), '/payload')

    def test_sbom_selector_pointer(self) -> None:
        config = actions.IngestSbomConfig.model_validate_json(
            '{"version_expression": "payload.version",'
            ' "sbom_selector": "/payload/sbom"}'
        )
        self.assertEqual(str(config.sbom_selector), '/payload/sbom')

    def test_missing_required_version_expression(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            actions.IngestSbomConfig.model_validate_json('{}')


class IngestSbomTests(helpers.TestCase):
    """Behavior of ``actions.ingest_sbom`` end-to-end (mocking the API)."""

    def _config(
        self, sbom_pointer: str = '/payload/sbom'
    ) -> actions.IngestSbomConfig:
        return actions.IngestSbomConfig.model_validate_json(
            json.dumps(
                {
                    'version_expression': 'payload.version',
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
                event=_event(envelope),
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
                event=_event(envelope),
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
                event=_event(envelope),
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
                event=_event(envelope),
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
                event=_event(envelope),
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
                        'payload.ref_name == "main"'
                        ' ? substring(payload.sha, 0, 7) : payload.ref_name'
                    ),
                    'sbom_selector': '/payload/sbom',
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
                event=_event(envelope),
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
                        'payload.ref_name == "main"'
                        ' ? substring(payload.sha, 0, 7) : payload.ref_name'
                    ),
                    'sbom_selector': '/payload/sbom',
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
                event=_event(envelope),
            )

        mock_list.assert_awaited_once_with('org', 'proj', tag='release/2.0.x')

    async def test_drops_when_version_expression_evaluates_null(self) -> None:
        # CEL ``null`` (e.g. a field that doesn't exist with the ?
        # navigation operator) means we have no release identity and
        # must not call list_releases.
        envelope = {'ref_name': None, 'sbom': {'specVersion': '1.7'}}
        config = actions.IngestSbomConfig.model_validate_json(
            json.dumps(
                {
                    'version_expression': 'payload.ref_name',
                    'sbom_selector': '/payload/sbom',
                }
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
                event=_event(envelope),
            )

        mock_list.assert_not_awaited()
        mock_put.assert_not_awaited()


class IngestSbomAutoCreateTests(helpers.TestCase):
    """Behaviour of ``ingest_sbom`` when ``committish_expression`` is set."""

    def _config(
        self, *, title_selector: str | None = None
    ) -> actions.IngestSbomConfig:
        config: dict[str, str] = {
            'version_expression': 'payload.version',
            'sbom_selector': '/payload/sbom',
            'committish_expression': 'payload.committish',
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
                event=_event(envelope),
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
                event=_event(envelope),
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
                action_config=self._config(title_selector='/payload/title'),
                event=_event(envelope),
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
                event=_event(envelope),
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
                event=_event(envelope),
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
                event=_event(envelope),
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
                event=_event(envelope),
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
            self.assertLogs('imbi.gateway.actions', level='WARNING') as cm,
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
