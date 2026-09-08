"""End-to-end check of the Iggy write path.

Publishes one ``events`` row the way the gateway will publish it and
reads it back out of ClickHouse, so the producer, the Iggy server, the
connectors runtime and the ClickHouse sink are all exercised together.
ADR 0019 §6 asks for exactly this, and it is the gate WP3 waits on: no
call site moves off the direct insert until this has been seen passing.

The stack comes from ``compose.ci.yaml`` via ``moon run root:services``,
which provisions the streams and then starts the connectors runtime.
Skipped when ``IGGY_URL`` is unset, which is what a checkout without
those services looks like.
"""

import asyncio
import datetime
import os
import typing
import unittest

from imbi.common import clickhouse, iggy, models

#: How long the sink is given to pick the message up. The poll interval
#: is 250 ms and the insert is one round trip, so this is slack for a
#: cold consumer group, not an expected wait.
TIMEOUT = 15.0
INTERVAL = 0.25


@unittest.skipUnless(
    os.environ.get('IGGY_URL'),
    'IGGY_URL is unset; run `moon run root:services` first',
)
class IggyToClickHouseTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await clickhouse.setup_schema()
        self.addAsyncCleanup(clickhouse.aclose)
        self.addAsyncCleanup(iggy.aclose)

    async def _await_row(self, event_id: str) -> dict[str, typing.Any]:
        """Poll for the row until the sink has written it."""
        deadline = asyncio.get_running_loop().time() + TIMEOUT
        while True:
            rows = await clickhouse.query(
                'SELECT id, project_id, recorded_at, type, integration, '
                'attributed_to, metadata, payload, version '
                'FROM events WHERE id = %(id)s',
                {'id': event_id},
            )
            if rows:
                return rows[0]
            if asyncio.get_running_loop().time() >= deadline:
                self.fail(
                    f'the sink did not write event {event_id} within '
                    f'{TIMEOUT:.0f}s; check `docker compose -f '
                    f'compose.ci.yaml logs iggy-connect`'
                )
            await asyncio.sleep(INTERVAL)

    async def test_published_event_reaches_clickhouse(self) -> None:
        recorded_at = datetime.datetime.now(datetime.UTC).replace(
            microsecond=0
        )
        event = models.Event(
            project_id='e2e-project',
            recorded_at=recorded_at,
            type='webhook',
            integration='github',
            attributed_to='e2e@example.com',
            metadata={'event_type': 'pull_request', 'handlers': []},
            payload={'action': 'opened', 'number': 42},
            version=0,
        )
        await iggy.publish(
            'events',
            'gateway',
            [event],
            headers={'producer': 'gateway', 'integration': 'github'},
        )
        row = await self._await_row(event.id)
        self.assertEqual(row['project_id'], event.project_id)
        self.assertEqual(row['type'], event.type)
        self.assertEqual(row['integration'], event.integration)
        self.assertEqual(row['attributed_to'], event.attributed_to)
        self.assertEqual(row['version'], event.version)
        self.assertEqual(clickhouse.as_utc(row['recorded_at']), recorded_at)
        self.assertEqual(row['metadata']['event_type'], 'pull_request')
        self.assertEqual(row['payload']['action'], 'opened')
