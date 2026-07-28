import datetime
import unittest
import zoneinfo

import pydantic

from imbi.scheduler import triggers

UTC = zoneinfo.ZoneInfo('UTC')
NYC = zoneinfo.ZoneInfo('America/New_York')

# 2026-03-08 02:00 local: EST (UTC-5) becomes EDT (UTC-4).
SPRING_FORWARD = datetime.datetime(2026, 3, 8, tzinfo=NYC)
# 2026-11-01 02:00 local: EDT becomes EST.
FALL_BACK = datetime.datetime(2026, 11, 1, tzinfo=NYC)


def utc(*args: int) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=datetime.UTC)


class CronTriggerTests(unittest.TestCase):
    def test_next_fire_time_is_strictly_after(self) -> None:
        trigger = triggers.CronTrigger(expression='0 6 * * *')
        # Standing exactly on a firing yields the following one, so a task
        # that fires at 06:00 cannot re-fire at 06:00.
        self.assertEqual(
            utc(2026, 7, 29, 6),
            trigger.next_fire_time(utc(2026, 7, 28, 6), UTC),
        )

    def test_next_fire_time_same_day(self) -> None:
        trigger = triggers.CronTrigger(expression='30 6 * * *')
        self.assertEqual(
            utc(2026, 7, 28, 6, 30),
            trigger.next_fire_time(utc(2026, 7, 28, 5), UTC),
        )

    def test_six_field_expression_reads_seconds_last(self) -> None:
        # croniter's sixth field is seconds and trails the expression, so
        # this is 06:00:30 daily rather than 00:30 on the 6th.
        trigger = triggers.CronTrigger(expression='0 6 * * * 30')
        self.assertEqual(
            utc(2026, 7, 28, 6, 0, 30),
            trigger.next_fire_time(utc(2026, 7, 28, 5), UTC),
        )

    def test_evaluated_in_task_timezone(self) -> None:
        trigger = triggers.CronTrigger(expression='0 12 * * *')
        # 12:00 EDT is 16:00 UTC.
        self.assertEqual(
            utc(2026, 7, 28, 16),
            trigger.next_fire_time(utc(2026, 7, 28, 10), NYC),
        )

    def test_wall_clock_survives_spring_forward(self) -> None:
        trigger = triggers.CronTrigger(expression='0 12 * * *')
        before = trigger.next_fire_time(
            SPRING_FORWARD - datetime.timedelta(days=1), NYC
        )
        assert before is not None
        after = trigger.next_fire_time(before, NYC)
        assert after is not None
        # Local noon both days, but the UTC offset moved by an hour.
        self.assertEqual(12, before.astimezone(NYC).hour)
        self.assertEqual(12, after.astimezone(NYC).hour)
        self.assertEqual(17, before.hour)
        self.assertEqual(16, after.hour)

    def test_wall_clock_survives_fall_back(self) -> None:
        trigger = triggers.CronTrigger(expression='0 12 * * *')
        before = trigger.next_fire_time(
            FALL_BACK - datetime.timedelta(days=1), NYC
        )
        assert before is not None
        after = trigger.next_fire_time(before, NYC)
        assert after is not None
        self.assertEqual(12, before.astimezone(NYC).hour)
        self.assertEqual(12, after.astimezone(NYC).hour)
        self.assertEqual(16, before.hour)
        self.assertEqual(17, after.hour)

    def test_jitter_stays_within_bounds(self) -> None:
        trigger = triggers.CronTrigger(expression='0 6 * * *', jitter=30)
        base = utc(2026, 7, 29, 6)
        for _ in range(25):
            fires = trigger.next_fire_time(utc(2026, 7, 28, 7), UTC)
            assert fires is not None
            self.assertGreaterEqual(fires, base)
            self.assertLessEqual(fires, base + datetime.timedelta(seconds=30))

    def test_naive_input_is_treated_as_utc(self) -> None:
        trigger = triggers.CronTrigger(expression='0 6 * * *')
        naive = datetime.datetime(2026, 7, 28, 5)  # noqa: DTZ001
        self.assertEqual(
            utc(2026, 7, 28, 6), trigger.next_fire_time(naive, UTC)
        )

    def test_rejects_wrong_field_count(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            triggers.CronTrigger(expression='0 6 * *')

    def test_rejects_invalid_expression(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            triggers.CronTrigger(expression='0 99 * * *')

    def test_rejects_negative_jitter(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            triggers.CronTrigger(expression='0 6 * * *', jitter=-1)


class IntervalTriggerTests(unittest.TestCase):
    def test_without_start_anchors_on_now(self) -> None:
        trigger = triggers.IntervalTrigger(minutes=15)
        self.assertEqual(
            utc(2026, 7, 28, 6, 15),
            trigger.next_fire_time(utc(2026, 7, 28, 6), UTC),
        )

    def test_future_start_is_the_first_firing(self) -> None:
        trigger = triggers.IntervalTrigger(
            hours=1, start_at=utc(2026, 7, 28, 9)
        )
        self.assertEqual(
            utc(2026, 7, 28, 9),
            trigger.next_fire_time(utc(2026, 7, 28, 6), UTC),
        )

    def test_steps_from_the_anchor_not_from_now(self) -> None:
        trigger = triggers.IntervalTrigger(
            hours=1, start_at=utc(2026, 7, 28, 6, 30)
        )
        # 06:30 + 4h = 10:30, the first step strictly after 09:45.
        self.assertEqual(
            utc(2026, 7, 28, 10, 30),
            trigger.next_fire_time(utc(2026, 7, 28, 9, 45), UTC),
        )

    def test_exact_boundary_advances(self) -> None:
        trigger = triggers.IntervalTrigger(
            hours=1, start_at=utc(2026, 7, 28, 6)
        )
        self.assertEqual(
            utc(2026, 7, 28, 8),
            trigger.next_fire_time(utc(2026, 7, 28, 7), UTC),
        )

    def test_end_at_stops_the_series(self) -> None:
        trigger = triggers.IntervalTrigger(
            hours=1,
            start_at=utc(2026, 7, 28, 6),
            end_at=utc(2026, 7, 28, 8),
        )
        self.assertIsNone(trigger.next_fire_time(utc(2026, 7, 28, 8), UTC))

    def test_combined_components(self) -> None:
        trigger = triggers.IntervalTrigger(days=1, hours=2, minutes=3)
        self.assertEqual(
            datetime.timedelta(days=1, hours=2, minutes=3), trigger.interval
        )

    def test_interval_is_absolute_across_dst(self) -> None:
        trigger = triggers.IntervalTrigger(
            days=1, start_at=SPRING_FORWARD - datetime.timedelta(days=1)
        )
        fires = trigger.next_fire_time(SPRING_FORWARD, NYC)
        assert fires is not None
        # The anchor is midnight local. 24 elapsed hours across a 23-hour
        # local day lands at 01:00, not midnight: an interval trigger
        # measures elapsed time, not wall clock.
        self.assertEqual(1, fires.astimezone(NYC).hour)

    def test_rejects_zero_interval(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            triggers.IntervalTrigger()

    def test_rejects_end_before_start(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            triggers.IntervalTrigger(
                hours=1,
                start_at=utc(2026, 7, 28, 8),
                end_at=utc(2026, 7, 28, 6),
            )


class CalendarTriggerTests(unittest.TestCase):
    def test_daily_at_time(self) -> None:
        trigger = triggers.CalendarTrigger(
            days=1, at_time=datetime.time(6, 30)
        )
        self.assertEqual(
            utc(2026, 7, 28, 6, 30),
            trigger.next_fire_time(utc(2026, 7, 28, 5), UTC),
        )

    def test_advances_when_time_has_passed(self) -> None:
        trigger = triggers.CalendarTrigger(
            days=1, at_time=datetime.time(6, 30)
        )
        self.assertEqual(
            utc(2026, 7, 29, 6, 30),
            trigger.next_fire_time(utc(2026, 7, 28, 7), UTC),
        )

    def test_weekly_step(self) -> None:
        trigger = triggers.CalendarTrigger(
            weeks=1,
            at_time=datetime.time(9),
            start_at=utc(2026, 7, 6, 9),
        )
        self.assertEqual(
            utc(2026, 7, 27, 9),
            trigger.next_fire_time(utc(2026, 7, 21, 10), UTC),
        )

    def test_monthly_step(self) -> None:
        trigger = triggers.CalendarTrigger(
            months=1,
            at_time=datetime.time(9),
            start_at=utc(2026, 1, 15, 9),
        )
        self.assertEqual(
            utc(2026, 8, 15, 9),
            trigger.next_fire_time(utc(2026, 7, 20), UTC),
        )

    def test_quarterly_step_from_a_distant_anchor(self) -> None:
        trigger = triggers.CalendarTrigger(
            months=3,
            at_time=datetime.time(9),
            start_at=utc(2020, 1, 1, 9),
        )
        self.assertEqual(
            utc(2026, 10, 1, 9),
            trigger.next_fire_time(utc(2026, 7, 28), UTC),
        )

    def test_month_end_anchor_clamps(self) -> None:
        trigger = triggers.CalendarTrigger(
            months=1,
            at_time=datetime.time(9),
            start_at=utc(2026, 1, 31, 9),
        )
        # February has no 31st: clamp rather than skip the month.
        self.assertEqual(
            utc(2026, 2, 28, 9),
            trigger.next_fire_time(utc(2026, 2, 1), UTC),
        )

    def test_december_rolls_into_january(self) -> None:
        trigger = triggers.CalendarTrigger(
            months=1,
            at_time=datetime.time(9),
            start_at=utc(2026, 12, 5, 9),
        )
        self.assertEqual(
            utc(2027, 1, 5, 9),
            trigger.next_fire_time(utc(2026, 12, 6), UTC),
        )

    def test_wall_clock_survives_spring_forward(self) -> None:
        trigger = triggers.CalendarTrigger(
            days=1,
            at_time=datetime.time(12),
            start_at=SPRING_FORWARD - datetime.timedelta(days=3),
        )
        before = trigger.next_fire_time(
            SPRING_FORWARD - datetime.timedelta(days=1), NYC
        )
        assert before is not None
        after = trigger.next_fire_time(before, NYC)
        assert after is not None
        self.assertEqual(12, before.astimezone(NYC).hour)
        self.assertEqual(12, after.astimezone(NYC).hour)
        self.assertEqual(17, before.hour)
        self.assertEqual(16, after.hour)

    def test_end_at_stops_the_series(self) -> None:
        trigger = triggers.CalendarTrigger(
            days=1,
            at_time=datetime.time(9),
            start_at=utc(2026, 7, 1, 9),
            end_at=utc(2026, 7, 3, 9),
        )
        self.assertIsNone(trigger.next_fire_time(utc(2026, 7, 3, 10), UTC))

    def test_rejects_months_with_days(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            triggers.CalendarTrigger(months=1, days=1)

    def test_rejects_missing_step(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            triggers.CalendarTrigger()

    def test_rejects_negative_step(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            triggers.CalendarTrigger(days=-1)

    def test_rejects_aware_at_time(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            triggers.CalendarTrigger(
                days=1, at_time=datetime.time(9, tzinfo=datetime.UTC)
            )


class DateTriggerTests(unittest.TestCase):
    def test_fires_once(self) -> None:
        trigger = triggers.DateTrigger(run_at=utc(2026, 7, 28, 9))
        self.assertEqual(
            utc(2026, 7, 28, 9),
            trigger.next_fire_time(utc(2026, 7, 28, 8), UTC),
        )

    def test_does_not_fire_again(self) -> None:
        trigger = triggers.DateTrigger(run_at=utc(2026, 7, 28, 9))
        self.assertIsNone(trigger.next_fire_time(utc(2026, 7, 28, 9), UTC))


class TriggerUnionTests(unittest.TestCase):
    class Holder(pydantic.BaseModel):
        trigger: triggers.Trigger

    def test_discriminates_on_kind(self) -> None:
        for payload, expected in (
            (
                {'kind': 'cron', 'expression': '0 6 * * *'},
                triggers.CronTrigger,
            ),
            ({'kind': 'interval', 'hours': 1}, triggers.IntervalTrigger),
            ({'kind': 'calendar', 'days': 1}, triggers.CalendarTrigger),
            (
                {'kind': 'date', 'run_at': '2026-07-28T09:00:00Z'},
                triggers.DateTrigger,
            ),
        ):
            with self.subTest(kind=payload['kind']):
                holder = self.Holder.model_validate({'trigger': payload})
                self.assertIsInstance(holder.trigger, expected)

    def test_rejects_unknown_kind(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            self.Holder.model_validate({'trigger': {'kind': 'sunspot'}})
