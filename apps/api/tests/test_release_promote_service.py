"""Tests for the release-promote watcher (poll loop, status, outcomes)."""

from __future__ import annotations

import typing
import unittest
from unittest import mock

from imbi.api.release_promote import service
from imbi.common.plugins import base as plugin_base


def _job(**overrides: typing.Any) -> service.WatchJob:
    fields: dict[str, typing.Any] = {
        'org_slug': 'octo',
        'project_id': 'p1',
        'release_id': 'rel1',
        'tag': '1.2.3',
        'committish': 'abc1234',
        'to_environment': 'staging',
        'from_environment': 'testing',
        'run_id': '4242',
        'run_url': 'https://ghe/run/4242',
        'requested_by': 'daves@aweber.com',
        'deploy': True,
    }
    fields.update(overrides)
    return service.WatchJob(**fields)


def _run(status: str, run_url: str | None = None) -> plugin_base.ArtifactRun:
    return plugin_base.ArtifactRun(
        run_id='4242',
        run_url=run_url,
        status=typing.cast(typing.Any, status),
    )


def _deployment(
    status: str = 'queued', run_id: str = '99'
) -> plugin_base.DeploymentRun:
    return plugin_base.DeploymentRun(
        run_id=run_id,
        run_url='https://ghe/deployments/99',
        status=typing.cast(typing.Any, status),
    )


