"""A 1 MiB task event through Iggy and iggy-connect into ClickHouse.

Harness plan spike 4: the ``turn`` and ``tool_call`` payload limit goes
to 1 MiB (ADR 0022), so the real sink must carry a message of that
size. iggy-connect does not run on the development Mac, so CI runs
this. Skipped when ``IGGY_URL`` is unset.
"""

import asyncio
import datetime
import os
import unittest
import uuid

from imbi.api.agent_tasks import log
from imbi.common import clickhouse, iggy
from imbi.common.clickhouse import client as clickhouse_client
from imbi.common.iggy import client as iggy_client

#: Slack for a cold consumer group and a large insert.
TIMEOUT = 30.0
INTERVAL = 0.5
MIB = 1024 * 1024


@unittest.skipUnless(
    os.environ.get('IGGY_URL'),
    'IGGY_URL is unset; run `moon run root:services` first',
)
class LargeTaskEventTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Both clients bind to the loop that opened them, and each test
        # has its own loop, so this test takes its own clients (the
        # pattern of test_agent_task_log.ClickHouseTestCase).
        previous = (
            clickhouse_client.Clickhouse._instance,
            iggy_client.Iggy._instance,
        )
        clickhouse_client.Clickhouse._instance = None
        iggy_client.Iggy._instance = None

        async def restore() -> None:
            await clickhouse.aclose()
            await iggy.aclose()
            (
                clickhouse_client.Clickhouse._instance,
                iggy_client.Iggy._instance,
            ) = previous

        self.addAsyncCleanup(restore)
        await clickhouse.initialize()
        await clickhouse.setup_schema()

    async def test_one_mib_event_reaches_clickhouse(self) -> None:
        task_id = uuid.uuid4()
        task = {
            'organization_id': 'e2e-org',
            'id': task_id,
            'short_id': 'T-1',
            'agent_id': 'e2e-agent',
            'agent_version': 1,
            'project_id': None,
        }
        # The payload JSON is 1 MiB: the new inline limit.
        result = 'x' * (MIB - len('{"result":""}'))
        event = {
            'seq': 1,
            'event_id': uuid.uuid4(),
            'type': 'tool_call',
            'schema_version': 1,
            'actor_kind': 'agent',
            'actor_id': 'e2e-agent',
            'channel': 'harness',
            'session_id': None,
            'at': datetime.datetime.now(datetime.UTC).replace(microsecond=0),
            'payload': {'result': result},
        }
        row = log.event_row(task, event)
        self.assertEqual(len(row['payload']), MIB)
        await iggy.publish_rows(log.EVENTS_STREAM, log.TOPIC, [row])

        deadline = asyncio.get_running_loop().time() + TIMEOUT
        while True:
            rows = await clickhouse.query(
                'SELECT length(payload) AS size FROM agent_task_events '
                'WHERE task_id = %(task_id)s',
                {'task_id': str(task_id)},
            )
            if rows:
                break
            if asyncio.get_running_loop().time() >= deadline:
                self.fail(
                    f'the sink did not write the 1 MiB event within '
                    f'{TIMEOUT:.0f}s; check `docker compose -f '
                    f'compose.ci.yaml --profile connect logs iggy-connect`'
                )
            await asyncio.sleep(INTERVAL)
        self.assertEqual(rows[0]['size'], MIB)
