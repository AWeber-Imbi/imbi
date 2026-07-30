import datetime
import unittest
import uuid

from apps.scheduler.tests import helpers
from imbi.common import clickhouse
from imbi.scheduler import models, runs

FIRED_AT = datetime.datetime(2026, 7, 28, 6, tzinfo=datetime.UTC)


class ScrubTests(unittest.TestCase):
    def test_redacts_bearer_tokens(self) -> None:
        scrubbed = runs.scrub('Authorization: Bearer abc123.def-456')
        self.assertNotIn('abc123', scrubbed)
        self.assertIn('Bearer [redacted]', scrubbed)

    def test_redacts_basic_credentials(self) -> None:
        self.assertIn(
            'Basic [redacted]', runs.scrub('Basic dXNlcjpwYXNzd29yZA==')
        )

    def test_redacts_api_keys(self) -> None:
        scrubbed = runs.scrub('key=ik_abcdefgh12345678 rest')
        self.assertNotIn('ik_abcdefgh', scrubbed)
        self.assertIn('rest', scrubbed)

    def test_redacts_jwts(self) -> None:
        token = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhIn0.c2lnbmF0dXJl'
        self.assertNotIn('eyJhbGciOi', runs.scrub(f'token {token}'))

    def test_redacts_secret_json_fields(self) -> None:
        scrubbed = runs.scrub('{"client_secret": "hunter2", "keep": "me"}')
        self.assertNotIn('hunter2', scrubbed)
        self.assertIn('"keep": "me"', scrubbed)

    def test_redacts_oauth_style_token_fields(self) -> None:
        # The keyword can sit anywhere in the key. Requiring the key to *be*
        # `token` let an OAuth-shaped response body persist its credentials
        # into `response_excerpt` verbatim.
        for key in (
            'access_token',
            'refresh_token',
            'id_token',
            'api_key_id',
            'client_secret_new',
            'my_password_field',
        ):
            with self.subTest(key=key):
                scrubbed = runs.scrub(f'{{"{key}": "opaque-credential"}}')
                self.assertNotIn('opaque-credential', scrubbed)
                self.assertIn(key, scrubbed)

    def test_leaves_ordinary_text_alone(self) -> None:
        body = '{"queued": 42, "reason": "scheduled_recompute"}'
        self.assertEqual(body, runs.scrub(body))

    def test_the_widened_key_pattern_spares_unrelated_fields(self) -> None:
        body = '{"project": "imbi", "count": "42", "status": "ok"}'
        self.assertEqual(body, runs.scrub(body))


class ExcerptTests(unittest.TestCase):
    def test_empty_body(self) -> None:
        self.assertEqual('', runs.excerpt(None))
        self.assertEqual('', runs.excerpt(''))

    def test_short_body_is_kept(self) -> None:
        self.assertEqual('ok', runs.excerpt('ok'))

    def test_long_body_is_capped(self) -> None:
        capped = runs.excerpt('x' * (runs.RESPONSE_EXCERPT_LIMIT + 500))
        self.assertLess(len(capped), runs.RESPONSE_EXCERPT_LIMIT + 50)
        self.assertTrue(capped.endswith('[truncated]'))

    def test_scrubs_before_capping(self) -> None:
        body = 'Bearer secrettoken123' + 'x' * runs.RESPONSE_EXCERPT_LIMIT
        self.assertNotIn('secrettoken123', runs.excerpt(body))


