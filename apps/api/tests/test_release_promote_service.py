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


class _Harness:
    """Patches the endpoint helpers ``run_watch`` delegates to."""

    def __init__(self, *statuses: str) -> None:
        self.poll = mock.AsyncMock(
            side_effect=[_run(status) for status in statuses]
        )
        self.complete = mock.AsyncMock()
        self.fail = mock.AsyncMock()
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
                'imbi.api.endpoints.project_deployments'
                '.complete_promote_build',
                self.complete,
            ),
            mock.patch(
                'imbi.api.endpoints.project_deployments.fail_promote_build',
                self.fail,
            ),
            mock.patch.object(service, 'set_status', self.set_status),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        for patch in reversed(self._patches):
            patch.stop()

    def states(self) -> list[str]:
        return [
            call.kwargs['status'] for call in self.set_status.await_args_list
        ]


class RunWatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_completes_and_deploys(self) -> None:
        db = mock.AsyncMock()
        with _Harness('success') as harness:
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
        # ``deploying`` before the work, ``success`` after it.
        self.assertEqual(['deploying', 'success'], harness.states())

    async def test_releasable_only_skips_the_deploy_phase(self) -> None:
        db = mock.AsyncMock()
        with _Harness('success') as harness:
            state = await service.run_watch(
                db, _job(deploy=False, to_environment=''), sleep=harness.sleep
            )
        self.assertEqual('success', state)
        self.assertFalse(harness.complete.await_args.kwargs['deploy'])
        # Never advertises a deploy phase it isn't going to run.
        self.assertNotIn('deploying', harness.states())

    async def test_polls_until_terminal(self) -> None:
        db = mock.AsyncMock()
        with _Harness('queued', 'in_progress', 'success') as harness:
            state = await service.run_watch(db, _job(), sleep=harness.sleep)
        self.assertEqual('success', state)
        self.assertEqual(3, harness.poll.await_count)
        # Interval backs off between polls and is capped.
        self.assertEqual(2, len(harness.slept))
        self.assertLessEqual(harness.slept[0], harness.slept[1])
        self.assertLessEqual(max(harness.slept), service.POLL_MAX_SECONDS)
        self.assertIn('building', harness.states())

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
        with _Harness('success') as harness:
            harness.poll.side_effect = [
                _run('success', run_url='https://ghe/run/late')
            ]
            await service.run_watch(db, _job(run_url=''), sleep=harness.sleep)
        self.assertEqual(
            'https://ghe/run/late',
            harness.complete.await_args.kwargs['run_url'],
        )


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
