"""Tests for the maintenance per-project execute functions."""

from __future__ import annotations

import contextlib
import time
import unittest
from unittest import mock

import fastapi
from imbi_common.plugins.errors import PluginRateLimited

from imbi_api.commit_sync.service import CommitSyncUnavailable
from imbi_api.maintenance import operations
from imbi_api.pr_sync.service import PRSyncUnavailable


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
                'imbi_api.endpoints.project_analysis.run_and_persist', run
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


class ExecuteCommitSyncTests(unittest.IsolatedAsyncioTestCase):
    def _patches(
        self, run_sync: mock.AsyncMock
    ) -> tuple[
        mock.AsyncMock, list[contextlib.AbstractContextManager[object]]
    ]:
        set_status = mock.AsyncMock()
        return set_status, [
            mock.patch.object(operations, '_org_slug_for', _org_slug('org')),
            mock.patch('imbi_api.commit_sync.service.run_sync', run_sync),
            mock.patch('imbi_api.commit_sync.service.set_status', set_status),
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
                'imbi_api.pr_sync.service.run_sync',
                mock.AsyncMock(return_value=7),
            ),
            mock.patch('imbi_api.pr_sync.service.set_status', set_status),
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
                'imbi_api.pr_sync.service.run_sync',
                mock.AsyncMock(side_effect=PRSyncUnavailable('unbound')),
            ),
            mock.patch(
                'imbi_api.pr_sync.service.set_status', mock.AsyncMock()
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
                'imbi_api.endpoints.project_deployments.resync_for_project',
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
                    'imbi_api.endpoints.project_deployments'
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
                'imbi_api.endpoints.project_deployments.resync_for_project',
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
