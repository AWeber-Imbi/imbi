"""Agent usage endpoints (ADR 0020).

Token use and cost of agent tasks, from the ``agent_usage`` table in
ClickHouse. ClickHouse is analytics only: the budget authority is the
Postgres ledger. A task counts as one run of its agent when it has a
usage report in the range.

Like the task routes, every route needs the caller to be a member of
the organization (``MEMBER_OF``).
"""

import asyncio
import datetime
import decimal
import typing

import fastapi
import pydantic

from imbi.api.auth import organizations, permissions
from imbi.common import clickhouse

#: The longest range that one request can ask for, in days.
MAX_RANGE_DAYS = 366

#: The range when the request gives no start, in days.
DEFAULT_RANGE_DAYS = 30


class AgentUsageTotals(pydantic.BaseModel):
    agent_id: str
    #: Tasks with a usage report in the range.
    tasks: int
    #: Input tokens. Cache reads and writes are not included.
    tokens_in: int
    tokens_out: int
    cache_read_tokens: int
    cache_write_tokens: int
    #: USD. A report with no price adds nothing.
    cost: decimal.Decimal


class AgentUsageDay(AgentUsageTotals):
    day: datetime.date


class AgentUsage(pydantic.BaseModel):
    start: datetime.date
    end: datetime.date
    #: One row for each day and agent with usage, by day.
    days: list[AgentUsageDay]
    #: One row for each agent with usage in the range, by cost.
    agents: list[AgentUsageTotals]
    #: USD this UTC calendar month, by agent id, for the advisory
    #: monthly cost cap. It does not depend on ``start`` and ``end``.
    month_to_date: dict[str, decimal.Decimal]


# FINAL, so that a row the sweep published again counts one time.
_FROM = """
FROM imbi.agent_usage FINAL
WHERE organization_id = {organization_id:String}
  AND recorded_at >= {since:DateTime64(6)}
  AND recorded_at < {until:DateTime64(6)}
  AND ({agent_id:String} = '' OR agent_id = {agent_id:String})
"""

_TOTALS = """
       uniqExact(task_id) AS tasks,
       ifNull(sum(tokens_in), 0) AS tokens_in,
       ifNull(sum(tokens_out), 0) AS tokens_out,
       ifNull(sum(cache_read_tokens), 0) AS cache_read_tokens,
       ifNull(sum(cache_write_tokens), 0) AS cache_write_tokens,
       ifNull(sum(cost), 0) AS cost
"""

_DAYS_QUERY = f"""
SELECT toDate(recorded_at) AS day, agent_id, {_TOTALS} {_FROM}
GROUP BY day, agent_id
ORDER BY day, agent_id
"""

_AGENTS_QUERY = f"""
SELECT agent_id, {_TOTALS} {_FROM}
GROUP BY agent_id
ORDER BY cost DESC, agent_id
"""

_MONTH_QUERY = f"""
SELECT agent_id, ifNull(sum(cost), 0) AS cost {_FROM}
GROUP BY agent_id
"""


def _midnight(day: datetime.date) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time.min, datetime.UTC)


agent_usage_router = fastapi.APIRouter(
    tags=['Agent Usage'],
    dependencies=[fastapi.Depends(organizations.member_org_id)],
)


@agent_usage_router.get('/', response_model=AgentUsage)
async def get_agent_usage(
    org_id: organizations.MemberOrgId,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('agent_task:read')),
    ],
    start: datetime.date | None = None,
    end: datetime.date | None = None,
    agent_id: str | None = None,
) -> AgentUsage:
    """Return token use and cost by day and by agent.

    ``start`` and ``end`` are UTC days and are both in the range. The
    default range is the 30 days that end today. ``agent_id`` keeps
    the usage of one agent.

    Raises:
        403: The caller is not a member of the org.
        404: No such organization.
        422: ``start`` is after ``end``, or the range is too long.

    """
    today = datetime.datetime.now(datetime.UTC).date()
    end = end or today
    start = start or end - datetime.timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if start > end:
        raise fastapi.HTTPException(
            status_code=422, detail='start is after end'
        )
    if (end - start).days >= MAX_RANGE_DAYS:
        raise fastapi.HTTPException(
            status_code=422,
            detail=f'The range is more than {MAX_RANGE_DAYS} days',
        )
    params: dict[str, typing.Any] = {
        'organization_id': org_id,
        'agent_id': agent_id or '',
        'since': _midnight(start),
        'until': _midnight(end + datetime.timedelta(days=1)),
    }
    month = {
        **params,
        'since': _midnight(today.replace(day=1)),
        'until': _midnight(today + datetime.timedelta(days=1)),
    }
    days, agents, month_rows = await asyncio.gather(
        clickhouse.query(_DAYS_QUERY, params),
        clickhouse.query(_AGENTS_QUERY, params),
        clickhouse.query(_MONTH_QUERY, month),
    )
    return AgentUsage(
        start=start,
        end=end,
        days=[AgentUsageDay.model_validate(row) for row in days],
        agents=[AgentUsageTotals.model_validate(row) for row in agents],
        month_to_date={row['agent_id']: row['cost'] for row in month_rows},
    )
