"""Tests for the agent usage endpoint (ADR 0020).

The usage rows go into the live ClickHouse that ``root:services`` boots,
in the shape that :func:`imbi.api.agent_tasks.log.usage_row` makes.
"""

import datetime
import decimal
import typing
import uuid

from apps.api.tests.endpoints import test_agent_task_log
from imbi.api.agent_tasks import log
from imbi.common import iggy

TODAY = datetime.datetime.now(datetime.UTC).replace(
    hour=12, minute=0, second=0, microsecond=0
)


class AgentUsageTests(test_agent_task_log.ClickHouseTestCase):
    async def publish(
        self,
        *,
        org: str | None = None,
        agent: str = 'agent-a',
        task: str = 'T-1',
        days_ago: int = 0,
        tokens_in: int | None = 1000,
        cost: str | None = '1.50',
        report_id: str | None = None,
    ) -> None:
        """Publish one usage report of ``task``."""
        org = org or self.org
        task_row = {
            'organization_id': org,
            'id': uuid.uuid5(uuid.NAMESPACE_URL, f'{org}/{task}'),
            'short_id': task,
            'agent_id': agent,
            'project_id': None,
        }
        ledger: dict[str, typing.Any] = {
            'session_id': None,
            'id': report_id or str(uuid.uuid4()),
            'model_id': 'opus',
            'recorded_at': TODAY - datetime.timedelta(days=days_ago),
            'tokens_in': tokens_in,
            'tokens_out': 100,
            'cache_read_tokens': 500,
            'cache_write_tokens': None,
            'input_cost_per_million': None,
            'output_cost_per_million': None,
            'cache_read_cost_per_million': None,
            'cache_write_cost_per_million': None,
            'cost': None if cost is None else decimal.Decimal(cost),
        }
        await iggy.publish_rows(
            log.USAGE_STREAM, log.TOPIC, [log.usage_row(task_row, ledger)]
        )

    async def get_usage(
        self, org: str | None = None, **params: typing.Any
    ) -> dict[str, typing.Any]:
        response = await self.client.get(
            f'/organizations/{org or self.org}/agent-usage/', params=params
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_totals_by_agent_and_day(self) -> None:
        duplicate = str(uuid.uuid4())
        await self.publish(report_id=duplicate)
        # The sweep can publish a row again; it counts one time.
        await self.publish(report_id=duplicate)
        await self.publish(task='T-2', tokens_in=None, cost=None)
        await self.publish(task='T-2', days_ago=1, cost='0.25')
        await self.publish(agent='agent-b', task='T-3', cost='4')
        # Out of the default range.
        await self.publish(task='T-4', days_ago=40)
        # Another organization.
        await self.publish(org=self.other_org, cost='99')

        usage = await self.get_usage()

        today = TODAY.date()
        self.assertEqual(usage['end'], today.isoformat())
        self.assertEqual(
            usage['start'], (today - datetime.timedelta(days=29)).isoformat()
        )
        by_agent = {row['agent_id']: row for row in usage['agents']}
        self.assertEqual(list(by_agent), ['agent-b', 'agent-a'])
        self.assertEqual(by_agent['agent-a']['tasks'], 2)
        # An unmeasured report adds no tokens and no cost.
        self.assertEqual(by_agent['agent-a']['tokens_in'], 2000)
        self.assertEqual(by_agent['agent-a']['tokens_out'], 300)
        self.assertEqual(by_agent['agent-a']['cache_read_tokens'], 1500)
        self.assertEqual(by_agent['agent-a']['cache_write_tokens'], 0)
        self.assertEqual(decimal.Decimal(by_agent['agent-a']['cost']), 1.75)
        self.assertEqual(by_agent['agent-b']['tasks'], 1)
        self.assertEqual(decimal.Decimal(by_agent['agent-b']['cost']), 4)

        days = [
            (row['day'], row['agent_id'], row['tasks'], row['cost'])
            for row in usage['days']
        ]
        yesterday = (today - datetime.timedelta(days=1)).isoformat()
        self.assertEqual(
            [(d, a, t, decimal.Decimal(c)) for d, a, t, c in days],
            [
                (yesterday, 'agent-a', 1, decimal.Decimal('0.25')),
                (today.isoformat(), 'agent-a', 2, decimal.Decimal('1.5')),
                (today.isoformat(), 'agent-b', 1, decimal.Decimal(4)),
            ],
        )

    async def test_range_and_agent_filters(self) -> None:
        await self.publish(days_ago=40)
        await self.publish(days_ago=35, task='T-2')
        await self.publish(agent='agent-b', days_ago=40, task='T-3')
        start = (TODAY - datetime.timedelta(days=40)).date().isoformat()
        end = (TODAY - datetime.timedelta(days=36)).date().isoformat()

        usage = await self.get_usage(start=start, end=end, agent_id='agent-a')

        self.assertEqual(usage['start'], start)
        self.assertEqual(usage['end'], end)
        self.assertEqual(
            [(row['agent_id'], row['tasks']) for row in usage['agents']],
            [('agent-a', 1)],
        )
        self.assertEqual([row['day'] for row in usage['days']], [start])

    async def test_month_to_date(self) -> None:
        await self.publish(cost='2')
        await self.publish(task='T-2', days_ago=TODAY.day, cost='50')

        usage = await self.get_usage()

        self.assertEqual(
            {k: decimal.Decimal(v) for k, v in usage['month_to_date'].items()},
            {'agent-a': 2},
        )

    async def test_other_organization_is_not_visible(self) -> None:
        await self.publish(org=self.other_org)

        usage = await self.get_usage()

        self.assertEqual(usage['agents'], [])
        self.assertEqual(usage['days'], [])
        self.assertEqual(usage['month_to_date'], {})

    async def test_not_a_member(self) -> None:
        response = await self.client.get(
            f'/organizations/{self.foreign_org}/agent-usage/'
        )
        self.assertEqual(response.status_code, 403, response.text)

    async def test_needs_agent_task_read(self) -> None:
        self.permissions.discard('agent_task:read')
        response = await self.client.get(
            f'/organizations/{self.org}/agent-usage/'
        )
        self.assertEqual(response.status_code, 403, response.text)

    async def test_bad_range(self) -> None:
        for params in (
            {'start': '2026-02-01', 'end': '2026-01-01'},
            {'start': '2024-01-01', 'end': '2026-01-01'},
        ):
            response = await self.client.get(
                f'/organizations/{self.org}/agent-usage/', params=params
            )
            self.assertEqual(response.status_code, 422, response.text)
