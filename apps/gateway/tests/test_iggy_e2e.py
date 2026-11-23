"""End-to-end check of the Iggy write path.

Publishes one ``events`` row the way the gateway will publish it and
reads it back out of ClickHouse, so the producer, the Iggy server, the
connectors runtime and the ClickHouse sink are all exercised together.
ADR 0019 §6 asks for exactly this. The second case drives the gateway's
real ``DeliveryRecorder`` over the same path, both phases unmocked.

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

import nanoid

from imbi.common import clickhouse, iggy, models
from imbi.gateway import notifications

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


@unittest.skipUnless(
    os.environ.get('IGGY_URL'),
    'IGGY_URL is unset; run `moon run root:services` first',
)
class DeliveryRecorderTestCase(unittest.IsolatedAsyncioTestCase):
    """Drive the gateway's real recorder over the whole write path.

    Both phases go through :class:`DeliveryRecorder` with nothing
    mocked, so this covers the two publishes the notification endpoint
    makes, the sink, and the ``ReplacingMergeTree`` collapse of the
    version 0 / version 1 pair.
    """

    async def asyncSetUp(self) -> None:
        await clickhouse.setup_schema()
        self.addAsyncCleanup(clickhouse.aclose)
        self.addAsyncCleanup(iggy.aclose)
        self.project_id = f'e2e-recorder-{nanoid.generate()[:12]}'
        self.webhook_id = f'e2e-webhook-{nanoid.generate()[:12]}'

    async def _await_disposition(self) -> None:
        """Poll until the phase-2 row has been written.

        Only the version-1 row is waited on, and the version-0 row may
        never be visible: both phases usually reach the sink inside one
        batch, and ClickHouse's ``optimize_on_insert`` collapses a
        ``ReplacingMergeTree`` block as it is written, so the pair
        arrives already collapsed to the winner. Two separate batches
        leave both rows until a merge, which is why the assertions
        below read the table with ``FINAL``.
        """
        deadline = asyncio.get_running_loop().time() + TIMEOUT
        while True:
            rows = await clickhouse.query(
                'SELECT max(version) AS version FROM events '
                'WHERE project_id = %(pid)s',
                {'pid': self.project_id},
            )
            if rows and rows[0]['version'] == 1:
                return
            if asyncio.get_running_loop().time() >= deadline:
                self.fail(
                    f'the sink did not write the phase-2 row for project '
                    f'{self.project_id} within {TIMEOUT:.0f}s; check '
                    f'`docker compose -f compose.ci.yaml --profile connect '
                    f'logs iggy-connect`'
                )
            await asyncio.sleep(INTERVAL)

    async def test_recorded_delivery_reaches_clickhouse(self) -> None:
        recorder = notifications.DeliveryRecorder()
        outcome = notifications.HandlerOutcome(
            handler='stub#do_thing', status='succeeded', duration_ms=7
        )
        # Both publishes swallow their failures, the way the endpoint
        # needs them to, so a broken write path shows up here as an
        # ERROR log rather than as a raise.
        with self.assertNoLogs('imbi.gateway.notifications', level='ERROR'):
            await recorder.record_received(
                [{'project_id': self.project_id}],
                integration_slug='github',
                user_id='e2e@example.com',
                event_type='pull_request',
                metadata={
                    'webhook_id': self.webhook_id,
                    'headers': {'x-github-event': 'pull_request'},
                },
                payload={'action': 'opened', 'number': 42},
            )
            recorder.outcomes_for(self.project_id).append(outcome)
            await recorder.record_dispositions()

        await self._await_disposition()

        rows = await clickhouse.query(
            'SELECT id, project_id, type, integration, attributed_to, '
            'metadata, payload, version FROM events FINAL '
            'WHERE project_id = %(pid)s',
            {'pid': self.project_id},
        )
        self.assertEqual(1, len(rows))
        row = rows[0]
        # version 1 wins the collapse, so the disposition is what the
        # activity feed reads.
        self.assertEqual(1, row['version'])
        self.assertEqual('webhook', row['type'])
        self.assertEqual('github', row['integration'])
        self.assertEqual('e2e@example.com', row['attributed_to'])
        self.assertEqual(self.webhook_id, row['metadata']['webhook_id'])
        self.assertEqual('pull_request', row['metadata']['event_type'])
        self.assertEqual('opened', row['payload']['action'])
        self.assertEqual(
            [outcome.model_dump(exclude_none=True)],
            row['metadata']['handlers'],
        )
