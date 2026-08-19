"""Tests for the SBoM component backfill and reconciliation."""

import typing
import unittest
from unittest import mock

from imbi.api import sbom_backfill
from imbi.common import graph


def _row(**overrides: typing.Any) -> dict[str, typing.Any]:
    row: dict[str, typing.Any] = {
        'release_id': 'r-1',
        'component_id': 'c-1',
        'purl_name': 'pkg:pypi/requests',
        'ecosystem': 'pypi',
        'component_release_id': 'cr-1',
        'version': '2.32.0',
        'scope': 'required',
        'groups': ['runtime'],
    }
    row.update(overrides)
    return row


class BackfillProjectTests(unittest.IsolatedAsyncioTestCase):
    """`backfill_project` publishes one batch per unbatched release."""

    def setUp(self) -> None:
        self.db = mock.AsyncMock(spec=graph.Graph)
        self.db.execute.return_value = [_row()]
        self.query = mock.AsyncMock(return_value=[])
        self.publish = mock.AsyncMock()
        for target, replacement in (
            ('imbi.common.clickhouse.query', self.query),
            ('imbi.api.sbom.publish_batch', self.publish),
        ):
            patcher = mock.patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_publishes_a_backfill_batch(self) -> None:
        summary = await sbom_backfill.backfill_project(self.db, 'p-1')
        self.assertEqual(summary.releases_published, 1)
        self.assertEqual(summary.components_written, 1)
        kwargs = self.publish.await_args.kwargs
        self.assertEqual(kwargs['source'], 'backfill')

    async def test_records_carry_the_batch_id_of_their_batch(self) -> None:
        self.db.execute.return_value = [
            _row(component_id='c-1', component_release_id='cr-1'),
            _row(component_id='c-2', component_release_id='cr-2'),
        ]
        await sbom_backfill.backfill_project(self.db, 'p-1')
        args = self.publish.await_args.args
        batch_id, records = args[2], args[4]
        self.assertEqual(len(records), 2)
        self.assertEqual({r.batch_id for r in records}, {batch_id})

    async def test_each_release_gets_its_own_batch(self) -> None:
        self.db.execute.return_value = [
            _row(release_id='r-1'),
            _row(release_id='r-2'),
        ]
        await sbom_backfill.backfill_project(self.db, 'p-1')
        self.assertEqual(self.publish.await_count, 2)
        ids = {call.args[2] for call in self.publish.await_args_list}
        self.assertEqual(len(ids), 2)

    async def test_release_with_an_existing_batch_is_skipped(self) -> None:
        """Re-running writes nothing; the skip keeps that cheap."""
        self.query.return_value = [{'release_id': 'r-1'}]
        summary = await sbom_backfill.backfill_project(self.db, 'p-1')
        self.assertEqual(summary.releases_published, 0)
        self.assertEqual(summary.releases_skipped, 1)
        self.publish.assert_not_awaited()

    async def test_project_with_no_component_edges_publishes_nothing(
        self,
    ) -> None:
        """Absent edges are not evidence of an empty dependency set."""
        self.db.execute.return_value = []
        summary = await sbom_backfill.backfill_project(self.db, 'p-1')
        self.assertEqual(summary.releases_published, 0)
        self.publish.assert_not_awaited()
        self.query.assert_not_awaited()

    async def test_counts_agree_so_the_batch_is_not_flagged_partial(
        self,
    ) -> None:
        await sbom_backfill.backfill_project(self.db, 'p-1')
        args = self.publish.await_args.args
        self.assertEqual(len(args[4]), args[5])


class ReconcileProjectTests(unittest.IsolatedAsyncioTestCase):
    """`reconcile_project` compares content, not counts."""

    def setUp(self) -> None:
        self.db = mock.AsyncMock(spec=graph.Graph)
        self.db.execute.return_value = [_row()]
        self.query = mock.AsyncMock(return_value=[])
        patcher = mock.patch('imbi.common.clickhouse.query', self.query)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _published(self, *rows: tuple[str, str, str]) -> None:
        self.query.return_value = [
            {
                'release_id': 'r-1',
                'component_id': component_id,
                'component_release_id': component_release_id,
                'version': version,
            }
            for component_id, component_release_id, version in rows
        ]

    async def test_identical_sets_match(self) -> None:
        self._published(('c-1', 'cr-1', '2.32.0'))
        summary = await sbom_backfill.reconcile_project(self.db, 'p-1')
        self.assertTrue(summary.ok)
        self.assertEqual(summary.matched, 1)

    async def test_ordering_does_not_affect_the_comparison(self) -> None:
        self.db.execute.return_value = [
            _row(component_id='c-1', component_release_id='cr-1'),
            _row(component_id='c-2', component_release_id='cr-2'),
        ]
        self._published(('c-2', 'cr-2', '2.32.0'), ('c-1', 'cr-1', '2.32.0'))
        summary = await sbom_backfill.reconcile_project(self.db, 'p-1')
        self.assertTrue(summary.ok)

    async def test_equal_counts_with_different_members_is_a_mismatch(
        self,
    ) -> None:
        """The failure a row count cannot see."""
        self._published(('c-9', 'cr-9', '2.32.0'))
        summary = await sbom_backfill.reconcile_project(self.db, 'p-1')
        self.assertFalse(summary.ok)
        self.assertIn('r-1', summary.mismatched)

    async def test_mismatch_names_the_differing_members(self) -> None:
        """Counts alone leave an operator nothing to go look at."""
        self._published(('c-9', 'cr-9', '2.32.0'))
        summary = await sbom_backfill.reconcile_project(self.db, 'p-1')
        reason = summary.mismatched['r-1']
        self.assertIn('c-1/cr-1@2.32.0', reason)
        self.assertIn('c-9/cr-9@2.32.0', reason)

    async def test_differing_version_is_a_mismatch(self) -> None:
        self._published(('c-1', 'cr-1', '2.31.0'))
        summary = await sbom_backfill.reconcile_project(self.db, 'p-1')
        self.assertFalse(summary.ok)

    async def test_release_with_no_published_batch_is_a_mismatch(
        self,
    ) -> None:
        """That is exactly what the backfill was meant to fix."""
        summary = await sbom_backfill.reconcile_project(self.db, 'p-1')
        self.assertFalse(summary.ok)
        self.assertIn('no published batch', summary.mismatched['r-1'])

    async def test_matched_count_distinguishes_agreement_from_no_work(
        self,
    ) -> None:
        self.db.execute.return_value = []
        summary = await sbom_backfill.reconcile_project(self.db, 'p-1')
        self.assertTrue(summary.ok)
        self.assertEqual(summary.matched, 0)


