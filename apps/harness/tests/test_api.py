import json
import unittest

import httpx
import respx

from imbi.harness import api

BASE = 'http://imbi.test'


class ApiTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.api = api.Api(BASE)
        self.mock = respx.mock(base_url=BASE, assert_all_called=False)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    async def test_pool_token(self) -> None:
        route = self.mock.post('/auth/token').respond(
            200, json={'access_token': 'pool-token'}
        )
        self.assertEqual(
            await self.api.pool_token('id', 'secret'), 'pool-token'
        )
        body = route.calls.last.request.content.decode()
        self.assertIn('grant_type=client_credentials', body)

    async def test_pool_token_refused(self) -> None:
        self.mock.post('/auth/token').respond(401)
        with self.assertRaises(api.Refused) as ctx:
            await self.api.pool_token('id', 'bad')
        self.assertEqual(ctx.exception.code, 'invalid_pool_credential')

    async def test_register_sends_bearer(self) -> None:
        route = self.mock.post('/harness/runners').respond(
            201, json={'runner_id': 'r'}
        )
        body = await self.api.register('pool-token', 'general', 'pod', '1')
        self.assertEqual(body, {'runner_id': 'r'})
        request = route.calls.last.request
        self.assertEqual(request.headers['Authorization'], 'Bearer pool-token')

    async def test_claim_no_content(self) -> None:
        self.mock.post('/harness/runners/r/claim').respond(204)
        self.assertIsNone(await self.api.claim('r', 't', 0))

    async def test_claim(self) -> None:
        route = self.mock.post('/harness/runners/r/claim').respond(
            200, json={'chain_id': 'c'}
        )
        self.assertEqual(await self.api.claim('r', 't', 5), {'chain_id': 'c'})
        self.assertEqual(route.calls.last.request.url.params['wait'], '5')

    async def test_error_code_from_envelope(self) -> None:
        self.mock.post('/harness/executor/secret-materializations').respond(
            409, json={'detail': {'error': 'resolution_already_used'}}
        )
        with self.assertRaises(api.Refused) as ctx:
            await self.api.materialize('e', {'handle': 'h'})
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.code, 'resolution_already_used')

    async def test_error_without_envelope(self) -> None:
        self.mock.post('/harness/runners/r/heartbeat').respond(
            502, text='bad gateway'
        )
        with self.assertRaises(api.Refused) as ctx:
            await self.api.heartbeat('r', 't')
        self.assertEqual(ctx.exception.code, '502')

    async def test_error_with_a_json_body_that_is_not_an_object(self) -> None:
        for body in (b'null', b'[1]', b'"text"'):
            with self.subTest(body=body):
                self.mock.post('/harness/runners/r/finish').respond(
                    500,
                    content=body,
                    headers={'Content-Type': 'application/json'},
                )
                with self.assertRaises(api.Refused) as ctx:
                    await self.api.finish('r', 't')
                self.assertEqual(ctx.exception.code, '500')

    async def test_heartbeat_reads_only_the_status(self) -> None:
        self.mock.post('/harness/runners/r/heartbeat').respond(
            200, text='not json'
        )
        # The lease is renewed by the status; a bad body gives no tokens.
        self.assertEqual(await self.api.heartbeat('r', 't'), {})

    async def test_heartbeat_renews_api_tokens(self) -> None:
        route = self.mock.post('/harness/runners/r/heartbeat').respond(
            200,
            json={
                'state': 'busy',
                'api_tokens': {'T-1': {'token': 'new', 'expires_at': 'x'}},
            },
        )
        self.assertEqual(
            await self.api.heartbeat('r', 't', ['T-1']), {'T-1': 'new'}
        )
        self.assertEqual(
            json.loads(route.calls.last.request.content), {'tasks': ['T-1']}
        )

    async def test_other_routes(self) -> None:
        self.mock.post('/harness/runners/r/heartbeat').respond(
            200, json={'state': 'idle'}
        )
        self.mock.post('/harness/runners/r/finish').respond(200, json={})
        self.mock.post('/harness/secret-resolutions').respond(
            201, json={'handle': 'h'}
        )
        self.mock.post(
            '/harness/executor/secret-resolutions/x/release'
        ).respond(200, json={'state': 'released'})
        await self.api.heartbeat('r', 't')
        await self.api.finish('r', 't')
        self.assertEqual(
            await self.api.create_resolution('a', {}), {'handle': 'h'}
        )
        self.assertEqual(
            await self.api.release('e', 'x'), {'state': 'released'}
        )

    async def test_transport_error_is_not_refused(self) -> None:
        self.mock.post('/harness/runners/r/heartbeat').mock(
            side_effect=httpx.ConnectError('down')
        )
        with self.assertRaises(httpx.ConnectError):
            await self.api.heartbeat('r', 't')


class TaskApiTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.api = api.TaskApi(api.Api(BASE), 'iat_token', 'org', 'T-1')
        self.mock = respx.mock(base_url=BASE, assert_all_called=True)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    async def test_routes(self) -> None:
        base = '/organizations/org/agent-tasks/T-1'
        routes = {
            name: self.mock.post(base + path).respond(200, json={'ok': name})
            for name, path in (
                ('open', '/sessions'),
                ('heartbeat', '/sessions/s/heartbeat'),
                ('close', '/sessions/s/close'),
                ('events', '/events'),
                ('usage', '/usage'),
                ('outcome', '/outcome'),
            )
        }
        resolution = self.mock.post('/harness/secret-resolutions').respond(
            201, json={'handle': 'h'}
        )
        await self.api.open_session('k', 'pod')
        await self.api.heartbeat('s')
        await self.api.close_session('s', 'stopped')
        await self.api.append_events('s', [{'type': 'turn'}])
        await self.api.report_usage({'model_id': 'm'})
        await self.api.set_outcome('done_acted', None)
        await self.api.create_resolution({'purpose': 'p'})
        for route in routes.values():
            request = route.calls.last.request
            self.assertEqual(
                request.headers['Authorization'], 'Bearer iat_token'
            )
        self.assertEqual(
            json.loads(routes['open'].calls.last.request.content),
            {'session_key': 'k', 'harness_instance': 'pod'},
        )
        self.assertEqual(
            json.loads(routes['events'].calls.last.request.content),
            {'session_id': 's', 'events': [{'type': 'turn'}]},
        )
        self.assertEqual(
            json.loads(resolution.calls.last.request.content),
            {'short_id': 'T-1', 'purpose': 'p'},
        )

    def test_items(self) -> None:
        self.assertEqual(api.items({'a': None}, 'a'), [])
        self.assertEqual(api.items({'a': [1]}, 'a'), [1])


class SliceTwoRoutesTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = api.Api(BASE)
        self.api = api.TaskApi(self.client, 'iat_token', 'org', 'T-1')
        self.mock = respx.mock(base_url=BASE, assert_all_called=True)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    async def test_routes(self) -> None:
        events = self.mock.get('/harness/tasks/T-1/events').respond(
            200, json=[{'seq': 3}]
        )
        child = self.mock.post('/harness/tasks/T-1/children').respond(
            201, json={'short_id': 'T-2'}
        )
        check = self.mock.post('/harness/tasks/T-1/tool-calls/check').respond(
            200, json={'allowed': True}
        )
        request = self.mock.post(
            '/organizations/org/agent-tasks/T-1/requests'
        ).respond(201, json={'request': {'id': 'q'}})
        claim = self.mock.post('/harness/runners/r/chain/claim')
        claim.side_effect = [
            httpx.Response(200, json={'chain_id': 'c'}),
            httpx.Response(204),
        ]
        self.assertEqual(await self.api.events(2), [{'seq': 3}])
        self.assertEqual(
            events.calls.last.request.url.params['after_seq'], '2'
        )
        await self.api.create_child({'agent_slug': 'a'})
        self.assertEqual(
            json.loads(child.calls.last.request.content), {'agent_slug': 'a'}
        )
        await self.api.check_tool('deploy.run')
        self.assertEqual(
            json.loads(check.calls.last.request.content),
            {'tool_key': 'deploy.run'},
        )
        await self.api.open_request({'kind': 'feedback'})
        self.assertEqual(
            request.calls.last.request.headers['Authorization'],
            'Bearer iat_token',
        )
        self.assertEqual(
            await self.client.chain_claim('r', 'rt'), {'chain_id': 'c'}
        )
        self.assertIsNone(await self.client.chain_claim('r', 'rt'))
