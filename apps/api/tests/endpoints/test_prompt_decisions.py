"""Tests for decision prompts: kind rules, render, and run."""

import hashlib
import json
import typing
from unittest import mock

from apps.api.tests.endpoints import test_ai_providers as provider_tests
from apps.api.tests.endpoints import test_prompts as base
from imbi.api.endpoints import ai_providers, prompts
from imbi.common.llm import typesafe

ORG = base.ORG
RENDER_URL = base.RENDER_URL
RUN_URL = f'/organizations/{ORG}/prompts/run'
GET_PROVIDER = ai_providers._GET_QUERY
RUN_MODEL = prompts._RUN_MODEL_QUERY

QUESTIONS: dict[str, typing.Any] = {
    'urgent': {
        'type': 'noul',
        'instructions': 'Is {{ service }} down?',
        'criteria': {'true': 'Down', 'false': 'Up'},
    },
    'team': {
        'type': 'choice',
        'instructions': 'Which team?',
        'criteria': {'payments': 'Billing', 'other': None},
    },
}
SCHEMA = {'service': {'type': 'str', 'required': True}}

DECISION_MODEL_ROW = [
    {'model_id': 'jev-latest', 'enabled': True, 'model_type': 'decision'}
]
RUN_MODEL_ROW = [
    {
        'model_id': 'jev-latest',
        'enabled': True,
        'model_type': 'decision',
        'provider_id': 'prv-ts',
    }
]
TYPESAFE_PROVIDER = [
    {
        'p': provider_tests.provider_props(
            id='prv-ts',
            slug='typesafe',
            name='TypeSafe',
            driver='typesafe',
            credentials_encrypted='ciphertext',
        )
    }
]
ANSWERS = {
    'model': 'jev-latest',
    'answers': {
        'urgent': {'type': 'noul', 'noul': 0.9},
        'team': {
            'type': 'choice',
            'choice': 'payments',
            'probabilities': {'payments': 0.8, 'other': 0.2},
            'confidence': 0.7,
        },
    },
    'usage': {'input_tokens': 20, 'output_tokens': 2},
}


def decision_prompt_row(latest: int = 1) -> list[dict]:
    return base.prompt_row(latest, kind='decision', slug='triage')


def decision_version_row(n: int = 1, **overrides: typing.Any) -> list[dict]:
    return base.version_row(
        n,
        system='',
        model='jev',
        model_id='jev-latest',
        params=json.dumps({}),
        variable_schema=json.dumps(SCHEMA),
        state='{"service": {{ service | tojson }}}',
        questions=json.dumps(QUESTIONS),
        **overrides,
    )


def decision_content(**overrides: typing.Any) -> dict[str, typing.Any]:
    body: dict[str, typing.Any] = {
        'state': '{"service": {{ service | tojson }}}',
        'questions': QUESTIONS,
        'variable_schema': SCHEMA,
        'model': 'jev',
    }
    body.update(overrides)
    return body