class FingerprintTests(unittest.TestCase):
    """The digest depends on content alone."""

    def test_order_independent(self) -> None:
        a = sbom_backfill._fingerprint(
            [('c-1', 'cr-1', '1'), ('c-2', 'cr-2', '2')]
        )
        b = sbom_backfill._fingerprint(
            [('c-2', 'cr-2', '2'), ('c-1', 'cr-1', '1')]
        )
        self.assertEqual(a, b)

    def test_distinguishes_members(self) -> None:
        a = sbom_backfill._fingerprint([('c-1', 'cr-1', '1')])
        b = sbom_backfill._fingerprint([('c-2', 'cr-1', '1')])
        self.assertNotEqual(a, b)

    def test_repeated_members_do_not_change_the_digest(self) -> None:
        """A repeated tuple carries no fact the first one did not."""
        a = sbom_backfill._fingerprint([('c-1', 'cr-1', '1')])
        b = sbom_backfill._fingerprint(
            [('c-1', 'cr-1', '1'), ('c-1', 'cr-1', '1')]
        )
        self.assertEqual(a, b)

    def test_field_boundaries_are_not_ambiguous(self) -> None:
        """Concatenation without a separator would collide these."""
        a = sbom_backfill._fingerprint([('ab', 'c', 'd')])
        b = sbom_backfill._fingerprint([('a', 'bc', 'd')])
        self.assertNotEqual(a, b)


class GraphComponentsTests(unittest.TestCase):
    """Grouping the graph rows by release."""

    def test_row_without_a_release_id_is_dropped(self) -> None:
        """A row that cannot be attributed cannot be compared."""
        grouped = sbom_backfill._graph_components(
            [_row(), _row(release_id=None)]
        )
        self.assertEqual(list(grouped), ['r-1'])
        self.assertEqual(len(grouped['r-1']), 1)


class SampleTests(unittest.TestCase):
    """A reason names a few members, never a whole component set."""

    def test_empty_side_renders_as_an_empty_list(self) -> None:
        self.assertEqual(sbom_backfill._sample(set()), '[]')

    def test_members_are_sorted_so_two_runs_read_the_same(self) -> None:
        rows = {('c-2', 'cr-2', '2'), ('c-1', 'cr-1', '1')}
        self.assertEqual(
            sbom_backfill._sample(rows), '[c-1/cr-1@1, c-2/cr-2@2]'
        )

    def test_long_lists_are_truncated_with_a_remainder(self) -> None:
        rows = {
            (f'c-{index}', f'cr-{index}', '1')
            for index in range(sbom_backfill._SAMPLE_LIMIT + 3)
        }
        rendered = sbom_backfill._sample(rows)
        self.assertIn('+3 more]', rendered)
        self.assertEqual(rendered.count('@'), sbom_backfill._SAMPLE_LIMIT)


class GroupsCoercionTests(unittest.TestCase):
    """Edge properties that are not lists do not reach the model."""

    def test_list_passes_through(self) -> None:
        self.assertEqual(sbom_backfill._groups(['a', 'b']), ['a', 'b'])

    def test_none_becomes_empty(self) -> None:
        self.assertEqual(sbom_backfill._groups(None), [])

    def test_unexpected_scalar_becomes_empty(self) -> None:
        self.assertEqual(sbom_backfill._groups('runtime'), [])


class RegistrationTests(unittest.TestCase):
    """Registering an operation is what renders its button."""

    def test_both_operations_are_registered(self) -> None:
        from imbi.api.maintenance import registry

        for slug in ('sbom-backfill', 'sbom-backfill-report'):
            with self.subTest(slug=slug):
                self.assertIn(slug, registry.OPERATIONS)

    def test_registered_against_the_right_callables(self) -> None:
        from imbi.api.maintenance import operations, registry

        self.assertIs(
            registry.OPERATIONS['sbom-backfill'].execute,
            operations.execute_sbom_backfill,
        )
        self.assertIs(
            registry.OPERATIONS['sbom-backfill-report'].execute,
            operations.execute_sbom_backfill_report,
        )

    def test_the_report_operation_is_enumerated_per_project(self) -> None:
        """Chunking by project is what keeps the graph reads bounded."""
        from imbi.api.maintenance import operations, registry

        for slug in ('sbom-backfill', 'sbom-backfill-report'):
            with self.subTest(slug=slug):
                self.assertIs(
                    registry.OPERATIONS[slug].enumerate,
                    operations.enumerate_all_projects,
                )
