import unittest.mock

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
            await actions.update_project('myorg', 'proj-1', body, spec)

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
            await actions.update_project('org', 'proj', body, spec)

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
            await actions.update_project('org', 'proj', {}, '[]')

        mock_patch.assert_called_once_with('org', 'proj', [])

    async def test_invalid_update_spec_raises_validation_error(self) -> None:
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self.assertRaises(pydantic.ValidationError),
        ):
            await actions.update_project('org', 'proj', {}, 'not-json')

    async def test_missing_pointer_in_body_raises(self) -> None:
        body = {'foo': 'bar'}
        spec = '[{"path": "/x", "from": "/does/not/exist"}]'
        with (
            self.override_environment(ACTIONS_IMBI_TOKEN=_TOKEN),
            self.assertRaises(jsonpointer.JsonPointerException),
        ):
            await actions.update_project('org', 'proj', body, spec)


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


JsonPointerAdapter = pydantic.TypeAdapter(actions.JsonPointer)


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