class _Harness:
    """Patches the endpoint helpers ``run_watch`` delegates to.

    *statuses* drives the build poll; *rollout* drives the rollout poll
    that follows it.  ``complete_promote_build`` hands back a Deployment
    by default, because that is what a deployable promote does.
    """

    def __init__(self, *statuses: str, rollout: tuple[str, ...] = ()) -> None:
        self.poll = mock.AsyncMock(
            side_effect=[_run(status) for status in statuses]
        )
        self.complete = mock.AsyncMock(return_value=_deployment())
        self.poll_rollout = mock.AsyncMock(
            side_effect=[_deployment(status) for status in rollout]
        )
        self.fail = mock.AsyncMock()
        self.append = mock.AsyncMock(return_value=(mock.Mock(), 'appended'))
        self.set_status = mock.AsyncMock()
        self.slept: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)

    def __enter__(self) -> _Harness:
        self._patches = [
            mock.patch(
                'imbi.api.endpoints.project_deployments.poll_artifact_run',
                self.poll,
            ),
            mock.patch(
                'imbi.api.endpoints.project_deployments.poll_promote_rollout',
                self.poll_rollout,
            ),
            mock.patch(
                'imbi.api.endpoints.project_deployments'
                '.complete_promote_build',
                self.complete,
            ),
            mock.patch(
                'imbi.api.endpoints.project_deployments.fail_promote_build',
                self.fail,
            ),
            mock.patch(
                'imbi.api.endpoints.releases.append_deployment_event',
                self.append,
            ),
            mock.patch.object(service, 'set_status', self.set_status),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        for patch in reversed(self._patches):
            patch.stop()

    def closed(self) -> list[tuple[str, str | None]]:
        """``(status, note)`` of every deployment close-out written."""
        return [
            (call.kwargs['status'], call.kwargs.get('note'))
            for call in self.append.await_args_list
        ]

    def states(self) -> list[str]:
        return [
            call.kwargs['status'] for call in self.set_status.await_args_list
        ]


class RunWatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_completes_and_deploys(self) -> None:
        db = mock.AsyncMock()
        with _Harness('success', rollout=('success',)) as harness:
            state = await service.run_watch(
                db, _job(), sleep=harness.sleep, valkey_client='vk'
            )
        self.assertEqual('success', state)
        harness.complete.assert_awaited_once()
        harness.fail.assert_not_awaited()
        kwargs = harness.complete.await_args.kwargs
        self.assertTrue(kwargs['deploy'])
        self.assertEqual('1.2.3', kwargs['tag'])
        self.assertEqual('daves@aweber.com', kwargs['requested_by'])
        self.assertEqual('vk', kwargs['valkey_client'])
        # ``deploying`` spans creating the Deployment *and* waiting on the
        # rollout; ``success`` lands only once that rollout is green.
        self.assertEqual(
            ['deploying', 'deploying', 'success'], harness.states()
        )

    async def test_success_waits_for_the_rollout(self) -> None:
        """``success`` must not land when the Deployment is merely created.

        Regression guard: reporting success at the handover told the UI
        the promote had shipped while the rollout had not yet started,
        which tore down the progress toast and refetched the release
        views before there was anything new to read.
        """
        db = mock.AsyncMock()
        with _Harness(
            'success', rollout=('in_progress', 'success')
        ) as harness:
            state = await service.run_watch(db, _job(), sleep=harness.sleep)
        self.assertEqual('success', state)
        self.assertEqual(2, harness.poll_rollout.await_count)
        self.assertEqual(
            '99', harness.poll_rollout.await_args.kwargs['run_id']
        )
        # Still ``deploying`` on every write until the rollout settles.
        self.assertEqual(
            ['deploying', 'deploying', 'deploying', 'success'],
            harness.states(),
        )

    async def test_releasable_only_skips_the_deploy_phase(self) -> None:
        db = mock.AsyncMock()
        with _Harness('success') as harness:
            # A build-only promote creates no Deployment to watch.
            harness.complete.return_value = None
            state = await service.run_watch(
                db, _job(deploy=False, to_environment=''), sleep=harness.sleep
            )
        self.assertEqual('success', state)
        self.assertFalse(harness.complete.await_args.kwargs['deploy'])
        harness.poll_rollout.assert_not_awaited()
        # Never advertises a deploy phase it isn't going to run.
        self.assertNotIn('deploying', harness.states())

    async def test_deployment_without_a_run_id_settles_immediately(
        self,
    ) -> None:
        """Nothing to poll is not a failure; the Deployment still exists."""
        db = mock.AsyncMock()
        with _Harness('success') as harness:
            harness.complete.return_value = _deployment(run_id='')
            state = await service.run_watch(db, _job(), sleep=harness.sleep)
        self.assertEqual('success', state)
        harness.poll_rollout.assert_not_awaited()

    async def test_polls_until_terminal(self) -> None:
        db = mock.AsyncMock()
        with _Harness(
            'queued', 'in_progress', 'success', rollout=('success',)
        ) as harness:
            state = await service.run_watch(db, _job(), sleep=harness.sleep)
        self.assertEqual('success', state)
        self.assertEqual(3, harness.poll.await_count)
        # Build intervals back off and are capped; the trailing sleep is
        # the rollout loop's, which has its own ceiling.
        build_sleeps = harness.slept[:2]
        self.assertEqual(2, len(build_sleeps))
        self.assertLessEqual(build_sleeps[0], build_sleeps[1])
        self.assertLessEqual(max(build_sleeps), service.POLL_MAX_SECONDS)
        self.assertIn('building', harness.states())

    async def test_rollout_backs_off_and_is_capped(self) -> None:
        db = mock.AsyncMock()
        with _Harness(
            'success', rollout=('queued', 'in_progress', 'success')
        ) as harness:
            await service.run_watch(db, _job(), sleep=harness.sleep)
        # No build sleeps (one poll, terminal), so every sleep is a
        # rollout sleep.
        self.assertEqual(3, len(harness.slept))
        self.assertEqual(service.DEPLOY_POLL_INITIAL_SECONDS, harness.slept[0])
        self.assertLessEqual(harness.slept[0], harness.slept[1])
        self.assertLessEqual(
            max(harness.slept), service.DEPLOY_POLL_MAX_SECONDS
        )

    async def test_failed_rollout_does_not_block_the_release(self) -> None:
        """A green build with a red rollout leaves the tag shippable."""
        db = mock.AsyncMock()
        with _Harness('success', rollout=('failure',)) as harness:
            state = await service.run_watch(db, _job(), sleep=harness.sleep)
        self.assertEqual('deploy_failed', state)
        # ``fail_promote_build`` is what blocks a tag — never called here.
        harness.fail.assert_not_awaited()
        self.assertEqual('deploy_failed', harness.states()[-1])
        error = harness.set_status.await_args_list[-1].kwargs['error']
        self.assertIn('staging', error)
        self.assertIn('not blocked', error)

    async def test_cancelled_rollout_does_not_block_the_release(self) -> None:
        db = mock.AsyncMock()
        with _Harness('success', rollout=('cancelled',)) as harness:
            state = await service.run_watch(db, _job(), sleep=harness.sleep)
        self.assertEqual('deploy_failed', state)
        harness.fail.assert_not_awaited()

    async def test_rollout_timeout_does_not_block_the_release(self) -> None:
        db = mock.AsyncMock()
        with _Harness('success', rollout=('in_progress',)) as harness:
            state = await service.run_watch(
                db,
                _job(),
                sleep=harness.sleep,
                deploy_timeout_seconds=0,
            )
        self.assertEqual('deploy_failed', state)
        harness.fail.assert_not_awaited()
        error = harness.set_status.await_args_list[-1].kwargs['error']
        self.assertIn('did not finish', error)

    async def test_lost_rollout_reports_failed_not_deploying(self) -> None:
        """A poll that blows up must not strand the status on ``deploying``.

        The UI polls until it sees a terminal state, so leaving
        ``deploying`` behind would spin forever against a promote nothing
        is driving.
        """
        db = mock.AsyncMock()
        with _Harness('success') as harness:
            harness.poll_rollout.side_effect = RuntimeError('ghe exploded')
            state = await service.run_watch(db, _job(), sleep=harness.sleep)
        self.assertEqual('failed', state)
        harness.fail.assert_not_awaited()
        self.assertEqual('failed', harness.states()[-1])
        error = harness.set_status.await_args_list[-1].kwargs['error']
        self.assertIn('ghe exploded', error)

    async def test_failed_build_blocks_the_release(self) -> None:
        db = mock.AsyncMock()
        with _Harness('failure') as harness:
            state = await service.run_watch(db, _job(), sleep=harness.sleep)
        self.assertEqual('build_failed', state)
        harness.complete.assert_not_awaited()
        harness.fail.assert_awaited_once()
        kwargs = harness.fail.await_args.kwargs
        self.assertEqual('1.2.3', kwargs['tag'])
        self.assertIn('failure', kwargs['reason'])
        self.assertEqual(['build_failed'], harness.states())

    async def test_cancelled_build_blocks_the_release(self) -> None:
        db = mock.AsyncMock()
        with _Harness('cancelled') as harness:
            state = await service.run_watch(db, _job(), sleep=harness.sleep)
        self.assertEqual('build_failed', state)
        harness.fail.assert_awaited_once()
        self.assertIn('cancelled', harness.fail.await_args.kwargs['reason'])

    async def test_timeout_blocks_the_release(self) -> None:
        db = mock.AsyncMock()
        with _Harness('in_progress') as harness:
            state = await service.run_watch(
                db,
                _job(),
                sleep=harness.sleep,
                timeout_seconds=0,
            )
        self.assertEqual('build_failed', state)
        harness.complete.assert_not_awaited()
        harness.fail.assert_awaited_once()
        self.assertIn(
            'did not finish', harness.fail.await_args.kwargs['reason']
        )

    async def test_missing_run_id_does_not_block(self) -> None:
        """A dispatch with no run id is unwatchable, not a failed build.

        The build may well be green, so blocking the tag would wedge a
        release that is fine.  Report it and leave the tag shippable.
        """
        db = mock.AsyncMock()
        with _Harness() as harness:
            state = await service.run_watch(
                db, _job(run_id=''), sleep=harness.sleep
            )
        self.assertEqual('failed', state)
        harness.poll.assert_not_awaited()
        harness.fail.assert_not_awaited()
        harness.complete.assert_not_awaited()
        self.assertEqual(['failed'], harness.states())

    async def test_completion_failure_does_not_block(self) -> None:
        """The build succeeded; only Imbi's follow-through broke."""
        db = mock.AsyncMock()
        with _Harness('success') as harness:
            harness.complete.side_effect = RuntimeError('graph exploded')
            state = await service.run_watch(db, _job(), sleep=harness.sleep)
        self.assertEqual('failed', state)
        harness.fail.assert_not_awaited()
        self.assertEqual(['deploying', 'failed'], harness.states())
        error = harness.set_status.await_args_list[-1].kwargs['error']
        self.assertIn('graph exploded', error)

    async def test_run_url_from_the_poll_is_carried_forward(self) -> None:
        db = mock.AsyncMock()
        with _Harness('success', rollout=('success',)) as harness:
            harness.poll.side_effect = [
                _run('success', run_url='https://ghe/run/late')
            ]
            await service.run_watch(db, _job(run_url=''), sleep=harness.sleep)
        self.assertEqual(
            'https://ghe/run/late',
            harness.complete.await_args.kwargs['run_url'],
        )
        # The rollout phase keeps pointing at the build run rather than
        # swapping in the Deployment's own URL.
        self.assertEqual(
            'https://ghe/run/late',
            harness.set_status.await_args_list[-1].kwargs['artifact_run_url'],
        )


class RolloutCloseOutTests(unittest.IsolatedAsyncioTestCase):
    """The watcher closes the deployment it opened.

    Before this the watcher wrote its answer only to
    ``Project.promote_status``, so a failed rollout left its deployment
    ``in_progress`` forever and a successful one depended on a webhook
    correlating -- the missing close-out that grew the stuck backlog.
    """

    async def test_successful_rollout_is_recorded(self) -> None:
        db = mock.AsyncMock()
        with _Harness('success', rollout=('success',)) as harness:
            await service.run_watch(db, _job(), sleep=harness.sleep)
        self.assertEqual([('success', 'rollout succeeded')], harness.closed())
        kwargs = harness.append.await_args.kwargs
        self.assertEqual('rel1', kwargs['release_id'])
        self.assertEqual('staging', kwargs['env_slug'])
        # The rollout's own run id, not the build's.
        self.assertEqual('99', kwargs['external_run_id'])
        self.assertEqual('promote-watcher', kwargs['source'])

    async def test_failed_rollout_is_recorded(self) -> None:
        db = mock.AsyncMock()
        with _Harness('success', rollout=('failure',)) as harness:
            state = await service.run_watch(db, _job(), sleep=harness.sleep)
        self.assertEqual('deploy_failed', state)
        self.assertEqual([('failed', 'rollout failure')], harness.closed())

    async def test_rollout_timeout_is_recorded(self) -> None:
        db = mock.AsyncMock()
        with _Harness(
            'success', rollout=('in_progress', 'in_progress')
        ) as harness:
            state = await service.run_watch(
                db,
                _job(),
                sleep=harness.sleep,
                deploy_timeout_seconds=0,
            )
        self.assertEqual('deploy_failed', state)
        status, note = harness.closed()[0]
        self.assertEqual('failed', status)
        assert note is not None
        self.assertIn('did not finish', note)

    async def test_write_failure_does_not_change_the_outcome(self) -> None:
        db = mock.AsyncMock()
        with _Harness('success', rollout=('success',)) as harness:
            harness.append.side_effect = RuntimeError('graph down')
            state = await service.run_watch(db, _job(), sleep=harness.sleep)
        self.assertEqual('success', state)


class MarkAbandonedTests(unittest.IsolatedAsyncioTestCase):
    """A dead-lettered promote closes the deployment it opened.

    Nothing is going to watch it now, so leaving it in flight would add
    to the stuck backlog the queue's own docstring warns about.
    """

    async def test_closes_the_in_flight_deployment(self) -> None:
        from imbi.api.release_promote import queue

        db = mock.AsyncMock()
        with (
            mock.patch(
                'imbi.common.deployments.close_in_flight',
                mock.AsyncMock(return_value=['dep-1']),
            ) as close,
            mock.patch.object(queue, 'set_status', mock.AsyncMock()),
        ):
            await queue._mark_abandoned(db, _job())
        kwargs = close.await_args.kwargs
        self.assertEqual('rel1', kwargs['release_id'])
        self.assertEqual('staging', kwargs['env_slug'])
        self.assertEqual('failed', kwargs['status'])
        self.assertEqual('promote-queue', kwargs['source'])

    async def test_a_close_failure_still_reports_the_status(self) -> None:
        from imbi.api.release_promote import queue

        db = mock.AsyncMock()
        with (
            mock.patch(
                'imbi.common.deployments.close_in_flight',
                mock.AsyncMock(side_effect=RuntimeError('graph down')),
            ),
            mock.patch.object(
                queue, 'set_status', mock.AsyncMock()
            ) as set_status,
        ):
            await queue._mark_abandoned(db, _job())
        set_status.assert_awaited_once()


class ReadStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_project_is_idle(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        status = await service.read_status(db, 'p1')
        self.assertEqual('idle', status.status)

    async def test_unrecognized_status_falls_back_to_idle(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = [{'status': 'wat', 'tag': '1.0.0'}]
        status = await service.read_status(db, 'p1')
        self.assertEqual('idle', status.status)
