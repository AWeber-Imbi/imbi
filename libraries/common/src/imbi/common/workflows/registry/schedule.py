"""Schedule trigger: the scheduler starts a run on a cron schedule."""

import datetime
import typing
import zoneinfo

import pydantic

from imbi.common.workflows import step_type


def _check_timezone(value: str) -> str:
    try:
        zoneinfo.ZoneInfo(value)
    except (ValueError, zoneinfo.ZoneInfoNotFoundError) as e:
        raise ValueError(f'Unknown time zone {value!r}') from e
    return value


class Params(pydantic.BaseModel):
    # ponytail: the cron syntax is checked by the scheduler when W5
    # binds the trigger; imbi-common has no cron parser.
    cron: str = pydantic.Field(min_length=1)
    timezone: str = 'UTC'

    _timezone = pydantic.field_validator('timezone')(_check_timezone)


class Output(pydantic.BaseModel):
    fired_at: datetime.datetime


def required_permissions(_params: dict[str, typing.Any]) -> set[str]:
    """imbi-workflows makes a scheduler task for this trigger. The
    activator must be able to make that task.
    """
    return {'scheduled_task:create'}


STEP = step_type.StepType(
    type='schedule',
    category='trigger',
    label='Schedule',
    description='Starts a run on a cron schedule.',
    params=Params,
    output=Output,
    sample_output={'fired_at': '2026-01-01T09:00:00Z'},
    trigger=True,
    required_permissions=required_permissions,
)
