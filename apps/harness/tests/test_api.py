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
        self.assertIsNone(await self.api.heartbeat('r', 't'))

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
