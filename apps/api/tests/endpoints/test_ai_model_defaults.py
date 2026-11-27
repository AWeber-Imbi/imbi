"""Tests for the default model of an organization and a team."""

import typing

from apps.api.tests.endpoints import test_ai_models as model_tests
from imbi.api.endpoints import ai_model_defaults

ORG_DEFAULT = ai_model_defaults._ORG_DEFAULT_QUERY
TEAM_DEFAULT = ai_model_defaults._TEAM_DEFAULT_QUERY

ORG_DEFAULT_URL = '/organizations/acme/default-ai-model'
TEAM_DEFAULT_URL = '/organizations/acme/teams/platform/default-ai-model'
CLEAR_ORG = ai_model_defaults._CLEAR_DEFAULT_QUERIES['Organization']
LINK_ORG = ai_model_defaults._LINK_DEFAULT_QUERIES['Organization']
LINK_TEAM = ai_model_defaults._LINK_DEFAULT_QUERIES['Team']


def candidate(**overrides: typing.Any) -> list[dict[str, typing.Any]]:
    return [
        {
            'id': 'mdl-1',
            'model_type': 'generative',
            'access_scope': 'organization',
            'team': None,
            **overrides,
        }
    ]


class DefaultModelTestCase(model_tests.AIModelTestBase):
    """``GET``/``PUT`` of the organization and team default model."""

    def setUp(self) -> None:
        super().setUp()

        async def locked(_key: str, work: typing.Any) -> typing.Any:
            return await work(self.mock_db.execute)

        self.mock_db.locked.side_effect = locked

    def test_get_organization_default(self) -> None:
        self.route(
            (
                ORG_DEFAULT,
                [{'id': 'org-1', 'slug': 'default-chat'}],
            )
        )
        response = self.client.get(ORG_DEFAULT_URL)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'slug': 'default-chat'})

    def test_missing_organization_or_team_is_404(self) -> None:
        self.route()
        for url in (ORG_DEFAULT_URL, TEAM_DEFAULT_URL):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
                response = self.client.put(url, json={'slug': None})
                self.assertEqual(response.status_code, 404)

    def test_set_organization_default(self) -> None:
        router = self.route(
            (
                ORG_DEFAULT,
                [{'id': 'org-1', 'slug': None}],
            ),
            (ai_model_defaults._DEFAULT_CANDIDATE_QUERY, candidate()),
        )
        response = self.client.put(
            ORG_DEFAULT_URL, json={'slug': 'default-chat'}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'slug': 'default-chat'})
        self.assertEqual(router.params_for(CLEAR_ORG), {'id': 'org-1'})
        self.assertEqual(
            router.params_for(LINK_ORG), {'id': 'org-1', 'model': 'mdl-1'}
        )
        self.mock_db.locked.assert_awaited_once()

    def test_clear_organization_default(self) -> None:
        router = self.route(
            (
                ORG_DEFAULT,
                [{'id': 'org-1', 'slug': 'default-chat'}],
            ),
        )
        response = self.client.put(ORG_DEFAULT_URL, json={'slug': None})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'slug': None})
        self.assertEqual(router.params_for(CLEAR_ORG), {'id': 'org-1'})
        self.assertFalse(any(LINK_ORG in q for q, _ in router.calls))

    def test_default_must_be_a_generative_catalog_model(self) -> None:
        for rows in ([], candidate(model_type='decision')):
            with self.subTest(rows=rows):
                router = self.route(
                    (
                        ORG_DEFAULT,
                        [{'id': 'org-1', 'slug': None}],
                    ),
                    (ai_model_defaults._DEFAULT_CANDIDATE_QUERY, rows),
                )
                response = self.client.put(
                    ORG_DEFAULT_URL, json={'slug': 'jev'}
                )
                self.assertEqual(response.status_code, 422, response.text)
                self.assertFalse(any(CLEAR_ORG in q for q, _ in router.calls))

    def test_team_default_must_allow_the_team(self) -> None:
        team = (
            ai_model_defaults._TEAM_DEFAULT_QUERY,
            [{'id': 'tm-1', 'slug': None}],
        )
        router = self.route(
            team,
            (
                ai_model_defaults._DEFAULT_CANDIDATE_QUERY,
                candidate(access_scope='restricted'),
            ),
        )
        response = self.client.put(TEAM_DEFAULT_URL, json={'slug': 'opus'})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            router.params_for(ai_model_defaults._DEFAULT_CANDIDATE_QUERY),
            {'slug': 'opus', 'team_id': 'tm-1'},
        )
        router = self.route(
            team,
            (
                ai_model_defaults._DEFAULT_CANDIDATE_QUERY,
                candidate(access_scope='restricted', team='tm-1'),
            ),
        )
        response = self.client.put(TEAM_DEFAULT_URL, json={'slug': 'opus'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            router.params_for(LINK_TEAM), {'id': 'tm-1', 'model': 'mdl-1'}
        )
        self.route(
            (
                ai_model_defaults._TEAM_DEFAULT_QUERY,
                [{'id': 'tm-1', 'slug': 'opus'}],
            )
        )
        response = self.client.get(TEAM_DEFAULT_URL)
        self.assertEqual(response.json(), {'slug': 'opus'})


class DefaultModelPermissionTestCase(model_tests.AIModelTestBase):
    """Permission enforcement for a non-admin principal."""

    is_admin = False

    def test_set_defaults_denied(self) -> None:
        """The org default needs ai_model:update; a team default needs
        team:update."""
        self.route()
        for url in (ORG_DEFAULT_URL, TEAM_DEFAULT_URL):
            with self.subTest(url=url):
                response = self.client.put(url, json={'slug': None})
                self.assertEqual(response.status_code, 403)
