"""Store tests.

These run against the live Postgres that `root:services` boots, in a
dedicated schema so they cannot disturb a real deployment.
"""

import asyncio
import datetime
import os
import typing
import uuid

import psycopg
from psycopg import rows, sql

from apps.scheduler.tests import helpers
from imbi.scheduler import models, store, triggers
from imbi.scheduler.store import initializer
from imbi.scheduler.store import tasks as tasks_repo

TEST_SCHEMA = 'scheduler_test'


def utc(*args: int) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=datetime.UTC)


class StoreTestCase(helpers.TestCase):
    """Base case owning the schema and a pool."""

    pool: store.Pool
    tasks: tasks_repo.Tasks

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        os.environ['IMBI_SCHEDULER_SCHEMA'] = TEST_SCHEMA
        await initializer.initialize()
        self.pool = store.create_pool()
        await self.pool.open()
        self.tasks = tasks_repo.Tasks(self.pool, schema=TEST_SCHEMA)
        await self._truncate()

    async def asyncTearDown(self) -> None:
        await self.pool.close()
        os.environ.pop('IMBI_SCHEDULER_SCHEMA', None)
        await super().asyncTearDown()

    async def _truncate(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                sql.SQL('TRUNCATE {table}').format(
                    table=sql.Identifier(TEST_SCHEMA, 'tasks')
                )
            )

    async def _column_value(
        self, task_id: uuid.UUID, column: str
    ) -> typing.Any:
        async with self.pool.connection() as conn:
            async with conn.cursor(row_factory=rows.dict_row) as cursor:
                await cursor.execute(
                    sql.SQL('SELECT {col} FROM {table} WHERE id = %s').format(
                        col=sql.Identifier(column),
                        table=sql.Identifier(TEST_SCHEMA, 'tasks'),
                    ),
                    (task_id,),
                )
                row = await cursor.fetchone()
        assert row is not None
        return row[column]


class InitializerTests(StoreTestCase):
    async def test_initialize_is_idempotent(self) -> None:
        await initializer.initialize()
        await initializer.initialize()
        async with self.pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    'SELECT COUNT(*) FROM information_schema.tables'
                    ' WHERE table_schema = %s AND table_name = %s',
                    (TEST_SCHEMA, 'tasks'),
                )
                row = await cursor.fetchone()
        assert row is not None
        self.assertEqual(1, row[0])

    async def test_restores_a_dropped_column(self) -> None:
        # CREATE TABLE IF NOT EXISTS alone would leave the schema behind
        # schemata.toml, so the initializer also adds missing columns.
        async with self.pool.connection() as conn:
            await conn.execute(
                sql.SQL('ALTER TABLE {table} DROP COLUMN tags').format(
                    table=sql.Identifier(TEST_SCHEMA, 'tasks')
                )
            )
        await initializer.initialize()
        async with self.pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    'SELECT COUNT(*) FROM information_schema.columns'
                    ' WHERE table_schema = %s AND table_name = %s'
                    ' AND column_name = %s',
                    (TEST_SCHEMA, 'tasks', 'tags'),
                )
                row = await cursor.fetchone()
        assert row is not None
        self.assertEqual(1, row[0])

    async def test_declared_columns_match_the_model(self) -> None:
        declared = set(
            initializer.load_schemata()['tables'][0]['columns'].keys()
        )
        self.assertEqual(set(tasks_repo.COLUMNS), declared)
        self.assertEqual(set(models.Task.model_fields), declared)


