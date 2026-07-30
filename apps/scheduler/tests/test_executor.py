import datetime
import unittest

import httpx
import respx

from apps.scheduler.tests import helpers
from imbi.common import clickhouse
from imbi.scheduler import (
    executor,
    identity,
    models,
    render,
    runs,
    settings,
)

FIRED_AT = datetime.datetime(2026, 7, 28, 6, tzinfo=datetime.UTC)
API_URL = 'http://api.test'
GATEWAY_URL = 'http://gateway.test'


def config(**overrides: object) -> settings.Scheduler:
    values: dict[str, object] = {
        'IMBI_INTERNAL_API_URL': API_URL,
        'gateway_url': GATEWAY_URL,
        'sa_slug': 'imbi-scheduler',
        'sa_client_id': 'cid',
        'sa_client_secret': 'secret',
    }
    values.update(overrides)
    return settings.Scheduler.model_validate(values)


class ExecutorTestCase(helpers.TestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # The executor writes the `running` row itself, so history is live
        # here. respx does not intercept clickhouse-connect (urllib3, not
        # httpx), so the two coexist.
        self.assertTrue(await clickhouse.initialize())
        await clickhouse.setup_schema()
        self.settings = config()
        self.client = httpx.AsyncClient()
        self.resolver = identity.Resolver(self.client, self.settings)
        self.executor = executor.Executor(
            self.client, self.resolver, self.settings
        )
        self.mock = respx.mock(assert_all_called=False)
        self.mock.start()
        self.token_route = self.mock.post(f'{API_URL}/auth/token').mock(
            return_value=httpx.Response(
                200, json={'access_token': 'sa-token', 'expires_in': 900}
            )
        )

    async def asyncTearDown(self) -> None:
        self.mock.stop()
        await self.client.aclose()
        await clickhouse.aclose()
        await super().asyncTearDown()


class ApiTargetTests(ExecutorTestCase):
    async def test_success(self) -> None:
        route = self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            return_value=httpx.Response(202, json={'queued': 12})
        )
        run = await self.executor.execute(helpers.build_task(), FIRED_AT)
        self.assertEqual('succeeded', run.state)
        self.assertEqual(202, run.http_status)
        self.assertEqual('imbi-scheduler', run.principal_name)
        self.assertTrue(route.called)

    async def test_sends_the_service_account_bearer(self) -> None:
        route = self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            return_value=httpx.Response(202)
        )
        await self.executor.execute(helpers.build_task(), FIRED_AT)
        self.assertEqual(
            'Bearer sa-token', route.calls[0].request.headers['authorization']
        )

    async def test_client_error_does_not_retry(self) -> None:
        route = self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            return_value=httpx.Response(403, text='forbidden')
        )
        task = helpers.build_task(
            execution=models.ExecutionPolicy(retries=3, retry_backoff='none')
        )
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('failed', run.state)
        self.assertEqual('http_403', run.error_type)
        self.assertEqual(1, route.call_count)

    async def test_server_error_retries_to_exhaustion(self) -> None:
        route = self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            return_value=httpx.Response(503)
        )
        task = helpers.build_task(
            execution=models.ExecutionPolicy(retries=2, retry_backoff='none')
        )
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('failed', run.state)
        self.assertEqual(3, route.call_count)
        self.assertEqual(3, run.attempt)

    async def test_rate_limit_is_retried(self) -> None:
        route = self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            side_effect=[httpx.Response(429), httpx.Response(202)]
        )
        task = helpers.build_task(
            execution=models.ExecutionPolicy(retries=1, retry_backoff='none')
        )
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('succeeded', run.state)
        self.assertEqual(2, route.call_count)

    async def test_timeout(self) -> None:
        self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            side_effect=httpx.ReadTimeout('too slow')
        )
        task = helpers.build_task(execution=models.ExecutionPolicy(retries=0))
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('timed_out', run.state)
        self.assertEqual('timeout', run.error_type)

    async def test_transport_error(self) -> None:
        self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            side_effect=httpx.ConnectError('refused')
        )
        run = await self.executor.execute(helpers.build_task(), FIRED_AT)
        self.assertEqual('failed', run.state)
        self.assertEqual('transport', run.error_type)

    async def test_organization_scoped_path(self) -> None:
        route = self.mock.post(
            f'{API_URL}/organizations/aweber/scoring/recompute-all'
        ).mock(return_value=httpx.Response(202))
        task = helpers.build_task(organization='aweber')
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('succeeded', run.state)
        self.assertTrue(route.called)

    async def test_a_prefix_match_is_not_a_scope_match(self) -> None:
        # Without a separator boundary a task scoped to `acme` reaches
        # `acme-corp` unrewritten — a different organization, with this
        # task's credential.
        route = self.mock.post(
            f'{API_URL}/organizations/acme/organizations/acme-corp/projects'
        ).mock(return_value=httpx.Response(202))
        task = helpers.build_task(
            organization='acme',
            target=models.ApiTarget(
                method='POST', path='/organizations/acme-corp/projects'
            ),
        )
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('succeeded', run.state)
        self.assertTrue(route.called)

    async def test_an_exact_scope_match_is_not_rewritten(self) -> None:
        route = self.mock.post(f'{API_URL}/organizations/acme').mock(
            return_value=httpx.Response(202)
        )
        task = helpers.build_task(
            organization='acme',
            target=models.ApiTarget(method='POST', path='/organizations/acme'),
        )
        await self.executor.execute(task, FIRED_AT)
        self.assertTrue(route.called)

    async def test_renders_the_body_and_query(self) -> None:
        route = self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            return_value=httpx.Response(202)
        )
        task = helpers.build_task(
            target=models.ApiTarget(
                method='POST',
                path='/scoring/recompute-all',
                query={'slug': '{{ task.slug }}'},
                body={'reason': 'run {{ run.id }}'},
            )
        )
        await self.executor.execute(task, FIRED_AT)
        request = route.calls[0].request
        self.assertIn('slug=nightly-recompute', str(request.url))
        self.assertIn(b'run ', request.content)

    async def test_sends_the_idempotency_key(self) -> None:
        route = self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            return_value=httpx.Response(202)
        )
        task = helpers.build_task(
            execution=models.ExecutionPolicy(
                idempotency_key='{{ task.slug }}-{{ run.id }}'
            )
        )
        await self.executor.execute(task, FIRED_AT)
        self.assertTrue(
            route.calls[0]
            .request.headers['idempotency-key']
            .startswith('nightly-recompute-')
        )

    async def test_render_failure_makes_no_request(self) -> None:
        route = self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            return_value=httpx.Response(202)
        )
        task = helpers.build_task(
            target=models.ApiTarget(
                method='POST', path='/scoring/{{ missing.thing }}'
            )
        )
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('failed', run.state)
        self.assertEqual('render', run.error_type)
        self.assertFalse(route.called)


