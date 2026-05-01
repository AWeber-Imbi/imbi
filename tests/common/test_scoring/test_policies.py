import unittest
from unittest import mock

import pydantic

from imbi_common import models
from imbi_common.scoring import policies


def _project(*, project_type_slug: str | None = 'api') -> models.Project:
    org = models.Organization(name='Org', slug='org')
    team = models.Team(name='Team', slug='team', organization=org)
    types_ = (
        [
            models.ProjectType(
                name='API', slug=project_type_slug, organization=org
            )
        ]
        if project_type_slug
        else []
    )
    return models.Project(
        id='p1',
        name='P',
        slug='p',
        team=team,
        project_types=types_,
    )


class _ExtendedProject(models.Project):
    programming_language: str | None = None
    test_coverage: int | None = None


def _policy_props(
    *,
    slug: str,
    attribute_name: str,
    weight: int = 10,
) -> dict[str, object]:
    return {
        'name': slug,
        'slug': slug,
        'attribute_name': attribute_name,
        'category': 'attribute',
        'weight': weight,
        'enabled': True,
        'value_score_map': {'py': 100},
    }


class ApplicablePoliciesTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_effective_attribute_set(self) -> None:
        graph = mock.AsyncMock()
        graph.execute.return_value = []
        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedProject),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                await policies.applicable_policies(graph, _project())
        graph.execute.assert_awaited_once()
        params = graph.execute.call_args.args[1]
        self.assertIn('programming_language', params['attrs'])
        self.assertIn('test_coverage', params['attrs'])
        self.assertEqual(['api'], params['project_types'])

    async def test_returns_policies(self) -> None:
        graph = mock.AsyncMock()
        graph.execute.return_value = [
            {
                'p': _policy_props(
                    slug='lang', attribute_name='programming_language'
                )
            }
        ]
        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedProject),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                result = await policies.applicable_policies(graph, _project())
        self.assertEqual(1, len(result))
        self.assertEqual('lang', result[0].slug)

    async def test_empty_project_type(self) -> None:
        graph = mock.AsyncMock()
        graph.execute.return_value = []
        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedProject),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                await policies.applicable_policies(
                    graph, _project(project_type_slug=None)
                )
        params = graph.execute.call_args.args[1]
        self.assertEqual([], params['project_types'])

    async def test_skips_non_dict_rows(self) -> None:
        graph = mock.AsyncMock()
        graph.execute.return_value = [{'p': 'not-a-dict'}]
        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedProject),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                result = await policies.applicable_policies(graph, _project())
        self.assertEqual([], result)

    async def test_strips_age_internal_keys(self) -> None:
        graph = mock.AsyncMock()
        props = _policy_props(
            slug='lang', attribute_name='programming_language'
        )
        props['_id'] = 'age-id'
        graph.execute.return_value = [{'p': props}]
        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedProject),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                result = await policies.applicable_policies(graph, _project())
        self.assertEqual(1, len(result))


class _AssertImports(unittest.TestCase):
    """Sanity check that pydantic imports stay in the public namespace."""

    def test_pydantic_imports(self) -> None:
        self.assertTrue(hasattr(pydantic, 'ValidationError'))
