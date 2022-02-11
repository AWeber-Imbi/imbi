"""
Application Metrics

"""
import collections
import logging
import re
import socket
import typing

from . import base

LOGGER = logging.getLogger(__name__)
INF = float('inf')
TAGS = re.compile(r'(([\w_-]+)=([\w_\+\.-]+))')


class RequestHandler(base.RequestHandler):
    """Returns internal metrics in Prometheus line format"""
    BUCKETS = (.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5,
               5.0, 7.5, 10.0, INF)
    NAME = 'metrics'

    @staticmethod
    def _build_key_dict(key_in: str) -> dict:
        tags = {}
        for match in TAGS.finditer(key_in):
            tags[match.group(2)] = match.group(3)
        return tags

    def _build_output_key(self, key_in: str, suffix: str) -> str:
        tags = self._build_key_dict(key_in)
        key = tags.pop('key')
        tag_repr = ','.join(f'{k}="{v}"' for k, v in tags.items())
        return f'{key}_{suffix}{{{tag_repr}}}'

    async def get(self):
        """Tornado RequestHandler GET request endpoint for reporting status"""
        all_hosts = self.get_argument('all_hosts', 'false').lower() == 'true'
        flush = self.get_argument('flush', 'true').lower() == 'true'

        self.set_header('Content-Type', 'text/plain; version=0.0.4')
        self.write('# Prometheus line format\n')
        self.write(
            f'# Generated on {socket.gethostname()}, all_hosts={all_hosts},'
            f' flush={flush}\n\n')

        counters = await self.application.stats.counters(all_hosts, flush)
        chunks = {}
        for counter in sorted(counters.keys()):
            key = self._build_output_key(counter, 'total')
            chunk_key = key.split('{')[0]
            if chunk_key not in chunks:
                chunks[chunk_key] = []
            chunks[chunk_key].append(f'{key} {counters[counter]}\n')
        for key in chunks:
            self.write(f'# TYPE {key} counter\n')
            for item in chunks[key]:
                self.write(item)
            self.write('\n')

        timers = await self.application.stats.durations(all_hosts, flush)
        values: typing.Dict[str, typing.List[str]] = {}
        for timer in sorted(timers.keys()):
            chunk_key = self._build_output_key(timer, 'seconds').split('{')[0]
            if chunk_key not in values:
                values[chunk_key] = []
            buckets = collections.Counter()
            counts = collections.Counter()
            sums = collections.Counter()
            while timers[timer]:
                value = timers[timer].pop(0)
                counts[timer] += 1
                sums[timer] += value
                for bucket in self.BUCKETS:
                    if bucket not in buckets:
                        buckets[bucket] = 0
                    if value <= bucket:
                        buckets[bucket] += 1
            for bucket in self.BUCKETS:
                if bucket == INF:
                    continue
                key = self._build_output_key(
                    f'{timer}:le={bucket}', 'seconds_bucket')
                values[chunk_key].append(f'{key} {buckets[bucket]}\n')

            key = self._build_output_key(f'{timer}:le=Inf+', 'seconds_bucket')
            values[chunk_key].append(f'{key} {counts[timer]}\n')

            key = self._build_output_key(f'{timer}', 'seconds_count')
            values[chunk_key].append(f'{key} {counts[timer]}\n')
            key = self._build_output_key(f'{timer}', 'seconds_sum')
            values[chunk_key].append(f'{key} {sums[timer]}\n')

        for chunk_key in sorted(values):
            self.write(f'# TYPE {chunk_key} histogram\n')
            for metric in values[chunk_key]:
                self.write(metric)
            self.write('\n')

        postgres = await self.application.postgres_status()
        self.write(
            '# HELP postgres_pool_size The number of open connections '
            'in the pool\n')
        self.write('# TYPE postgres_pool_size gauge\n')
        self.write(
            f'postgres_pool_size{{host="{socket.gethostname()}"}} '
            f'{postgres["pool_size"]}\n\n')
        self.write(
            '# HELP postgres_pool_free The number of free connections '
            'in the pool\n')
        self.write('# TYPE postgres_pool_free gauge\n')
        self.write(
            f'postgres_pool_free{{host="{socket.gethostname()}"}} '
            f'{postgres["pool_free"]}\n\n')
