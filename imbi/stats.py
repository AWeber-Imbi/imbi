"""
Interface for aggregating stats into Redis for single view of all metrics when
polling.

"""
import contextlib
import logging
import os
import time

import aioredis

from imbi import timestamp

LOGGER = logging.getLogger(__name__)

DEFAULT_POOL_SIZE = 10


class Stats:
    """Class used for aggregating stats to be exposed to an external metric
    collector.

    """
    def __init__(self, client: aioredis.Redis):
        """Create a new instance of the Stats class"""
        self._client = client

    async def decr(self, key, value=1):
        """Decrement a counter

        :param str key: The key to decrement
        :param int value: The value to decrement by

        """
        await self._client.decrby('c:{}'.format(key), value)

    async def incr(self, key, value=1):
        """Increment a counter

        :param str key: The key to increment
        :param int value: The value to increment by

        """
        await self._client.incrby('c:{}'.format(key), value)

    async def add_duration(self, key, value):
        """Add a duration for the specified key

        :param str key: The value name
        :param float value: The value

        """
        await self._client.lpush(
            'd:{}'.format(key), '{},{}'.format(
                timestamp.isoformat(), value))

    @contextlib.asynccontextmanager
    async def track_duration(self, key):
        """Context manager that sets a value with the duration of time that it
        takes to execute whatever it is wrapping.

        :param str key: The timing name

        """
        start_time = time.time()
        try:
            yield
        finally:
            await self.add_duration(key, time.time() - start_time)

    async def counters(self, flush=False):
        """Return a dict of counters and their values

        :param bool flush: Flush existing values
        :rtype: dict

        """
        counters = {}
        keys = await self._client.keys('c:*')
        LOGGER.debug('Counters: %r', keys)
        if keys:
            values = await self._client.mget(*keys)
            for offset, key in enumerate(keys):
                counters[key[2:].decode('utf-8')] = int(values[offset])
            if flush:
                self._client.delete(*keys)
        return counters

    async def durations(self, flush=False):
        """Return a dict of durations and their values

        :param bool flush: Flush existing values
        :rtype: dict

        """
        durations = {}
        keys = await self._client.keys('d:*')
        LOGGER.debug('Durations: %r', keys)
        for key in keys:
            values = await self._client.lrange(key, 0, -1)
            values = [v.decode('utf-8') for v in values]
            durations[key[2:].decode('utf-8')] = \
                [(r.split(',')[0], float(r.split(',')[1])) for r in values]
            if flush:
                await self._client.delete(key)
        return durations


async def create(redis_url):
    """Create a new instance of the Stats class

    :param str redis_url: The Redis URL to use for stats
    :rtype: Stats


    """
    redis_client = await aioredis.create_pool(
        redis_url, maxsize=int(os.environ.get(
            'STATS_POOL_SIZE', DEFAULT_POOL_SIZE)))
    return Stats(redis_client)
