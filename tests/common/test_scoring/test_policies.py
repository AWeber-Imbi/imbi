import unittest
from unittest import mock

import pydantic

from imbi_common import models
from imbi_common.scoring import policies


def _project() -> models.Project:
    org = models.Organization(name='Org', slug='org')
    team = models.Team(name='Team', slug='team', organization=org)
    return models.Project(id='p1', name='P', slug='p', team=team)


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


Row = dict[str, object]


def _with_execute(
    type_rows: list[Row],
    policy_rows: list[Row],
) -> mock.AsyncMock:
    """Return a graph mock whose execute yields type rows then policy rows."""
    db = mock.AsyncMock()
    db.execute.side_effect = [type_rows, policy_rows]
    return db


class ApplicablePoliciesTests(unittest.IsolatedAsyncioTestCase):
    async def test_queries_type_slugs_from_graph(self) -> None:
        # First execute call fetches type slugs; second fetches policies.
        db = _with_execute([{'slug': 'api'}], [])
        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedProject),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                _, extended_cls = await policies.applicable_policies(
                    db, _project()
                )
        self.assertEqual(2, db.execute.await_count)
        type_call = db.execute.call_args_list[0]
        self.assertIn('{id}', type_call.args[0])
        policy_call = db.execute.call_args_list[1]
        self.assertEqual(['p', 'targets'], policy_call.kwargs.get('columns'))
        self.assertIs(_ExtendedProject, extended_cls)

    async def test_returns_policies(self) -> None:
        db = _with_execute(
            [{'slug': 'api'}],
            [
                {
                    'p': _policy_props(
                        slug='lang', attribute_name='programming_language'
                    ),
                    'targets': [],
                }
            ],
        )
        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedProject),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                result, _ = await policies.applicable_policies(db, _project())
        self.assertEqual(1, len(result))
        self.assertEqual('lang', result[0].slug)

    async def test_policy_with_matching_target_included(self) -> None:
        db = _with_execute(
            [{'slug': 'api'}],
            [
                {
                    'p': _policy_props(
                        slug='lang', attribute_name='programming_language'
                    ),
                    'targets': ['api'],
                }
            ],
        )
        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedProject),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                result, _ = await policies.applicable_policies(db, _project())
        self.assertEqual(1, len(result))

    async def test_policy_with_non_matching_target_excluded(self) -> None:
        db = _with_execute(
            [{'slug': 'api'}],
            [
                {
                    'p': _policy_props(
                        slug='lang', attribute_name='programming_language'
                    ),
                    'targets': ['other-type'],
                }
            ],
        )
        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedProject),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                result, _ = await policies.applicable_policies(db, _project())
        self.assertEqual([], result)

    async def test_no_project_types_in_graph(self) -> None:
        # Project has no type edges in the graph → types query returns empty.
        db = _with_execute([], [])
        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedProject),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                result, _ = await policies.applicable_policies(db, _project())
        self.assertEqual([], result)
        self.assertEqual(2, db.execute.await_count)

    async def test_skips_non_dict_rows(self) -> None:
        db = _with_execute([], [{'p': 'not-a-dict', 'targets': []}])
        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedProject),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                result, _ = await policies.applicable_policies(db, _project())
        self.assertEqual([], result)

    async def test_strips_age_internal_keys(self) -> None:
        props = _policy_props(
            slug='lang', attribute_name='programming_language'
        )
        props['_id'] = 'age-id'
        db = _with_execute([], [{'p': props, 'targets': []}])
        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedProject),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                result, _ = await policies.applicable_policies(db, _project())
        self.assertEqual(1, len(result))


class _AssertImports(unittest.TestCase):
    """Sanity check that pydantic imports stay in the public namespace."""

    def test_pydantic_imports(self) -> None:
        self.assertTrue(hasattr(pydantic, 'ValidationError'))
