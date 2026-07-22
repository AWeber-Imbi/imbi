import unittest
from unittest import mock

import pydantic

from imbi_common import models
from imbi_common.scoring import models as models_module
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

    async def test_link_presence_policy_loaded(self) -> None:
        db = _with_execute(
            [],
            [
                {
                    'p': {
                        'name': 'Has source',
                        'slug': 'has-source',
                        'category': 'link_presence',
                        'link_slug': 'source-code',
                        'weight': 10,
                        'enabled': True,
                    },
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
        policy = result[0]
        self.assertIsInstance(policy, models_module.LinkPresencePolicy)
        assert isinstance(policy, models_module.LinkPresencePolicy)
        self.assertEqual('has-source', policy.slug)
        self.assertEqual('link_presence', policy.category)
        self.assertEqual('source-code', policy.link_slug)

    async def test_age_policy_loaded(self) -> None:
        db = _with_execute(
            [],
            [
                {
                    'p': {
                        'name': 'Last commit age',
                        'slug': 'last-commit-age',
                        'category': 'age',
                        'attribute_name': 'last_commit_at',
                        'weight': 10,
                        'enabled': True,
                        'age_score_map': {'>30d': 0, '<=30d': 100},
                    },
                    'targets': [],
                }
            ],
        )

        class _ExtendedWithDate(models.Project):
            last_commit_at: str | None = None

        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedWithDate),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                result, _ = await policies.applicable_policies(db, _project())
        self.assertEqual(1, len(result))
        policy = result[0]
        self.assertIsInstance(policy, models_module.AgePolicy)
        assert isinstance(policy, models_module.AgePolicy)
        self.assertEqual('age', policy.category)
        self.assertEqual('last_commit_at', policy.attribute_name)
        self.assertEqual({'>30d': 0, '<=30d': 100}, policy.age_score_map)

    async def test_invalid_policy_rows_log_warning(self) -> None:
        # weight is required by _PolicyBase; omit it to trigger ValidationError
        invalid_props = {
            'name': 'Broken',
            'slug': 'broken',
            'category': 'attribute',
            'attribute_name': 'programming_language',
            'enabled': True,
        }
        db = _with_execute([], [{'p': invalid_props, 'targets': []}])
        with mock.patch(
            'imbi_common.scoring.policies.blueprints.get_model',
            new=mock.AsyncMock(return_value=_ExtendedProject),
        ):
            with mock.patch(
                'imbi_common.scoring.policies.graph.parse_agtype',
                side_effect=lambda v: v,
            ):
                with self.assertLogs(
                    'imbi_common.scoring.policies', level='WARNING'
                ) as captured:
                    result, _ = await policies.applicable_policies(
                        db, _project()
                    )
        self.assertEqual([], result)
        self.assertTrue(
            any('broken' in line for line in captured.output),
            captured.output,
        )


class _AssertImports(unittest.TestCase):
    """Sanity check that pydantic imports stay in the public namespace."""

    def test_pydantic_imports(self) -> None:
        self.assertTrue(hasattr(pydantic, 'ValidationError'))
