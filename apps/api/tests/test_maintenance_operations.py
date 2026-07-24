"""Tests for the maintenance per-project execute functions."""

from __future__ import annotations

import contextlib
import datetime
import json
import time
import unittest
from unittest import mock

import fastapi

from imbi.api.commit_sync.service import CommitSyncUnavailable
from imbi.api.maintenance import operations
from imbi.api.pr_sync.service import PRSyncUnavailable
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
