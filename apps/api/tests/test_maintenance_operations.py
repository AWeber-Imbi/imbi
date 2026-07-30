"""Tests for the maintenance per-project execute functions."""

from __future__ import annotations

import contextlib
import datetime
import json
import time
import typing
import unittest
from unittest import mock

import fastapi

from imbi.api.commit_sync.service import CommitSyncUnavailable
from imbi.api.maintenance import operations
from imbi.api.pr_sync.service import PRSyncUnavailable
from imbi.common import graph
from imbi.common import models as common_models
from imbi.common.plugins.errors import PluginRateLimited


def _org_slug(value: str | None) -> mock.AsyncMock:
    return mock.AsyncMock(return_value=value)


class SystemAuthTests(unittest.TestCase):
    def test_principal_name_is_maintenance(self) -> None:
        auth = operations._system_auth()
        self.assertEqual('maintenance', auth.principal_name)
        self.assertFalse(auth.is_admin)


class ExecuteAnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_skipped_without_org(self) -> None:
        with mock.patch.object(operations, '_org_slug_for', _org_slug(None)):
            outcome = await operations.execute_analysis(
                mock.AsyncMock(), mock.AsyncMock(), 'p1'
            )
        self.assertEqual('skipped', outcome)

    async def test_runs_and_persists(self) -> None:
        run = mock.AsyncMock()
        with (
            mock.patch.object(operations, '_org_slug_for', _org_slug('org')),
            mock.patch(
                'imbi.api.endpoints.project_analysis.run_and_persist', run
            ),
        ):
            outcome = await operations.execute_analysis(
                mock.AsyncMock(), mock.AsyncMock(), 'p1'
            )
        self.assertEqual('succeeded', outcome)
        args = run.await_args.args
        self.assertEqual('org', args[1])
        self.assertEqual('p1', args[2])
        self.assertEqual('maintenance', args[3].principal_name)


def _remediate_response(*statuses: str) -> mock.Mock:
    """A fake RemediateAllResponse carrying outcomes of the given statuses."""
    outcomes = [
        mock.Mock(result=mock.Mock(status=status)) for status in statuses
    ]
    return mock.Mock(outcomes=outcomes)


class ExecuteRemediateTests(unittest.IsolatedAsyncioTestCase):
    def _patch(self, remediate: mock.AsyncMock) -> contextlib.ExitStack:
        stack = contextlib.ExitStack()
        stack.enter_context(
            mock.patch.object(operations, '_org_slug_for', _org_slug('org'))
        )
        stack.enter_context(
            mock.patch(
                'imbi.api.endpoints.project_analysis'
                '.remediate_all_for_project',
                remediate,
            )
        )
        return stack

    async def test_skipped_without_org(self) -> None:
        with mock.patch.object(operations, '_org_slug_for', _org_slug(None)):
            outcome = await operations.execute_remediate(
                mock.AsyncMock(), mock.AsyncMock(), 'p1'
            )
        self.assertEqual('skipped', outcome)

    async def test_skipped_without_report(self) -> None:
        remediate = mock.AsyncMock(return_value=None)
        with self._patch(remediate):
            outcome = await operations.execute_remediate(
                mock.AsyncMock(), mock.AsyncMock(), 'p1'
            )
        self.assertEqual('skipped', outcome)
        self.assertEqual(
            'maintenance', remediate.await_args.kwargs['auth'].principal_name
        )

    async def test_skipped_without_fixable_findings(self) -> None:
        remediate = mock.AsyncMock(return_value=_remediate_response())
        with self._patch(remediate):
            outcome = await operations.execute_remediate(
                mock.AsyncMock(), mock.AsyncMock(), 'p1'
            )
        self.assertEqual('skipped', outcome)

    async def test_all_fixed_is_succeeded(self) -> None:
        remediate = mock.AsyncMock(
            return_value=_remediate_response('fixed', 'noop')
        )
        with self._patch(remediate):
            outcome = await operations.execute_remediate(
                mock.AsyncMock(), mock.AsyncMock(), 'p1'
            )
        self.assertEqual('succeeded', outcome)

    async def test_any_failed_raises_item_failed(self) -> None:
        remediate = mock.AsyncMock(
            return_value=_remediate_response('fixed', 'failed')
        )
        with self._patch(remediate):
            with self.assertRaises(operations.MaintenanceItemFailed):
                await operations.execute_remediate(
                    mock.AsyncMock(), mock.AsyncMock(), 'p1'
                )


