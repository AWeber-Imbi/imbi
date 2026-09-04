"""Tests for the org-scoped AI model catalog endpoints."""

import typing

from apps.api.tests.endpoints import test_ai_providers as provider_tests
from imbi.api.endpoints import ai_models, ai_providers

ORG = provider_tests.ORG
BASE = f'/organizations/{ORG}/ai-models'
IMPORT_BASE = f'/organizations/{ORG}/ai-providers'

# Matched by exact template where a substring rule would be shadowed by
# the write queries that embed the same ``MATCH``.
GET_MODEL = ai_models._GET_QUERY
LIST_MODELS = ai_models._LIST_QUERY
SLUG_TAKEN = ai_models._SLUG_TAKEN_QUERY
MODEL_ID_TAKEN = ai_models._MODEL_ID_TAKEN_QUERY
TEAM = ai_models._TEAM_QUERY
EXISTING_IDS = ai_models._EXISTING_IDS_QUERY
TAKEN_SLUGS = ai_models._TAKEN_SLUGS_QUERY
GET_PROVIDER = ai_providers._GET_QUERY
CREATE = 'CREATE (m:AIModel'
UPDATE = 'SET m.'
DELETE = 'DETACH DELETE m'
CLEAR_TEAMS = ai_models._CLEAR_TEAMS_QUERY
ADD_TEAM = ai_models._ADD_TEAM_QUERY


def model_props(**overrides: typing.Any) -> dict[str, typing.Any]:
    """Return a default AIModel vertex property dict."""
    data: dict[str, typing.Any] = {
        'id': 'mdl-1',
        'name': 'Default Chat',
        'slug': 'default-chat',
        'description': None,
        'icon': None,
        'model_id': 'claude-opus-5',
        'kind': 'chat',
        'enabled': True,
        'access_scope': 'organization',
        'context_window': 200000,
        'max_output_tokens': 64000,
        'input_cost_per_million': '3',
        'output_cost_per_million': '15',
        'default_temperature': None,
        'default_top_p': None,
        'monthly_spend_cap': None,
        'created_at': '2026-09-01T12:00:00Z',
        'updated_at': '2026-09-01T12:00:00Z',
    }
    data.update(overrides)
    return data


def team_props(
    id: str = 'tm-1', name: str = 'Platform', slug: str = 'platform'
) -> dict[str, typing.Any]:
    """Return a Team vertex property dict."""
    return {'id': id, 'name': name, 'slug': slug}


class AIModelTestBase(provider_tests.AIProviderTestBase):
    """Reuses the provider fixture: same app, principal, and mocks."""


class ReadModelTestCase(AIModelTestBase):
    """``GET`` list and detail."""

    def test_list_folds_team_rows_into_one_model(self) -> None:
        """Three ALLOWED_FOR rows collapse into one model."""
        self.route(
            (
                LIST_MODELS,
                [
                    {
                        'm': model_props(access_scope='restricted'),
                        'p': provider_tests.provider_props(),
                        't': team_props(),
                    },
                    {
                        'm': model_props(access_scope='restricted'),
                        'p': provider_tests.provider_props(),
                        't': team_props('tm-2', 'Apps', 'apps'),
                    },
                ],
            )
        )
        response = self.client.get(BASE + '/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(
            [team['slug'] for team in data[0]['allowed_teams']],
            ['apps', 'platform'],
        )
        self.assertEqual(data[0]['provider_id'], 'prv-1')
        self.assertEqual(data[0]['provider_name'], 'Anthropic')

    def test_list_handles_a_model_with_no_teams(self) -> None:
        """A null ``t`` from the OPTIONAL MATCH yields an empty list."""
        self.route(
            (
                LIST_MODELS,
                [
                    {
                        'm': model_props(),
                        'p': provider_tests.provider_props(),
                        't': None,
                    }
                ],
            )
        )
        response = self.client.get(BASE + '/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['allowed_teams'], [])

    def test_get_returns_model(self) -> None:
        """A model in this organization is returned with its costs."""
        self.route(
            (
                GET_MODEL,
                [
                    {
                        'm': model_props(),
                        'p': provider_tests.provider_props(),
                        't': None,
                    }
                ],
            )
        )
        response = self.client.get(f'{BASE}/mdl-1')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['id'], 'mdl-1')
        self.assertEqual(data['model_id'], 'claude-opus-5')
        self.assertEqual(data['input_cost_per_million'], '3')

    def test_get_cross_org_is_404(self) -> None:
        """A valid id under the wrong organization is not found."""
        router = self.route()
        response = self.client.get('/organizations/other/ai-models/mdl-1')
        self.assertEqual(response.status_code, 404)
        self.assert_scoped(router, GET_MODEL, 'other')