class TransitionTests(unittest.TestCase):
    def test_start_captures_identity_and_target(self) -> None:
        task = helpers.build_task(organization='aweber')
        run = runs.start(task, FIRED_AT)
        self.assertEqual('running', run.state)
        self.assertEqual('service_account', run.identity_kind)
        self.assertEqual('imbi-scheduler', run.principal_name)
        self.assertEqual('api', run.target_kind)
        self.assertEqual('POST /scoring/recompute-all', run.target_summary)
        self.assertEqual('aweber', run.organization)
        self.assertEqual('', run.consent_id)
        self.assertEqual(1, run.row_version)
        self.assertFalse(run.is_terminal)

    def test_start_for_a_gateway_task(self) -> None:
        task = helpers.build_task(
            identity=None,
            target=models.GatewayTarget(webhook_id='w-1', payload={}),
        )
        run = runs.start(task, FIRED_AT)
        self.assertEqual('none', run.identity_kind)
        self.assertEqual('gateway:w-1', run.principal_name)

    def test_start_records_consent(self) -> None:
        task = helpers.build_task(
            identity=models.Identity(
                kind='delegated_user',
                subject='gavinr@aweber.com',
                consent_id='c-9',
            )
        )
        self.assertEqual('c-9', runs.start(task, FIRED_AT).consent_id)

    def test_finish_increments_the_version(self) -> None:
        run = runs.start(helpers.build_task(), FIRED_AT)
        done = runs.finish(
            run,
            'succeeded',
            runs.Outcome(http_status=202, response='{"queued": 12}'),
            finished_at=FIRED_AT + datetime.timedelta(milliseconds=250),
        )
        self.assertEqual(2, done.row_version)
        self.assertEqual('succeeded', done.state)
        self.assertEqual(250, done.duration_ms)
        self.assertEqual(202, done.http_status)
        self.assertEqual('{"queued": 12}', done.response_excerpt)
        self.assertTrue(done.is_terminal)

    def test_finish_scrubs_the_response_and_error(self) -> None:
        run = runs.start(helpers.build_task(), FIRED_AT)
        done = runs.finish(
            run,
            'failed',
            runs.Outcome(
                http_status=401,
                response='Bearer leakedtoken999',
                error_type='unauthorized',
                error_message='rejected Bearer leakedtoken999',
            ),
        )
        self.assertNotIn('leakedtoken999', done.response_excerpt)
        self.assertNotIn('leakedtoken999', done.error_message)

    def test_duration_never_goes_negative(self) -> None:
        run = runs.start(helpers.build_task(), FIRED_AT)
        done = runs.finish(
            run, 'failed', finished_at=FIRED_AT - datetime.timedelta(hours=1)
        )
        self.assertEqual(0, done.duration_ms)

    def test_skipped_is_terminal_and_carries_a_reason(self) -> None:
        run = runs.skipped(helpers.build_task(), FIRED_AT, 'consent revoked')
        self.assertEqual('skipped', run.state)
        self.assertEqual('consent revoked', run.error_message)
        self.assertTrue(run.is_terminal)
        self.assertEqual(0, run.http_status)


class HistoryTests(helpers.TestCase):
    """Round-trip against the live ClickHouse `root:services` boots."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.assertTrue(await clickhouse.initialize())
        await clickhouse.setup_schema()
        self.task = helpers.build_task(id=uuid.uuid4())

    async def asyncTearDown(self) -> None:
        await clickhouse.aclose()
        await super().asyncTearDown()

    async def test_records_and_reads_back(self) -> None:
        run = runs.start(self.task, FIRED_AT)
        await runs.record(run)
        fetched = await runs.get(run.run_id)
        assert fetched is not None
        self.assertEqual(run.run_id, fetched.run_id)
        self.assertEqual('running', fetched.state)

    async def test_terminal_row_supersedes_running(self) -> None:
        run = runs.start(self.task, FIRED_AT)
        await runs.record(run)
        await runs.record(
            runs.finish(run, 'succeeded', runs.Outcome(http_status=202))
        )
        history = await runs.for_task(self.task.id)
        matching = [item for item in history if item.run_id == run.run_id]
        self.assertEqual(1, len(matching))
        self.assertEqual('succeeded', matching[0].state)

    async def test_unknown_run(self) -> None:
        self.assertIsNone(await runs.get(str(uuid.uuid4())))

    async def test_history_is_newest_first(self) -> None:
        for index in range(3):
            fired = FIRED_AT + datetime.timedelta(hours=index)
            await runs.record(
                runs.finish(
                    runs.start(self.task, fired),
                    'succeeded',
                    runs.Outcome(http_status=202),
                )
            )
        history = await runs.for_task(self.task.id, limit=2)
        self.assertEqual(2, len(history))
        self.assertGreater(history[0].fired_at, history[1].fired_at)

    async def test_no_effect_round_trips_as_its_own_state(self) -> None:
        run = runs.finish(
            runs.start(self.task, FIRED_AT),
            'no_effect',
            runs.Outcome(http_status=204),
        )
        await runs.record(run)
        fetched = await runs.get(run.run_id)
        assert fetched is not None
        self.assertEqual('no_effect', fetched.state)
        self.assertEqual(204, fetched.http_status)
