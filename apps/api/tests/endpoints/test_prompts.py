"""Tests for the prompt CMS endpoints."""

import json
import typing
from unittest import mock

import psycopg.errors

from apps.api.tests.endpoints import test_ai_providers as provider_tests
from imbi.api.endpoints import prompts, projects

ORG = provider_tests.ORG
BASE = f'/organizations/{ORG}/prompts'

GET_PROMPT = prompts._PROMPT_QUERY
LIST_PROMPTS = prompts._LIST_QUERY
LIST_NAMESPACE = prompts._LIST_NAMESPACE_QUERY
GET_VERSION = prompts._VERSION_QUERY
LIST_VERSIONS = prompts._VERSIONS_QUERY
MODEL = prompts._MODEL_QUERY
SET_LABELS = prompts._SET_LABELS_QUERY
SET_EVAL = prompts._SET_EVAL_QUERY
CREATE_PROMPT = 'CREATE (p:Prompt'
CREATE_VERSION = 'CREATE (v:PromptVersion'
UPDATE = 'SET p.'
DELETE_VERSIONS = prompts._DELETE_VERSIONS_QUERY
DELETE_PROMPT = prompts._DELETE_PROMPT_QUERY

STAMP = '2026-10-01T12:00:00Z'


class Router(provider_tests.QueryRouter):
    """A :class:`QueryRouter` whose results may depend on the params.

    A callable result is called with the query params; it may raise,
    to stand in for a database error.
    """

    def __call__(
        self,
        query: str,
        params: dict[str, typing.Any] | None = None,
        columns: list[str] | None = None,
        raw: bool = False,
    ) -> list[dict[str, typing.Any]]:
        result = super().__call__(query, params, columns, raw)
        if callable(result):
            return typing.cast(
                'list[dict[str, typing.Any]]', result(dict(params or {}))
            )
        return result


def label(name: str = 'stable', version: int = 1) -> dict[str, typing.Any]:
    return {
        'name': name,
        'version': version,
        'updated_by': 'admin@example.com',
        'updated_at': STAMP,
    }


def prompt_props(**overrides: typing.Any) -> dict[str, typing.Any]:
    """Return a Prompt vertex property dict, as AGE stores it."""
    data: dict[str, typing.Any] = {
        'id': 'prm-1',
        'name': 'Mender core',
        'slug': 'core',
        'namespace': 'mender',
        'description': None,
        'icon': None,
        'type': 'core_system',
        'default_label': 'stable',
        'labels': json.dumps([label()]),
        'created_at': STAMP,
        'updated_at': STAMP,
    }
    data.update(overrides)
    return data


def version_props(n: int = 1, **overrides: typing.Any) -> dict[str, typing.Any]:
    """Return a PromptVersion vertex property dict, as AGE stores it."""
    data: dict[str, typing.Any] = {
        'id': f'ver-{n}',
        'prompt_id': 'prm-1',
        'n': n,
        'summary': 'First pass',
        'system': 'You triage {{ project_slug }}.',
        'messages': json.dumps([]),
        'tools': json.dumps([]),
        'model': 'default-chat',
        'model_id': 'claude-opus-5',
        'params': json.dumps({'max_tokens': 4096, 'temperature': 1.0}),
        'variable_schema': json.dumps(
            {'project_slug': {'type': 'str', 'required': True}}
        ),
        'content_sha256': 'abc',
        'eval_summary': None,
        'created_by': 'admin@example.com',
        'created_at': STAMP,
    }
    data.update(overrides)
    return data


def prompt_row(latest: int = 1, **overrides: typing.Any) -> list[dict]:
    return [{'p': prompt_props(**overrides), 'latest': latest}]


def version_row(n: int = 1, **overrides: typing.Any) -> list[dict]:
    return [{'v': version_props(n, **overrides)}]


MODEL_ROW = [{'model_id': 'claude-opus-5', 'enabled': True}]


