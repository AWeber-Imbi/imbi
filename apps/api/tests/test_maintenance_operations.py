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
from imbi.api.maintenance import log, operations
from imbi.api.pr_sync.service import PRSyncUnavailable
from imbi.common import graph
from imbi.common import models as common_models
from imbi.common.plugins.errors import PluginRateLimited


def _ctx(item_id: str = 'p1') -> log.MaintenanceContext:
    """A context whose ItemLog only buffers -- nothing flushes it here."""
    return log.MaintenanceContext(
        run_id='run1',
        attempt_id='attempt1',
        item_id=item_id,
        project_id=item_id,
        project_slug='',
        log=log.ItemLog('slug', 'run1', 'attempt1', item_id, item_id),
    )


def _rows(ctx: log.MaintenanceContext) -> tuple[typing.Any, ...]:
    """The activity rows an operation buffered on its context."""
    return ctx.log.rows


def _actions(ctx: log.MaintenanceContext) -> list[tuple[str, str]]:
    return [(row.action, row.disposition) for row in _rows(ctx)]


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
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
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
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('succeeded', outcome)
        args = run.await_args.args
        self.assertEqual('org', args[1])
        self.assertEqual('p1', args[2])
        self.assertEqual('maintenance', args[3].principal_name)


def _remediate_response(*statuses: str) -> mock.Mock:
    """A fake RemediateAllResponse carrying outcomes of the given statuses."""
    outcomes = [
        mock.Mock(
            plugin_id='plugin',
            result=mock.Mock(message=f'{status} message', status=status),
            slug=f'finding-{index}',
        )
        for index, status in enumerate(statuses)
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
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('skipped', outcome)

    async def test_skipped_without_report(self) -> None:
        remediate = mock.AsyncMock(return_value=None)
        with self._patch(remediate):
            outcome = await operations.execute_remediate(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('skipped', outcome)
        self.assertEqual(
            'maintenance', remediate.await_args.kwargs['auth'].principal_name
        )

    async def test_skipped_without_fixable_findings(self) -> None:
        remediate = mock.AsyncMock(return_value=_remediate_response())
        with self._patch(remediate):
            outcome = await operations.execute_remediate(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('skipped', outcome)

    async def test_all_fixed_is_succeeded(self) -> None:
        remediate = mock.AsyncMock(
            return_value=_remediate_response('fixed', 'noop')
        )
        with self._patch(remediate):
            outcome = await operations.execute_remediate(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('succeeded', outcome)

    async def test_any_failed_raises_item_failed(self) -> None:
        remediate = mock.AsyncMock(
            return_value=_remediate_response('fixed', 'failed')
        )
        with self._patch(remediate):
            with self.assertRaises(operations.MaintenanceItemFailed):
                await operations.execute_remediate(
                    mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
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
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
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
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
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
                    mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
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
                    mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
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
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
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
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('skipped', outcome)


class ExecuteDeploymentSweepTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _sweep(result: object) -> mock.AsyncMock:
        return mock.AsyncMock(return_value=result)

    def _run(
        self,
        sweep_result: object,
        drift_result: object = 0,
        verdicts: object = 0,
    ) -> typing.Any:
        return (
            mock.patch(
                'imbi.api.deployment_sweeper.sweep_project',
                self._sweep(sweep_result),
            ),
            mock.patch.object(operations, '_org_slug_for', _org_slug('org')),
            mock.patch(
                'imbi.api.drift.sweep_project', self._sweep(drift_result)
            ),
            mock.patch(
                'imbi.api.drift.backfill_verdicts', self._sweep(verdicts)
            ),
        )

    async def test_swept_deployments_succeed(self) -> None:
        from imbi.api import deployment_sweeper

        sweep, org, drift, verdicts = self._run(
            deployment_sweeper.SweepSummary(examined=2)
        )
        with sweep, org, drift, verdicts:
            outcome = await operations.execute_deployment_sweep(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('succeeded', outcome)

    async def test_no_capability_is_skipped(self) -> None:
        sweep, org, drift, verdicts = self._run(None, None)
        with sweep, org, drift, verdicts:
            outcome = await operations.execute_deployment_sweep(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('skipped', outcome)

    async def test_nothing_stuck_is_skipped(self) -> None:
        from imbi.api import deployment_sweeper

        sweep, org, drift, verdicts = self._run(
            deployment_sweeper.SweepSummary(), 0
        )
        with sweep, org, drift, verdicts:
            outcome = await operations.execute_deployment_sweep(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('skipped', outcome)

    async def test_drift_failure_keeps_the_sweep_result(self) -> None:
        from imbi.api import deployment_sweeper

        sweep, org, _unused, verdicts = self._run(
            deployment_sweeper.SweepSummary(examined=2)
        )
        failing = mock.patch(
            'imbi.api.drift.sweep_project',
            mock.AsyncMock(side_effect=RuntimeError('boom')),
        )
        with (
            sweep,
            org,
            verdicts,
            failing,
            self.assertLogs(operations.LOGGER, level='ERROR'),
        ):
            outcome = await operations.execute_deployment_sweep(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('succeeded', outcome)

    async def test_drift_rate_limit_propagates(self) -> None:
        from imbi.api import deployment_sweeper

        sweep, org, _unused, verdicts = self._run(
            deployment_sweeper.SweepSummary()
        )
        limited = mock.patch(
            'imbi.api.drift.sweep_project',
            mock.AsyncMock(
                side_effect=operations.PluginRateLimited(retry_at=1.0)
            ),
        )
        with sweep, org, limited, verdicts:
            with self.assertRaises(operations.PluginRateLimited):
                await operations.execute_deployment_sweep(
                    mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
                )

    async def test_verdict_backfill_rate_limit_propagates(self) -> None:
        # The verdict backfill gets its own except-clause, so it needs
        # its own proof that a rate limit still reaches the worker and
        # leaves the project requeue-able.
        sweep, org, drift, _unused = self._run(None)
        limited = mock.patch(
            'imbi.api.drift.backfill_verdicts',
            mock.AsyncMock(
                side_effect=operations.PluginRateLimited(retry_at=1.0)
            ),
        )
        with sweep, org, drift, limited:
            with self.assertRaises(operations.PluginRateLimited):
                await operations.execute_deployment_sweep(
                    mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
                )

    async def test_both_backfills_failing_is_not_a_quiet_skip(self) -> None:
        # Nothing to sweep and both backfills broken: the attempt must
        # not claim there was nothing to do.
        sweep, org, _drift, _verdicts = self._run(None)
        failing_stamp = mock.patch(
            'imbi.api.drift.sweep_project',
            mock.AsyncMock(side_effect=RuntimeError('boom')),
        )
        failing_verdicts = mock.patch(
            'imbi.api.drift.backfill_verdicts',
            mock.AsyncMock(side_effect=RuntimeError('boom')),
        )
        with (
            sweep,
            org,
            failing_stamp,
            failing_verdicts,
            self.assertLogs(operations.LOGGER, level='ERROR'),
            self.assertRaises(operations.MaintenanceItemFailed) as raised,
        ):
            await operations.execute_deployment_sweep(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertIn('drift backfill', str(raised.exception))
        self.assertIn('recording drift verdicts', str(raised.exception))

    async def test_a_failure_alongside_real_work_still_succeeds(self) -> None:
        from imbi.api import deployment_sweeper

        # The sweep did something, so the item is not a failure even
        # though a backfill broke; the failed action row carries that.
        sweep, org, _drift, verdicts = self._run(
            deployment_sweeper.SweepSummary(examined=2)
        )
        failing = mock.patch(
            'imbi.api.drift.sweep_project',
            mock.AsyncMock(side_effect=RuntimeError('boom')),
        )
        with (
            sweep,
            org,
            failing,
            verdicts,
            self.assertLogs(operations.LOGGER, level='ERROR'),
        ):
            outcome = await operations.execute_deployment_sweep(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('succeeded', outcome)

    async def test_recorded_verdicts_alone_succeed(self) -> None:
        sweep, org, drift, verdicts = self._run(None, 0, 5)
        with sweep, org, drift, verdicts:
            outcome = await operations.execute_deployment_sweep(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('succeeded', outcome)

    async def test_a_verdict_failure_keeps_the_sweep_result(self) -> None:
        from imbi.api import deployment_sweeper

        sweep, org, drift, _unused = self._run(
            deployment_sweeper.SweepSummary(examined=2)
        )
        failing = mock.patch(
            'imbi.api.drift.backfill_verdicts',
            mock.AsyncMock(side_effect=RuntimeError('boom')),
        )
        with (
            sweep,
            org,
            drift,
            failing,
            self.assertLogs(operations.LOGGER, level='ERROR'),
        ):
            outcome = await operations.execute_deployment_sweep(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('succeeded', outcome)

    async def test_a_stamp_failure_still_records_verdicts(self) -> None:
        sweep, org, _unused, verdicts = self._run(None, 0, 4)
        failing = mock.patch(
            'imbi.api.drift.sweep_project',
            mock.AsyncMock(side_effect=RuntimeError('boom')),
        )
        with (
            sweep,
            org,
            failing,
            verdicts as verdict_mock,
            self.assertLogs(operations.LOGGER, level='ERROR'),
        ):
            outcome = await operations.execute_deployment_sweep(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        # The stamping and the recording are separate boundaries.
        self.assertEqual('succeeded', outcome)
        verdict_mock.assert_awaited_once()

    async def test_drift_backfill_alone_succeeds(self) -> None:
        sweep, org, drift_patch, verdicts = self._run(None, 3)
        with sweep, org, verdicts, drift_patch as drift_mock:
            outcome = await operations.execute_deployment_sweep(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('succeeded', outcome)
        self.assertEqual(
            {'org_slug': 'org', 'project_id': 'p1'},
            {
                k: v
                for k, v in drift_mock.await_args.kwargs.items()
                if k in ('org_slug', 'project_id')
            },
        )


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
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
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
                    mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
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
                    mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
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
                db, mock.AsyncMock(), 'p1', ctx=_ctx()
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
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
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
            ctx = _ctx()
            outcome = await operations.execute_rescore(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=ctx
            )
        self.assertEqual('skipped', outcome)
        # A bare 'skipped' leaves an operator guessing; say it debounced.
        row = _rows(ctx)[0]
        self.assertEqual('skipped', row.disposition)
        self.assertEqual('rescore', row.action)
        self.assertIn('already queued', row.message)


def _blocked_row(
    node_id: str,
    *,
    scope: str | None = None,
    reason: str | None = 'Rolled back',
    blocked_by: str | None = 'gr@example.com',
) -> dict[str, object]:
    """One row as ``_BLOCKED_RELEASES_QUERY`` returns it."""
    return {
        'id': node_id,
        'blocked_at': '2026-01-02T00:00:00+00:00',
        'blocked_by': blocked_by,
        'reason': reason,
        'scope': scope,
    }


class ExecuteBlockerMigrationTests(unittest.IsolatedAsyncioTestCase):
    """Old release-block flags become ``Blocker`` nodes."""

    @staticmethod
    def _db(
        rows: list[dict[str, object]],
        write_result: list[dict[str, object]] | None = None,
    ) -> mock.AsyncMock:
        db = mock.AsyncMock()
        if write_result is None:
            write_result = [{'id': 'r1'}]
        db.execute = mock.AsyncMock(side_effect=[rows] + [write_result] * 20)
        return db

    async def test_skipped_when_nothing_is_flagged(self) -> None:
        db = self._db([])
        outcome = await operations.execute_blocker_migration(
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
        )
        self.assertEqual('skipped', outcome)
        db.execute.assert_awaited_once()

    async def test_a_manual_block_becomes_a_commit_wide_blocker(self) -> None:
        db = self._db([_blocked_row('r1')])
        outcome = await operations.execute_blocker_migration(
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
        )
        self.assertEqual('succeeded', outcome)
        query, params, _ = db.execute.await_args_list[1].args
        self.assertIn('CREATE (r)-[:BLOCKED_BY]', query)
        self.assertEqual('manual', params['type'])
        self.assertEqual('commit', params['scope'])
        self.assertEqual('Rolled back', params['description'])
        self.assertEqual('gr@example.com', params['created_by'])
        # The blocker inherits when the block was made, not now.
        self.assertEqual('2026-01-02T00:00:00+00:00', params['created_at'])
        # And the flags go, which is what makes a re-run a no-op.
        self.assertIn('SET r.blocked_at = NULL', query)

    async def test_a_tag_scoped_block_becomes_a_build_failure(self) -> None:
        db = self._db([_blocked_row('r1', scope='tag')])
        await operations.execute_blocker_migration(
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
        )
        params = db.execute.await_args_list[1].args[1]
        self.assertEqual('build-failure', params['type'])
        self.assertEqual('tag', params['scope'])

    async def test_a_block_with_no_reason_still_migrates(self) -> None:
        db = self._db([_blocked_row('r1', reason=None, blocked_by=None)])
        await operations.execute_blocker_migration(
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
        )
        params = db.execute.await_args_list[1].args[1]
        self.assertEqual('Blocked', params['description'])
        self.assertEqual('maintenance', params['created_by'])

    async def test_every_flagged_release_is_migrated(self) -> None:
        db = self._db([_blocked_row('r1'), _blocked_row('r2')])
        outcome = await operations.execute_blocker_migration(
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
        )
        self.assertEqual('succeeded', outcome)
        migrated = [
            call.args[1]['id'] for call in db.execute.await_args_list[1:]
        ]
        self.assertEqual(['r1', 'r2'], migrated)

    async def test_a_release_cleared_mid_run_does_not_double_migrate(
        self,
    ) -> None:
        # Two overlapping runs read the same flagged release. The first
        # one's write clears the flags, so the second one's write matches
        # nothing: the query requires blocked_at to still be set, and a
        # rowless write must not count as migrated.
        db = self._db([_blocked_row('r1')], write_result=[])
        outcome = await operations.execute_blocker_migration(
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
        )
        self.assertEqual('skipped', outcome)
        query = db.execute.await_args_list[1].args[0]
        self.assertIn('WHERE r.blocked_at IS NOT NULL', query)


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
            self._db([]), mock.AsyncMock(), 'p1', ctx=_ctx()
        )
        self.assertEqual('skipped', outcome)

    async def test_skipped_when_nothing_needs_repair(self) -> None:
        db = self._db([_release_row('r1', '2.21.0', '287d291', edges=1)])
        outcome = await operations.execute_release_repair(
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
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
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
        )
        self.assertEqual('succeeded', outcome)
        params = db.execute.await_args_list[1].args[1]
        self.assertEqual('287d291', params['committish'])
        self.assertEqual('r1', params['id'])

    async def test_leaves_a_branch_committish_alone(self) -> None:
        db = self._db([_release_row('r1', None, 'main', edges=1)])
        outcome = await operations.execute_release_repair(
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
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
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
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
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
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
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
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
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
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
            db, mock.AsyncMock(), 'p1', ctx=_ctx()
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
            db, mock.AsyncMock(), 'Document:doc-1', ctx=_ctx()
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
            db, mock.AsyncMock(), 'Document:ghost', ctx=_ctx()
        )
        self.assertEqual('skipped', outcome)
        db.embed_node.assert_not_awaited()

    async def test_skips_a_label_that_is_no_longer_embeddable(self) -> None:
        db = self._db()
        outcome = await operations.execute_search_reindex(
            db, mock.AsyncMock(), 'Retired:n-1', ctx=_ctx()
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
                db, mock.AsyncMock(), 'Document:doc-1', ctx=_ctx()
            )


class Phase3WrapperTests(unittest.IsolatedAsyncioTestCase):
    """The phase-3 execute wrappers map summaries to run outcomes."""

    def _patch(
        self, name: str, summary: object
    ) -> tuple[contextlib.ExitStack, mock.AsyncMock]:
        call = mock.AsyncMock(return_value=summary)
        stack = contextlib.ExitStack()
        stack.enter_context(
            mock.patch.object(operations, '_org_slug_for', _org_slug('org'))
        )
        stack.enter_context(
            mock.patch(f'imbi.api.deployment_migration.{name}', call)
        )
        return stack, call

    async def test_dup_merge_report_is_a_dry_run(self) -> None:
        from imbi.api import deployment_migration

        stack, call = self._patch(
            'merge_duplicate_releases',
            deployment_migration.DupMergeSummary(groups=2),
        )
        with stack:
            outcome = await operations.execute_release_dup_merge_report(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('succeeded', outcome)
        self.assertTrue(call.await_args.kwargs['dry_run'])

    async def test_dup_merge_with_no_duplicates_is_skipped(self) -> None:
        from imbi.api import deployment_migration

        stack, call = self._patch(
            'merge_duplicate_releases', deployment_migration.DupMergeSummary()
        )
        with stack:
            outcome = await operations.execute_release_dup_merge(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('skipped', outcome)
        self.assertFalse(call.await_args.kwargs['dry_run'])
        self.assertEqual('org', call.await_args.kwargs['org_slug'])

    async def test_dup_merge_without_an_org_is_skipped(self) -> None:
        with mock.patch.object(operations, '_org_slug_for', _org_slug(None)):
            outcome = await operations.execute_release_dup_merge(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('skipped', outcome)

    async def test_migration_maps_edges_to_outcome(self) -> None:
        from imbi.api import deployment_migration

        for edges, expected in ((1, 'succeeded'), (0, 'skipped')):
            call = mock.AsyncMock(
                return_value=deployment_migration.MigrationSummary(edges=edges)
            )
            with mock.patch(
                'imbi.api.deployment_migration.migrate_deployment_arrays',
                call,
            ):
                outcome = await operations.execute_deployment_migration(
                    mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
                )
            self.assertEqual(expected, outcome)
            self.assertFalse(call.await_args.kwargs['dry_run'])

    async def test_migration_report_is_a_dry_run(self) -> None:
        from imbi.api import deployment_migration

        call = mock.AsyncMock(
            return_value=deployment_migration.MigrationSummary(edges=1)
        )
        with mock.patch(
            'imbi.api.deployment_migration.migrate_deployment_arrays', call
        ):
            outcome = await operations.execute_deployment_migration_report(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('succeeded', outcome)
        self.assertTrue(call.await_args.kwargs['dry_run'])

    async def test_orphan_check_skips_an_unanswerable_project(self) -> None:
        stack, call = self._patch('purge_orphan_releases', None)
        with stack:
            outcome = await operations.execute_orphan_release_check(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('skipped', outcome)
        self.assertTrue(call.await_args.kwargs['dry_run'])

    async def test_orphan_purge_succeeds_when_candidates_exist(self) -> None:
        from imbi.api import deployment_migration

        stack, call = self._patch(
            'purge_orphan_releases',
            deployment_migration.OrphanSummary(
                tagged=3, candidates=1, orphans=1, deleted=1
            ),
        )
        with stack:
            outcome = await operations.execute_orphan_release_purge(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('succeeded', outcome)
        self.assertFalse(call.await_args.kwargs['dry_run'])

    async def test_orphan_purge_without_confirmed_orphans_is_skipped(
        self,
    ) -> None:
        # A candidate whose tag lookup failed (or whose tag exists) is
        # not an orphan; succeeded would misread as "orphans handled".
        from imbi.api import deployment_migration

        stack, _call = self._patch(
            'purge_orphan_releases',
            deployment_migration.OrphanSummary(
                tagged=3, candidates=1, unresolved=1, orphans=0
            ),
        )
        with stack:
            outcome = await operations.execute_orphan_release_purge(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=_ctx()
            )
        self.assertEqual('skipped', outcome)


class ActivityLoggingTests(unittest.IsolatedAsyncioTestCase):
    """What operations record beyond their attempt row.

    The attempt row already says succeeded / skipped / failed. These
    assert the *why*, which before this only reached the server log.
    """

    async def test_a_missing_organization_says_so(self) -> None:
        ctx = _ctx()
        with mock.patch.object(operations, '_org_slug_for', _org_slug(None)):
            outcome = await operations.execute_analysis(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=ctx
            )
        self.assertEqual('skipped', outcome)
        self.assertEqual([('no-organization', 'skipped')], _actions(ctx))

    @staticmethod
    def _commit_sync_patches(
        run_sync: mock.AsyncMock,
    ) -> list[contextlib.AbstractContextManager[object]]:
        return [
            mock.patch.object(operations, '_org_slug_for', _org_slug('org')),
            mock.patch('imbi.api.commit_sync.service.run_sync', run_sync),
            mock.patch(
                'imbi.api.commit_sync.service.set_status', mock.AsyncMock()
            ),
        ]

    async def test_commit_sync_records_the_unavailable_reason(self) -> None:
        ctx = _ctx()
        org, run_sync, set_status = self._commit_sync_patches(
            mock.AsyncMock(
                side_effect=CommitSyncUnavailable('No commit-sync integration')
            )
        )
        with org, run_sync, set_status:
            outcome = await operations.execute_commit_sync(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=ctx
            )
        self.assertEqual('skipped', outcome)
        row = _rows(ctx)[0]
        self.assertEqual('commit-sync', row.action)
        self.assertIn('No commit-sync integration', row.message)

    async def test_commit_sync_records_what_it_synced(self) -> None:
        ctx = _ctx()
        org, run_sync, set_status = self._commit_sync_patches(
            mock.AsyncMock(return_value=(12, 3))
        )
        with org, run_sync, set_status:
            await operations.execute_commit_sync(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=ctx
            )
        row = _rows(ctx)[0]
        self.assertEqual({'commits': 12, 'tags': 3}, row.detail)

    async def test_each_failed_remediation_gets_a_row(self) -> None:
        ctx = _ctx()
        remediate = mock.AsyncMock(
            return_value=_remediate_response('failed', 'fixed', 'failed')
        )
        with (
            mock.patch.object(operations, '_org_slug_for', _org_slug('org')),
            mock.patch(
                'imbi.api.endpoints.project_analysis.'
                'remediate_all_for_project',
                remediate,
            ),
            self.assertRaises(operations.MaintenanceItemFailed),
        ):
            await operations.execute_remediate(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=ctx
            )
        failures = [r for r in _rows(ctx) if r.disposition == 'failed']
        # Two per-finding rows plus the summary, which is also a failure.
        self.assertEqual(3, len(failures))
        self.assertEqual(
            ['finding-0', 'finding-2'],
            [r.detail['finding'] for r in failures if 'finding' in r.detail],
        )
        self.assertEqual(1, failures[-1].detail['fixed'])

    async def test_the_sweep_records_its_counts(self) -> None:
        from imbi.api import deployment_sweeper

        ctx = _ctx()
        with (
            mock.patch(
                'imbi.api.deployment_sweeper.sweep_project',
                mock.AsyncMock(
                    return_value=deployment_sweeper.SweepSummary(
                        attached=1, examined=4, expired=1, resolved=2
                    )
                ),
            ),
            mock.patch.object(operations, '_org_slug_for', _org_slug('org')),
            mock.patch(
                'imbi.api.drift.sweep_project', mock.AsyncMock(return_value=3)
            ),
            mock.patch(
                'imbi.api.drift.backfill_verdicts',
                mock.AsyncMock(return_value=2),
            ),
        ):
            await operations.execute_deployment_sweep(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=ctx
            )
        self.assertEqual(
            [
                ('deployment-sweep', 'succeeded'),
                ('drift-backfill', 'succeeded'),
                ('drift-verdicts', 'succeeded'),
            ],
            _actions(ctx),
        )
        self.assertEqual(2, _rows(ctx)[0].detail['resolved'])
        self.assertEqual(3, _rows(ctx)[1].detail['stamped'])

    async def test_an_unresolvable_orphan_candidate_is_recorded(self) -> None:
        from imbi.api import deployment_migration

        ctx = _ctx()
        with (
            mock.patch.object(operations, '_org_slug_for', _org_slug('org')),
            mock.patch(
                'imbi.api.deployment_migration.purge_orphan_releases',
                mock.AsyncMock(
                    return_value=deployment_migration.OrphanSummary(
                        candidates=2, tagged=5, unresolved=2
                    )
                ),
            ),
        ):
            outcome = await operations.execute_orphan_release_check(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=ctx
            )
        self.assertEqual('skipped', outcome)
        self.assertEqual(
            [
                ('orphan-release-check', 'skipped'),
                ('orphan-release-check', 'skipped'),
            ],
            _actions(ctx),
        )
        self.assertEqual(2, _rows(ctx)[0].detail['unresolved'])

    async def test_a_dry_run_says_it_was_one(self) -> None:
        from imbi.api import deployment_migration

        ctx = _ctx()
        with (
            mock.patch.object(operations, '_org_slug_for', _org_slug('org')),
            mock.patch(
                'imbi.api.deployment_migration.merge_duplicate_releases',
                mock.AsyncMock(
                    return_value=deployment_migration.DupMergeSummary(
                        groups=2, merged=3
                    )
                ),
            ),
        ):
            await operations.execute_release_dup_merge_report(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=ctx
            )
        row = _rows(ctx)[0]
        self.assertEqual('release-dup-merge-report', row.action)
        self.assertTrue(row.detail['dry_run'])
        self.assertIn('dry run', row.message)

    async def test_malformed_migration_entries_are_recorded(self) -> None:
        from imbi.api import deployment_migration

        ctx = _ctx()
        with mock.patch(
            'imbi.api.deployment_migration.migrate_deployment_arrays',
            mock.AsyncMock(
                return_value=deployment_migration.MigrationSummary(
                    created=1, edges=2, entries=4, malformed=2
                )
            ),
        ):
            await operations.execute_deployment_migration(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=ctx
            )
        self.assertEqual(
            [
                ('deployment-migration', 'failed'),
                ('deployment-migration', 'succeeded'),
            ],
            _actions(ctx),
        )
        self.assertEqual(2, _rows(ctx)[0].detail['malformed'])

    async def test_a_reindex_of_a_retired_label_says_why(self) -> None:
        ctx = _ctx()
        outcome = await operations.execute_search_reindex(
            mock.AsyncMock(), mock.AsyncMock(), 'Retired:n1', ctx=ctx
        )
        self.assertEqual('skipped', outcome)
        self.assertEqual('Retired', _rows(ctx)[0].detail['label'])


class SbomActivityLoggingTests(unittest.IsolatedAsyncioTestCase):
    """The SBoM operations' rows.

    The reconcile report is the sharpest case for the activity log: it
    found its mismatches per release and told only the server log.
    """

    async def test_each_mismatched_release_gets_a_row(self) -> None:
        from imbi.api import sbom_backfill

        ctx = _ctx()
        summary = sbom_backfill.ReconcileSummary(
            matched=7,
            mismatched={
                'r-1': 'graph has 3, clickhouse has 2',
                'r-2': 'drift',
            },
        )
        with mock.patch(
            'imbi.api.sbom_backfill.reconcile_project',
            mock.AsyncMock(return_value=summary),
        ):
            outcome = await operations.execute_sbom_backfill_report(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=ctx
            )
        self.assertEqual('succeeded', outcome)
        mismatches = [r for r in _rows(ctx) if r.action == 'sbom-mismatch']
        self.assertEqual(
            ['r-1', 'r-2'], [r.detail['release_id'] for r in mismatches]
        )
        self.assertEqual(
            'graph has 3, clickhouse has 2', mismatches[0].message
        )
        summary_row = _rows(ctx)[-1]
        self.assertEqual(2, summary_row.detail['mismatched'])
        self.assertEqual(7, summary_row.detail['matched'])

    async def test_agreeing_stores_say_how_much_was_checked(self) -> None:
        from imbi.api import sbom_backfill

        ctx = _ctx()
        with mock.patch(
            'imbi.api.sbom_backfill.reconcile_project',
            mock.AsyncMock(
                return_value=sbom_backfill.ReconcileSummary(matched=12)
            ),
        ):
            outcome = await operations.execute_sbom_backfill_report(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=ctx
            )
        self.assertEqual('skipped', outcome)
        self.assertEqual(12, _rows(ctx)[0].detail['matched'])

    async def test_the_backfill_records_what_it_published(self) -> None:
        from imbi.api import sbom_backfill

        ctx = _ctx()
        with mock.patch(
            'imbi.api.sbom_backfill.backfill_project',
            mock.AsyncMock(
                return_value=sbom_backfill.BackfillSummary(
                    components_written=40,
                    releases_published=4,
                    releases_skipped=6,
                )
            ),
        ):
            outcome = await operations.execute_sbom_backfill(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=ctx
            )
        self.assertEqual('succeeded', outcome)
        row = _rows(ctx)[0]
        self.assertEqual(4, row.detail['releases_published'])
        self.assertEqual(40, row.detail['components_written'])

    async def test_a_fully_batched_project_says_so(self) -> None:
        from imbi.api import sbom_backfill

        ctx = _ctx()
        with mock.patch(
            'imbi.api.sbom_backfill.backfill_project',
            mock.AsyncMock(
                return_value=sbom_backfill.BackfillSummary(releases_skipped=9)
            ),
        ):
            outcome = await operations.execute_sbom_backfill(
                mock.AsyncMock(), mock.AsyncMock(), 'p1', ctx=ctx
            )
        self.assertEqual('skipped', outcome)
        self.assertEqual(9, _rows(ctx)[0].detail['releases_skipped'])