class RunningRowTests(ExecutorTestCase):
    """The run is visible while it runs, not only once it is over."""

    async def test_a_running_row_is_written_before_the_request(self) -> None:
        seen: list[str] = []

        async def observe(_request: httpx.Request) -> httpx.Response:
            # Reading history from inside the handler is the only way to
            # assert on a row that a later write supersedes.
            history = await runs.for_task(task.id)
            seen.extend(run.state for run in history)
            return httpx.Response(202)

        task = helpers.build_task()
        self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            side_effect=observe
        )
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual(['running'], seen)
        self.assertEqual('succeeded', run.state)

    async def test_the_terminal_row_supersedes_it(self) -> None:
        task = helpers.build_task()
        self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            return_value=httpx.Response(202)
        )
        run = await self.executor.execute(task, FIRED_AT)
        await runs.record(run)
        history = await runs.for_task(task.id)
        self.assertEqual(1, len(history))
        self.assertEqual('succeeded', history[0].state)

    async def test_a_retried_run_still_collapses_to_its_last_attempt(
        self,
    ) -> None:
        # Retries do not add rows: the sort key is (task_id, run_id), and only
        # the attempt that ended the run is recorded.
        task = helpers.build_task(
            execution=models.ExecutionPolicy(retries=2, retry_backoff='none')
        )
        self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(503),
                httpx.Response(202),
            ]
        )
        run = await self.executor.execute(task, FIRED_AT)
        await runs.record(run)
        history = await runs.for_task(task.id)
        self.assertEqual(1, len(history))
        self.assertEqual('succeeded', history[0].state)
        self.assertEqual(3, history[0].attempt)

    async def test_an_identity_skip_reuses_the_running_run(self) -> None:
        # One firing is one run_id: a skip that minted its own would leave the
        # `running` row behind forever as a second, never-finished run.
        self.token_route.mock(return_value=httpx.Response(401))
        task = helpers.build_task()
        run = await self.executor.execute(task, FIRED_AT)
        await runs.record(run)
        history = await runs.for_task(task.id)
        self.assertEqual(1, len(history))
        self.assertEqual('skipped', history[0].state)


