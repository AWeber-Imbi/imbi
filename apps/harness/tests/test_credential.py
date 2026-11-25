"""The renewal of a setup secret (WIF plan 4.6 and 4.7)."""

import asyncio
import contextlib
import datetime
import types
import typing
import unittest
from unittest import mock

import httpx

from imbi.harness import credential, proxy

ERRORS = (httpx.HTTPError, ValueError)


def expiring(value: str, seconds: float) -> proxy.Credential:
    return proxy.Credential(
        value,
        datetime.datetime.now(datetime.UTC)
        + datetime.timedelta(seconds=seconds),
        bearer=True,
    )


class Clock:
    """Stands in for ``asyncio.sleep`` in :mod:`credential`: records
    each wait and returns at once, until ``limit`` waits; then it waits
    for ever, so the renewal stops where the test looks at it."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.sleeps: list[float] = []
        self.real = asyncio.sleep

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if len(self.sleeps) >= self.limit:
            await asyncio.Event().wait()
        await self.real(0)

    async def reached(self) -> None:
        for _ in range(1000):
            if len(self.sleeps) >= self.limit:
                return
            await self.real(0)
        raise AssertionError(f'only {self.sleeps} waits')


class RefresherTestCase(unittest.IsolatedAsyncioTestCase):
    def refresher(self, *results: typing.Any) -> credential.Refresher:
        self.fetch = mock.AsyncMock(side_effect=list(results))
        made = credential.Refresher(self.fetch, 'Test key', 'T-1', ERRORS)
        self.addAsyncCleanup(self.finish, made)
        return made

    async def finish(self, made: credential.Refresher) -> None:
        made.stop()
        if made.task is not None:
            with contextlib.suppress(BaseException):
                await made.task

    async def renewing(self, made: credential.Refresher, limit: int) -> Clock:
        """Start ``made`` and run its renewal until ``limit`` waits."""
        clock = Clock(limit)
        patcher = mock.patch.object(
            credential, 'asyncio', wraps=asyncio, sleep=clock.sleep
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        await made.start()
        await clock.reached()
        return clock

    async def test_a_static_secret_is_fetched_once(self) -> None:
        made = self.refresher(proxy.Credential('static'))
        await made.start()
        await made.renew()
        await made.renew('static')
        self.assertEqual(made.credential.value, 'static')
        self.fetch.assert_awaited_once()

    async def first_wait(
        self, jitter: typing.Callable[[float, float], float]
    ) -> float:
        """The wait before the first renewal of a secret that expires in
        600 seconds, with the clock frozen and ``jitter`` choosing from
        its range."""
        now = datetime.datetime.now(datetime.UTC)
        made = self.refresher(
            proxy.Credential(
                't1', now + datetime.timedelta(seconds=600), bearer=True
            ),
            expiring('t2', 600),
        )
        frozen = types.SimpleNamespace(
            UTC=datetime.UTC,
            datetime=types.SimpleNamespace(now=mock.Mock(return_value=now)),
        )
        with mock.patch.multiple(
            credential,
            datetime=frozen,
            random=types.SimpleNamespace(uniform=jitter),
        ):
            clock = await self.renewing(made, 2)
        self.assertEqual(made.credential.value, 't2')
        return clock.sleeps[0]

    async def test_a_secret_is_renewed_before_it_expires(self) -> None:
        self.assertEqual(await self.first_wait(min), 480.0)

    async def test_the_jitter_is_at_most_half_of_the_lead(self) -> None:
        self.assertEqual(await self.first_wait(max), 420.0)

    async def test_a_failed_renewal_is_retried_and_logged(self) -> None:
        made = self.refresher(
            expiring('t1', 0),
            httpx.ConnectError('down'),
            expiring('t2', 600),
        )
        with self.assertLogs('imbi.harness.credential', 'WARNING') as logs:
            clock = await self.renewing(made, 3)
        self.assertEqual(clock.sleeps[:2], [0.0, 1.0])
        self.assertEqual(made.credential.value, 't2')
        self.assertIn('Test key renewal of T-1 failed: down', logs.output[0])

    async def test_the_minimum_wait_after_a_renewal_to_an_expired_secret(
        self,
    ) -> None:
        made = self.refresher(
            expiring('t1', 0), ValueError('partial reply'), expiring('t2', 0)
        )
        with self.assertLogs('imbi.harness.credential', 'WARNING'):
            clock = await self.renewing(made, 3)
        self.assertEqual(clock.sleeps, [0.0, 1.0, credential.RENEW_MIN])

    async def test_the_minimum_wait_after_a_renewal_with_the_same_expiry(
        self,
    ) -> None:
        first = expiring('t1', 0)
        made = self.refresher(first, first._replace(value='t2'))
        clock = await self.renewing(made, 2)
        self.assertEqual(clock.sleeps, [0.0, credential.RENEW_MIN])
        self.assertEqual(self.fetch.await_count, 2)

    async def test_an_error_outside_the_retry_set_ends_the_renewal(
        self,
    ) -> None:
        made = self.refresher(expiring('t1', 0), RuntimeError('bug'))
        clock = Clock(2)
        with mock.patch.object(
            credential, 'asyncio', wraps=asyncio, sleep=clock.sleep
        ):
            await made.start()
            for _ in range(20):
                await asyncio.sleep(0)
        # One renewal, and no wait for a retry.
        self.assertEqual(clock.sleeps, [0.0])
        self.assertEqual(self.fetch.await_count, 2)
        self.assertEqual(made.credential.value, 't1')

    async def test_concurrent_renewals_fetch_once(self) -> None:
        made = self.refresher(expiring('t1', 600), expiring('t2', 600))
        made.credential = await self.fetch()
        await asyncio.gather(made.renew('t1'), made.renew('t1'))
        self.assertEqual(made.credential.value, 't2')
        self.assertEqual(self.fetch.await_count, 2)

    async def test_a_renewal_of_a_replaced_value_does_nothing(self) -> None:
        made = self.refresher(expiring('t2', 600))
        made.credential = expiring('t1', 600)
        await made.renew('t0')
        self.assertEqual(made.credential.value, 't1')
        self.fetch.assert_not_awaited()