class ExecuteCommitSyncTests(unittest.IsolatedAsyncioTestCase):
    def _patches(
        self, run_sync: mock.AsyncMock
    ) -> tuple[
        mock.AsyncMock, list[contextlib.AbstractContextManager[object]]
    ]:
        set_status = mock.AsyncMock()
        return set_status, [
            mock.patch.object(operations, '_org_slug_for', _org_slug('org')),
            mock.patch('imbi.api.commit_sync.service.run_sync', run_sync),
            mock.patch('imbi.api.commit_sync.service.set_status', set_status),
        ]

    async def test_success(self) -> None:
        set_status, patches = self._patches(
            mock.AsyncMock(return_value=(3, 2))
        )
        with patches[0], patches[1], patches[2]:
            outcome = await operations.execute_commit_sync(
                mock.AsyncMock(), mock.AsyncMock(), 'p1'
            )
        self.assertEqual('succeeded', outcome)
        statuses = [c.kwargs['status'] for c in set_status.await_args_list]
        self.assertEqual(['running', 'success'], statuses)
        self.assertEqual(3, set_status.await_args_list[-1].kwargs['commits'])

    async def test_unavailable_is_skipped(self) -> None:
        set_status, patches = self._patches(
            mock.AsyncMock(side_effect=CommitSyncUnavailable('unbound'))
        )
        with patches[0], patches[1], patches[2]:
            outcome = await operations.execute_commit_sync(
                mock.AsyncMock(), mock.AsyncMock(), 'p1'
            )
        self.assertEqual('skipped', outcome)
        self.assertEqual(
            'failed', set_status.await_args_list[-1].kwargs['status']
        )

    async def test_rate_limited_propagates_with_queued_status(self) -> None:
        set_status, patches = self._patches(
            mock.AsyncMock(side_effect=PluginRateLimited(time.time() + 60))
        )
        with patches[0], patches[1], patches[2]:
            with self.assertRaises(PluginRateLimited):
                await operations.execute_commit_sync(
                    mock.AsyncMock(), mock.AsyncMock(), 'p1'
                )
        self.assertEqual(
            'queued', set_status.await_args_list[-1].kwargs['status']
        )

    async def test_other_error_raises_item_failed(self) -> None:
        set_status, patches = self._patches(
            mock.AsyncMock(side_effect=RuntimeError('boom'))
        )
        with patches[0], patches[1], patches[2]:
            with self.assertRaises(operations.MaintenanceItemFailed):
                await operations.execute_commit_sync(
                    mock.AsyncMock(), mock.AsyncMock(), 'p1'
                )
        self.assertEqual(
            'failed', set_status.await_args_list[-1].kwargs['status']
        )


class ExecutePRSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_success(self) -> None:
        set_status = mock.AsyncMock()
        with (
            mock.patch.object(operations, '_org_slug_for', _org_slug('org')),
            mock.patch(
                'imbi.api.pr_sync.service.run_sync',
                mock.AsyncMock(return_value=7),
            ),
            mock.patch('imbi.api.pr_sync.service.set_status', set_status),
        ):
            outcome = await operations.execute_pr_sync(
                mock.AsyncMock(), mock.AsyncMock(), 'p1'
            )
        self.assertEqual('succeeded', outcome)
        self.assertEqual(7, set_status.await_args_list[-1].kwargs['prs'])

    async def test_unavailable_is_skipped(self) -> None:
        with (
            mock.patch.object(operations, '_org_slug_for', _org_slug('org')),
            mock.patch(
                'imbi.api.pr_sync.service.run_sync',
                mock.AsyncMock(side_effect=PRSyncUnavailable('unbound')),
            ),
            mock.patch(
                'imbi.api.pr_sync.service.set_status', mock.AsyncMock()
            ),
        ):
            outcome = await operations.execute_pr_sync(
                mock.AsyncMock(), mock.AsyncMock(), 'p1'
            )
        self.assertEqual('skipped', outcome)


class ExecuteDeploymentResyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_success(self) -> None:
        resync = mock.AsyncMock()
        with (
            mock.patch.object(operations, '_org_slug_for', _org_slug('org')),
            mock.patch(
                'imbi.api.endpoints.project_deployments.resync_for_project',
                resync,
            ),
        ):
            outcome = await operations.execute_deployment_resync(
                mock.AsyncMock(), mock.AsyncMock(), 'p1'
            )
        self.assertEqual('succeeded', outcome)
        self.assertEqual(
            'maintenance', resync.await_args.kwargs['auth'].principal_name
        )

    async def test_no_capability_is_skipped(self) -> None:
        for status_code in (400, 404):
            with (
                mock.patch.object(
                    operations, '_org_slug_for', _org_slug('org')
                ),
                mock.patch(
                    'imbi.api.endpoints.project_deployments'
                    '.resync_for_project',
                    mock.AsyncMock(
                        side_effect=fastapi.HTTPException(
                            status_code=status_code, detail='nope'
                        )
                    ),
                ),
            ):
                outcome = await operations.execute_deployment_resync(
                    mock.AsyncMock(), mock.AsyncMock(), 'p1'
                )
            self.assertEqual('skipped', outcome)

    async def test_other_http_error_fails(self) -> None:
        with (
            mock.patch.object(operations, '_org_slug_for', _org_slug('org')),
            mock.patch(
                'imbi.api.endpoints.project_deployments.resync_for_project',
                mock.AsyncMock(
                    side_effect=fastapi.HTTPException(
                        status_code=503, detail='no credentials'
                    )
                ),
            ),
        ):
            with self.assertRaises(operations.MaintenanceItemFailed) as ctx:
                await operations.execute_deployment_resync(
                    mock.AsyncMock(), mock.AsyncMock(), 'p1'
                )
        self.assertIn('no credentials', str(ctx.exception))


def _edge_row(
    *,
    env_slug: str = 'production',
    tag: str | None = 'v1.2.3',
    committish: str | None = 'abc1234',
    deployments: list[dict[str, object]],
) -> dict[str, object]:
    """A graph row as ``execute_opslog_backfill`` reads it.

    ``parse_agtype`` passes plain strings through and JSON-decodes the
    ``deployments`` payload, so encoding it as JSON mirrors the AGE
    edge-property shape.
    """
    return {
        'env_slug': env_slug,
        'tag': tag,
        'committish': committish,
        'deployments': json.dumps(deployments),
    }


def _existing_row(
    *,
    entry_id: str = 'opslog-1',
    version: str = 'v1.2.3',
    environment_slug: str = 'production',
    description: str | None = None,
) -> dict[str, object]:
    """An ops-log row as ``SELECT *`` returns it, minus commit_sha."""
    return {
        'id': entry_id,
        'environment_slug': environment_slug,
        'entry_type': 'Deployed',
        'description': description
        if description is not None
        else json.dumps({'action': 'deploy', 'plugin_slug': 'github'}),
        'version': version,
        'external_run_id': None,
        '_row_version': 7,
        'is_deleted': 0,
    }


def _event(
    *,
    status: str = 'success',
    performed_by: str | None = 'alice@example.com',
    external_run_id: str | None = 'run-1',
    timestamp: str = '2026-01-01T00:00:00+00:00',
    external_run_url: str | None = 'https://ci.example.com/run-1',
) -> dict[str, object]:
    return {
        'status': status,
        'performed_by': performed_by,
        'external_run_id': external_run_id,
        'external_run_url': external_run_url,
        'timestamp': timestamp,
    }


class ExecuteOpslogBackfillTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self,
        *,
        edge_rows: list[dict[str, object]],
        existing_ch_rows: list[dict[str, object]] | None = None,
    ) -> tuple[operations.ExecuteOutcome, mock.Mock]:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=edge_rows)
        instance = mock.Mock()
        instance.query = mock.AsyncMock(return_value=existing_ch_rows or [])
        instance.insert = mock.AsyncMock()
        with (
            mock.patch.object(
                operations.clickhouse.client.Clickhouse,
                'get_instance',
                return_value=instance,
            ),
            mock.patch(
                'imbi.api.endpoints._helpers.lookup_project_slugs',
                mock.AsyncMock(return_value=('proj', 'team')),
            ),
        ):
            outcome = await operations.execute_opslog_backfill(
                db, mock.AsyncMock(), 'p1'
            )
        return outcome, instance

    @staticmethod
    def _inserted_row(instance: mock.Mock) -> dict[str, object]:
        _table, values, columns = instance.insert.await_args.args
        assert len(values) == 1
        return dict(zip(columns, values[0], strict=True))

    async def test_skipped_without_edges(self) -> None:
        outcome, instance = await self._run(edge_rows=[])
        self.assertEqual('skipped', outcome)
        instance.insert.assert_not_awaited()

    async def test_inserts_row_for_attributed_success(self) -> None:
        outcome, instance = await self._run(
            edge_rows=[_edge_row(deployments=[_event()])]
        )
        self.assertEqual('succeeded', outcome)
        instance.insert.assert_awaited_once()
        table = instance.insert.await_args.args[0]
        self.assertEqual('operations_log', table)
        row = self._inserted_row(instance)
        self.assertEqual('Deployed', row['entry_type'])
        self.assertEqual('alice@example.com', row['performed_by'])
        self.assertEqual('maintenance-opslog-backfill', row['recorded_by'])
        self.assertEqual('production', row['environment_slug'])
        self.assertEqual('v1.2.3', row['version'])
        self.assertEqual('run-1', row['external_run_id'])

    async def test_occurred_at_matches_event_timestamp(self) -> None:
        _outcome, instance = await self._run(
            edge_rows=[
                _edge_row(
                    deployments=[_event(timestamp='2025-06-15T12:34:56+00:00')]
                )
            ]
        )
        row = self._inserted_row(instance)
        self.assertEqual(
            datetime.datetime(2025, 6, 15, 12, 34, 56, tzinfo=datetime.UTC),
            row['occurred_at'],
        )

    async def test_skips_events_without_performed_by(self) -> None:
        outcome, instance = await self._run(
            edge_rows=[_edge_row(deployments=[_event(performed_by=None)])]
        )
        self.assertEqual('skipped', outcome)
        instance.insert.assert_not_awaited()

    async def test_skips_non_success_events(self) -> None:
        outcome, instance = await self._run(
            edge_rows=[_edge_row(deployments=[_event(status='in_progress')])]
        )
        self.assertEqual('skipped', outcome)
        instance.insert.assert_not_awaited()

    async def test_dedupes_by_external_run_id(self) -> None:
        # The env/version differ from the event's, so only the run-id
        # match can suppress the insert.
        outcome, instance = await self._run(
            edge_rows=[_edge_row(deployments=[_event()])],
            existing_ch_rows=[
                {
                    'environment_slug': 'staging',
                    'version': 'v9.9.9',
                    'external_run_id': 'run-1',
                }
            ],
        )
        self.assertEqual('skipped', outcome)
        instance.insert.assert_not_awaited()

    async def test_dedupes_by_env_and_version(self) -> None:
        # No run id on the event, but the committish candidate matches an
        # existing (env, version) row -> nothing to insert.
        outcome, instance = await self._run(
            edge_rows=[_edge_row(deployments=[_event(external_run_id=None)])],
            existing_ch_rows=[
                {
                    'environment_slug': 'production',
                    'version': 'abc1234',
                    'external_run_id': None,
                }
            ],
        )
        self.assertEqual('skipped', outcome)
        instance.insert.assert_not_awaited()

    async def test_newest_attributed_event_wins_dedupe(self) -> None:
        # Two success events on one edge, same (env, version), no run ids.
        # Only the newer one is inserted so argMax reflects the latest
        # deployer.
        outcome, instance = await self._run(
            edge_rows=[
                _edge_row(
                    deployments=[
                        _event(
                            performed_by='old@example.com',
                            external_run_id=None,
                            timestamp='2025-01-01T00:00:00+00:00',
                        ),
                        _event(
                            performed_by='new@example.com',
                            external_run_id=None,
                            timestamp='2026-01-01T00:00:00+00:00',
                        ),
                    ]
                )
            ]
        )
        self.assertEqual('succeeded', outcome)
        row = self._inserted_row(instance)
        self.assertEqual('new@example.com', row['performed_by'])

    async def test_unsafe_run_url_is_dropped(self) -> None:
        # A plugin-supplied external_run_url with a non-http(s) scheme
        # must not reach the audit link or description JSON (XSS defense
        # in depth), even on the backfill path.
        _outcome, instance = await self._run(
            edge_rows=[
                _edge_row(
                    deployments=[
                        _event(external_run_url='javascript:alert(1)')
                    ]
                )
            ]
        )
        row = self._inserted_row(instance)
        self.assertIsNone(row['link'])
        description = json.loads(str(row['description']))
        self.assertIsNone(description['run_url'])

    async def test_fills_commit_sha_on_existing_row(self) -> None:
        # A row written before the audit payload carried commit_sha is
        # re-inserted with the edge's committish and a bumped
        # _row_version, so ReplacingMergeTree collapses to the repaired
        # row. The event itself dedupes away, so the repair is the only
        # write.
        outcome, instance = await self._run(
            edge_rows=[_edge_row(deployments=[_event(external_run_id=None)])],
            existing_ch_rows=[_existing_row()],
        )
        self.assertEqual('succeeded', outcome)
        row = self._inserted_row(instance)
        self.assertEqual('opslog-1', row['id'])
        description = json.loads(str(row['description']))
        self.assertEqual('abc1234', description['commit_sha'])
        self.assertEqual('deploy', description['action'])
        self.assertGreater(int(str(row['_row_version'])), 7)

    async def test_leaves_rows_that_already_have_commit_sha(self) -> None:
        outcome, instance = await self._run(
            edge_rows=[_edge_row(deployments=[_event(external_run_id=None)])],
            existing_ch_rows=[
                _existing_row(
                    description=json.dumps(
                        {'action': 'deploy', 'commit_sha': 'abc1234'}
                    )
                )
            ],
        )
        self.assertEqual('skipped', outcome)
        instance.insert.assert_not_awaited()

    async def test_leaves_free_text_descriptions_alone(self) -> None:
        # Human-authored entries own their description; never rewrite one.
        outcome, instance = await self._run(
            edge_rows=[_edge_row(deployments=[_event(external_run_id=None)])],
            existing_ch_rows=[
                _existing_row(description='deployed by hand during incident')
            ],
        )
        self.assertEqual('skipped', outcome)
        instance.insert.assert_not_awaited()

    async def test_repairs_row_matched_by_committish_version(self) -> None:
        # The row records the committish as its version (an untagged
        # deploy); it still gets the commit_sha so the tagged rows of the
        # same release can join it.
        _outcome, instance = await self._run(
            edge_rows=[_edge_row(deployments=[_event(external_run_id=None)])],
            existing_ch_rows=[_existing_row(version='abc1234')],
        )
        row = self._inserted_row(instance)
        description = json.loads(str(row['description']))
        self.assertEqual('abc1234', description['commit_sha'])

    async def test_repairs_each_row_once(self) -> None:
        # Two releases cut from the same commit both list the committish
        # as a version candidate, so both edges resolve the same untagged
        # row. It must be re-inserted once, not once per edge.
        _outcome, instance = await self._run(
            edge_rows=[
                _edge_row(deployments=[_event(external_run_id=None)]),
                _edge_row(
                    tag='v1.2.4',
                    deployments=[_event(external_run_id=None)],
                ),
            ],
            existing_ch_rows=[_existing_row(version='abc1234')],
        )
        _table, values, _columns = instance.insert.await_args.args
        self.assertEqual(1, len(values))

    async def test_existing_rows_query_filters_soft_deleted(self) -> None:
        # A tombstoned (is_deleted=1) ops-log row must not dedupe-suppress
        # a backfill insert, so the existing-rows read filters them out.
        _outcome, instance = await self._run(
            edge_rows=[_edge_row(deployments=[_event()])]
        )
        sql = instance.query.await_args.args[0]
        self.assertIn('is_deleted = 0', sql)


class ExecuteRescoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueued_is_succeeded(self) -> None:
        enqueue = mock.AsyncMock(return_value=True)
        with mock.patch.object(
            operations.score_queue, 'enqueue_recompute', enqueue
        ):
            outcome = await operations.execute_rescore(
                mock.AsyncMock(), mock.AsyncMock(), 'p1'
            )
        self.assertEqual('succeeded', outcome)
        args = enqueue.await_args.args
        self.assertEqual('p1', args[1])
        self.assertEqual('bulk_rescore', args[2])
        self.assertEqual('maintenance', args[3])

    async def test_debounced_is_skipped(self) -> None:
        with mock.patch.object(
            operations.score_queue,
            'enqueue_recompute',
            mock.AsyncMock(return_value=False),
        ):
            outcome = await operations.execute_rescore(
                mock.AsyncMock(), mock.AsyncMock(), 'p1'
            )
        self.assertEqual('skipped', outcome)


def _release_row(
    node_id: str,
    tag: str | None,
    committish: str,
    edges: int = 0,
    description: str | None = None,
    created_at: str = '2026-01-01T00:00:00+00:00',
) -> dict[str, object]:
    """One row as ``_RELEASE_NODES_QUERY`` returns it (agtype-parsed)."""
    return {
        'id': node_id,
        'tag': tag,
        'committish': committish,
        'description': description,
        'links': None,
        'created_at': created_at,
        'edges': edges,
    }