class ReauthTests(ExecutorTestCase):
    """A 401 earns exactly one re-auth, and it costs no retries."""

    async def test_a_401_re_authenticates_and_retries_once(self) -> None:
        route = self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            side_effect=[httpx.Response(401), httpx.Response(202)]
        )
        self.token_route.mock(
            side_effect=[
                httpx.Response(
                    200, json={'access_token': 'stale', 'expires_in': 900}
                ),
                httpx.Response(
                    200, json={'access_token': 'fresh', 'expires_in': 900}
                ),
            ]
        )
        task = helpers.build_task(execution=models.ExecutionPolicy(retries=0))
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('succeeded', run.state)
        self.assertEqual(2, self.token_route.call_count)
        self.assertEqual(
            ['Bearer stale', 'Bearer fresh'],
            [call.request.headers['authorization'] for call in route.calls],
        )

    async def test_the_re_auth_does_not_consume_a_retry(self) -> None:
        route = self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            side_effect=[
                httpx.Response(401),
                httpx.Response(503),
                httpx.Response(202),
            ]
        )
        task = helpers.build_task(
            execution=models.ExecutionPolicy(retries=1, retry_backoff='none')
        )
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('succeeded', run.state)
        self.assertEqual(3, route.call_count)

    async def test_a_second_401_is_the_answer_not_the_credential(self) -> None:
        route = self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            return_value=httpx.Response(401)
        )
        task = helpers.build_task(execution=models.ExecutionPolicy(retries=0))
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('failed', run.state)
        self.assertEqual('http_401', run.error_type)
        self.assertEqual(2, route.call_count)
        self.assertEqual(2, self.token_route.call_count)

    async def test_a_401_without_a_bearer_is_not_re_authenticated(
        self,
    ) -> None:
        route = self.mock.post(f'{GATEWAY_URL}/notifications/w-1').mock(
            return_value=httpx.Response(401)
        )
        task = helpers.build_task(
            slug='synthetic-delivery',
            identity=None,
            target=models.GatewayTarget(webhook_id='w-1', payload={}),
        )
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('failed', run.state)
        self.assertEqual(1, route.call_count)
        self.assertFalse(self.token_route.called)

    async def test_a_failed_re_auth_skips_rather_than_fails(self) -> None:
        self.mock.post(f'{API_URL}/scoring/recompute-all').mock(
            return_value=httpx.Response(401)
        )
        self.token_route.mock(
            side_effect=[
                httpx.Response(
                    200, json={'access_token': 'stale', 'expires_in': 900}
                ),
                httpx.Response(503),
            ]
        )
        task = helpers.build_task(execution=models.ExecutionPolicy(retries=0))
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('skipped', run.state)
        self.assertIn('503', run.error_message)


class ApiPrefixTests(ExecutorTestCase):
    """imbi-api mounts its routers under the path of its public URL.

    ``IMBI_INTERNAL_API_URL`` is a bare origin, so without re-deriving that
    prefix every request the scheduler makes is a 404.
    """

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.settings = config(IMBI_API_URL='https://imbi.test/api')
        self.resolver = identity.Resolver(self.client, self.settings)
        self.executor = executor.Executor(
            self.client, self.resolver, self.settings
        )
        self.token_route = self.mock.post(f'{API_URL}/api/auth/token').mock(
            return_value=httpx.Response(
                200, json={'access_token': 'sa-token', 'expires_in': 900}
            )
        )

    def test_base_url_carries_the_prefix(self) -> None:
        self.assertEqual(f'{API_URL}/api', self.settings.api_base_url)

    async def test_the_token_request_is_prefixed(self) -> None:
        self.mock.post(f'{API_URL}/api/scoring/recompute-all').mock(
            return_value=httpx.Response(202)
        )
        run = await self.executor.execute(helpers.build_task(), FIRED_AT)
        self.assertEqual('succeeded', run.state)
        self.assertTrue(self.token_route.called)

    async def test_the_target_request_is_prefixed(self) -> None:
        route = self.mock.post(f'{API_URL}/api/scoring/recompute-all').mock(
            return_value=httpx.Response(202)
        )
        await self.executor.execute(helpers.build_task(), FIRED_AT)
        self.assertEqual(
            f'{API_URL}/api/scoring/recompute-all',
            str(route.calls[0].request.url),
        )

    async def test_the_organization_scope_stays_inside_the_prefix(
        self,
    ) -> None:
        route = self.mock.post(
            f'{API_URL}/api/organizations/aweber/scoring/recompute-all'
        ).mock(return_value=httpx.Response(202))
        run = await self.executor.execute(
            helpers.build_task(organization='aweber'), FIRED_AT
        )
        self.assertEqual('succeeded', run.state)
        self.assertTrue(route.called)