class CrudTests(StoreTestCase):
    async def test_create_and_get_round_trip(self) -> None:
        task = helpers.build_task(
            description='Recompute every project score',
            organization='aweber',
            tags=['scoring', 'nightly'],
            next_run_at=utc(2026, 7, 29, 6),
        )
        created = await self.tasks.create(task)
        self.assertEqual(task, created)
        fetched = await self.tasks.get(task.slug)
        self.assertEqual(task, fetched)

    async def test_round_trips_every_trigger_kind(self) -> None:
        for index, trigger in enumerate(
            (
                triggers.CronTrigger(expression='0 6 * * *', jitter=15),
                triggers.IntervalTrigger(minutes=30),
                triggers.CalendarTrigger(
                    months=1, at_time=datetime.time(9, 30)
                ),
                triggers.DateTrigger(run_at=utc(2027, 1, 1)),
            )
        ):
            with self.subTest(kind=trigger.kind):
                task = await self.tasks.create(
                    helpers.build_task(slug=f'task-{index}', trigger=trigger)
                )
                fetched = await self.tasks.get(task.slug)
                assert fetched is not None
                self.assertEqual(trigger, fetched.trigger)

    async def test_round_trips_a_gateway_target(self) -> None:
        task = helpers.build_task(
            slug='synthetic-delivery',
            identity=None,
            target=models.GatewayTarget(
                webhook_id='w-1',
                payload={'nested': {'values': [1, 2, 3]}},
                headers={'X-Source': 'scheduler'},
            ),
        )
        await self.tasks.create(task)
        fetched = await self.tasks.get(task.slug)
        assert fetched is not None
        self.assertEqual(task.target, fetched.target)
        self.assertIsNone(fetched.identity)

    async def test_get_unknown_slug(self) -> None:
        self.assertIsNone(await self.tasks.get('nope'))

    async def test_get_by_id(self) -> None:
        task = await self.tasks.create(helpers.build_task())
        self.assertEqual(task, await self.tasks.get_by_id(task.id))

    async def test_get_by_unknown_id(self) -> None:
        self.assertIsNone(await self.tasks.get_by_id(uuid.uuid4()))

    async def test_duplicate_slug_is_rejected(self) -> None:
        await self.tasks.create(helpers.build_task())
        with self.assertRaises(psycopg.errors.UniqueViolation):
            await self.tasks.create(helpers.build_task(id=uuid.uuid4()))

    async def test_update_replaces_and_stamps(self) -> None:
        task = await self.tasks.create(helpers.build_task())
        changed = task.model_copy(
            update={'name': 'Renamed', 'tags': ['changed']}
        )
        updated = await self.tasks.update(changed)
        assert updated is not None
        self.assertEqual('Renamed', updated.name)
        self.assertEqual(['changed'], updated.tags)
        self.assertGreater(updated.updated_at, task.updated_at)

    async def test_update_unknown_task(self) -> None:
        self.assertIsNone(await self.tasks.update(helpers.build_task()))

    async def test_delete(self) -> None:
        task = await self.tasks.create(helpers.build_task())
        self.assertTrue(await self.tasks.delete(task.slug))
        self.assertFalse(await self.tasks.delete(task.slug))
        self.assertIsNone(await self.tasks.get(task.slug))

    async def test_set_enabled(self) -> None:
        task = await self.tasks.create(helpers.build_task())
        paused = await self.tasks.set_enabled(task.slug, enabled=False)
        assert paused is not None
        self.assertFalse(paused.enabled)
        resumed = await self.tasks.set_enabled(task.slug, enabled=True)
        assert resumed is not None
        self.assertTrue(resumed.enabled)

    async def test_enabling_reschedules_from_now(self) -> None:
        task = await self.tasks.create(
            helpers.build_task(next_run_at=utc(2020, 1, 1))
        )
        await self.tasks.set_enabled(task.slug, enabled=False)
        resumed = await self.tasks.set_enabled(task.slug, enabled=True)
        assert resumed is not None
        assert resumed.next_run_at is not None
        self.assertGreater(
            resumed.next_run_at, datetime.datetime.now(datetime.UTC)
        )
        self.assertEqual(
            resumed.next_run_at,
            await self._column_value(task.id, 'next_run_at'),
        )

    async def test_disabling_leaves_the_schedule_alone(self) -> None:
        task = await self.tasks.create(
            helpers.build_task(next_run_at=utc(2026, 7, 28, 6))
        )
        paused = await self.tasks.set_enabled(task.slug, enabled=False)
        assert paused is not None
        self.assertEqual(utc(2026, 7, 28, 6), paused.next_run_at)

    async def test_set_enabled_unknown_task(self) -> None:
        self.assertIsNone(await self.tasks.set_enabled('nope', enabled=False))


