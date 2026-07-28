"""Trigger models and their fire-time arithmetic.

Every trigger answers one question: given an instant, when does this fire
next? The engine asks nothing else of them, which is what keeps the
scheduling engine replaceable (see ADR 0001).

All boundary datetimes are timezone-aware and UTC. Wall-clock reasoning
happens in the task's IANA timezone, so a ``0 2 * * *`` cron stays at 02:00
local across a daylight-saving transition rather than drifting by an hour.
"""

import calendar
import datetime
import secrets
import typing
import zoneinfo

import croniter
import pydantic

#: A cron expression carries either five fields (minute, hour, day-of-month,
#: month, day-of-week) or six, where croniter reads the sixth as *seconds* —
#: it trails the expression rather than leading it.
CRON_FIELD_COUNTS = (5, 6)

_MONTHS_PER_YEAR = 12


def _as_utc(value: datetime.datetime) -> datetime.datetime:
    """Return `value` as an aware UTC datetime."""
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.UTC)
    return value.astimezone(datetime.UTC)


class CronTrigger(pydantic.BaseModel):
    """Fire on a cron expression, evaluated in the task's timezone.

    Only the expression form is supported; discrete field arguments would
    be a second way to say the same thing.
    """

    kind: typing.Literal['cron'] = 'cron'
    expression: str
    jitter: int | None = None

    @pydantic.field_validator('expression')
    @classmethod
    def _validate_expression(cls, value: str) -> str:
        if len(value.split()) not in CRON_FIELD_COUNTS:
            raise ValueError(
                'cron expression must have 5 or 6 whitespace-separated fields'
            )
        if not croniter.croniter.is_valid(value):
            raise ValueError(f'invalid cron expression: {value}')
        return value

    @pydantic.field_validator('jitter')
    @classmethod
    def _validate_jitter(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError('jitter must not be negative')
        return value

    def next_fire_time(
        self, after: datetime.datetime, tz: zoneinfo.ZoneInfo
    ) -> datetime.datetime | None:
        """Return the first firing strictly after `after`."""
        local = _as_utc(after).astimezone(tz)
        cursor = croniter.croniter(self.expression, local)
        fires: datetime.datetime = cursor.get_next(datetime.datetime)
        result = _as_utc(fires)
        if self.jitter:
            result += datetime.timedelta(
                seconds=secrets.randbelow(self.jitter + 1)
            )
        return result


class IntervalTrigger(pydantic.BaseModel):
    """Fire on a fixed elapsed interval.

    The interval is absolute rather than calendar-based: an interval of one
    day is 24 hours, so across a daylight-saving transition the local time
    of the firing shifts. Use a calendar trigger when the wall-clock time
    matters.
    """

    kind: typing.Literal['interval'] = 'interval'
    seconds: int = 0
    minutes: int = 0
    hours: int = 0
    days: int = 0
    start_at: datetime.datetime | None = None
    end_at: datetime.datetime | None = None

    @pydantic.model_validator(mode='after')
    def _validate_interval(self) -> typing.Self:
        if self.interval <= datetime.timedelta(0):
            raise ValueError('interval must be greater than zero')
        if (
            self.start_at is not None
            and self.end_at is not None
            and self.end_at <= self.start_at
        ):
            raise ValueError('end_at must be after start_at')
        return self

    @property
    def interval(self) -> datetime.timedelta:
        return datetime.timedelta(
            days=self.days,
            hours=self.hours,
            minutes=self.minutes,
            seconds=self.seconds,
        )

    def next_fire_time(
        self,
        after: datetime.datetime,
        tz: zoneinfo.ZoneInfo,  # noqa: ARG002 - absolute interval, tz unused
    ) -> datetime.datetime | None:
        """Return the first firing strictly after `after`."""
        moment = _as_utc(after)
        interval = self.interval
        if self.start_at is None:
            fires = moment + interval
        else:
            start = _as_utc(self.start_at)
            if start > moment:
                fires = start
            else:
                elapsed = moment - start
                steps = elapsed // interval + 1
                fires = start + steps * interval
        if self.end_at is not None and fires > _as_utc(self.end_at):
            return None
        return fires


class CalendarTrigger(pydantic.BaseModel):
    """Fire at a wall-clock time on a calendar-based interval.

    Unlike an interval trigger this keeps ``at_time`` fixed in local time
    across daylight-saving transitions, because each candidate is built from
    a local date plus ``at_time`` and only then converted to UTC.

    The step is expressed either in ``months`` or in ``weeks``/``days``, not
    both — combining them makes the anchor semantics ambiguous for no
    practical gain.
    """

    kind: typing.Literal['calendar'] = 'calendar'
    days: int = 0
    weeks: int = 0
    months: int = 0
    at_time: datetime.time = datetime.time(0, 0)
    start_at: datetime.datetime | None = None
    end_at: datetime.datetime | None = None

    @pydantic.model_validator(mode='after')
    def _validate_step(self) -> typing.Self:
        if min(self.days, self.weeks, self.months) < 0:
            raise ValueError('calendar step components must not be negative')
        if self.months and (self.days or self.weeks):
            raise ValueError('specify either months or weeks/days, not both')
        if not (self.months or self.weeks or self.days):
            raise ValueError('a calendar step is required')
        if self.at_time.tzinfo is not None:
            raise ValueError('at_time must not carry a timezone')
        return self

    def next_fire_time(
        self, after: datetime.datetime, tz: zoneinfo.ZoneInfo
    ) -> datetime.datetime | None:
        """Return the first firing strictly after `after`.

        ``start_at`` is a lower bound as well as the step anchor, matching
        `IntervalTrigger`. Anchoring on its date alone would let the first
        firing land at ``at_time`` on that date — earlier in the day than
        ``start_at`` itself.
        """
        floor = _as_utc(after)
        anchor_at = floor
        if self.start_at is not None:
            anchor_at = _as_utc(self.start_at)
            floor = max(floor, anchor_at)
        local = floor.astimezone(tz)
        candidate = self._seek(anchor_at.astimezone(tz).date(), local, tz)
        if candidate is None:
            return None
        fires = _as_utc(candidate)
        if self.end_at is not None and fires > _as_utc(self.end_at):
            return None
        return fires

    def _seek(
        self,
        anchor: datetime.date,
        local: datetime.datetime,
        tz: zoneinfo.ZoneInfo,
    ) -> datetime.datetime | None:
        """Walk forward from `anchor` to the first firing after `local`."""
        # `_skip_ahead` floors, and candidate dates strictly increase, so the
        # first firing after `local` is at `step` or the one after it.
        step = self._skip_ahead(anchor, local.date())
        for offset in (step, step + 1):
            candidate = datetime.datetime.combine(
                self._date_at(anchor, offset), self.at_time, tzinfo=tz
            )
            if candidate > local:
                return candidate
        return None

    def _skip_ahead(self, anchor: datetime.date, target: datetime.date) -> int:
        """Return a step count at or before the first candidate.

        Avoids iterating one step at a time from a distant anchor. Always
        undershoots, so `_seek` still decides the boundary.
        """
        if target <= anchor:
            return 0
        if self.months:
            elapsed = (target.year - anchor.year) * _MONTHS_PER_YEAR + (
                target.month - anchor.month
            )
            return max(0, elapsed // self.months)
        return max(0, (target - anchor).days // (self.weeks * 7 + self.days))

    def _date_at(self, anchor: datetime.date, offset: int) -> datetime.date:
        """Return the date `offset` steps after `anchor`."""
        if not self.months:
            return anchor + datetime.timedelta(
                days=offset * (self.weeks * 7 + self.days)
            )
        total = (anchor.month - 1) + offset * self.months
        year = anchor.year + total // _MONTHS_PER_YEAR
        month = total % _MONTHS_PER_YEAR + 1
        # Clamp to the month's length so a day-31 anchor still fires in
        # February rather than being skipped.
        last_day = calendar.monthrange(year, month)[1]
        return datetime.date(year, month, min(anchor.day, last_day))


class DateTrigger(pydantic.BaseModel):
    """Fire exactly once, at `run_at`."""

    kind: typing.Literal['date'] = 'date'
    run_at: datetime.datetime

    def next_fire_time(
        self,
        after: datetime.datetime,
        tz: zoneinfo.ZoneInfo,  # noqa: ARG002 - absolute instant, tz unused
    ) -> datetime.datetime | None:
        """Return `run_at` if it is still ahead, otherwise nothing."""
        fires = _as_utc(self.run_at)
        if fires > _as_utc(after):
            return fires
        return None


Trigger = typing.Annotated[
    CronTrigger | IntervalTrigger | CalendarTrigger | DateTrigger,
    pydantic.Field(discriminator='kind'),
]

#: Composite AndTrigger / OrTrigger are deliberately deferred; nothing on the
#: platform needs them yet and they change the claim query's shape.
__all__ = [
    'CalendarTrigger',
    'CronTrigger',
    'DateTrigger',
    'IntervalTrigger',
    'Trigger',
]
