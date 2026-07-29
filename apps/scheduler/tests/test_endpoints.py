"""HTTP API tests.

The auth dependency that is stubbed is ``get_current_user`` -- the one that
would need a real JWT and a real graph. ``require_permission`` itself runs for
real above it, so the per-route permission checks and the ownership rule are
exercised rather than mocked past.

Postgres and ClickHouse are live: these assert what a request actually did to
the store and to run history, which is the only way to catch a route that
returns 200 and changes nothing.
"""

import asyncio
import datetime
import typing
import uuid

import httpx

import imbi.scheduler.app
from apps.scheduler.tests import helpers, test_engine, test_store
from imbi.common import clickhouse
from imbi.common import models as common_models
from imbi.common.auth import permissions
from imbi.scheduler import engine as engine_module
from imbi.scheduler import models, runs, settings, triggers
from imbi.scheduler.endpoints import dependencies

ALL_PERMISSIONS = frozenset(
    {
        dependencies.READ,
        dependencies.CREATE,
        dependencies.WRITE,
        dependencies.DELETE,
        dependencies.RUN,
    }
)

OWNER = 'owner@example.com'
OTHER = 'other@example.com'


def task_body(**overrides: typing.Any) -> dict[str, typing.Any]:
    """Return a valid ``POST /tasks`` body."""
    body: dict[str, typing.Any] = {
        'slug': 'nightly-recompute',
        'name': 'Nightly recompute',
        'trigger': {'kind': 'cron', 'expression': '0 6 * * *'},
        'identity': {'kind': 'service_account', 'subject': 'imbi-scheduler'},
        'target': {
            'kind': 'api',
            'method': 'POST',
            'path': '/scoring/recompute-all',
        },
    }
    body.update(overrides)
    return body