class CreateModelTestCase(AIModelTestBase):
    """``POST /organizations/{org}/ai-models``."""

    def _body(self, **overrides: typing.Any) -> dict[str, typing.Any]:
        body: dict[str, typing.Any] = {
            'provider_id': 'prv-1',
            'name': 'Default Chat',
            'model_id': 'claude-opus-5',
        }
        body.update(overrides)
        return body

    def test_create_derives_slug_from_name(self) -> None:
        """An omitted slug is slugified from the name."""
        router = self.route(
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
            (CREATE, [{'m': model_props()}]),
        )
        response = self.client.post(BASE + '/', json=self._body())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['slug'], 'default-chat')
        self.assertEqual(router.params_for(CREATE)['slug'], 'default-chat')

    def test_create_attaches_allowed_teams(self) -> None:
        """Restricted access writes one ALLOWED_FOR edge per team."""
        router = self.route(
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
            (TEAM, [{'t': team_props()}]),
            (
                CREATE,
                [{'m': model_props(access_scope='restricted')}],
            ),
        )
        response = self.client.post(
            BASE + '/',
            json=self._body(
                access_scope='restricted', allowed_team_ids=['tm-1']
            ),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            [team['slug'] for team in response.json()['allowed_teams']],
            ['platform'],
        )
        self.assertEqual(router.params_for(ADD_TEAM)['team_id'], 'tm-1')

    def test_create_under_an_openai_compatible_provider(self) -> None:
        """A provider whose validator needs base_url still round-trips.

        The response is rebuilt by re-validating the provider, and
        ``AIProvider`` rejects ``openai_compatible`` without a
        ``base_url`` -- so a partial provider dict 500s the create.
        """
        provider = provider_tests.provider_props(
            driver='openai_compatible',
            name='vLLM',
            slug='vllm',
            base_url='https://vllm.example.com/v1',
        )
        self.route(
            (GET_PROVIDER, [{'p': provider}]),
            (CREATE, [{'m': model_props()}]),
        )
        response = self.client.post(BASE + '/', json=self._body())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['provider_name'], 'vLLM')

    def test_organization_scope_writes_no_team_edges(self) -> None:
        """Team ids sent with org-wide access are validated, then dropped."""
        router = self.route(
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
            (TEAM, [{'t': team_props()}]),
            (CREATE, [{'m': model_props()}]),
        )
        response = self.client.post(
            BASE + '/',
            json=self._body(
                access_scope='organization', allowed_team_ids=['tm-1']
            ),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['allowed_teams'], [])
        self.assertNotIn(ADD_TEAM, [query for query, _ in router.calls])

    def test_create_skips_the_clear_teams_round_trip(self) -> None:
        """A node created moments ago has no edges to clear."""
        router = self.route(
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
            (CREATE, [{'m': model_props()}]),
        )
        self.client.post(BASE + '/', json=self._body())
        self.assertNotIn(CLEAR_TEAMS, [query for query, _ in router.calls])

    def test_team_edges_are_scoped_to_the_org(self) -> None:
        """The ALLOWED_FOR write carries the BELONGS_TO hop."""
        router = self.route(
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
            (TEAM, [{'t': team_props()}]),
            (CREATE, [{'m': model_props(access_scope='restricted')}]),
        )
        response = self.client.post(
            BASE + '/',
            json=self._body(
                access_scope='restricted', allowed_team_ids=['tm-1']
            ),
        )
        self.assertEqual(response.status_code, 201)
        self.assert_scoped(router, ADD_TEAM, ORG)

    def test_restricted_without_teams_is_422(self) -> None:
        """Restricted access with nobody allowed is rejected."""
        self.route((GET_PROVIDER, [{'p': provider_tests.provider_props()}]))
        response = self.client.post(
            BASE + '/', json=self._body(access_scope='restricted')
        )
        self.assertEqual(response.status_code, 422)

    def test_team_outside_org_is_422(self) -> None:
        """A team from another organization cannot be granted access."""
        self.route((GET_PROVIDER, [{'p': provider_tests.provider_props()}]))
        response = self.client.post(
            BASE + '/',
            json=self._body(
                access_scope='restricted', allowed_team_ids=['tm-other']
            ),
        )
        self.assertEqual(response.status_code, 422)

    def test_unknown_provider_is_404(self) -> None:
        """The provider must exist in this organization."""
        self.route()
        response = self.client.post(BASE + '/', json=self._body())
        self.assertEqual(response.status_code, 404)

    def test_provider_in_another_org_is_404(self) -> None:
        """A provider id valid elsewhere is not found here."""
        router = self.route()
        response = self.client.post(BASE + '/', json=self._body())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(router.params_for(GET_PROVIDER)['org_slug'], ORG)

    def test_duplicate_slug_in_org_conflicts(self) -> None:
        """Model slugs are unique per organization."""
        self.route(
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
            (SLUG_TAKEN, [{'id': 'mdl-other'}]),
        )
        response = self.client.post(BASE + '/', json=self._body())
        self.assertEqual(response.status_code, 409)

    def test_duplicate_model_id_on_provider_conflicts(self) -> None:
        """A provider cannot serve the same vendor model twice."""
        self.route(
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
            (MODEL_ID_TAKEN, [{'id': 'mdl-other'}]),
        )
        response = self.client.post(BASE + '/', json=self._body())
        self.assertEqual(response.status_code, 409)

    def test_rejects_out_of_range_temperature(self) -> None:
        """Sampling parameters are bounded."""
        self.route((GET_PROVIDER, [{'p': provider_tests.provider_props()}]))
        response = self.client.post(
            BASE + '/', json=self._body(default_temperature=9)
        )
        self.assertEqual(response.status_code, 422)

    def test_rejects_negative_cost(self) -> None:
        """Costs cannot be negative; zero means self-hosted."""
        self.route((GET_PROVIDER, [{'p': provider_tests.provider_props()}]))
        response = self.client.post(
            BASE + '/', json=self._body(input_cost_per_million='-1')
        )
        self.assertEqual(response.status_code, 422)

    def test_create_cross_org_is_404(self) -> None:
        """Creating under an organization without the provider is 404."""
        router = self.route()
        response = self.client.post(
            '/organizations/other/ai-models/', json=self._body()
        )
        self.assertEqual(response.status_code, 404)
        self.assert_scoped(router, GET_PROVIDER, 'other')


