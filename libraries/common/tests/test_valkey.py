"""Tests for the valkey module."""

import unittest

import dotenv
import fastapi
import fastapi.testclient
import valkey.asyncio

from imbi.common import lifespan
from imbi.common import valkey as imbi_valkey

dotenv.load_dotenv()


class ValkeyLifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_yields_valkey_client(self) -> None:
        async with imbi_valkey.valkey_lifespan() as client:
            self.assertIsInstance(client, valkey.asyncio.Valkey)

    async def test_client_usable_inside_context(self) -> None:
        async with imbi_valkey.valkey_lifespan() as client:
            self.assertTrue(await client.ping())
            await client.set('imbi-common:test', 'value')
            self.assertEqual(b'value', await client.get('imbi-common:test'))
            await client.delete('imbi-common:test')


class ValkeyDependencyInjectionTests(unittest.TestCase):
    def test_client_injected_into_route(self) -> None:
        app = fastapi.FastAPI(
            lifespan=lifespan.Lifespan(imbi_valkey.valkey_lifespan),
        )

        @app.get('/test')
        async def handler(*, client: imbi_valkey.Client) -> dict[str, bool]:
            return {'pong': await client.ping()}

        with fastapi.testclient.TestClient(app) as test_client:
            response = test_client.get('/test')
            self.assertEqual(200, response.status_code)
            self.assertTrue(response.json()['pong'])