class EndpointTestCase(test_store.StoreTestCase):
    """Boots the app with the store, engine, and caller under our control."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.assertTrue(await clickhouse.initialize())
        await clickhouse.setup_schema()
        self.executor = test_engine.StubExecutor()
        self.engine = engine_module.Engine(
            self.tasks,
            typing.cast('typing.Any', self.executor),
            settings.Scheduler(),
        )
        self.app = imbi.scheduler.app.create_app()
        self.app.dependency_overrides[dependencies._inject_tasks] = (
            lambda: self.tasks
        )
        self.app.dependency_overrides[dependencies._inject_engine] = (
            lambda: self.engine
        )
        self.as_user(OWNER, ALL_PERMISSIONS)
        # ASGITransport rather than TestClient: TestClient drives the app from
        # a worker thread with its own event loop, and the psycopg pool these
        # cases assert against belongs to this one. Nothing enters the app's
        # lifespan either -- that would bootstrap the graph and start the
        # trigger loop; the routes get their resources from the overrides.
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url='http://scheduler.test',
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        await clickhouse.aclose()
        await super().asyncTearDown()

    def as_user(
        self, email: str, granted: typing.Iterable[str], *, admin: bool = False
    ) -> None:
        """Authenticate every subsequent request as this principal."""
        context = permissions.AuthContext(
            user=common_models.User(
                email=email, display_name=email, is_admin=admin
            ),
            auth_method='jwt',
            permissions=set(granted),
        )
        self.app.dependency_overrides[permissions.get_current_user] = (
            lambda: context
        )

    def as_service_account(
        self, slug: str, granted: typing.Iterable[str]
    ) -> None:
        """Authenticate as a service account, which has no ``user``."""
        context = permissions.AuthContext(
            service_account=common_models.ServiceAccount(
                slug=slug, display_name=slug
            ),
            auth_method='client_credentials',
            permissions=set(granted),
        )
        self.app.dependency_overrides[permissions.get_current_user] = (
            lambda: context
        )

    async def given_task(self, **overrides: typing.Any) -> models.Task:
        """Store a task owned by ``OWNER``."""
        overrides.setdefault('created_by', OWNER)
        overrides.setdefault('kind', 'user')
        return await self.tasks.create(helpers.build_task(**overrides))


class PermissionTests(EndpointTestCase):
    """Every route enforces the permission the PRD assigns it."""

    async def test_each_route_requires_its_permission(self) -> None:
        task = await self.given_task()
        run = runs.start(task, datetime.datetime.now(datetime.UTC))
        await runs.record(run)
        cases: list[tuple[str, str, str, dict[str, typing.Any]]] = [
            ('GET', '/api/tasks', dependencies.READ, {}),
            (
                'POST',
                '/api/tasks',
                dependencies.CREATE,
                {'json': task_body(slug='another')},
            ),
            ('GET', f'/api/tasks/{task.slug}', dependencies.READ, {}),
            (
                'PATCH',
                f'/api/tasks/{task.slug}',
                dependencies.WRITE,
                {'json': [{'op': 'replace', 'path': '/name', 'value': 'x'}]},
            ),
            ('DELETE', f'/api/tasks/{task.slug}', dependencies.DELETE, {}),
            ('POST', f'/api/tasks/{task.slug}/pause', dependencies.WRITE, {}),
            ('POST', f'/api/tasks/{task.slug}/resume', dependencies.WRITE, {}),
            ('POST', f'/api/tasks/{task.slug}/run', dependencies.RUN, {}),
            ('POST', f'/api/tasks/{task.slug}/dry-run', dependencies.READ, {}),
            ('GET', f'/api/tasks/{task.slug}/runs', dependencies.READ, {}),
            ('GET', f'/api/runs/{run.run_id}', dependencies.READ, {}),
            ('POST', f'/api/runs/{run.run_id}/cancel', dependencies.RUN, {}),
        ]
        for method, path, needed, kwargs in cases:
            with self.subTest(route=f'{method} {path}', permission=needed):
                self.as_user(OWNER, ALL_PERMISSIONS - {needed})
                denied = await self.client.request(method, path, **kwargs)
                self.assertEqual(403, denied.status_code)
                self.as_user(OWNER, {needed})
                allowed = await self.client.request(method, path, **kwargs)
                self.assertNotEqual(403, allowed.status_code)

    async def test_an_admin_user_bypasses_the_permission_check(self) -> None:
        await self.given_task()
        self.as_user(OWNER, set(), admin=True)
        self.assertEqual(
            200, (await self.client.get('/api/tasks')).status_code
        )

    async def test_a_service_account_never_bypasses(self) -> None:
        # `is_admin` reads False for a service account by construction, so a
        # machine principal needs the permission granted explicitly.
        self.as_service_account('imbi-scheduler', set())
        self.assertEqual(
            403, (await self.client.get('/api/tasks')).status_code
        )


class OwnershipTests(EndpointTestCase):
    """A caller manages their own tasks; anything else needs admin."""

    async def test_another_principals_task_cannot_be_managed(self) -> None:
        task = await self.given_task(created_by=OTHER)
        self.as_user(OWNER, ALL_PERMISSIONS)
        response = await self.client.post(f'/api/tasks/{task.slug}/pause')
        self.assertEqual(403, response.status_code)
        self.assertIn(OTHER, response.json()['detail'])

    async def test_scheduled_task_admin_manages_anyones_task(self) -> None:
        task = await self.given_task(created_by=OTHER)
        self.as_user(OWNER, {dependencies.WRITE, dependencies.ADMIN})
        response = await self.client.post(f'/api/tasks/{task.slug}/pause')
        self.assertEqual(200, response.status_code)
        self.assertFalse(response.json()['enabled'])

    async def test_a_system_task_needs_admin_even_from_its_creator(
        self,
    ) -> None:
        # The scheduler's own service account creates the platform's system
        # tasks, so ownership alone would hand every one of them to whoever
        # holds that account.
        task = await self.given_task(kind='system', created_by=OWNER)
        self.as_user(OWNER, ALL_PERMISSIONS)
        response = await self.client.delete(f'/api/tasks/{task.slug}')
        self.assertEqual(403, response.status_code)
        self.assertIn('system tasks', response.json()['detail'])

    async def test_reading_is_not_restricted_by_ownership(self) -> None:
        task = await self.given_task(created_by=OTHER)
        self.as_user(OWNER, {dependencies.READ})
        self.assertEqual(
            200, (await self.client.get(f'/api/tasks/{task.slug}')).status_code
        )

    async def test_a_missing_task_is_404_not_403(self) -> None:
        self.as_user(OWNER, ALL_PERMISSIONS)
        self.assertEqual(
            404, (await self.client.post('/api/tasks/nope/pause')).status_code
        )

    async def test_creating_a_system_task_needs_admin(self) -> None:
        self.as_user(OWNER, {dependencies.CREATE})
        refused = await self.client.post(
            '/api/tasks', json=task_body(kind='system')
        )
        self.assertEqual(403, refused.status_code)
        self.as_user(OWNER, {dependencies.CREATE, dependencies.ADMIN})
        created = await self.client.post(
            '/api/tasks', json=task_body(kind='system')
        )
        self.assertEqual(201, created.status_code)


class CreateTests(EndpointTestCase):
    async def test_the_server_owns_the_derived_fields(self) -> None:
        response = await self.client.post('/api/tasks', json=task_body())
        self.assertEqual(201, response.status_code)
        body = response.json()
        # created_by is the authenticated caller, never a claim in the body.
        self.assertEqual(OWNER, body['created_by'])
        self.assertIsNotNone(body['next_run_at'])
        self.assertEqual(0, body['consecutive_skips'])
        stored = await self.tasks.get('nightly-recompute')
        assert stored is not None
        self.assertEqual(OWNER, stored.created_by)

    async def test_a_created_task_is_scheduled_immediately(self) -> None:
        # Without this the task would sit with a null next_run_at until
        # something else rescheduled it, which nothing does.
        response = await self.client.post(
            '/api/tasks',
            json=task_body(trigger={'kind': 'interval', 'hours': 1}),
        )
        due = datetime.datetime.fromisoformat(response.json()['next_run_at'])
        self.assertGreater(due, datetime.datetime.now(datetime.UTC))

    async def test_a_disabled_task_is_not_scheduled(self) -> None:
        response = await self.client.post(
            '/api/tasks', json=task_body(enabled=False)
        )
        self.assertIsNone(response.json()['next_run_at'])

    async def test_a_foreign_service_account_is_422(self) -> None:
        # W6's obligation: store.UnresolvableIdentity is a well-formed request
        # naming a principal this scheduler could never run as.
        response = await self.client.post(
            '/api/tasks',
            json=task_body(
                identity={
                    'kind': 'service_account',
                    'subject': 'someone-elses-sa',
                }
            ),
        )
        self.assertEqual(422, response.status_code)
        self.assertIn('ADR 0002', response.json()['detail'])

    async def test_an_unknown_field_is_refused(self) -> None:
        response = await self.client.post(
            '/api/tasks', json=task_body(next_run_at='2026-01-01T00:00:00Z')
        )
        self.assertEqual(422, response.status_code)

    async def test_an_api_target_without_an_identity_is_422(self) -> None:
        body = task_body()
        del body['identity']
        self.assertEqual(
            422, (await self.client.post('/api/tasks', json=body)).status_code
        )


class PatchTests(EndpointTestCase):
    async def test_a_trigger_change_recomputes_the_next_firing(self) -> None:
        task = await self.given_task(
            trigger=triggers.CronTrigger(expression='0 6 * * *'),
            next_run_at=test_store.utc(2030, 1, 1, 6),
        )
        response = await self.client.patch(
            f'/api/tasks/{task.slug}',
            json=[
                {
                    'op': 'replace',
                    'path': '/trigger',
                    'value': {'kind': 'interval', 'minutes': 5},
                }
            ],
        )
        self.assertEqual(200, response.status_code)
        due = datetime.datetime.fromisoformat(response.json()['next_run_at'])
        # The old 2030 time would otherwise stand, so the change would look
        # accepted and then be ignored for years.
        self.assertLess(
            due,
            datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(minutes=6),
        )

    async def test_a_timezone_change_recomputes_the_next_firing(self) -> None:
        task = await self.given_task(next_run_at=test_store.utc(2030, 1, 1, 6))
        response = await self.client.patch(
            f'/api/tasks/{task.slug}',
            json=[
                {
                    'op': 'replace',
                    'path': '/timezone',
                    'value': 'America/New_York',
                }
            ],
        )
        self.assertEqual(200, response.status_code)
        self.assertNotEqual(
            test_store.utc(2030, 1, 1, 6),
            datetime.datetime.fromisoformat(response.json()['next_run_at']),
        )

    async def test_an_unrelated_change_leaves_the_schedule_alone(self) -> None:
        when = test_store.utc(2030, 1, 1, 6)
        task = await self.given_task(next_run_at=when)
        response = await self.client.patch(
            f'/api/tasks/{task.slug}',
            json=[{'op': 'replace', 'path': '/name', 'value': 'Renamed'}],
        )
        self.assertEqual('Renamed', response.json()['name'])
        self.assertEqual(
            when,
            datetime.datetime.fromisoformat(response.json()['next_run_at']),
        )

    async def test_a_server_owned_field_cannot_be_patched(self) -> None:
        task = await self.given_task()
        for path in ('/id', '/created_by', '/created_at', '/next_run_at'):
            with self.subTest(path=path):
                response = await self.client.patch(
                    f'/api/tasks/{task.slug}',
                    json=[{'op': 'replace', 'path': path, 'value': 'x'}],
                )
                self.assertEqual(400, response.status_code)
                self.assertIn('read-only', response.json()['detail'])

    async def test_the_slug_cannot_be_patched(self) -> None:
        task = await self.given_task()
        response = await self.client.patch(
            f'/api/tasks/{task.slug}',
            json=[{'op': 'replace', 'path': '/slug', 'value': 'renamed'}],
        )
        self.assertEqual(400, response.status_code)

    async def test_a_patch_into_an_invalid_task_is_422(self) -> None:
        task = await self.given_task()
        response = await self.client.patch(
            f'/api/tasks/{task.slug}',
            json=[
                {'op': 'replace', 'path': '/timezone', 'value': 'Mars/Olympus'}
            ],
        )
        self.assertEqual(422, response.status_code)

    async def test_a_patch_to_a_foreign_service_account_is_422(self) -> None:
        # The same predicate creation uses, so a patch cannot reach a state
        # POST would have refused.
        task = await self.given_task()
        response = await self.client.patch(
            f'/api/tasks/{task.slug}',
            json=[
                {
                    'op': 'replace',
                    'path': '/identity/subject',
                    'value': 'someone-elses-sa',
                }
            ],
        )
        self.assertEqual(422, response.status_code)
        self.assertIn('ADR 0002', response.json()['detail'])

    async def test_a_failed_test_operation_is_422(self) -> None:
        task = await self.given_task()
        response = await self.client.patch(
            f'/api/tasks/{task.slug}',
            json=[{'op': 'test', 'path': '/name', 'value': 'wrong'}],
        )
        self.assertEqual(422, response.status_code)


class LifecycleTests(EndpointTestCase):
    async def test_pause_disables_without_deleting(self) -> None:
        task = await self.given_task()
        response = await self.client.post(f'/api/tasks/{task.slug}/pause')
        self.assertFalse(response.json()['enabled'])
        self.assertIsNotNone(await self.tasks.get(task.slug))

    async def test_resume_reschedules_from_now(self) -> None:
        task = await self.given_task(
            enabled=False, next_run_at=test_store.utc(2020, 1, 1)
        )
        response = await self.client.post(f'/api/tasks/{task.slug}/resume')
        self.assertTrue(response.json()['enabled'])
        due = datetime.datetime.fromisoformat(response.json()['next_run_at'])
        # A stale past time would read as a misfire on the first tick, making
        # a resumed task indistinguishable from one that never recovered.
        self.assertGreater(due, datetime.datetime.now(datetime.UTC))

    async def test_delete_removes_the_task(self) -> None:
        task = await self.given_task()
        self.assertEqual(
            204,
            (await self.client.delete(f'/api/tasks/{task.slug}')).status_code,
        )
        self.assertIsNone(await self.tasks.get(task.slug))

    async def test_listing_filters(self) -> None:
        await self.given_task(slug='alpha', organization='aweber')
        await self.given_task(slug='beta', organization='other')
        await self.given_task(slug='gamma', enabled=False)
        cases: list[tuple[dict[str, str], list[str]]] = [
            ({'organization': 'aweber'}, ['alpha']),
            ({'enabled': 'false'}, ['gamma']),
            ({'kind': 'user'}, ['alpha', 'beta', 'gamma']),
        ]
        for params, expected in cases:
            with self.subTest(params=params):
                response = await self.client.get('/api/tasks', params=params)
                self.assertEqual(
                    expected, [row['slug'] for row in response.json()]
                )


class RunNowTests(EndpointTestCase):
    async def test_running_a_task_records_a_run(self) -> None:
        task = await self.given_task()
        response = await self.client.post(f'/api/tasks/{task.slug}/run')
        self.assertEqual(200, response.status_code)
        self.assertEqual('succeeded', response.json()['state'])
        self.assertEqual([task.slug], self.executor.fired)
        self.assertEqual(1, len(await runs.for_task(task.id)))

    async def test_a_disabled_task_still_runs_on_demand(self) -> None:
        # Disabling stops the schedule; firing by hand is usually how an
        # operator decides whether it is safe to re-enable.
        task = await self.given_task(enabled=False)
        response = await self.client.post(f'/api/tasks/{task.slug}/run')
        self.assertEqual(200, response.status_code)
        self.assertEqual([task.slug], self.executor.fired)

    async def test_an_on_demand_run_respects_the_instance_limit(self) -> None:
        task = await self.given_task()
        held = await self.tasks.acquire_lease(
            task.id,
            run_id=uuid.uuid4(),
            limit=1,
            ttl=datetime.timedelta(minutes=1),
        )
        self.assertIsNotNone(held)
        response = await self.client.post(f'/api/tasks/{task.slug}/run')
        self.assertEqual('skipped', response.json()['state'])
        self.assertEqual([], self.executor.fired)

    async def test_an_on_demand_run_ignores_misfire_grace(self) -> None:
        # A manual run is on time by definition; the stale next_run_at that
        # would misfire a scheduled firing must not block it.
        task = await self.given_task(
            next_run_at=test_store.utc(2020, 1, 1),
            execution=models.ExecutionPolicy(misfire_grace_time=1),
        )
        response = await self.client.post(f'/api/tasks/{task.slug}/run')
        self.assertEqual('succeeded', response.json()['state'])


class DryRunTests(EndpointTestCase):
    async def test_a_dry_run_makes_no_call_and_records_nothing(self) -> None:
        task = await self.given_task()
        response = await self.client.post(f'/api/tasks/{task.slug}/dry-run')
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()['would_run'])
        self.assertEqual([], self.executor.fired)
        # A dry run in history would corrupt the outcome counters.
        self.assertEqual([], await runs.for_task(task.id))

    async def test_a_dry_run_needs_only_read(self) -> None:
        task = await self.given_task()
        self.as_user(OWNER, {dependencies.READ})
        self.assertEqual(
            200,
            (
                await self.client.post(f'/api/tasks/{task.slug}/dry-run')
            ).status_code,
        )

    async def test_a_dry_run_is_not_restricted_by_ownership(self) -> None:
        task = await self.given_task(created_by=OTHER)
        self.as_user(OWNER, {dependencies.READ})
        self.assertEqual(
            200,
            (
                await self.client.post(f'/api/tasks/{task.slug}/dry-run')
            ).status_code,
        )


class HistoryTests(EndpointTestCase):
    async def test_a_run_is_readable_by_id(self) -> None:
        task = await self.given_task()
        run = runs.start(task, datetime.datetime.now(datetime.UTC))
        await runs.record(run)
        response = await self.client.get(f'/api/runs/{run.run_id}')
        self.assertEqual(200, response.status_code)
        self.assertEqual(run.run_id, response.json()['run_id'])

    async def test_an_unknown_run_is_404(self) -> None:
        self.assertEqual(
            404,
            (await self.client.get(f'/api/runs/{uuid.uuid4()}')).status_code,
        )

    async def test_history_pages(self) -> None:
        task = await self.given_task()
        for index in range(3):
            await runs.record(
                runs.start(
                    task,
                    datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(seconds=index),
                )
            )
        first = await self.client.get(
            f'/api/tasks/{task.slug}/runs', params={'limit': 2}
        )
        self.assertEqual(2, len(first.json()))
        rest = await self.client.get(
            f'/api/tasks/{task.slug}/runs', params={'limit': 2, 'offset': 2}
        )
        self.assertEqual(1, len(rest.json()))

    async def test_an_out_of_range_limit_is_refused(self) -> None:
        task = await self.given_task()
        self.assertEqual(
            422,
            (
                await self.client.get(
                    f'/api/tasks/{task.slug}/runs', params={'limit': 10_000}
                )
            ).status_code,
        )

    async def test_history_for_an_unknown_task_is_404(self) -> None:
        self.assertEqual(
            404, (await self.client.get('/api/tasks/nope/runs')).status_code
        )


class CancelEndpointTests(EndpointTestCase):
    async def _in_flight(self, **overrides: typing.Any) -> runs.Run:
        """Record a running run for a task and give it an execution lease."""
        task = await self.given_task(**overrides)
        run = runs.start(
            task, datetime.datetime.now(datetime.UTC), run_id=uuid.uuid4()
        )
        await runs.record(run)
        lease = await self.tasks.acquire_lease(
            task.id,
            run_id=uuid.UUID(run.run_id),
            limit=1,
            ttl=datetime.timedelta(minutes=1),
        )
        assert lease is not None
        return run

    async def test_cancelling_an_in_flight_run_is_accepted(self) -> None:
        run = await self._in_flight()
        response = await self.client.post(f'/api/runs/{run.run_id}/cancel')
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()['requested'])
        self.assertTrue(
            await self.tasks.cancel_requested(uuid.UUID(run.run_id))
        )

    async def test_cancelling_a_finished_run_is_409(self) -> None:
        task = await self.given_task()
        run = runs.finish(
            runs.start(task, datetime.datetime.now(datetime.UTC)),
            'succeeded',
            runs.Outcome(http_status=200),
        )
        await runs.record(run)
        response = await self.client.post(f'/api/runs/{run.run_id}/cancel')
        self.assertEqual(409, response.status_code)
        self.assertIn('already finished', response.json()['detail'])

    async def test_cancelling_a_run_with_no_lease_is_409(self) -> None:
        # Recorded as running but its lease is gone: the replica died, or it
        # finished between the history read and now.
        task = await self.given_task()
        run = runs.start(task, datetime.datetime.now(datetime.UTC))
        await runs.record(run)
        response = await self.client.post(f'/api/runs/{run.run_id}/cancel')
        self.assertEqual(409, response.status_code)
        self.assertIn('not in flight', response.json()['detail'])

    async def test_cancelling_an_unknown_run_is_404(self) -> None:
        self.assertEqual(
            404,
            (
                await self.client.post(f'/api/runs/{uuid.uuid4()}/cancel')
            ).status_code,
        )

    async def test_cancelling_anothers_run_needs_admin(self) -> None:
        run = await self._in_flight(created_by=OTHER)
        self.as_user(OWNER, {dependencies.RUN})
        self.assertEqual(
            403,
            (
                await self.client.post(f'/api/runs/{run.run_id}/cancel')
            ).status_code,
        )
        self.as_user(OWNER, {dependencies.RUN, dependencies.ADMIN})
        self.assertEqual(
            200,
            (
                await self.client.post(f'/api/runs/{run.run_id}/cancel')
            ).status_code,
        )


class CancelEnforcementTests(test_engine.EngineTestCase):
    """Cancellation has to interrupt the call, not just record the ask."""

    async def test_the_owning_replica_interrupts_the_run(self) -> None:
        # A long-running firing, cancelled mid-flight: the run must come back
        # `cancelled` rather than sitting out its timeout.
        self.executor.delay = 30
        task = await self.tasks.create(helpers.build_task())
        async with self.engine.listening(self.pool):
            firing = asyncio.create_task(self.engine.run_now(task))
            await self._wait_for_lease(task.id)
            run_id = await self._lease_run_id(task.id)
            self.assertTrue(await self.engine.cancel(str(run_id)))
            run = await asyncio.wait_for(firing, timeout=10)
        self.assertEqual('cancelled', run.state)
        self.assertIn('may have already acted', run.error_message)

    async def test_a_cancel_before_the_call_says_nothing_happened(
        self,
    ) -> None:
        # Flagged between taking the lease and starting, so the NOTIFY had
        # nothing in `_in_flight` to cancel. The message must not imply the
        # target was reached.
        task = await self.tasks.create(helpers.build_task())
        run_id = uuid.uuid4()
        await self.tasks.acquire_lease(
            task.id,
            run_id=run_id,
            limit=5,
            ttl=datetime.timedelta(minutes=1),
        )
        await self.tasks.request_cancel(str(run_id))
        run = await self.engine._execute(
            task, datetime.datetime.now(datetime.UTC), run_id
        )
        self.assertEqual('cancelled', run.state)
        self.assertIn('before the request was sent', run.error_message)
        self.assertEqual([], self.executor.fired)

    async def test_a_replica_not_running_the_job_does_nothing(self) -> None:
        # Every replica gets the NOTIFY; only the owner has a task to cancel.
        self.engine._cancel_local(str(uuid.uuid4()))

    async def test_an_unrequested_cancellation_is_not_swallowed(self) -> None:
        # Shutdown, or whoever awaited the firing going away. Treating that as
        # a cancelled run would invent a cancellation nobody asked for and
        # would break the caller's own cancellation, so it has to propagate.
        self.executor.delay = 30
        task = await self.tasks.create(helpers.build_task())
        firing = asyncio.create_task(self.engine.run_now(task))
        await self._wait_for_lease(task.id)
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(firing, timeout=0.5)
        self.assertEqual(
            [],
            [
                run
                for run in await runs.for_task(task.id)
                if run.state == 'cancelled'
            ],
        )

    async def test_cancelling_an_unleased_run_reports_false(self) -> None:
        self.assertFalse(await self.engine.cancel(str(uuid.uuid4())))

    async def test_a_cancelled_run_frees_its_slot(self) -> None:
        # The lease is released in a `finally`, so an interrupted run must not
        # leave the task unable to fire again.
        self.executor.delay = 30
        task = await self.tasks.create(helpers.build_task())
        async with self.engine.listening(self.pool):
            firing = asyncio.create_task(self.engine.run_now(task))
            await self._wait_for_lease(task.id)
            await self.engine.cancel(str(await self._lease_run_id(task.id)))
            await asyncio.wait_for(firing, timeout=10)
        self.assertEqual(0, await self._lease_count(task.id))

    async def _wait_for_lease(self, task_id: uuid.UUID) -> None:
        for _ in range(500):
            if await self._lease_count(task_id):
                return
            await asyncio.sleep(0.01)
        self.fail('no lease was taken')

    async def _lease_count(self, task_id: uuid.UUID) -> int:
        async with self.pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(
                f'SELECT COUNT(*) FROM {test_store.TEST_SCHEMA}.run_leases'
                ' WHERE task_id = %s',
                (task_id,),
            )
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def _lease_run_id(self, task_id: uuid.UUID) -> uuid.UUID:
        async with self.pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute(
                f'SELECT run_id FROM {test_store.TEST_SCHEMA}.run_leases'
                ' WHERE task_id = %s',
                (task_id,),
            )
            row = await cursor.fetchone()
        assert row is not None
        return typing.cast('uuid.UUID', row[0])