class GatewayTargetTests(ExecutorTestCase):
    def _task(self, **overrides: object) -> models.Task:
        fields: dict[str, object] = {
            'slug': 'synthetic-delivery',
            'identity': None,
            'target': models.GatewayTarget(
                webhook_id='w-1', payload={'event': 'ping'}
            ),
        }
        fields.update(overrides)
        return helpers.build_task(**fields)

    async def test_accepted_is_success(self) -> None:
        route = self.mock.post(f'{GATEWAY_URL}/notifications/w-1').mock(
            return_value=httpx.Response(202)
        )
        run = await self.executor.execute(self._task(), FIRED_AT)
        self.assertEqual('succeeded', run.state)
        self.assertTrue(route.called)

    async def test_dropped_is_no_effect_not_success(self) -> None:
        self.mock.post(f'{GATEWAY_URL}/notifications/w-1').mock(
            return_value=httpx.Response(204)
        )
        run = await self.executor.execute(self._task(), FIRED_AT)
        self.assertEqual('no_effect', run.state)
        self.assertEqual(204, run.http_status)

    async def test_no_effect_is_not_retried(self) -> None:
        route = self.mock.post(f'{GATEWAY_URL}/notifications/w-1').mock(
            return_value=httpx.Response(204)
        )
        task = self._task(
            execution=models.ExecutionPolicy(retries=3, retry_backoff='none')
        )
        await self.executor.execute(task, FIRED_AT)
        self.assertEqual(1, route.call_count)

    async def test_unparseable_body_is_failure(self) -> None:
        self.mock.post(f'{GATEWAY_URL}/notifications/w-1').mock(
            return_value=httpx.Response(422)
        )
        run = await self.executor.execute(self._task(), FIRED_AT)
        self.assertEqual('failed', run.state)

    async def test_carries_no_authorization_header(self) -> None:
        route = self.mock.post(f'{GATEWAY_URL}/notifications/w-1').mock(
            return_value=httpx.Response(202)
        )
        await self.executor.execute(self._task(), FIRED_AT)
        self.assertNotIn('authorization', route.calls[0].request.headers)
        self.assertFalse(self.token_route.called)

    async def test_principal_is_the_webhook(self) -> None:
        self.mock.post(f'{GATEWAY_URL}/notifications/w-1').mock(
            return_value=httpx.Response(202)
        )
        run = await self.executor.execute(self._task(), FIRED_AT)
        self.assertEqual('gateway:w-1', run.principal_name)
        self.assertEqual('none', run.identity_kind)

    async def test_renders_nested_payload_values(self) -> None:
        route = self.mock.post(f'{GATEWAY_URL}/notifications/w-1').mock(
            return_value=httpx.Response(202)
        )
        task = self._task(
            target=models.GatewayTarget(
                webhook_id='w-1',
                payload={'meta': {'slugs': ['{{ task.slug }}']}},
            )
        )
        await self.executor.execute(task, FIRED_AT)
        self.assertEqual(
            b'{"meta":{"slugs":["synthetic-delivery"]}}',
            route.calls[0].request.content,
        )


class IdentityFailureTests(ExecutorTestCase):
    async def test_unconfigured_service_account_skips(self) -> None:
        bare = config(sa_client_id=None, sa_client_secret=None)
        exec_ = executor.Executor(
            self.client, identity.Resolver(self.client, bare), bare
        )
        run = await exec_.execute(helpers.build_task(), FIRED_AT)
        self.assertEqual('skipped', run.state)
        self.assertIn('not configured', run.error_message)

    async def test_delegated_identity_skips_until_phase_two(self) -> None:
        task = helpers.build_task(
            identity=models.Identity(
                kind='delegated_user',
                subject='gavinr@aweber.com',
                consent_id='c-1',
            )
        )
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('skipped', run.state)
        self.assertIn('token-exchange', run.error_message)

    async def test_foreign_service_account_skips(self) -> None:
        task = helpers.build_task(
            identity=models.Identity(
                kind='service_account', subject='someone-else'
            )
        )
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual('skipped', run.state)
        self.assertIn('ADR 0002', run.error_message)

    async def test_token_endpoint_failure_skips(self) -> None:
        self.token_route.mock(return_value=httpx.Response(401))
        run = await self.executor.execute(helpers.build_task(), FIRED_AT)
        self.assertEqual('skipped', run.state)
        self.assertIn('401', run.error_message)

    async def test_skip_does_not_consume_retries(self) -> None:
        self.token_route.mock(return_value=httpx.Response(401))
        task = helpers.build_task(
            execution=models.ExecutionPolicy(retries=5, retry_backoff='none')
        )
        run = await self.executor.execute(task, FIRED_AT)
        self.assertEqual(1, run.attempt)
        self.assertEqual(1, self.token_route.call_count)


