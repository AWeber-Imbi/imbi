"""
Interface for aggregating stats into Redis for single view of all metrics when
polling.

"""
import contextlib
import os
import socket
import time
import typing

import aioredis

DEFAULT_POOL_SIZE = 10


class Stats:
    """Class used for aggregating stats to be exposed to an external metric
    collector.

    """
    def __init__(self, client: aioredis.Redis):
        """Create a new instance of the Stats class"""
        self._client = client
        self._hostname = socket.gethostname()

    async def decr(self, tags: dict, value: int = 1) -> None:
        """Decrement a counter

        :param tags: The key tags to decrement
        :param value: The value to decrement by

        """
        await self._client.decrby(self._compose_key('c', tags), value)

    async def incr(self, tags: dict, value: int = 1) -> None:
        """Increment a counter

        :param tags: The key tags to increment
        :param value: The value to increment by

        """
        await self._client.incrby(self._compose_key('c', tags), value)

    async def add_duration(self, tags: dict, value: float) -> None:
        """Add a duration for the specified key

        :param tags: The key tags to record the timing for
        :param value: The value of the duration

        """
        await self._client.lpush(self._compose_key('d', tags), value)

    @contextlib.asynccontextmanager
    async def track_duration(self, tags: dict) -> typing.AsyncContextManager:
        """Context manager that sets a value with the duration of time that it
        takes to execute whatever it is wrapping.

        :param tags: The key tags to track the duration of

        """
        start_time = time.time()
        try:
            yield
        finally:
            await self.add_duration(tags, time.time() - start_time)

    async def counters(self,
                       all_hosts: bool = False,
                       flush: bool = False) -> typing.Dict[str, int]:
        """Return a dict of counters and their values

        :param all_hosts: Process counters for all hosts
        :param flush: Flush existing values

        """
        counters = {}
        keys = await self._client.keys(
            'c:*' if all_hosts else f'c:*hostname={self._hostname}*')
        if keys:
            values = await self._client.mget(*keys)
            for offset, key in enumerate(keys):
                counters[key[2:].decode('utf-8')] = int(values[offset])
            if flush:
                await self._client.delete(*keys)
        return counters

    async def durations(self,
                        all_hosts: bool = False,
                        flush: bool = False) \
            -> typing.Dict[str, typing.List[float]]:
        """Return a dict of durations and their values

        :param all_hosts: Process durations for all hosts
        :param flush: Flush existing values

        """
        durations = {}
        keys = await self._client.keys(
            'd:*' if all_hosts else f'd:*hostname={self._hostname}*')
        for key in keys:
            durations[key[2:].decode('utf-8')] = sorted(
                float(v) for v in await self._client.lrange(key, 0, -1))
            if flush:
                await self._client.delete(key)
        return durations

    def _compose_key(self, prefix: str, tags: dict) -> str:
        """Create the deterministically sorted compound key that is used
        to ensure we're always incrementing or adding to the same set for
        the same set of values.

        :param prefix: The key prefix
        :param tags: The key tags that will be used to compose the key

        """
        parts = [f'hostname={self._hostname}']
        for key, value in tags.items():
            parts.append(f'{key}={value}')
        return f'{prefix}:' + ':'.join(value for value in sorted(parts))


async def create(redis_url):
    """Create a new instance of the Stats class

    :param str redis_url: The Redis URL to use for stats
    :rtype: Stats


    """
    redis_client = await aioredis.create_pool(
        redis_url, maxsize=int(os.environ.get(
            'STATS_POOL_SIZE', DEFAULT_POOL_SIZE)))
    return Stats(redis_client)
