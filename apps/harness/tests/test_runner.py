"""The runner's lease fence and its one chain.

The SDK session and the user switches need the pod; the kind suite in
``isolation/`` covers them.
"""

import asyncio
import contextlib
import pathlib
import tempfile
import typing
import unittest
from unittest import mock

import respx

from imbi.harness import api, ipc, privilege, runner


class Fenced(BaseException):
    """Not an Exception, as os._exit is not: the heartbeat must not
    catch its own fence."""


def make_runner() -> runner.Runner:
    settings = runner.Settings(
        api_url='http://imbi.test',
        pool='general',
        instance='pod',
        model=None,
    )
    return runner.Runner(
        settings, ('id', 'secret'), pathlib.Path('/nonexistent')
    )


REAL_SLEEP = asyncio.sleep


class Clock:
    """Controlled time for the runner module: ``time.monotonic``,
    ``asyncio.sleep``, and ``asyncio.timeout``. A sleep moves the clock
    and yields once; a timeout only records its delay."""

    def __init__(self) -> None:
        self.now = 0.0
        self.delay = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.now += delay
        await REAL_SLEEP(0)

    @contextlib.asynccontextmanager
    async def timeout(self, delay: float) -> typing.AsyncIterator[None]:
        self.delay = delay
        yield

    async def black_hole(self, *_: typing.Any) -> None:
        """A request with no reply: it ends at its timeout."""
        self.now += self.delay
        raise TimeoutError

    async def until(self, at: float) -> None:
        while self.now < at:
            await REAL_SLEEP(0)


class _Asyncio:
    """The asyncio module, with the clock's sleep and timeout."""

    def __init__(self, clock: Clock) -> None:
        self.sleep = clock.sleep
        self.timeout = clock.timeout

    def __getattr__(self, name: str) -> typing.Any:
        return getattr(asyncio, name)


class HeartbeatTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.runner = make_runner()
        self.api = mock.AsyncMock(spec=api.Api)
        self.runner.api = self.api
        self.clock = Clock()
        for name, value in (
            ('_fence', mock.Mock(side_effect=Fenced)),
            ('time', mock.Mock(monotonic=self.clock.monotonic)),
            ('asyncio', _Asyncio(self.clock)),
        ):
            patcher = mock.patch.object(runner, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.fence = typing.cast('mock.Mock', runner._fence)

    async def test_fences_before_the_lease_expires(self) -> None:
        self.api.heartbeat.side_effect = self.clock.black_hole
        with self.assertRaises(Fenced):
            await self.runner.heartbeat(lease_seconds=3)
        # The margin is a third of the lease: fence at 2 s, not at 3 s.
        self.assertLess(self.clock.now, 2.5)
        self.assertIn('lease', self.fence.call_args.args[0])

    async def test_fences_when_the_runner_is_unknown(self) -> None:
        self.api.heartbeat.side_effect = api.Refused(
            401, 'invalid_runner_credential'
        )
        with self.assertRaises(Fenced):
            await self.runner.heartbeat(lease_seconds=3)
        self.assertIn('does not know', self.fence.call_args.args[0])

    async def test_unexpected_error_is_a_failed_renewal(self) -> None:
        # For example a decode error: it must not end the heartbeat
        # before the fence.
        self.api.heartbeat.side_effect = ValueError('bad body')
        with (
            self.assertLogs('imbi.harness.runner', 'WARNING') as logs,
            self.assertRaises(Fenced),
        ):
            await self.runner.heartbeat(lease_seconds=3)
        self.assertGreaterEqual(self.clock.now, 1.5)
        self.assertIn('lease', self.fence.call_args.args[0])
        self.assertNotIn('bad body', '\n'.join(logs.output))

    async def test_non_json_body_still_renews(self) -> None:
        # Api.heartbeat reads only the status; a 200 renews.
        self.mock = respx.mock(base_url='http://imbi.test')
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.mock.post('/harness/runners/r/heartbeat').respond(
            200, text='not json'
        )
        self.runner.api = api.Api('http://imbi.test')
        self.runner.runner_id = 'r'
        task = asyncio.create_task(self.runner.heartbeat(lease_seconds=3))
        await asyncio.wait_for(self.clock.until(3.5), 10)
        self.assertFalse(task.done())
        task.cancel()
        self.fence.assert_not_called()

    async def test_heartbeat_that_stops_fences(self) -> None:
        with mock.patch.object(
            self.runner, '_renew', side_effect=RuntimeError('bug')
        ):
            with self.assertRaises(Fenced):
                await self.runner.heartbeat(lease_seconds=3)
        self.assertIn('RuntimeError', self.fence.call_args.args[0])

    async def test_cancel_does_not_fence(self) -> None:
        self.api.heartbeat.return_value = None
        task = asyncio.create_task(self.runner.heartbeat(lease_seconds=3))
        await asyncio.sleep(0.1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.fence.assert_not_called()

    async def test_keeps_running_while_renewed(self) -> None:
        self.api.heartbeat.return_value = None
        task = asyncio.create_task(self.runner.heartbeat(lease_seconds=3))
        await asyncio.wait_for(self.clock.until(3.5), 10)
        self.assertFalse(task.done())
        task.cancel()
        self.fence.assert_not_called()
        self.assertGreaterEqual(self.api.heartbeat.await_count, 4)


class OneChainTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_serve_returns_after_the_claim_even_on_failure(self) -> None:
        subject = make_runner()
        calls = 0

        async def cycle() -> None:
            nonlocal calls
            calls += 1
            subject.claimed = True
            raise api.Refused(500, 'finish_failed')

        subject.cycle = cycle  # type: ignore[method-assign]
        subject.remove_old_workspaces = mock.Mock()  # type: ignore[method-assign]
        with mock.patch.object(pathlib.Path, 'exists', return_value=True):
            await asyncio.wait_for(subject.serve(), 2)
        self.assertEqual(calls, 1)

    async def test_end_chain_kills_and_removes_the_workspace(self) -> None:
        subject = make_runner()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        workspace = pathlib.Path(tmp.name) / 'chain'
        (workspace / 'home').mkdir(parents=True)
        (workspace / 'home' / 'file').write_text('x')
        with (
            mock.patch.object(privilege, 'kill_agent') as kill,
            mock.patch.object(
                privilege, 'effective', return_value=contextlib.nullcontext()
            ) as effective,
            mock.patch.object(ipc, 'call', mock.AsyncMock()) as call,
        ):
            await subject.end_chain(workspace)
        kill.assert_called_once_with()
        call.assert_awaited_once_with({'op': 'end_chain'})
        effective.assert_called_once_with(privilege.AGENT)
        self.assertFalse(workspace.exists())

    async def test_end_chain_without_executor(self) -> None:
        subject = make_runner()
        with (
            mock.patch.object(privilege, 'kill_agent'),
            mock.patch.object(
                privilege, 'effective', return_value=contextlib.nullcontext()
            ),
            mock.patch.object(
                ipc, 'call', mock.AsyncMock(side_effect=FileNotFoundError)
            ),
            self.assertLogs('imbi.harness.runner', 'WARNING'),
        ):
            await subject.end_chain(pathlib.Path('/nonexistent/chain'))


class CycleTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_runs_the_root_task_and_finishes(self) -> None:
        subject = make_runner()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        subject.credentials = pathlib.Path(tmp.name)
        subject.api = mock.AsyncMock(spec=api.Api)
        subject.api.register.return_value = {
            'runner_id': 'r',
            'runner_token': 'ihr_runner_token_0123456789',
            'executor_token': 'ihe_executor_token_0123456789',
            'lease_seconds': 30,
        }
        claim = {'chain_id': 'c', 'agent_token': 'iat_agent_token_0123456789'}
        subject.api.claim.side_effect = [None, claim]
        subject.heartbeat = mock.AsyncMock()  # type: ignore[method-assign]
        subject.end_chain = mock.AsyncMock()  # type: ignore[method-assign]
        with (
            mock.patch.object(ipc, 'call', mock.AsyncMock()) as call,
            mock.patch.object(runner.task, 'TaskRun') as task_run,
            mock.patch.object(runner.task.Layout, 'make') as make,
        ):
            task_run.return_value.run = mock.AsyncMock()
            await subject.cycle()
        call.assert_awaited_once_with(
            {'op': 'hello', 'executor_token': 'ihe_executor_token_0123456789'}
        )
        make.assert_called_once_with()
        args = task_run.call_args.args
        self.assertEqual(args[1], claim)
        self.assertEqual(args[2].root, runner.WORK / 'c')
        task_run.return_value.run.assert_awaited_once_with()
        subject.end_chain.assert_awaited_once_with(runner.WORK / 'c')
        subject.api.finish.assert_awaited_once_with(
            'r', 'ihr_runner_token_0123456789'
        )
        for value in (
            'ihr_runner_token_0123456789',
            'ihe_executor_token_0123456789',
            'iat_agent_token_0123456789',
            'secret',
        ):
            self.assertEqual(subject.redactor.text(value), '[REDACTED]')
        self.assertEqual(
            (subject.credentials / 'runner.token').read_text(),
            'ihr_runner_token_0123456789',
        )
