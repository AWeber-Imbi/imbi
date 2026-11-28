"""Tests for generative prompt runs and their call record."""

import asyncio
import decimal
import json
import typing
import unittest
import uuid
from unittest import mock

import httpx

from apps.api.tests.endpoints import test_ai_models as model_tests
from apps.api.tests.endpoints import test_ai_providers as provider_tests
from apps.api.tests.endpoints import test_prompts as base
from imbi.api.endpoints import prompts
from imbi.api.llm import generate as model_generate
from imbi.common import models
from imbi.common.auth import permissions as common_permissions
from imbi.common.llm import generate
from imbi.common.llm import resolve as llm_resolve
from imbi.common.prompts import resolve as prompt_resolve

RUN_URL = f'/organizations/{base.ORG}/prompts/run'
CALL_ID = uuid.UUID('00000000-0000-0000-0000-000000000001')
MODEL_ROW = model_tests.model_props(
    model_type='generative', supports_structured_output=True
)
FIELDS = [{'name': 'severity', 'type': 'string', 'required': True}]
WF_PROMPT = f'{base.ORG}.deploy.summary'


def provider_row(**overrides: typing.Any) -> dict[str, typing.Any]:
    return provider_tests.provider_props(
        credentials_encrypted='ciphertext', **overrides
    )


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

    def route_run(
        self,
        version: dict[str, typing.Any] | None = None,
        provider: dict[str, typing.Any] | None = None,
        **model: typing.Any,
    ) -> base.Router:
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
                    ),
                    **(version or {}),
                ),
            ),
            (
                llm_resolve.EXPLICIT_QUERY,
                [
                    {
                        'm': {**MODEL_ROW, **model},
                        'p': provider_row(**(provider or {})),
                    }
                ],
            ),
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
        self.route_run(supports_structured_output=False)
        response = self.run_ref(output_fields=FIELDS)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()['detail'],
            {'error': 'model_no_structured_output', 'retry': False},
        )
        self.calls.start.assert_not_awaited()

    def test_completion_model_is_refused(self) -> None:
        self.route_run(kind='completion')
        response = self.run_ref()
        self.assertEqual(response.status_code, 422)
        self.assertIn('completion model', response.json()['detail'])
        self.calls.start.assert_not_awaited()
        self.generate.assert_not_awaited()
        self.generate.assert_not_awaited()

    def test_model_at_its_spend_cap_is_refused(self) -> None:
        self.route_run(monthly_spend_cap='5')
        self.mock_db.pool = mock.MagicMock()
        for spend, status in (('4.99', 200), ('5', 422)):
            with (
                self.subTest(spend=spend),
                mock.patch.object(
                    llm_resolve,
                    'month_spend',
                    mock.AsyncMock(
                        return_value={MODEL_ROW['id']: decimal.Decimal(spend)}
                    ),
                ),
            ):
                response = self.run_ref()
            self.assertEqual(response.status_code, status, response.text)
        self.assertIn('monthly spend cap', response.json()['detail'])
        self.assertEqual(self.calls.start.await_count, 1)
        call = self.calls.start.await_args.args[0]
        self.assertEqual(call['ai_model_id'], MODEL_ROW['id'])

    def test_cached_tokens_use_the_cache_read_price(self) -> None:
        self.generate.return_value = generate.Result(
            'All good',
            None,
            {
                'input_tokens': 1024,
                'output_tokens': 0,
                'cache_read_tokens': 1024,
            },
            None,
        )
        self.route_run(
            input_cost_per_million='2', cache_read_cost_per_million='1'
        )
        response = self.run_ref()
        self.assertEqual(response.status_code, 200, response.text)
        # 1024 at $2/M plus 1024 at $1/M, not 2048 at $2/M.
        self.assertAlmostEqual(response.json()['cost_usd'], 0.003072)
        usage = self.calls.finish.await_args.kwargs['usage']
        self.assertEqual(usage['cache_read_tokens'], 1024)

    def test_restricted_model_needs_an_allowed_team(self) -> None:
        self.as_principal('prompt:run')
        router = self.route_run(access_scope='restricted')
        response = self.run_ref()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()['detail'],
            {
                'error': 'model_not_allowed',
                'retry': False,
                'message': "The model 'default-chat' is restricted to teams "
                'that do not include the caller',
            },
        )
        self.generate.assert_not_awaited()
        self.calls.start.assert_not_awaited()
        self.assertEqual(
            router.params_for(prompt_resolve.ALLOWED_MEMBER_QUERY)['email'],
            self.user.email,
        )
        router.rules.insert(
            0, (prompt_resolve.ALLOWED_MEMBER_QUERY, [{'id': 'team-1'}])
        )
        self.assertEqual(self.run_ref().status_code, 200)

    def run_workflow_prompt_as(self, account: str) -> base.Router:
        """Act as the service account ``account``, without a user, on
        a restricted model of a workflow step prompt."""
        self.as_principal('prompt:run')
        self.auth_context.user = None
        self.auth_context.service_account = models.ServiceAccount(
            slug=account, display_name=account
        )
        router = self.route_run(access_scope='restricted')
        router.rules[0] = (
            base.GET_PROMPT,
            base.prompt_row(namespace='workflows', slug=WF_PROMPT),
        )
        self.workflow_store.get.return_value = {'owner_team_id': 'team-1'}
        return router

    def test_restricted_model_refuses_another_service_account(
        self,
    ) -> None:
        router = self.run_workflow_prompt_as('imbi-scheduler')
        router.rules.insert(
            0, (prompt_resolve.ALLOWED_TEAM_QUERY, [{'id': 'team-1'}])
        )
        with mock.patch.object(
            prompts,
            'caller_org_slugs',
            mock.AsyncMock(return_value={base.ORG}),
        ):
            response = self.run_ref(ref=f'workflows/{WF_PROMPT}@1')
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()['detail'],
            {
                'error': 'model_not_allowed',
                'retry': False,
                'message': "The model 'default-chat' is restricted to teams "
                'that do not include the caller',
            },
        )
        self.generate.assert_not_awaited()

    def test_restricted_model_in_a_workflow_needs_the_owner_team(
        self,
    ) -> None:
        slug = WF_PROMPT
        router = self.run_workflow_prompt_as(
            common_permissions.WORKFLOWS_ACCOUNT
        )
        with mock.patch.object(
            prompts,
            'caller_org_slugs',
            mock.AsyncMock(return_value={base.ORG}),
        ):
            response = self.run_ref(ref=f'workflows/{slug}@1')
            self.assertEqual(response.status_code, 403, response.text)
            self.workflow_store.get.assert_awaited_with('org-1', 'deploy')
            self.assertEqual(
                router.params_for(prompt_resolve.ALLOWED_TEAM_QUERY)['team'],
                'team-1',
            )
            router.rules.insert(
                0, (prompt_resolve.ALLOWED_TEAM_QUERY, [{'id': 'team-1'}])
            )
            response = self.run_ref(ref=f'workflows/{slug}@1')
            self.assertEqual(response.status_code, 200, response.text)

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
        # An unknown count makes the cost unknown, not a subtotal.
        self.assertIsNone(response.json()['cost_usd'])
        self.assertIsNone(self.calls.finish.await_args.kwargs['cost_usd'])
        sent: generate.Request = self.generate.await_args.args[0]
        self.assertEqual(sent.output_fields[0].name, 'severity')
        # A model without the flag predates it: a forced tool choice.
        self.assertTrue(sent.forced_tool_choice)

    def test_forced_tool_choice_flag_reaches_the_adapter(self) -> None:
        self.route_run(supports_forced_tool_choice=False)
        response = self.run_ref(output_fields=FIELDS)
        self.assertEqual(response.status_code, 200, response.text)
        sent: generate.Request = self.generate.await_args.args[0]
        self.assertFalse(sent.forced_tool_choice)

    def test_grant_in_another_org_does_not_run(self) -> None:
        # prompt:update in another org only: check_member keeps the
        # permissions of this org, which has none.
        self.as_principal('prompt:update')

        async def narrow(_slug: str, _db: object, auth: typing.Any) -> str:
            auth.permissions = set()
            return 'org-1'

        self._patch(
            prompts.organizations,
            'check_member',
            mock.AsyncMock(side_effect=narrow),
        )
        self.route_run()
        response = self.run_ref()
        self.assertEqual(response.status_code, 403, response.text)
        self.generate.assert_not_awaited()
        self.calls.start.assert_not_awaited()

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

    def test_attempt_out_of_the_integer_range_is_422(self) -> None:
        self.route_run()
        key = f'run-1:node-a:{prompts.MAX_ATTEMPT + 1}'
        response = self.run_ref(headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, 422, response.text)
        self.calls.start.assert_not_awaited()
        self.generate.assert_not_awaited()

    def test_attempt_that_is_not_a_number_is_none(self) -> None:
        # str.isdigit accepts '²', but int() does not parse it.
        for attempt in ('-1', '\u00b2', 'x'):
            context = prompts._key_context(f'run-1:node-a:{attempt}')
            self.assertIsNone(context['attempt'])

    def test_version_with_tools_is_refused(self) -> None:
        self.route_run(version={'tools': json.dumps([{'name': 'lookup'}])})
        response = self.run_ref()
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn('no tools', response.json()['detail'])
        self.calls.start.assert_not_awaited()
        self.generate.assert_not_awaited()

    def test_blank_temperature_uses_the_catalog_default(self) -> None:
        for temperature, expected in ((None, 0.3), (0, 0)):
            self.route_run(
                version={'params': json.dumps({'temperature': temperature})},
                default_temperature=0.3,
            )
            response = self.run_ref()
            self.assertEqual(response.status_code, 200, response.text)
            sent: generate.Request = self.generate.await_args.args[0]
            self.assertEqual(sent.params.temperature, expected)

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

    def test_repeat_after_the_prompt_is_deleted(self) -> None:
        self.calls.repeat.return_value = {
            'id': CALL_ID,
            'status': 'succeeded',
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
        }
        self.route_run()
        self.mock_db.execute.side_effect.rules[0] = (base.GET_PROMPT, [])
        response = self.run_ref(
            ref='mender/core@1',
            headers={'Idempotency-Key': 'run-1:node-a:1'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['text'], 'Stored')
        self.generate.assert_not_awaited()

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
        # The call may have reached the provider: no retry.
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()['detail'],
            {'error': 'provider_outcome_unknown', 'retry': False},
        )
        self.calls.finish.assert_awaited_once_with(
            CALL_ID, 'failed', error='provider_outcome_unknown'
        )

    def test_deadline_before_dispatch_is_retried(self) -> None:
        async def slow(*_: object) -> None:
            await asyncio.sleep(1)

        self.decrypt.return_value = None
        self._patch(model_generate, 'sigv4', slow)
        self.route_run(provider={'driver': 'bedrock', 'region': 'us-east-1'})
        with mock.patch.object(prompts, 'CALL_DEADLINE', 0.01):
            response = self.run_ref()
        # No request was sent: the retry is safe.
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()['detail'],
            {'error': 'credentials_unavailable', 'retry': True},
        )
        self.calls.finish.assert_awaited_once_with(
            CALL_ID, 'failed', error='credentials_unavailable'
        )
        self.generate.assert_not_awaited()

    def test_provider_outcome_unknown_is_not_retried(self) -> None:
        self.generate.side_effect = generate.GenerateError(
            'provider_outcome_unknown'
        )
        self.route_run()
        response = self.run_ref()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()['detail'],
            {'error': 'provider_outcome_unknown', 'retry': False},
        )
        self.calls.finish.assert_awaited_once_with(
            CALL_ID, 'failed', error='provider_outcome_unknown'
        )

    def test_repeat_of_an_unknown_provider_outcome_makes_no_call(
        self,
    ) -> None:
        response = self._repeat(
            status='failed', error='provider_outcome_unknown'
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()['detail'],
            {'error': 'provider_outcome_unknown', 'retry': False},
        )
        self.generate.assert_not_awaited()

    def test_vertex_needs_a_key(self) -> None:
        self.decrypt.return_value = None
        self.route_run(provider={'driver': 'vertex'})
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
            model_generate, 'sigv4', mock.AsyncMock(return_value=signer)
        )
        self.route_run(provider={'driver': 'bedrock', 'region': 'us-east-1'})
        self.assertEqual(self.run_ref().status_code, 200)
        sent: generate.Request = self.generate.await_args.args[0]
        self.assertIs(sent.auth, signer)
        self.assertIsNone(sent.credential)