class ExecuteReleaseRepairTests(unittest.IsolatedAsyncioTestCase):
    """The release-identity repair, driven off stubbed graph rows."""

    @staticmethod
    def _db(rows: list[dict[str, object]]) -> mock.AsyncMock:
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(side_effect=[rows] + [[]] * 20)
        return db

    @staticmethod
    def _queries(db: mock.AsyncMock) -> list[str]:
        return [call.args[0] for call in db.execute.await_args_list[1:]]

    async def test_skipped_without_releases(self) -> None:
        outcome = await operations.execute_release_repair(
            self._db([]), mock.AsyncMock(), 'p1'
        )
        self.assertEqual('skipped', outcome)

    async def test_skipped_when_nothing_needs_repair(self) -> None:
        db = self._db([_release_row('r1', '2.21.0', '287d291', edges=1)])
        outcome = await operations.execute_release_repair(
            db, mock.AsyncMock(), 'p1'
        )
        self.assertEqual('skipped', outcome)
        self.assertEqual([], self._queries(db))

    async def test_normalizes_a_full_length_committish(self) -> None:
        db = self._db(
            [
                _release_row(
                    'r1',
                    '2.21.0',
                    '287d2912fb7ae2086a9a25dd56a8369a1b2c3d4e',
                )
            ]
        )
        outcome = await operations.execute_release_repair(
            db, mock.AsyncMock(), 'p1'
        )
        self.assertEqual('succeeded', outcome)
        params = db.execute.await_args_list[1].args[1]
        self.assertEqual('287d291', params['committish'])
        self.assertEqual('r1', params['id'])

    async def test_leaves_a_branch_committish_alone(self) -> None:
        db = self._db([_release_row('r1', None, 'main', edges=1)])
        outcome = await operations.execute_release_repair(
            db, mock.AsyncMock(), 'p1'
        )
        self.assertEqual('skipped', outcome)

    async def test_moves_the_tag_onto_the_node_owning_history(self) -> None:
        # The reported break: the deploy attached to the untagged node, so
        # the env showed a bare SHA while the tag sat on an edge-less node.
        db = self._db(
            [
                _release_row('untagged', None, '287d291', edges=1),
                _release_row(
                    'tagged', '2.21.0', '287d291', description='notes'
                ),
            ]
        )
        outcome = await operations.execute_release_repair(
            db, mock.AsyncMock(), 'p1'
        )
        self.assertEqual('succeeded', outcome)
        queries = self._queries(db)
        self.assertIn('SET r.tag', queries[0])
        retag = db.execute.await_args_list[1].args[1]
        self.assertEqual('untagged', retag['id'])
        self.assertEqual('2.21.0', retag['tag'])
        self.assertEqual('notes', retag['description'])
        # ...and the now-redundant edge-less node is removed.
        self.assertIn('DETACH DELETE', queries[1])
        self.assertEqual('tagged', db.execute.await_args_list[2].args[1]['id'])

    async def test_salvages_notes_from_the_deleted_duplicate(self) -> None:
        # The target already carries the tag but no notes, while the
        # edge-less duplicate about to be deleted holds them.
        db = self._db(
            [
                _release_row('kept', '2.21.0', '287d291', edges=1),
                _release_row('dupe', '2.21.0', '287d291', description='notes'),
            ]
        )
        outcome = await operations.execute_release_repair(
            db, mock.AsyncMock(), 'p1'
        )
        self.assertEqual('succeeded', outcome)
        queries = self._queries(db)
        self.assertIn('SET r.tag', queries[0])
        salvage = db.execute.await_args_list[1].args[1]
        self.assertEqual('kept', salvage['id'])
        self.assertEqual('notes', salvage['description'])
        self.assertIn('DETACH DELETE', queries[1])
        self.assertEqual('dupe', db.execute.await_args_list[2].args[1]['id'])

    async def test_no_salvage_write_when_the_target_has_the_notes(
        self,
    ) -> None:
        # Nothing to move: the target already holds notes, so the duplicate
        # is simply removed without a pointless write.
        db = self._db(
            [
                _release_row(
                    'kept', '2.21.0', '287d291', edges=1, description='mine'
                ),
                _release_row(
                    'dupe', '2.21.0', '287d291', description='theirs'
                ),
            ]
        )
        outcome = await operations.execute_release_repair(
            db, mock.AsyncMock(), 'p1'
        )
        self.assertEqual('succeeded', outcome)
        queries = self._queries(db)
        self.assertNotIn('SET r.tag', ' '.join(queries))
        self.assertIn('DETACH DELETE', queries[0])
        self.assertEqual('dupe', db.execute.await_args_list[1].args[1]['id'])

    async def test_keeps_a_duplicate_that_carries_history(self) -> None:
        db = self._db(
            [
                _release_row('a', None, '287d291', edges=2),
                _release_row('b', '2.21.0', '287d291', edges=1),
            ]
        )
        outcome = await operations.execute_release_repair(
            db, mock.AsyncMock(), 'p1'
        )
        self.assertEqual('succeeded', outcome)
        self.assertNotIn('DETACH DELETE', ' '.join(self._queries(db)))

    async def test_leaves_a_retagged_commit_alone(self) -> None:
        # Two tags on one commit is ambiguous — never guess which wins.
        db = self._db(
            [
                _release_row('a', '2.21.0', '287d291', edges=1),
                _release_row('b', '2.21.1', '287d291'),
            ]
        )
        outcome = await operations.execute_release_repair(
            db, mock.AsyncMock(), 'p1'
        )
        self.assertEqual('skipped', outcome)
        self.assertEqual([], self._queries(db))