class ServiceAccountTokenTests(ExecutorTestCase):
    async def test_token_is_cached(self) -> None:
        await self.resolver.service_account.token()
        await self.resolver.service_account.token()
        self.assertEqual(1, self.token_route.call_count)

    async def test_invalidate_forces_a_refetch(self) -> None:
        await self.resolver.service_account.token()
        self.resolver.service_account.invalidate()
        await self.resolver.service_account.token()
        self.assertEqual(2, self.token_route.call_count)

    async def test_near_expiry_token_is_refreshed(self) -> None:
        self.token_route.mock(
            return_value=httpx.Response(
                200, json={'access_token': 'brief', 'expires_in': 10}
            )
        )
        await self.resolver.service_account.token()
        await self.resolver.service_account.token()
        self.assertEqual(2, self.token_route.call_count)

    async def test_missing_access_token(self) -> None:
        self.token_route.mock(return_value=httpx.Response(200, json={}))
        with self.assertRaises(identity.IdentityError):
            await self.resolver.service_account.token()

    async def test_transport_failure(self) -> None:
        self.token_route.mock(side_effect=httpx.ConnectError('refused'))
        with self.assertRaises(identity.IdentityError):
            await self.resolver.service_account.token()

    async def test_a_non_numeric_expires_in_is_an_identity_error(self) -> None:
        # Anything escaping as its own exception type would crash the firing
        # instead of recording it as `skipped`, which is what `execute` does
        # with an `IdentityError`.
        self.token_route.mock(
            return_value=httpx.Response(
                200, json={'access_token': 'x', 'expires_in': 'soon'}
            )
        )
        with self.assertRaises(identity.IdentityError):
            await self.resolver.service_account.token()

    async def test_a_null_expires_in_is_an_identity_error(self) -> None:
        self.token_route.mock(
            return_value=httpx.Response(
                200, json={'access_token': 'x', 'expires_in': None}
            )
        )
        with self.assertRaises(identity.IdentityError):
            await self.resolver.service_account.token()

    async def test_a_non_json_body_is_an_identity_error(self) -> None:
        self.token_route.mock(
            return_value=httpx.Response(200, content=b'not json')
        )
        with self.assertRaises(identity.IdentityError):
            await self.resolver.service_account.token()

    async def test_a_json_array_body_is_an_identity_error(self) -> None:
        self.token_route.mock(return_value=httpx.Response(200, json=[]))
        with self.assertRaises(identity.IdentityError):
            await self.resolver.service_account.token()


class BackoffTests(unittest.TestCase):
    def test_none(self) -> None:
        task = helpers.build_task(
            execution=models.ExecutionPolicy(retry_backoff='none')
        )
        self.assertEqual(0.0, executor._backoff(task, 3))

    def test_linear(self) -> None:
        task = helpers.build_task(
            execution=models.ExecutionPolicy(retry_backoff='linear')
        )
        self.assertEqual(3.0, executor._backoff(task, 3))

    def test_exponential(self) -> None:
        task = helpers.build_task()
        self.assertEqual(
            [1.0, 2.0, 4.0],
            [executor._backoff(task, n) for n in (1, 2, 3)],
        )


class RenderTests(unittest.TestCase):
    def test_sandbox_blocks_attribute_escapes(self) -> None:
        renderer = render.Renderer({'task': {'slug': 'a'}})
        with self.assertRaises(render.RenderError):
            renderer.text("{{ ''.__class__.__mro__ }}")

    def test_strict_undefined(self) -> None:
        renderer = render.Renderer({})
        with self.assertRaises(render.RenderError):
            renderer.text('{{ nope }}')

    def test_document_leaves_keys_alone(self) -> None:
        renderer = render.Renderer({'task': {'slug': 'a'}})
        self.assertEqual(
            {'{{ literal }}': 'a'},
            renderer.document({'{{ literal }}': '{{ task.slug }}'}),
        )

    def test_document_passes_non_strings_through(self) -> None:
        renderer = render.Renderer({})
        self.assertEqual(
            {'n': 1, 'b': True, 'z': None},
            renderer.document({'n': 1, 'b': True, 'z': None}),
        )