class DecisionKindTestCase(base.PromptTestBase):
    def test_create_decision_prompt(self) -> None:
        router = self.route(
            (base.MODEL, DECISION_MODEL_ROW),
            (base.CREATE_PROMPT, [{'p': base.prompt_props()}]),
        )
        response = self.client.post(
            '/prompts/',
            json={
                'namespace': 'mender',
                'name': 'Triage',
                'kind': 'decision',
                'version': decision_content(),
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['kind'], 'decision')
        params = router.params_for(base.CREATE_PROMPT)
        self.assertEqual(params['kind'], 'decision')
        self.assertEqual(
            json.loads(params['v_questions'])['team']['criteria'],
            {'payments': 'Billing', 'other': None},
        )

    def test_kind_and_content_must_match(self) -> None:
        self.route((base.MODEL, DECISION_MODEL_ROW))
        cases = [
            ('generative', decision_content(model=None)),
            ('decision', {**decision_content(), 'system': 'Hello'}),
            ('decision', decision_content(params={'temperature': 0.5})),
        ]
        for kind, version in cases:
            with self.subTest(kind=kind, keys=sorted(version)):
                response = self.client.post(
                    '/prompts/',
                    json={
                        'namespace': 'mender',
                        'name': 'Triage',
                        'kind': kind,
                        'version': version,
                    },
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_model_type_must_match_kind(self) -> None:
        self.route((base.MODEL, base.MODEL_ROW))  # generative model
        response = self.client.post(
            '/prompts/',
            json={
                'namespace': 'mender',
                'name': 'Triage',
                'kind': 'decision',
                'version': decision_content(model='default-chat'),
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn('needs a decision model', response.json()['detail'])

    def test_template_errors_name_the_field(self) -> None:
        questions = {
            'q': {'type': 'noul', 'instructions': 'Is {{ broken'},
        }
        response = self.client.post(
            '/prompts/',
            json={
                'namespace': 'mender',
                'name': 'Triage',
                'kind': 'decision',
                'version': decision_content(questions=questions, model=None),
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn('questions.q.instructions', response.json()['detail'])

    def test_kind_is_read_only(self) -> None:
        self.route((base.GET_PROMPT, decision_prompt_row()))
        response = self.client.patch(
            '/prompts/mender/triage',
            json=[{'op': 'replace', 'path': '/kind', 'value': 'generative'}],
        )
        self.assertEqual(response.status_code, 400)

    def test_new_version_checks_kind(self) -> None:
        self.route(
            (base.GET_PROMPT, decision_prompt_row()),
            (base.GET_VERSION, decision_version_row()),
        )
        response = self.client.post(
            '/prompts/mender/triage/versions',
            json={'system': 'Hello', 'model': None},
        )
        self.assertEqual(response.status_code, 422)

    def test_unchanged_generative_hash_is_stable(self) -> None:
        # Empty decision fields are not hashed, so versions saved before
        # decision prompts keep their hash.
        content = prompts.PromptVersionContent(system='Hi')
        legacy = json.dumps(
            {
                'system': 'Hi',
                'messages': [],
                'tools': [],
                'model': None,
                'params': {
                    'max_tokens': None,
                    'temperature': None,
                    'top_p': None,
                    'stop_sequences': [],
                },
                'variable_schema': {},
            },
            sort_keys=True,
            separators=(',', ':'),
        )
        self.assertEqual(
            prompts.content_sha256(content),
            hashlib.sha256(legacy.encode()).hexdigest(),
        )
        changed = prompts.PromptVersionContent(state='x', questions=QUESTIONS)
        self.assertNotEqual(
            prompts.content_sha256(content), prompts.content_sha256(changed)
        )


class DecisionRenderTestCase(base.PromptTestBase):
    def test_render_returns_state_and_questions(self) -> None:
        self.route(
            (base.GET_PROMPT, decision_prompt_row()),
            (base.GET_VERSION, decision_version_row()),
        )
        response = self.client.post(
            RENDER_URL,
            json={
                'ref': 'mender/triage@stable',
                'variables': {'service': 'b'},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['kind'], 'decision')
        self.assertEqual(data['state'], {'service': 'b'})
        self.assertEqual(
            data['questions']['urgent']['instructions'], 'Is b down?'
        )
        self.assertEqual(data['system'], '')


class DecisionRunTestCase(base.PromptTestBase):
    def setUp(self) -> None:
        super().setUp()
        decrypt = mock.patch.object(
            prompts, 'decrypt_config_value', return_value='ts-key'
        )
        self.decrypt = decrypt.start()
        self.addCleanup(decrypt.stop)
        decide = mock.patch.object(
            prompts.typesafe,
            'decide',
            mock.AsyncMock(return_value=ANSWERS),
        )
        self.decide = decide.start()
        self.addCleanup(decide.stop)

    def route_run(self, *extra: tuple[str, typing.Any]) -> base.Router:
        return self.route(
            *extra,
            (base.GET_PROMPT, decision_prompt_row()),
            (base.GET_VERSION, decision_version_row()),
            (RUN_MODEL, RUN_MODEL_ROW),
            (GET_PROVIDER, TYPESAFE_PROVIDER),
        )

    def run_ref(self, **body: typing.Any) -> typing.Any:
        return self.client.post(
            RUN_URL,
            json={
                'ref': 'mender/triage@stable',
                'variables': {'service': 'billing'},
                **body,
            },
        )

    def test_runs_a_saved_version(self) -> None:
        self.route_run()
        response = self.run_ref()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['ref'], 'mender/triage@1')
        self.assertEqual(data['answers']['urgent']['noul'], 0.9)
        self.assertEqual(data['request']['state'], {'service': 'billing'})
        args = self.decide.await_args.args
        self.assertEqual(args[0], 'ts-key')
        self.assertEqual(args[1], 'https://api.typesafe.ai/v1')
        self.assertEqual(args[2], 'jev-latest')
        self.assertEqual(
            args[4]['urgent'],
            {
                'type': 'noul',
                'instructions': 'Is billing down?',
                'criteria': {'true': 'Down', 'false': 'Up'},
            },
        )
        self.assertNotIn('ts-key', response.text)

    def test_runs_an_unsaved_draft(self) -> None:
        self.route_run()
        draft = decision_content(state='plain {{ service }}')
        response = self.client.post(
            RUN_URL,
            json={
                'draft': {
                    'namespace': 'mender',
                    'slug': 'triage',
                    'version': draft,
                },
                'variables': {'service': 'billing'},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()['n'])
        self.assertEqual(self.decide.await_args.args[3], 'plain billing')

    def test_draft_is_validated(self) -> None:
        self.route_run()
        response = self.client.post(
            RUN_URL,
            json={
                'draft': {
                    'namespace': 'mender',
                    'slug': 'triage',
                    'version': decision_content(state='{{ broken'),
                },
                'variables': {'service': 'billing'},
            },
        )
        self.assertEqual(response.status_code, 422)
        self.decide.assert_not_awaited()

    def test_needs_exactly_one_source(self) -> None:
        response = self.client.post(RUN_URL, json={'variables': {}})
        self.assertEqual(response.status_code, 422)

    def test_generative_prompt_is_422(self) -> None:
        self.route(
            (base.GET_PROMPT, base.prompt_row()),
            (base.GET_VERSION, base.version_row()),
        )
        response = self.run_ref(variables={'project_slug': 'x'})
        self.assertEqual(response.status_code, 422)
        self.decide.assert_not_awaited()

    def test_no_credentials_is_409(self) -> None:
        self.decrypt.return_value = None
        self.route_run()
        self.assertEqual(self.run_ref().status_code, 409)

    def test_non_typesafe_driver_is_422(self) -> None:
        self.route_run(
            (
                GET_PROVIDER,
                [{'p': provider_tests.provider_props(id='prv-ts')}],
            )
        )
        self.assertEqual(self.run_ref().status_code, 422)

    def test_disabled_provider_is_422(self) -> None:
        self.route_run(
            (
                GET_PROVIDER,
                [
                    {
                        'p': provider_tests.provider_props(
                            id='prv-ts',
                            slug='typesafe',
                            driver='typesafe',
                            enabled=False,
                            credentials_encrypted='ciphertext',
                        )
                    }
                ],
            )
        )
        response = self.run_ref()
        self.assertEqual(response.status_code, 422)
        self.assertIn('is disabled', response.json()['detail'])
        self.decide.assert_not_awaited()

    def test_upstream_error_is_502(self) -> None:
        self.decide.side_effect = typesafe.DecisionError(
            'TypeSafe returned HTTP 429'
        )
        self.route_run()
        response = self.run_ref()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()['detail'], 'TypeSafe returned HTTP 429'
        )

    def test_needs_update_permission(self) -> None:
        self.as_principal('prompt:read')
        self.route_run()
        self.assertEqual(self.run_ref().status_code, 403)
        self.decide.assert_not_awaited()
