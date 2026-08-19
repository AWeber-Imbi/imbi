"""Tests for the scheduled deployment sweeper."""

from __future__ import annotations

import datetime
import typing
import unittest
from unittest import mock

import fastapi
import httpx

from imbi.api import deployment_sweeper
from imbi.common import deployments
from imbi.common.plugins import base as plugin_base

NOW = datetime.datetime(2026, 8, 18, 12, tzinfo=datetime.UTC)


def _stuck(**overrides: typing.Any) -> deployments.StuckDeployment:
    fields: dict[str, typing.Any] = {
        'id': 'dep-1',
        'project_id': 'p1',
        'org_slug': 'octo',
        'env_slug': 'production',
        'external_run_id': 'run-42',
        'status': 'in_progress',
        'origin': 'gateway',
        'created_at': NOW - datetime.timedelta(hours=2),
        'release_id': 'rel-1',
        'release_tag': None,
        'release_committish': None,
    }
    fields.update(overrides)
    return deployments.StuckDeployment(**fields)


def _run(
    status: str, completed_at: datetime.datetime | None = None
) -> plugin_base.DeploymentRun:
    return plugin_base.DeploymentRun(
        run_id='run-42',
        run_url='https://gh/deployments/42',
        status=typing.cast('typing.Any', status),
        completed_at=completed_at,
    )


class SweeperTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.stuck = mock.AsyncMock(return_value=[_stuck()])
        self.poll = mock.AsyncMock(return_value=_run('success'))
        self.append = mock.AsyncMock(return_value=(mock.Mock(), 'updated'))
        self.upsert = mock.AsyncMock(
            return_value=deployments.UpsertResult('dep-1', 'updated')
        )
        self.attach = mock.AsyncMock(return_value=True)
        for target, replacement in (
            ('imbi.common.deployments.stuck_deployments', self.stuck),
            ('imbi.common.deployments.attach_release', self.attach),
            ('imbi.common.deployments.upsert_deployment', self.upsert),
            (
                'imbi.api.endpoints.project_deployments.poll_promote_rollout',
                self.poll,
            ),
            (
                'imbi.api.endpoints.releases.append_deployment_event',
                self.append,
            ),
        ):
            patcher = mock.patch(target, replacement)
            self.addCleanup(patcher.stop)
            patcher.start()

    async def _sweep(
        self, db: mock.AsyncMock | None = None
    ) -> deployment_sweeper.SweepSummary | None:
        return await deployment_sweeper.sweep_project(
            db or mock.AsyncMock(), 'p1', now=NOW
        )

    async def test_terminal_run_closes_the_deployment(self) -> None:
        summary = await self._sweep()
        assert summary is not None
        self.assertEqual(1, summary.resolved)
        self.assertEqual(0, summary.expired)
        kwargs = self.append.await_args.kwargs
        self.assertEqual('success', kwargs['status'])
        self.assertEqual('run-42', kwargs['external_run_id'])
        self.assertEqual('sweeper', kwargs['source'])
        self.assertEqual(
            'https://gh/deployments/42', kwargs['external_run_url']
        )

    async def test_close_out_is_stamped_with_the_run_completion(
        self,
    ) -> None:
        """A late close-out must not claim to have happened now.

        The current-release pointer only moves forward, so closing a
        week-old success at sweep time would let it supersede a release
        that shipped after it.
        """
        done = NOW - datetime.timedelta(days=3)
        self.poll.return_value = _run('success', completed_at=done)
        await self._sweep()
        self.assertEqual(done, self.append.await_args.kwargs['timestamp'])

    async def test_close_out_falls_back_to_the_start_time(self) -> None:
        await self._sweep()
        self.assertEqual(
            _stuck().created_at, self.append.await_args.kwargs['timestamp']
        )

    async def test_persistent_poll_failure_eventually_expires(self) -> None:
        self.stuck.return_value = [
            _stuck(created_at=NOW - datetime.timedelta(days=8))
        ]
        self.poll.side_effect = RuntimeError('gateway timeout')
        summary = await self._sweep()
        assert summary is not None
        self.assertEqual(1, summary.expired)
        kwargs = self.append.await_args.kwargs
        self.assertEqual('failed', kwargs['status'])
        self.assertTrue(
            kwargs['note'].startswith(deployment_sweeper.EXPIRED_NOTE)
        )

    async def test_vanished_remote_run_expires(self) -> None:
        """The dominant stuck class: dispatched, never updated, gone.

        GitHub's ``get_deployment_status`` raises for status, so a run
        the remote no longer has arrives as ``httpx.HTTPStatusError``
        rather than a result.  Those rows would otherwise be polled,
        fail, and be skipped on every sweep forever.
        """
        self.stuck.return_value = [
            _stuck(created_at=NOW - datetime.timedelta(days=200))
        ]
        self.poll.side_effect = httpx.HTTPStatusError(
            'Not Found',
            request=httpx.Request('GET', 'https://api.github.com/x'),
            response=httpx.Response(404),
        )
        summary = await self._sweep()
        assert summary is not None
        self.assertEqual(1, summary.expired)
        kwargs = self.append.await_args.kwargs
        self.assertEqual('failed', kwargs['status'])
        # The marker stays greppable and names why the remote could not
        # answer.
        self.assertEqual(
            f'{deployment_sweeper.EXPIRED_NOTE}: HTTPStatusError',
            kwargs['note'],
        )
        # Stamped with when it started, not when the sweep noticed.
        self.assertEqual(
            self.stuck.return_value[0].created_at, kwargs['timestamp']
        )

    async def test_young_vanished_run_is_left_for_the_next_sweep(
        self,
    ) -> None:
        self.poll.side_effect = httpx.HTTPStatusError(
            'Not Found',
            request=httpx.Request('GET', 'https://api.github.com/x'),
            response=httpx.Response(404),
        )
        summary = await self._sweep()
        assert summary is not None
        self.assertEqual(0, summary.expired)
        self.append.assert_not_awaited()

    async def test_missing_capability_still_aborts_the_project(self) -> None:
        """A resolution failure is not a per-item failure.

        It arrives as ``fastapi.HTTPException``, which only resolution
        raises -- so it must abort the project rather than expire one
        deployment, even though the status code matches a remote 404.
        """
        self.stuck.return_value = [
            _stuck(created_at=NOW - datetime.timedelta(days=200))
        ]
        self.poll.side_effect = fastapi.HTTPException(status_code=404)
        self.assertIsNone(await self._sweep())
        self.append.assert_not_awaited()

    async def test_recent_poll_failure_is_left_for_the_next_sweep(
        self,
    ) -> None:
        self.poll.side_effect = RuntimeError('gateway timeout')
        summary = await self._sweep()
        assert summary is not None
        self.assertEqual(0, summary.expired)
        self.append.assert_not_awaited()

    async def test_naive_now_does_not_raise(self) -> None:
        summary = await deployment_sweeper.sweep_project(
            mock.AsyncMock(),
            'p1',
            now=datetime.datetime(2026, 8, 18, 12),  # noqa: DTZ001
        )
        assert summary is not None
        self.assertEqual(1, summary.resolved)

    async def test_running_run_is_left_alone(self) -> None:
        self.poll.return_value = _run('in_progress')
        summary = await self._sweep()
        assert summary is not None
        self.assertEqual(0, summary.resolved)
        self.append.assert_not_awaited()

    async def test_run_still_unresolved_after_a_week_expires(self) -> None:
        self.poll.return_value = _run('in_progress')
        self.stuck.return_value = [
            _stuck(created_at=NOW - datetime.timedelta(days=8))
        ]
        summary = await self._sweep()
        assert summary is not None
        self.assertEqual(1, summary.expired)
        kwargs = self.append.await_args.kwargs
        self.assertEqual('failed', kwargs['status'])
        self.assertEqual(deployment_sweeper.EXPIRED_NOTE, kwargs['note'])

    async def test_advancing_status_is_recorded(self) -> None:
        self.poll.return_value = _run('in_progress')
        self.stuck.return_value = [_stuck(status='pending')]
        summary = await self._sweep()
        assert summary is not None
        self.assertEqual(1, summary.resolved)
        self.assertEqual(
            'in_progress', self.append.await_args.kwargs['status']
        )

    async def test_unattached_deployment_is_attached_to_its_release(
        self,
    ) -> None:
        self.stuck.return_value = [
            _stuck(release_id=None, release_tag='1.2.3')
        ]
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[{'id': 'rel-9'}])
        with mock.patch(
            'imbi.common.graph.parse_agtype', side_effect=lambda x: x
        ):
            summary = await self._sweep(db)
        assert summary is not None
        self.assertEqual(1, summary.attached)
        self.assertEqual('rel-9', self.attach.await_args.kwargs['release_id'])
        # Now that it has a release, the close-out goes through the
        # release path so a success still moves current_release.
        self.assertEqual('rel-9', self.append.await_args.kwargs['release_id'])

    async def test_unresolvable_release_writes_the_node_directly(
        self,
    ) -> None:
        self.stuck.return_value = [
            _stuck(release_id=None, release_tag='1.2.3')
        ]
        db = mock.AsyncMock()
        db.execute = mock.AsyncMock(return_value=[])
        summary = await self._sweep(db)
        assert summary is not None
        self.assertEqual(0, summary.attached)
        self.append.assert_not_awaited()
        self.assertEqual('success', self.upsert.await_args.kwargs['status'])

    async def test_project_without_a_deployment_plugin_is_skipped(
        self,
    ) -> None:
        self.poll.side_effect = fastapi.HTTPException(status_code=404)
        self.assertIsNone(await self._sweep())
        self.append.assert_not_awaited()

    async def test_a_poll_failure_does_not_stop_the_project(self) -> None:
        self.stuck.return_value = [_stuck(), _stuck(id='dep-2')]
        self.poll.side_effect = [RuntimeError('boom'), _run('failure')]
        summary = await self._sweep()
        assert summary is not None
        self.assertEqual(2, summary.examined)
        self.assertEqual(1, summary.resolved)
        self.assertEqual('failed', self.append.await_args.kwargs['status'])

    async def test_nothing_stuck_is_an_empty_summary(self) -> None:
        self.stuck.return_value = []
        summary = await self._sweep()
        self.assertEqual(deployment_sweeper.SweepSummary(), summary)
        self.poll.assert_not_awaited()

    async def test_only_deployments_past_the_stale_window_are_selected(
        self,
    ) -> None:
        await self._sweep()
        self.assertEqual(
            NOW - deployment_sweeper.STALE_AFTER,
            self.stuck.await_args.kwargs['cutoff'],
        )