class ListTests(StoreTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.tasks.create(
            helpers.build_task(
                slug='alpha', organization='aweber', tags=['scoring']
            )
        )
        await self.tasks.create(
            helpers.build_task(
                slug='beta',
                organization='other',
                kind='user',
                tags=['reports'],
            )
        )
        await self.tasks.create(
            helpers.build_task(slug='gamma', enabled=False)
        )

    async def test_lists_everything_ordered_by_slug(self) -> None:
        found = await self.tasks.search()
        self.assertEqual(
            ['alpha', 'beta', 'gamma'], [task.slug for task in found]
        )

    async def test_filters_by_organization(self) -> None:
        found = await self.tasks.search(organization='aweber')
        self.assertEqual(['alpha'], [task.slug for task in found])

    async def test_filters_by_kind(self) -> None:
        found = await self.tasks.search(kind='user')
        self.assertEqual(['beta'], [task.slug for task in found])

    async def test_filters_by_enabled(self) -> None:
        found = await self.tasks.search(enabled=False)
        self.assertEqual(['gamma'], [task.slug for task in found])

    async def test_filters_by_tag(self) -> None:
        found = await self.tasks.search(tag='reports')
        self.assertEqual(['beta'], [task.slug for task in found])

    async def test_filters_combine(self) -> None:
        found = await self.tasks.search(organization='aweber', kind='user')
        self.assertEqual([], found)


class ClaimTests(StoreTestCase):
    async def test_claims_a_due_task_and_advances_it(self) -> None:
        now = utc(2026, 7, 28, 6, 0, 30)
        await self.tasks.create(
            helpers.build_task(next_run_at=utc(2026, 7, 28, 6))
        )
        claimed = await self.tasks.claim_due(now)
        self.assertEqual(['nightly-recompute'], [t.slug for t in claimed])
        stored = await self.tasks.get('nightly-recompute')
        assert stored is not None
        self.assertEqual(now, stored.last_run_at)
        self.assertEqual(utc(2026, 7, 29, 6), stored.next_run_at)

    async def test_does_not_reclaim_after_advancing(self) -> None:
        now = utc(2026, 7, 28, 6, 0, 30)
        await self.tasks.create(
            helpers.build_task(next_run_at=utc(2026, 7, 28, 6))
        )
        self.assertEqual(1, len(await self.tasks.claim_due(now)))
        self.assertEqual([], await self.tasks.claim_due(now))

    async def test_skips_future_tasks(self) -> None:
        await self.tasks.create(
            helpers.build_task(next_run_at=utc(2026, 7, 29, 6))
        )
        self.assertEqual([], await self.tasks.claim_due(utc(2026, 7, 28, 6)))

    async def test_skips_disabled_tasks(self) -> None:
        await self.tasks.create(
            helpers.build_task(enabled=False, next_run_at=utc(2026, 7, 28, 6))
        )
        self.assertEqual([], await self.tasks.claim_due(utc(2026, 7, 28, 7)))

    async def test_skips_unscheduled_tasks(self) -> None:
        await self.tasks.create(helpers.build_task(next_run_at=None))
        self.assertEqual([], await self.tasks.claim_due(utc(2026, 7, 28, 7)))

    async def test_one_shot_stops_after_firing(self) -> None:
        await self.tasks.create(
            helpers.build_task(
                trigger=triggers.DateTrigger(run_at=utc(2026, 7, 28, 6)),
                next_run_at=utc(2026, 7, 28, 6),
            )
        )
        self.assertEqual(
            1, len(await self.tasks.claim_due(utc(2026, 7, 28, 6)))
        )
        stored = await self.tasks.get('nightly-recompute')
        assert stored is not None
        self.assertIsNone(stored.next_run_at)

    async def test_honors_the_limit(self) -> None:
        for index in range(5):
            await self.tasks.create(
                helpers.build_task(
                    slug=f'task-{index}', next_run_at=utc(2026, 7, 28, 6)
                )
            )
        claimed = await self.tasks.claim_due(utc(2026, 7, 28, 7), limit=2)
        self.assertEqual(2, len(claimed))

    async def test_a_held_claim_is_skipped_not_blocked(self) -> None:
        """The single-firing guarantee, demonstrated directly.

        A second claimer running while the first transaction is still open
        returns nothing rather than waiting — that is `SKIP LOCKED` doing the
        arbitration a distributed lock would otherwise have to do.
        """
        await self.tasks.create(
            helpers.build_task(next_run_at=utc(2026, 7, 28, 6))
        )
        now = utc(2026, 7, 28, 7)
        async with self.pool.connection() as holder:
            async with holder.transaction():
                async with holder.cursor() as cursor:
                    await cursor.execute(
                        sql.SQL(
                            'SELECT id FROM {table} WHERE enabled'
                            ' AND next_run_at <= %s FOR UPDATE SKIP LOCKED'
                        ).format(table=sql.Identifier(TEST_SCHEMA, 'tasks')),
                        (now,),
                    )
                    self.assertEqual(1, len(await cursor.fetchall()))
                # The row is locked and uncommitted here.
                second = await asyncio.wait_for(
                    self.tasks.claim_due(now), timeout=5
                )
                self.assertEqual([], second)

    async def test_concurrent_claimers_never_double_fire(self) -> None:
        for index in range(10):
            await self.tasks.create(
                helpers.build_task(
                    slug=f'task-{index}', next_run_at=utc(2026, 7, 28, 6)
                )
            )
        now = utc(2026, 7, 28, 7)
        claimers = [tasks_repo.Tasks(self.pool, schema=TEST_SCHEMA)] * 4
        results = await asyncio.gather(
            *(claimer.claim_due(now) for claimer in claimers)
        )
        claimed = [task.slug for batch in results for task in batch]
        self.assertEqual(10, len(claimed))
        self.assertEqual(10, len(set(claimed)))


class OutcomeTests(StoreTestCase):
    async def test_skip_increments_and_other_outcomes_reset(self) -> None:
        task = await self.tasks.create(helpers.build_task())
        await self.tasks.record_outcome(task.id, skipped=True)
        await self.tasks.record_outcome(task.id, skipped=True)
        self.assertEqual(
            2, await self._column_value(task.id, 'consecutive_skips')
        )
        await self.tasks.record_outcome(task.id)
        self.assertEqual(
            0, await self._column_value(task.id, 'consecutive_skips')
        )

    async def test_no_effect_counter_is_independent(self) -> None:
        task = await self.tasks.create(helpers.build_task())
        await self.tasks.record_outcome(task.id, no_effect=True)
        self.assertEqual(
            1, await self._column_value(task.id, 'consecutive_no_effect')
        )
        self.assertEqual(
            0, await self._column_value(task.id, 'consecutive_skips')
        )


class ScheduleTests(StoreTestCase):
    async def test_reschedule_computes_from_now(self) -> None:
        task = await self.tasks.create(
            helpers.build_task(
                trigger=triggers.IntervalTrigger(hours=1), next_run_at=None
            )
        )
        following = await self.tasks.reschedule(task)
        assert following is not None
        stored = await self.tasks.get(task.slug)
        assert stored is not None
        self.assertEqual(following, stored.next_run_at)

    async def test_next_due_at_returns_the_soonest(self) -> None:
        await self.tasks.create(
            helpers.build_task(slug='later', next_run_at=utc(2026, 7, 30, 6))
        )
        await self.tasks.create(
            helpers.build_task(slug='sooner', next_run_at=utc(2026, 7, 29, 6))
        )
        self.assertEqual(utc(2026, 7, 29, 6), await self.tasks.next_due_at())

    async def test_next_due_at_with_no_tasks(self) -> None:
        self.assertIsNone(await self.tasks.next_due_at())