class PatchModelTestCase(AIModelTestBase):
    """``PATCH`` with RFC 6902 operations."""

    def _installed(self, **overrides: typing.Any) -> None:
        self.route(
            (
                GET_MODEL,
                [
                    {
                        'm': model_props(**overrides),
                        'p': provider_tests.provider_props(),
                        't': None,
                    }
                ],
            ),
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
            (UPDATE, [{'m': model_props(**overrides)}]),
        )

    def test_toggle_enabled(self) -> None:
        """A replace on /enabled is persisted."""
        self._installed()
        router = typing.cast('typing.Any', self.mock_db.execute.side_effect)
        response = self.client.patch(
            f'{BASE}/mdl-1',
            json=[{'op': 'replace', 'path': '/enabled', 'value': False}],
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['enabled'])
        self.assertFalse(router.params_for(UPDATE)['enabled'])

    def test_teams_are_replaced_as_a_set(self) -> None:
        """Patching the team list clears the old edges first."""
        self.route(
            (
                GET_MODEL,
                [
                    {
                        'm': model_props(access_scope='restricted'),
                        'p': provider_tests.provider_props(),
                        't': team_props(),
                    }
                ],
            ),
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
            (TEAM, [{'t': team_props('tm-2', 'Apps', 'apps')}]),
            (UPDATE, [{'m': model_props(access_scope='restricted')}]),
        )
        router = typing.cast('typing.Any', self.mock_db.execute.side_effect)
        response = self.client.patch(
            f'{BASE}/mdl-1',
            json=[
                {
                    'op': 'replace',
                    'path': '/allowed_team_ids',
                    'value': ['tm-2'],
                }
            ],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [team['id'] for team in response.json()['allowed_teams']],
            ['tm-2'],
        )
        self.assertEqual(router.params_for(CLEAR_TEAMS)['id'], 'mdl-1')
        self.assertEqual(router.params_for(ADD_TEAM)['team_id'], 'tm-2')

    def test_patch_to_organization_clears_the_teams(self) -> None:
        """Widening access drops every ALLOWED_FOR edge."""
        self.route(
            (
                GET_MODEL,
                [
                    {
                        'm': model_props(access_scope='restricted'),
                        'p': provider_tests.provider_props(),
                        't': team_props(),
                    }
                ],
            ),
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
            (TEAM, [{'t': team_props()}]),
            (UPDATE, [{'m': model_props()}]),
        )
        router = typing.cast('typing.Any', self.mock_db.execute.side_effect)
        response = self.client.patch(
            f'{BASE}/mdl-1',
            json=[
                {
                    'op': 'replace',
                    'path': '/access_scope',
                    'value': 'organization',
                }
            ],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['allowed_teams'], [])
        self.assertEqual(router.params_for(CLEAR_TEAMS)['org_slug'], ORG)
        self.assertNotIn(ADD_TEAM, [query for query, _ in router.calls])

    def test_patch_rejects_a_derived_path(self) -> None:
        """Edge-derived response fields are refused, not ignored."""
        for path in ('/allowed_teams', '/provider_name', '/provider'):
            with self.subTest(path=path):
                self._installed()
                response = self.client.patch(
                    f'{BASE}/mdl-1',
                    json=[{'op': 'add', 'path': path, 'value': 'x'}],
                )
                self.assertEqual(response.status_code, 400)

    def test_patch_to_restricted_without_teams_is_422(self) -> None:
        """Narrowing access with nobody allowed is rejected."""
        self._installed()
        response = self.client.patch(
            f'{BASE}/mdl-1',
            json=[
                {
                    'op': 'replace',
                    'path': '/access_scope',
                    'value': 'restricted',
                }
            ],
        )
        self.assertEqual(response.status_code, 422)

    def test_patch_team_outside_org_is_422(self) -> None:
        """A team from another organization cannot be granted access."""
        self.route(
            (
                GET_MODEL,
                [
                    {
                        'm': model_props(),
                        'p': provider_tests.provider_props(),
                        't': None,
                    }
                ],
            ),
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
        )
        response = self.client.patch(
            f'{BASE}/mdl-1',
            json=[
                {
                    'op': 'replace',
                    'path': '/allowed_team_ids',
                    'value': ['tm-other'],
                }
            ],
        )
        self.assertEqual(response.status_code, 422)

    def test_patch_slug_collision_conflicts(self) -> None:
        """Renaming onto another model's slug is a conflict."""
        self.route(
            (
                GET_MODEL,
                [
                    {
                        'm': model_props(),
                        'p': provider_tests.provider_props(),
                        't': None,
                    }
                ],
            ),
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
            (SLUG_TAKEN, [{'id': 'mdl-2'}]),
        )
        response = self.client.patch(
            f'{BASE}/mdl-1',
            json=[{'op': 'replace', 'path': '/slug', 'value': 'taken'}],
        )
        self.assertEqual(response.status_code, 409)

    def test_patch_cross_org_is_404(self) -> None:
        """A valid id under the wrong organization is not found."""
        router = self.route()
        response = self.client.patch(
            '/organizations/other/ai-models/mdl-1',
            json=[{'op': 'replace', 'path': '/enabled', 'value': False}],
        )
        self.assertEqual(response.status_code, 404)
        self.assert_scoped(router, GET_MODEL, 'other')