class PromptTestBase(provider_tests.AIProviderTestBase):
    """Admin principal and a mocked graph."""

    def route(self, *rules: tuple[str, typing.Any]) -> Router:
        router = Router(*rules)
        self.mock_db.execute.side_effect = router
        return router

    def as_principal(self, *grants: str) -> None:
        """Act as a non-admin holding only ``grants``."""
        self.user.is_admin = False
        self.auth_context.permissions = set(grants)


class ReadPromptTestCase(PromptTestBase):
    def test_list_sorts_and_parses_labels(self) -> None:
        self.route(
            (
                LIST_PROMPTS,
                [
                    {'p': prompt_props(), 'latest': 14},
                    {
                        'p': prompt_props(
                            id='prm-2', namespace='imbi-assistant'
                        ),
                        'latest': None,
                    },
                ],
            )
        )
        response = self.client.get(BASE + '/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            [row['ref'] for row in data],
            ['imbi-assistant/core', 'mender/core'],
        )
        self.assertEqual(data[1]['latest_version'], 14)
        self.assertEqual(data[0]['latest_version'], 0)
        self.assertEqual(data[1]['labels'][0]['name'], 'stable')

    def test_list_filters_by_namespace(self) -> None:
        router = self.route((LIST_NAMESPACE, prompt_row()))
        response = self.client.get(BASE + '/?namespace=mender')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            router.params_for(LIST_NAMESPACE)['namespace'], 'mender'
        )

    def test_get_cross_org_is_404(self) -> None:
        router = self.route()
        response = self.client.get('/organizations/other/prompts/mender/core')
        self.assertEqual(response.status_code, 404)
        self.assert_scoped(router, GET_PROMPT, 'other')

    def test_list_versions_newest_first_with_labels(self) -> None:
        self.route(
            (GET_PROMPT, prompt_row(2)),
            (
                LIST_VERSIONS,
                [{'v': version_props(1)}, {'v': version_props(2)}],
            ),
        )
        response = self.client.get(BASE + '/mender/core/versions')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([v['n'] for v in data], [2, 1])
        self.assertEqual(data[1]['labels'], ['stable'])
        self.assertEqual(data[1]['ref'], 'mender/core@1')
        self.assertEqual(data[1]['params']['max_tokens'], 4096)

    def test_permission_required(self) -> None:
        self.as_principal()
        response = self.client.get(BASE + '/')
        self.assertEqual(response.status_code, 403)