class SigV4TestCase(base.PromptTestBase):
    def test_credential_failure_is_retryable(self) -> None:
        from botocore import exceptions

        aws = mock.Mock()
        aws.get_credentials.side_effect = exceptions.CredentialRetrievalError(
            provider='container-role', error_msg='down'
        )
        with (
            mock.patch.object(
                model_generate, '_aws_session', return_value=aws
            ),
            self.assertRaises(generate.GenerateError) as ctx,
        ):
            asyncio.run(model_generate.sigv4('us-east-1'))
        self.assertEqual(ctx.exception.code, 'credentials_unavailable')
        self.assertTrue(ctx.exception.retry)

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

    def test_signs_a_get_without_content_type(self) -> None:
        from botocore import credentials

        auth = model_generate.SigV4(
            credentials.ReadOnlyCredentials('AKID', 'secret', None),
            'us-east-1',
        )
        request = httpx.Request(
            'GET', 'https://bedrock.us-east-1.amazonaws.com/foundation-models'
        )
        signed = next(auth.auth_flow(request))
        self.assertIn('Credential=AKID/', signed.headers['Authorization'])


class DispatchTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_token_clears_dispatch(self) -> None:
        # A 401 is a known rejection: while Imbi waits for a new token,
        # no request is in flight, so a deadline then is safe to retry.
        dispatched = asyncio.Event()
        seen: list[bool] = []

        async def get(*_: object) -> mock.Mock:
            seen.append(dispatched.is_set())
            return mock.Mock(token=f'token-{len(seen)}')

        result = generate.Result('ok', None, {}, None)
        call = mock.AsyncMock(
            side_effect=[
                generate.GenerateError('provider_refused', status=401),
                result,
            ]
        )
        provider = mock.Mock(workload_identity=object())
        request = generate.Request(
            driver='anthropic', model_id='claude-opus-5', messages=[]
        )
        with (
            mock.patch.object(
                model_generate, 'decrypt_config_value', return_value=None
            ),
            mock.patch.object(model_generate.tokens, 'get', get),
            mock.patch.object(model_generate.tokens, 'CACHE'),
            mock.patch.object(generate, 'generate', call),
        ):
            answer = await model_generate.call(
                mock.Mock(), provider, request, dispatched
            )
        self.assertIs(answer, result)
        self.assertEqual(seen, [False, False])
        self.assertTrue(dispatched.is_set())

    async def test_request_bearer_and_auth_stay_without_a_credential(
        self,
    ) -> None:
        auth = mock.Mock()
        call = mock.AsyncMock(
            return_value=generate.Result('ok', None, {}, None)
        )
        provider = mock.Mock(workload_identity=None, driver='anthropic')
        request = generate.Request(
            driver='anthropic',
            model_id='claude-opus-5',
            messages=[],
            credential='token',
            bearer=True,
            auth=auth,
        )
        with (
            mock.patch.object(
                model_generate, 'decrypt_config_value', return_value=None
            ),
            mock.patch.object(generate, 'generate', call),
        ):
            await model_generate.call(mock.Mock(), provider, request)
        sent = call.await_args.args[0]
        self.assertTrue(sent.bearer)
        self.assertIs(sent.auth, auth)