class DeleteModelTestCase(AIModelTestBase):
    """``DELETE``."""

    def test_delete(self) -> None:
        """A model is removed with its edges."""
        self.route((DELETE, [{'m': model_props()}]))
        response = self.client.delete(f'{BASE}/mdl-1')
        self.assertEqual(response.status_code, 204)

    def test_delete_cross_org_is_404(self) -> None:
        """A valid id under the wrong organization is not found."""
        router = self.route()
        response = self.client.delete('/organizations/other/ai-models/mdl-1')
        self.assertEqual(response.status_code, 404)
        self.assert_scoped(router, DELETE, 'other')


class ImportModelsTestCase(AIModelTestBase):
    """``POST /ai-providers/{id}/import-models``."""

    def test_creates_new_and_skips_existing(self) -> None:
        """A model id the provider already serves is skipped, not an error."""
        self.route(
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
            (EXISTING_IDS, [{'model_id': 'claude-opus-5'}]),
            (TAKEN_SLUGS, [{'slug': 'claude-haiku-4-5'}]),
            (
                CREATE,
                [
                    {
                        'm': model_props(
                            id='mdl-2',
                            name='Claude Haiku 4.5',
                            slug='claude-haiku-4-5-2',
                            model_id='claude-haiku-4-5',
                        )
                    }
                ],
            ),
        )
        response = self.client.post(
            f'{IMPORT_BASE}/prv-1/import-models',
            json={
                'models': [
                    {
                        'model_id': 'claude-opus-5',
                        'display_name': 'Claude Opus 5',
                    },
                    {
                        'model_id': 'claude-haiku-4-5',
                        'display_name': 'Claude Haiku 4.5',
                    },
                ]
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['skipped'], ['claude-opus-5'])
        self.assertEqual(len(data['created']), 1)
        self.assertEqual(data['created'][0]['slug'], 'claude-haiku-4-5-2')

    def test_all_skipped_is_200_not_201(self) -> None:
        """Nothing was created, so nothing was created."""
        self.route(
            (GET_PROVIDER, [{'p': provider_tests.provider_props()}]),
            (EXISTING_IDS, [{'model_id': 'claude-opus-5'}]),
        )
        response = self.client.post(
            f'{IMPORT_BASE}/prv-1/import-models',
            json={'models': [{'model_id': 'claude-opus-5'}]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['created'], [])
        self.assertEqual(response.json()['skipped'], ['claude-opus-5'])

    def test_import_cross_org_is_404(self) -> None:
        """A valid provider id under the wrong organization is not found."""
        router = self.route()
        response = self.client.post(
            '/organizations/other/ai-providers/prv-1/import-models',
            json={'models': [{'model_id': 'claude-opus-5'}]},
        )
        self.assertEqual(response.status_code, 404)
        self.assert_scoped(router, GET_PROVIDER, 'other')


class ModelPermissionTestCase(AIModelTestBase):
    """Permission enforcement for a non-admin principal."""

    is_admin = False

    def test_list_denied(self) -> None:
        """Listing needs ai_model:read."""
        self.route()
        self.assertEqual(self.client.get(BASE + '/').status_code, 403)

    def test_create_denied(self) -> None:
        """Creating needs ai_model:create."""
        self.route()
        response = self.client.post(
            BASE + '/',
            json={
                'provider_id': 'prv-1',
                'name': 'Default Chat',
                'model_id': 'claude-opus-5',
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_patch_denied(self) -> None:
        """Updating needs ai_model:update."""
        self.route()
        response = self.client.patch(
            f'{BASE}/mdl-1',
            json=[{'op': 'replace', 'path': '/enabled', 'value': False}],
        )
        self.assertEqual(response.status_code, 403)

    def test_delete_denied(self) -> None:
        """Deleting needs ai_model:delete."""
        self.route()
        self.assertEqual(self.client.delete(f'{BASE}/mdl-1').status_code, 403)

    def test_import_denied(self) -> None:
        """Importing needs ai_model:create."""
        self.route()
        response = self.client.post(
            f'{IMPORT_BASE}/prv-1/import-models',
            json={'models': [{'model_id': 'claude-opus-5'}]},
        )
        self.assertEqual(response.status_code, 403)

    def test_read_permission_allows_listing(self) -> None:
        """``ai_model:read`` is enough to list."""
        self.auth_context.permissions = {'ai_model:read'}
        self.route()
        self.assertEqual(self.client.get(BASE + '/').status_code, 200)
