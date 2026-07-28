import datetime
import unittest
import uuid
import zoneinfo

import pydantic

from apps.scheduler.tests import helpers
from imbi.scheduler import models, triggers


class IdentityTests(unittest.TestCase):
    def test_delegated_user_requires_consent(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.Identity(kind='delegated_user', subject='gavinr@aweber.com')

    def test_delegated_user_with_consent(self) -> None:
        identity = models.Identity(
            kind='delegated_user',
            subject='gavinr@aweber.com',
            consent_id='c-1',
        )
        self.assertEqual('imbi-api:*', identity.scope)

    def test_service_account_rejects_consent(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.Identity(
                kind='service_account',
                subject='imbi-scheduler',
                consent_id='c-1',
            )


class ApiTargetTests(unittest.TestCase):
    def test_rejects_absolute_url(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.ApiTarget(method='GET', path='https://example.com/x')

    def test_rejects_protocol_relative_url(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.ApiTarget(method='GET', path='//example.com/x')

    def test_rejects_relative_path(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.ApiTarget(method='GET', path='scoring/recompute-all')

    def test_accepts_rooted_path(self) -> None:
        target = models.ApiTarget(method='GET', path='/projects')
        self.assertEqual('api', target.kind)


class ExecutionPolicyTests(unittest.TestCase):
    def test_defaults(self) -> None:
        policy = models.ExecutionPolicy()
        self.assertEqual(120, policy.timeout)
        self.assertEqual(300, policy.misfire_grace_time)
        self.assertTrue(policy.coalesce)
        self.assertEqual('exponential', policy.retry_backoff)

    def test_rejects_zero_timeout(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.ExecutionPolicy(timeout=0)

    def test_rejects_negative_retries(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.ExecutionPolicy(retries=-1)

    def test_rejects_zero_instances(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.ExecutionPolicy(max_running_instances=0)

    def test_rejects_negative_grace(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            models.ExecutionPolicy(misfire_grace_time=-1)

    def test_grace_may_be_disabled(self) -> None:
        self.assertIsNone(
            models.ExecutionPolicy(misfire_grace_time=None).misfire_grace_time
        )


class TaskTests(unittest.TestCase):
    def test_api_target_requires_identity(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            helpers.build_task(identity=None)

    def test_gateway_target_refuses_identity(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            helpers.build_task(
                target=models.GatewayTarget(webhook_id='w-1', payload={})
            )

    def test_gateway_target_without_identity(self) -> None:
        task = helpers.build_task(
            identity=None,
            target=models.GatewayTarget(webhook_id='w-1', payload={'a': 1}),
        )
        self.assertEqual('gateway:w-1', task.principal_name)

    def test_principal_name_is_the_subject(self) -> None:
        self.assertEqual('imbi-scheduler', helpers.build_task().principal_name)

    def test_target_summary_for_api(self) -> None:
        self.assertEqual(
            'POST /scoring/recompute-all',
            helpers.build_task().target_summary(),
        )

    def test_target_summary_for_gateway(self) -> None:
        task = helpers.build_task(
            identity=None,
            target=models.GatewayTarget(webhook_id='w-1', payload={}),
        )
        self.assertEqual('POST /notifications/w-1', task.target_summary())

    def test_rejects_unknown_timezone(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            helpers.build_task(timezone='Mars/Olympus_Mons')

    def test_tzinfo_round_trips(self) -> None:
        task = helpers.build_task(timezone='America/New_York')
        self.assertEqual(zoneinfo.ZoneInfo('America/New_York'), task.tzinfo)

    def test_next_fire_time_uses_task_timezone(self) -> None:
        task = helpers.build_task(
            timezone='America/New_York',
            trigger=triggers.CronTrigger(expression='0 6 * * *'),
        )
        fires = task.next_fire_time(
            datetime.datetime(2026, 7, 28, 5, tzinfo=datetime.UTC)
        )
        # 06:00 EDT is 10:00 UTC.
        self.assertEqual(
            datetime.datetime(2026, 7, 28, 10, tzinfo=datetime.UTC), fires
        )

    def test_rejects_bad_slug(self) -> None:
        for slug in ('Nightly', 'nightly_recompute', '-nightly', 'a' * 65):
            with self.subTest(slug=slug):
                with self.assertRaises(pydantic.ValidationError):
                    helpers.build_task(slug=slug)

    def test_accepts_single_character_slug(self) -> None:
        self.assertEqual('a', helpers.build_task(slug='a').slug)

    def test_round_trips_through_json(self) -> None:
        task = helpers.build_task()
        restored = models.Task.model_validate(task.model_dump(mode='json'))
        self.assertEqual(task, restored)

    def test_defaults(self) -> None:
        task = helpers.build_task()
        self.assertTrue(task.enabled)
        self.assertEqual([], task.tags)
        self.assertEqual(0, task.consecutive_skips)
        self.assertEqual(0, task.consecutive_no_effect)
        self.assertIsNone(task.next_run_at)
        self.assertIsInstance(task.id, uuid.UUID)


class RunStateTests(unittest.TestCase):
    def test_no_effect_is_terminal_and_distinct(self) -> None:
        self.assertIn('no_effect', models.TERMINAL_RUN_STATES)
        self.assertNotIn('running', models.TERMINAL_RUN_STATES)
        self.assertNotIn('pending', models.TERMINAL_RUN_STATES)
