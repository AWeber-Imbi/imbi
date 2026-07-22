import asyncio

from imbi.slackbot import inflight
from tests.slackbot import helpers


class InflightTests(helpers.TestCase):
    def setUp(self) -> None:
        super().setUp()
        inflight.reset()

    def tearDown(self) -> None:
        inflight.reset()
        super().tearDown()

    async def test_track_increments_and_decrements(self) -> None:
        self.assertEqual(0, inflight._active)
        async with inflight.track():
            self.assertEqual(1, inflight._active)
        self.assertEqual(0, inflight._active)

    async def test_track_decrements_on_exception(self) -> None:
        with self.assertRaises(RuntimeError):
            async with inflight.track():
                self.assertEqual(1, inflight._active)
                raise RuntimeError('boom')
        self.assertEqual(0, inflight._active)

    async def test_track_toggles_drain(self) -> None:
        async with inflight.track():
            self.assertFalse(inflight._get_drain().is_set())
        self.assertTrue(inflight._get_drain().is_set())

    async def test_multiple_concurrent_tracks(self) -> None:
        barrier = asyncio.Event()

        async def worker() -> None:
            async with inflight.track():
                await barrier.wait()

        t1 = asyncio.create_task(worker())
        t2 = asyncio.create_task(worker())
        await asyncio.sleep(0)
        self.assertEqual(2, inflight._active)
        self.assertFalse(inflight._get_drain().is_set())
        barrier.set()
        await asyncio.gather(t1, t2)
        self.assertEqual(0, inflight._active)
        self.assertTrue(inflight._get_drain().is_set())

    async def test_wait_for_drain_returns_when_idle(self) -> None:
        await inflight.wait_for_drain()

    async def test_wait_for_drain_waits_for_completion(self) -> None:
        order: list[str] = []

        async def slow_work() -> None:
            async with inflight.track():
                await asyncio.sleep(0.05)
                order.append('work')

        async def drain() -> None:
            await inflight.wait_for_drain()
            order.append('drain')

        work = asyncio.create_task(slow_work())
        await asyncio.sleep(0)
        waiter = asyncio.create_task(drain())
        await asyncio.gather(work, waiter)
        self.assertEqual(['work', 'drain'], order)

    async def test_wait_for_drain_times_out(self) -> None:
        original = inflight.SHUTDOWN_TIMEOUT
        inflight.SHUTDOWN_TIMEOUT = 0.05  # type: ignore[assignment]
        try:
            async with inflight.track():
                await inflight.wait_for_drain()
                self.assertEqual(1, inflight._active)
        finally:
            inflight.SHUTDOWN_TIMEOUT = original
