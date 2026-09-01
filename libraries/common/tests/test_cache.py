"""Unit tests for the shared bounded-cache primitives."""

import asyncio
import unittest
from unittest import mock

from imbi.common import cache


class LRUCacheTestCase(unittest.TestCase):
    def test_round_trip_and_miss(self) -> None:
        entries: cache.LRUCache[str, int] = cache.LRUCache(4)
        self.assertIsNone(entries.get('absent'))
        self.assertNotIn('absent', entries)
        entries.set('a', 1)
        self.assertEqual(1, entries.get('a'))
        self.assertIn('a', entries)
        self.assertEqual(1, len(entries))

    def test_rejects_a_useless_bound(self) -> None:
        with self.assertRaises(ValueError):
            cache.LRUCache[str, int](0)

    def test_evicts_least_recently_used(self) -> None:
        entries: cache.LRUCache[str, int] = cache.LRUCache(2)
        entries.set('a', 1)
        entries.set('b', 2)
        # Reading 'a' makes 'b' the eviction candidate.
        self.assertEqual(1, entries.get('a'))
        entries.set('c', 3)
        self.assertEqual(2, len(entries))
        self.assertIn('a', entries)
        self.assertNotIn('b', entries)
        self.assertIn('c', entries)

    def test_overwrite_does_not_grow_the_cache(self) -> None:
        entries: cache.LRUCache[str, int] = cache.LRUCache(2)
        entries.set('a', 1)
        entries.set('a', 2)
        self.assertEqual(1, len(entries))
        self.assertEqual(2, entries.get('a'))

    def test_instance_ttl_expires_entries(self) -> None:
        entries: cache.LRUCache[str, int] = cache.LRUCache(4, ttl=60)
        with mock.patch.object(cache.time, 'monotonic', return_value=1000.0):
            entries.set('a', 1)
        with mock.patch.object(cache.time, 'monotonic', return_value=1059.0):
            self.assertEqual(1, entries.get('a'))
            self.assertIn('a', entries)
        with mock.patch.object(cache.time, 'monotonic', return_value=1061.0):
            self.assertIsNone(entries.get('a'))
            self.assertNotIn('a', entries)
        # The expired entry is reaped by the lookup that found it stale.
        self.assertEqual(0, len(entries))

    def test_per_call_expires_at_overrides_the_ttl(self) -> None:
        entries: cache.LRUCache[str, int] = cache.LRUCache(4, ttl=60)
        with mock.patch.object(cache.time, 'monotonic', return_value=1000.0):
            entries.set('short', 1, expires_at=1010.0)
            entries.set('long', 2, expires_at=9999.0)
        with mock.patch.object(cache.time, 'monotonic', return_value=1030.0):
            self.assertIsNone(entries.get('short'))
            self.assertEqual(2, entries.get('long'))

    def test_no_ttl_never_expires(self) -> None:
        entries: cache.LRUCache[str, int] = cache.LRUCache(4)
        with mock.patch.object(cache.time, 'monotonic', return_value=1000.0):
            entries.set('a', 1)
        with mock.patch.object(cache.time, 'monotonic', return_value=1e9):
            self.assertEqual(1, entries.get('a'))

    def test_pop_removes_and_returns(self) -> None:
        entries: cache.LRUCache[str, int] = cache.LRUCache(4)
        entries.set('a', 1)
        self.assertEqual(1, entries.pop('a'))
        self.assertIsNone(entries.pop('a'))
        self.assertEqual(0, len(entries))

    def test_pop_reports_an_expired_entry_as_a_miss(self) -> None:
        entries: cache.LRUCache[str, int] = cache.LRUCache(4, ttl=60)
        with mock.patch.object(cache.time, 'monotonic', return_value=1000.0):
            entries.set('a', 1)
        with mock.patch.object(cache.time, 'monotonic', return_value=1100.0):
            self.assertIsNone(entries.pop('a'))
        self.assertEqual(0, len(entries))

    def test_clear(self) -> None:
        entries: cache.LRUCache[str, int] = cache.LRUCache(4)
        entries.set('a', 1)
        entries.set('b', 2)
        entries.clear()
        self.assertEqual(0, len(entries))
        self.assertIsNone(entries.get('a'))


class KeyedLockTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_same_key_runs_one_at_a_time(self) -> None:
        locks: cache.KeyedLock[str] = cache.KeyedLock()
        in_flight = 0
        peak = 0

        async def worker() -> None:
            nonlocal in_flight, peak
            async with locks('k'):
                in_flight += 1
                peak = max(peak, in_flight)
                await asyncio.sleep(0)
                in_flight -= 1

        await asyncio.gather(*(worker() for _ in range(5)))
        self.assertEqual(1, peak)

    async def test_cold_key_produces_once(self) -> None:
        locks: cache.KeyedLock[str] = cache.KeyedLock()
        entries: cache.LRUCache[str, str] = cache.LRUCache(4)
        produce = mock.AsyncMock(return_value='value')

        async def resolve() -> str:
            if (hit := entries.get('k')) is not None:
                return hit
            async with locks('k'):
                if (hit := entries.get('k')) is not None:
                    return hit
                value: str = await produce()
                entries.set('k', value)
                return value

        results = await asyncio.gather(*(resolve() for _ in range(8)))
        self.assertEqual(['value'] * 8, results)
        produce.assert_awaited_once()

    async def test_distinct_keys_do_not_block(self) -> None:
        locks: cache.KeyedLock[str] = cache.KeyedLock()
        started = asyncio.Event()

        async def holder() -> None:
            async with locks('a'):
                started.set()
                await asyncio.sleep(0.05)

        async def other() -> str:
            await started.wait()
            async with locks('b'):
                return 'ran'

        holding = asyncio.create_task(holder())
        # Would time out if 'b' waited behind 'a'.
        self.assertEqual('ran', await asyncio.wait_for(other(), timeout=0.5))
        await holding

    async def test_locks_are_released_when_idle(self) -> None:
        locks: cache.KeyedLock[str] = cache.KeyedLock()
        async with locks('k'):
            self.assertEqual(1, len(locks))
        self.assertEqual(0, len(locks))

    async def test_lock_released_on_error(self) -> None:
        locks: cache.KeyedLock[str] = cache.KeyedLock()
        with self.assertRaises(RuntimeError):
            async with locks('k'):
                raise RuntimeError('boom')
        self.assertEqual(0, len(locks))
        async with locks('k'):
            pass
