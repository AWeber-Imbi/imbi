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
            for table in ('tasks', 'run_leases'):
                await conn.execute(
                    sql.SQL('TRUNCATE {table}').format(
                        table=sql.Identifier(TEST_SCHEMA, table)
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
        tables = {
            table['name']: table
            for table in initializer.load_schemata()['tables']
        }
        declared = set(tables['tasks']['columns'].keys())
        self.assertEqual(set(tasks_repo.COLUMNS), declared)
        self.assertEqual(set(models.Task.model_fields), declared)
        self.assertEqual(
            {
                'id',
                'task_id',
                'run_id',
                'acquired_at',
                'expires_at',
                'cancel_requested',
            },
            set(tables['run_leases']['columns'].keys()),
        )


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

    async def test_a_foreign_service_account_is_refused_at_creation(
        self,
    ) -> None:
        # Fire time refuses it (ADR 0002), so storing it would only produce a
        # task that skips every firing.
        task = helpers.build_task(
            identity=models.Identity(
                kind='service_account', subject='someone-else'
            )
        )
        with self.assertRaises(tasks_repo.UnresolvableIdentity):
            await self.tasks.create(task)
        self.assertIsNone(await self.tasks.get(task.slug))

    async def test_a_delegated_task_is_still_creatable(self) -> None:
        # Refused at fire time until the token-exchange grant lands, but a
        # task may legitimately be written ahead of it.
        task = helpers.build_task(
            identity=models.Identity(
                kind='delegated_user',
                subject='gavinr@aweber.com',
                consent_id='c-1',
            )
        )
        self.assertIsNotNone(await self.tasks.create(task))

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


class LeaseTests(StoreTestCase):
    """`max_running_instances` has to hold across replicas, not per process."""

    ONE_MINUTE = datetime.timedelta(minutes=1)

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.task = await self.tasks.create(helpers.build_task())

    async def _acquire(
        self,
        *,
        limit: int = 1,
        ttl: datetime.timedelta | None = None,
        repo: tasks_repo.Tasks | None = None,
        run_id: uuid.UUID | None = None,
    ) -> uuid.UUID | None:
        return await (repo or self.tasks).acquire_lease(
            self.task.id,
            run_id=run_id or uuid.uuid4(),
            limit=limit,
            ttl=ttl or self.ONE_MINUTE,
        )

    async def test_a_free_slot_is_granted_and_released(self) -> None:
        lease = await self._acquire()
        assert lease is not None
        self.assertIsNone(await self._acquire())
        await self.tasks.release_lease(lease)
        self.assertIsNotNone(await self._acquire())

    async def test_the_limit_is_per_task_not_global(self) -> None:
        other = await self.tasks.create(helpers.build_task(slug='other'))
        self.assertIsNotNone(await self._acquire())
        self.assertIsNotNone(
            await self.tasks.acquire_lease(
                other.id,
                run_id=uuid.uuid4(),
                limit=1,
                ttl=self.ONE_MINUTE,
            )
        )

    async def test_a_higher_limit_grants_more_slots(self) -> None:
        self.assertIsNotNone(await self._acquire(limit=2))
        self.assertIsNotNone(await self._acquire(limit=2))
        self.assertIsNone(await self._acquire(limit=2))

    async def test_a_separate_repository_sees_the_same_slots(self) -> None:
        # Stands in for a second replica: an in-memory counter would grant
        # both, which is the defect this table exists to close.
        other_replica = tasks_repo.Tasks(self.pool, schema=TEST_SCHEMA)
        self.assertIsNotNone(await self._acquire())
        self.assertIsNone(await self._acquire(repo=other_replica))

    async def test_concurrent_acquirers_do_not_oversubscribe(self) -> None:
        replicas = [
            tasks_repo.Tasks(self.pool, schema=TEST_SCHEMA) for _ in range(6)
        ]
        granted = await asyncio.gather(
            *(self._acquire(limit=2, repo=replica) for replica in replicas)
        )
        self.assertEqual(2, len([lease for lease in granted if lease]))

    async def test_an_expired_lease_frees_its_slot(self) -> None:
        # A replica killed mid-run never releases; without expiry the task
        # would never fire again.
        self.assertIsNotNone(
            await self._acquire(ttl=datetime.timedelta(seconds=-1))
        )
        self.assertIsNotNone(await self._acquire())

    async def test_releasing_an_unknown_lease_is_harmless(self) -> None:
        await self.tasks.release_lease(uuid.uuid4())


class CancelRequestTests(StoreTestCase):
    """The lease row is what makes a run cancellable by id."""

    ONE_MINUTE = datetime.timedelta(minutes=1)

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.task = await self.tasks.create(helpers.build_task())
        self.run_id = uuid.uuid4()

    async def _lease(self, run_id: uuid.UUID | None = None) -> uuid.UUID:
        lease = await self.tasks.acquire_lease(
            self.task.id,
            run_id=run_id or self.run_id,
            limit=1,
            ttl=self.ONE_MINUTE,
        )
        assert lease is not None
        return lease

    async def test_requesting_a_cancel_marks_the_lease(self) -> None:
        await self._lease()
        self.assertFalse(await self.tasks.cancel_requested(self.run_id))
        self.assertTrue(await self.tasks.request_cancel(str(self.run_id)))
        self.assertTrue(await self.tasks.cancel_requested(self.run_id))

    async def test_a_run_with_no_lease_cannot_be_cancelled(self) -> None:
        # Finished, never started, or its replica died and the lease expired.
        # All three look alike, and all three mean there is nothing to stop.
        self.assertFalse(await self.tasks.request_cancel(str(uuid.uuid4())))

    async def test_a_released_lease_cannot_be_cancelled(self) -> None:
        lease = await self._lease()
        await self.tasks.release_lease(lease)
        self.assertFalse(await self.tasks.request_cancel(str(self.run_id)))

    async def test_cancel_requested_is_false_for_an_unknown_run(self) -> None:
        self.assertFalse(await self.tasks.cancel_requested(uuid.uuid4()))

    async def test_a_cancel_reaches_a_listener(self) -> None:
        """The NOTIFY is the enforcement half; without it the flag is inert."""
        await self._lease()
        async with self.pool.connection() as listener:
            await listener.set_autocommit(True)
            await listener.execute(
                sql.SQL('LISTEN {channel}').format(
                    channel=sql.Identifier(tasks_repo.CANCEL_CHANNEL)
                )
            )
            await self.tasks.request_cancel(str(self.run_id))
            notices = listener.notifies(timeout=5, stop_after=1)
            payloads = [notice.payload async for notice in notices]
        self.assertEqual([str(self.run_id)], payloads)

    async def test_the_lease_records_which_run_holds_it(self) -> None:
        await self._lease()
        async with (
            self.pool.connection() as conn,
            conn.cursor(row_factory=rows.dict_row) as cursor,
        ):
            await cursor.execute(
                sql.SQL('SELECT run_id FROM {table}').format(
                    table=sql.Identifier(TEST_SCHEMA, 'run_leases')
                )
            )
            found = await cursor.fetchall()
        self.assertEqual([self.run_id], [row['run_id'] for row in found])


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