class SearchReindexTests(unittest.IsolatedAsyncioTestCase):
    def _db(
        self,
        rows: list[dict[str, str]] | None = None,
        nodes: list[typing.Any] | None = None,
    ) -> mock.AsyncMock:
        db = mock.AsyncMock()
        db.execute.return_value = rows or []
        db.match.return_value = nodes or []
        return db

    async def test_enumerates_every_embeddable_label(self) -> None:
        db = self._db([{'id': '"n-1"'}, {'id': '""'}])
        items = await operations.enumerate_embeddable_nodes(db)
        labels = [t.__name__ for t in graph.embeddable_node_types()]
        # One item per label, falsy ids dropped.
        self.assertEqual([f'{label}:n-1' for label in labels], items)
        self.assertIn('Document', labels)
        self.assertIn('Comment', labels)

    async def test_reindexes_the_matched_node(self) -> None:
        node = common_models.Document.model_construct(
            id='doc-1', title='Runbook', content='body'
        )
        db = self._db(nodes=[node])
        outcome = await operations.execute_search_reindex(
            db, mock.AsyncMock(), 'Document:doc-1'
        )
        self.assertEqual('succeeded', outcome)
        self.assertEqual(common_models.Document, db.match.await_args.args[0])
        self.assertEqual({'id': 'doc-1'}, db.match.await_args.args[1])
        self.assertIs(node, db.embed_node.await_args.args[0])
        # A silent embedding failure must not be reported as success.
        self.assertTrue(db.embed_node.await_args.kwargs['raise_on_error'])

    async def test_skips_a_node_deleted_mid_run(self) -> None:
        db = self._db()
        outcome = await operations.execute_search_reindex(
            db, mock.AsyncMock(), 'Document:ghost'
        )
        self.assertEqual('skipped', outcome)
        db.embed_node.assert_not_awaited()

    async def test_skips_a_label_that_is_no_longer_embeddable(self) -> None:
        db = self._db()
        outcome = await operations.execute_search_reindex(
            db, mock.AsyncMock(), 'Retired:n-1'
        )
        self.assertEqual('skipped', outcome)
        db.match.assert_not_awaited()

    async def test_embedding_failure_is_recorded_against_the_node(
        self,
    ) -> None:
        db = self._db(
            nodes=[common_models.Document.model_construct(id='doc-1')]
        )
        db.embed_node.side_effect = RuntimeError('model unavailable')
        with self.assertRaises(operations.MaintenanceItemFailed):
            await operations.execute_search_reindex(
                db, mock.AsyncMock(), 'Document:doc-1'
            )