class CreatePromptTestCase(PromptTestBase):
    def _body(self, **version: typing.Any) -> dict[str, typing.Any]:
        return {
            'namespace': 'mender',
            'name': 'Core',
            'type': 'core_system',
            'version': {
                'system': 'Hello {{ name }}',
                'model': 'default-chat',
                'params': {'max_tokens': 1024},
                'variable_schema': {'name': {'type': 'str'}},
                **version,
            },
        }

    def test_create_writes_prompt_and_first_version(self) -> None:
        router = self.route(
            (MODEL, MODEL_ROW), (CREATE_PROMPT, [{'p': prompt_props()}])
        )
        response = self.client.post(BASE + '/', json=self._body())
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertEqual(data['ref'], 'mender/core')
        self.assertEqual(data['latest_version'], 1)
        self.assertEqual(data['labels'][0]['version'], 1)
        params = router.params_for(CREATE_PROMPT)
        self.assertIn(CREATE_VERSION, router.calls[-1][0])
        self.assertEqual(params['v_n'], 1)
        self.assertEqual(params['v_model_id'], 'claude-opus-5')
        self.assertEqual(json.loads(params['labels'])[0]['name'], 'stable')
        self.assertEqual(len(params['v_content_sha256']), 64)

    def test_duplicate_is_409(self) -> None:
        self.route((MODEL, MODEL_ROW), (GET_PROMPT, prompt_row()))
        response = self.client.post(BASE + '/', json=self._body())
        self.assertEqual(response.status_code, 409)

    def test_unknown_model_is_422(self) -> None:
        self.route()
        response = self.client.post(BASE + '/', json=self._body())
        self.assertEqual(response.status_code, 422)
        self.assertIn('not in the catalog', response.json()['detail'])

    def test_disabled_model_is_422(self) -> None:
        self.route((MODEL, [{'model_id': 'x', 'enabled': False}]))
        response = self.client.post(BASE + '/', json=self._body())
        self.assertEqual(response.status_code, 422)

    def test_no_model_is_allowed(self) -> None:
        self.route((CREATE_PROMPT, [{'p': prompt_props()}]))
        response = self.client.post(BASE + '/', json=self._body(model=None))
        self.assertEqual(response.status_code, 201, response.text)

    def test_template_syntax_error_is_422(self) -> None:
        self.route((MODEL, MODEL_ROW))
        response = self.client.post(
            BASE + '/', json=self._body(system='Hello {{ name ')
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn('system: line 1', response.json()['detail'])

    def test_variable_named_like_a_provider_is_422(self) -> None:
        self.route((MODEL, MODEL_ROW))
        response = self.client.post(
            BASE + '/',
            json=self._body(variable_schema={'project': {'type': 'int'}}),
        )
        self.assertEqual(response.status_code, 422)

    def test_invalid_namespace_is_422(self) -> None:
        body = self._body()
        body['namespace'] = 'Not Valid'
        response = self.client.post(BASE + '/', json=body)
        self.assertEqual(response.status_code, 422)


class CreateVersionTestCase(PromptTestBase):
    URL = BASE + '/mender/core/versions'
    BODY: typing.ClassVar[dict[str, typing.Any]] = {
        'system': 'You triage {{ project_slug }}.',
        'model': 'default-chat',
        'params': {'max_tokens': 4096, 'temperature': 1.0},
        'variable_schema': {
            'project_slug': {'type': 'str', 'required': True}
        },
    }

    def test_cuts_next_version(self) -> None:
        router = self.route(
            (GET_PROMPT, prompt_row(3)),
            (GET_VERSION, version_row(3)),
            (MODEL, MODEL_ROW),
            (CREATE_VERSION, [{'v': version_props(4)}]),
        )
        response = self.client.post(
            self.URL, json={**self.BODY, 'summary': 'Tighten rules'}
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['n'], 4)
        self.assertEqual(response.json()['summary'], 'Tighten rules')
        params = router.params_for(CREATE_VERSION)
        self.assertEqual(params['n'], 4)
        self.assertEqual(params['org_slug'], ORG)

    def test_same_content_is_a_no_op(self) -> None:
        sha = prompts.content_sha256(
            prompts.PromptVersionContent.model_validate(self.BODY)
        )
        router = self.route(
            (GET_PROMPT, prompt_row(3)),
            (GET_VERSION, version_row(3, content_sha256=sha)),
        )
        response = self.client.post(
            self.URL, json={**self.BODY, 'summary': 'ignored'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['n'], 3)
        self.assertFalse(
            any(CREATE_VERSION in query for query, _ in router.calls)
        )

    def test_concurrent_save_is_409(self) -> None:
        def collide(_params: dict[str, typing.Any]) -> list[dict]:
            raise psycopg.errors.UniqueViolation('duplicate key')

        self.route(
            (GET_PROMPT, prompt_row(3)),
            (GET_VERSION, version_row(3)),
            (MODEL, MODEL_ROW),
            (CREATE_VERSION, collide),
        )
        response = self.client.post(self.URL, json=self.BODY)
        self.assertEqual(response.status_code, 409)

    def test_requires_update_permission(self) -> None:
        self.as_principal('prompt:read')
        response = self.client.post(self.URL, json=self.BODY)
        self.assertEqual(response.status_code, 403)

    def test_update_permission_is_enough(self) -> None:
        self.as_principal('prompt:update')
        self.route(
            (GET_PROMPT, prompt_row(0)),
            (MODEL, MODEL_ROW),
            (CREATE_VERSION, [{'v': version_props(1)}]),
        )
        response = self.client.post(self.URL, json=self.BODY)
        self.assertEqual(response.status_code, 201, response.text)


class LabelTestCase(PromptTestBase):
    def test_promote_moves_label(self) -> None:
        moved = [label('stable', 1), label('canary', 2)]
        router = self.route(
            (GET_PROMPT, prompt_row(2)),
            (GET_VERSION, version_row(2)),
            (
                SET_LABELS,
                [{'p': prompt_props(labels=json.dumps(moved))}],
            ),
        )
        response = self.client.put(
            BASE + '/mender/core/labels/canary', json={'version': 2}
        )
        self.assertEqual(response.status_code, 200, response.text)
        params = router.params_for(SET_LABELS)
        self.assertEqual(params['expected_updated_at'], STAMP)
        written = {
            item['name']: item['version']
            for item in json.loads(params['labels'])
        }
        self.assertEqual(written, {'stable': 1, 'canary': 2})
        self.assertEqual(
            {item['name'] for item in response.json()['labels']},
            {'stable', 'canary'},
        )

    def test_concurrent_label_write_is_409(self) -> None:
        self.route((GET_PROMPT, prompt_row(2)), (GET_VERSION, version_row(2)))
        response = self.client.put(
            BASE + '/mender/core/labels/canary', json={'version': 2}
        )
        self.assertEqual(response.status_code, 409)

    def test_promote_to_missing_version_is_404(self) -> None:
        self.route((GET_PROMPT, prompt_row(2)))
        response = self.client.put(
            BASE + '/mender/core/labels/canary', json={'version': 9}
        )
        self.assertEqual(response.status_code, 404)

    def test_promote_needs_promote_permission(self) -> None:
        self.as_principal('prompt:read', 'prompt:update')
        response = self.client.put(
            BASE + '/mender/core/labels/stable', json={'version': 1}
        )
        self.assertEqual(response.status_code, 403)

    def test_delete_default_label_is_409(self) -> None:
        self.route((GET_PROMPT, prompt_row()))
        response = self.client.delete(BASE + '/mender/core/labels/stable')
        self.assertEqual(response.status_code, 409)

    def test_delete_unknown_label_is_404(self) -> None:
        self.route((GET_PROMPT, prompt_row()))
        response = self.client.delete(BASE + '/mender/core/labels/nope')
        self.assertEqual(response.status_code, 404)

    def test_default_label_must_exist(self) -> None:
        self.route((GET_PROMPT, prompt_row()))
        response = self.client.put(
            BASE + '/mender/core/default-label', json={'label': 'canary'}
        )
        self.assertEqual(response.status_code, 422)

    def test_set_default_label(self) -> None:
        labels = json.dumps([label('stable', 1), label('canary', 2)])
        router = self.route(
            (GET_PROMPT, prompt_row(2, labels=labels)),
            (
                SET_LABELS,
                [
                    {
                        'p': prompt_props(
                            labels=labels, default_label='canary'
                        )
                    }
                ],
            ),
        )
        response = self.client.put(
            BASE + '/mender/core/default-label', json={'label': 'canary'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['default_label'], 'canary')
        self.assertEqual(
            router.params_for(SET_LABELS)['default_label'], 'canary'
        )


class ResolveTestCase(PromptTestBase):
    def _route(self) -> Router:
        labels = json.dumps([label('stable', 1), label('canary', 2)])
        return self.route(
            (GET_PROMPT, prompt_row(2, labels=labels)),
            (
                GET_VERSION,
                lambda params: version_row(params['n']),
            ),
        )

    def resolve(self, ref: str) -> typing.Any:
        return self.client.get(BASE + '/resolve', params={'ref': ref})

    def test_resolves_label(self) -> None:
        self._route()
        response = self.resolve('mender/core@canary')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['label'], 'canary')
        self.assertEqual(response.json()['version']['n'], 2)

    def test_resolves_version_number(self) -> None:
        self._route()
        response = self.resolve('mender/core@1')
        self.assertEqual(response.json()['label'], None)
        self.assertEqual(response.json()['version']['n'], 1)

    def test_unknown_label_falls_back_to_default(self) -> None:
        self._route()
        response = self.resolve('mender/core@testing')
        self.assertEqual(response.json()['label'], 'stable')
        self.assertEqual(response.json()['version']['n'], 1)

    def test_no_label_uses_default(self) -> None:
        self._route()
        self.assertEqual(self.resolve('mender/core').json()['label'], 'stable')

    def test_invalid_ref_is_422(self) -> None:
        self.route()
        self.assertEqual(self.resolve('no-slash').status_code, 422)


class RenderTestCase(PromptTestBase):
    def _route(self, **version: typing.Any) -> Router:
        return self.route(
            (GET_PROMPT, prompt_row()),
            (GET_VERSION, version_row(1, **version)),
        )

    def render(self, **variables: typing.Any) -> typing.Any:
        return self.client.post(
            BASE + '/render',
            json={'ref': 'mender/core@stable', 'variables': variables},
        )

    def test_renders_system_and_messages(self) -> None:
        self._route(
            messages=json.dumps(
                [{'role': 'user', 'content': 'Fix {{ project_slug }}'}]
            )
        )
        response = self.render(project_slug='billing')
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['system'], 'You triage billing.')
        self.assertEqual(data['messages'][0]['content'], 'Fix billing')
        self.assertEqual(data['ref'], 'mender/core@1')
        self.assertEqual(data['label'], 'stable')
        self.assertEqual(data['model_id'], 'claude-opus-5')

    def test_missing_variable_is_422(self) -> None:
        self._route()
        response = self.render()
        self.assertEqual(response.status_code, 422)
        self.assertIn('project_slug', response.json()['detail'])

    def test_unknown_variable_is_422(self) -> None:
        self._route()
        response = self.render(project_slug='x', other=1)
        self.assertEqual(response.status_code, 422)

    def test_project_provider(self) -> None:
        self._route(
            system='Team: {{ project(project_id).name }}',
            variable_schema=json.dumps(
                {'project_id': {'type': 'str', 'required': True}}
            ),
        )
        found = mock.Mock()
        found.model_dump.return_value = {'name': 'Billing'}
        with mock.patch.object(
            projects, 'fetch_project', mock.AsyncMock(return_value=found)
        ) as fetch:
            response = self.render(project_id='p-1')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['system'], 'Team: Billing')
        self.assertEqual(fetch.await_args.args[1:3], (ORG, 'p-1'))

    def test_project_provider_needs_project_read(self) -> None:
        self.as_principal('prompt:read')
        self._route(
            system='{{ project(project_id).name }}',
            variable_schema=json.dumps({'project_id': {'type': 'str'}}),
        )
        response = self.render(project_id='p-1')
        self.assertEqual(response.status_code, 403)


class EvaluationAndDeleteTestCase(PromptTestBase):
    def test_records_evaluation(self) -> None:
        router = self.route(
            (GET_PROMPT, prompt_row()), (GET_VERSION, version_row(1))
        )
        response = self.client.put(
            BASE + '/mender/core/versions/1/evaluation',
            json={
                'verdict': 'pass',
                'run_id': 'eval-7d4f2a',
                'metrics': [{'label': 'Accepted', 'value': '78%'}],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        stored = json.loads(router.params_for(SET_EVAL)['eval_summary'])
        self.assertEqual(stored['verdict'], 'pass')
        self.assertEqual(response.json()['eval_summary']['run_id'], 'eval-7d4f2a')

    def test_delete_removes_versions_then_prompt(self) -> None:
        router = self.route((GET_PROMPT, prompt_row()))
        response = self.client.delete(BASE + '/mender/core')
        self.assertEqual(response.status_code, 204)
        queries = [query for query, _ in router.calls]
        self.assertLess(
            queries.index(DELETE_VERSIONS), queries.index(DELETE_PROMPT)
        )
