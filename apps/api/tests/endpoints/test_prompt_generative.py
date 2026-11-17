"""Tests for generative prompt runs and their call record."""

import asyncio
import json
import typing
import uuid
from unittest import mock

import httpx

from apps.api.tests.endpoints import test_ai_providers as provider_tests
from apps.api.tests.endpoints import test_prompts as base
from imbi.api.endpoints import ai_providers, prompts
from imbi.api.llm import generate as model_generate
from imbi.common.llm import generate

RUN_URL = f'/organizations/{base.ORG}/prompts/run'
CALL_ID = uuid.UUID('00000000-0000-0000-0000-000000000001')
MODEL_ROW = {
    'model_id': 'claude-opus-5',
    'enabled': True,
    'model_type': 'generative',
    'provider_id': 'prv-1',
    'structured': True,
    'input_cost': '3',
    'output_cost': '15',
}
FIELDS = [{'name': 'severity', 'type': 'string', 'required': True}]


def provider_row(**overrides: typing.Any) -> list[dict[str, typing.Any]]:
    return [
        {
            'p': provider_tests.provider_props(
                credentials_encrypted='ciphertext', **overrides
            )
        }
    ]


class GenerativeRunTestCase(base.PromptTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.generate = self._patch(
            generate,
            'generate',
            mock.AsyncMock(
                return_value=generate.Result(
                    'All good',
                    None,
                    {'input_tokens': 10, 'output_tokens': 5},
                    'req-1',
                )
            ),
        )
        self.decrypt = self._patch(
            model_generate, 'decrypt_config_value', mock.Mock(return_value='k')
        )
        self._patch(
            prompts.organizations,
            'check_member',
            mock.AsyncMock(return_value='org-1'),
        )
        self.calls.start.side_effect = lambda call, _stale: (
            {**call, 'id': CALL_ID},
            True,
        )

    def _patch(
        self, target: object, name: str, value: typing.Any
    ) -> typing.Any:
        patcher = mock.patch.object(target, name, value)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def route_run(self, **model: typing.Any) -> base.Router:
        return self.route(
            (base.GET_PROMPT, base.prompt_row()),
            (
                base.GET_VERSION,
                base.version_row(
                    messages=json.dumps(
                        [
                            {
                                'role': 'user',
                                'content': 'Check {{ project_slug }}',
                            }
                        ]
                    )
                ),
            ),
            (prompts._RUN_MODEL_QUERY, [{**MODEL_ROW, **model}]),
            (ai_providers._GET_QUERY, provider_row()),
        )

    def run_ref(self, **body: typing.Any) -> httpx.Response:
        headers = body.pop('headers', {})
        return self.client.post(
            RUN_URL,
            json={
                'ref': 'mender/core@stable',
                'variables': {'project_slug': 'billing'},
                **body,
            },
            headers=headers,
        )

    def test_runs_a_saved_version(self) -> None:
        self.route_run()
        response = self.run_ref()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['ref'], 'mender/core@1')
        self.assertEqual(data['n'], 1)
        self.assertEqual(data['text'], 'All good')
        self.assertIsNone(data['result'])
        self.assertEqual(data['content_sha256'], 'abc')
        self.assertEqual(data['call_id'], str(CALL_ID))
        self.assertAlmostEqual(data['cost_usd'], 0.000105)
        sent: generate.Request = self.generate.await_args.args[0]
        self.assertEqual(sent.credential, 'k')
        self.assertEqual(sent.system, 'You triage billing.')
        self.assertEqual(sent.messages[0].content, 'Check billing')
        call = self.calls.start.await_args.args[0]
        self.assertEqual(call['origin'], 'preview')
        self.assertEqual(call['organization_id'], 'org-1')
        self.assertIsNone(call['idempotency_key'])
        finished = self.calls.finish.await_args
        self.assertEqual(finished.args, (CALL_ID, 'succeeded'))
        self.assertEqual(finished.kwargs['provider_request_id'], 'req-1')

    def test_structured_fields_need_the_flag(self) -> None:
        self.route_run(structured=False)
        response = self.run_ref(output_fields=FIELDS)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()['detail'],
            {'error': 'model_no_structured_output', 'retry': False},
        )
        self.calls.start.assert_not_awaited()
        self.generate.assert_not_awaited()

    def test_structured_result(self) -> None:
        self.generate.return_value = generate.Result(
            '{"severity": "high"}',
            {'severity': 'high'},
            {'input_tokens': None, 'output_tokens': 5},
            None,
        )
        self.route_run()
        response = self.run_ref(output_fields=FIELDS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['result'], {'severity': 'high'})
        # An unmeasured count adds nothing (agent_tasks.usage_cost).
        self.assertAlmostEqual(response.json()['cost_usd'], 0.000075)
        sent: generate.Request = self.generate.await_args.args[0]
        self.assertEqual(sent.output_fields[0].name, 'severity')

    def test_run_permission_runs_a_saved_version(self) -> None:
        self.as_principal('prompt:run')
        self.route_run()
        self.assertEqual(self.run_ref().status_code, 200)

    def test_archived_workflow_prompt_runs_by_version(self) -> None:
        self.as_principal('prompt:run')
        slug = f'{base.ORG}.deploy.summary'
        self.route_run()
        self.mock_db.execute.side_effect.rules[0] = (
            base.GET_PROMPT,
            base.prompt_row(
                namespace='workflows', slug=slug, archived_at=base.STAMP
            ),
        )
        with mock.patch.object(
            prompts,
            'caller_org_slugs',
            mock.AsyncMock(return_value={base.ORG}),
        ):
            response = self.run_ref(ref=f'workflows/{slug}@1')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['ref'], f'workflows/{slug}@1')
            other = self.client.post(
                '/organizations/other/prompts/run',
                json={
                    'ref': f'workflows/{slug}@1',
                    'variables': {'project_slug': 'billing'},
                },
            )
        self.assertEqual(other.status_code, 422)

    def test_run_permission_cannot_run_a_draft(self) -> None:
        self.as_principal('prompt:run')
        self.route_run()
        response = self.client.post(
            RUN_URL,
            json={
                'draft': {
                    'namespace': 'mender',
                    'slug': 'core',
                    'version': {'system': 'Hi', 'model': 'default-chat'},
                }
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_workflow_write_runs_a_draft_of_its_prompt(self) -> None:
        slug = f'{base.ORG}.deploy.summary'
        self.route_run()
        draft = {
            'namespace': 'workflows',
            'slug': slug,
            'version': {'system': 'Hi', 'model': 'default-chat'},
        }
        with mock.patch.object(
            prompts,
            'caller_org_slugs',
            mock.AsyncMock(return_value={base.ORG}),
        ):
            # Not for another namespace.
            self.as_principal('workflow:write')
            response = self.client.post(
                RUN_URL,
                json={
                    'draft': {**draft, 'namespace': 'mender', 'slug': 'core'}
                },
            )
            self.assertEqual(response.status_code, 403)
            self.mock_db.execute.side_effect.rules[0] = (
                base.GET_PROMPT,
                base.prompt_row(namespace='workflows', slug=slug),
            )
            response = self.client.post(RUN_URL, json={'draft': draft})
            self.assertEqual(response.status_code, 200, response.text)
            self.as_principal('prompt:read')
            response = self.client.post(RUN_URL, json={'draft': draft})
            self.assertEqual(response.status_code, 403)

    def test_read_permission_is_not_enough(self) -> None:
        self.as_principal('prompt:read')
        self.route_run()
        self.assertEqual(self.run_ref().status_code, 403)
        self.generate.assert_not_awaited()

    def test_key_names_the_workflow_call(self) -> None:
        self.route_run()
        response = self.run_ref(headers={'Idempotency-Key': 'run-1:node-a:2'})
        self.assertEqual(response.status_code, 200, response.text)
        call = self.calls.start.await_args.args[0]
        self.assertEqual(call['origin'], 'workflow')
        self.assertEqual(call['idempotency_key'], 'run-1:node-a:2')
        self.assertEqual(
            (call['run_id'], call['node_id'], call['attempt']),
            ('run-1', 'node-a', 2),
        )

    def _repeat(self, **row: typing.Any) -> httpx.Response:
        enabled = row.pop('model_enabled', True)
        stored = {
            'id': CALL_ID,
            'prompt_ref': 'mender/core@1',
            'prompt_version': 1,
            'model': 'default-chat',
            'model_id': 'claude-opus-5',
            'content_sha256': 'abc',
            'text': 'Stored',
            'result': None,
            'usage': {'input_tokens': 1, 'output_tokens': 1},
            'cost_usd': None,
            'error': None,
            **row,
        }
        self.calls.repeat.return_value = stored
        self.route_run(enabled=enabled)
        return self.run_ref(headers={'Idempotency-Key': 'run-1:node-a:1'})

    def test_repeat_returns_the_stored_answer(self) -> None:
        response = self._repeat(status='succeeded')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['text'], 'Stored')
        self.generate.assert_not_awaited()
        self.calls.start.assert_not_awaited()
        self.calls.finish.assert_not_awaited()
        self.calls.repeat.assert_awaited_once_with(
            'org-1', mock.ANY, 'run-1:node-a:1', prompts.STALE_AFTER
        )

    def test_repeat_after_the_model_is_disabled(self) -> None:
        response = self._repeat(status='succeeded', model_enabled=False)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['text'], 'Stored')

    def test_repeat_while_running_is_409(self) -> None:
        response = self._repeat(status='running')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['detail'],
            {'error': 'call_in_progress', 'retry': True},
        )
        self.generate.assert_not_awaited()

    def test_repeat_of_unknown_outcome_is_409(self) -> None:
        response = self._repeat(status='outcome_unknown')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['error'], 'outcome_unknown')

    def test_repeat_of_a_failure_is_the_same_error(self) -> None:
        response = self._repeat(status='failed', error='provider_refused')
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()['detail'],
            {'error': 'provider_refused', 'retry': False},
        )

    def test_provider_error_is_recorded(self) -> None:
        self.generate.side_effect = generate.GenerateError(
            'rate_limited', retry=True, status=429
        )
        self.route_run()
        response = self.run_ref()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()['detail'],
            {'error': 'rate_limited', 'retry': True},
        )
        self.calls.finish.assert_awaited_once_with(
            CALL_ID, 'failed', error='rate_limited'
        )

    def test_call_past_the_deadline_is_recorded(self) -> None:
        self.assertLess(prompts.CALL_DEADLINE, prompts.STALE_AFTER)

        async def slow(*_: object) -> None:
            await asyncio.sleep(1)

        self.generate.side_effect = slow
        self.route_run()
        with mock.patch.object(prompts, 'CALL_DEADLINE', 0.01):
            response = self.run_ref()
        self.assertEqual(response.status_code, 503)
        self.calls.finish.assert_awaited_once_with(
            CALL_ID, 'failed', error='provider_unreachable'
        )

    def test_vertex_needs_a_key(self) -> None:
        self.decrypt.return_value = None
        self.route_run()
        self.mock_db.execute.side_effect.rules.insert(
            0, (ai_providers._GET_QUERY, provider_row(driver='vertex'))
        )
        response = self.run_ref()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()['detail']['error'], 'provider_misconfigured'
        )
        self.generate.assert_not_awaited()

    def test_bedrock_without_a_key_signs_with_sigv4(self) -> None:
        self.decrypt.return_value = None
        signer = mock.Mock(spec=httpx.Auth)
        self._patch(
            model_generate, '_sigv4', mock.AsyncMock(return_value=signer)
        )
        self.route_run()
        self.mock_db.execute.side_effect.rules.insert(
            0,
            (
                ai_providers._GET_QUERY,
                provider_row(driver='bedrock', region='us-east-1'),
            ),
        )
        self.assertEqual(self.run_ref().status_code, 200)
        sent: generate.Request = self.generate.await_args.args[0]
        self.assertIs(sent.auth, signer)
        self.assertIsNone(sent.credential)


class SigV4TestCase(base.PromptTestBase):
    def test_signs_for_bedrock(self) -> None:
        from botocore import credentials

        auth = model_generate.SigV4(
            credentials.ReadOnlyCredentials('AKID', 'secret', None),
            'us-east-1',
        )
        request = httpx.Request(
            'POST',
            'https://bedrock-runtime.us-east-1.amazonaws.com/model/m/converse',
            json={'messages': []},
        )
        signed = next(auth.auth_flow(request))
        self.assertRegex(
            signed.headers['Authorization'],
            r'^AWS4-HMAC-SHA256 Credential=AKID/\d{8}/us-east-1/bedrock/',
        )
        self.assertIn('X-Amz-Date', signed.headers)
