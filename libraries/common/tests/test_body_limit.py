"""Tests for body_limit."""

import collections.abc
import unittest

import fastapi
import httpx
from fastapi import testclient

from imbi.common import body_limit


def _make_app() -> tuple[fastapi.FastAPI, list[str]]:
    reads: list[str] = []
    app = fastapi.FastAPI()

    @app.post('/echo')
    async def echo(  # pyright: ignore[reportUnusedFunction]
        request: fastapi.Request,
    ) -> dict[str, int]:
        reads.append('echo')
        return {'size': len(await request.body())}

    @app.post('/big/')
    async def big(  # pyright: ignore[reportUnusedFunction]
        request: fastapi.Request,
    ) -> dict[str, int]:
        return {'size': len(await request.body())}

    app.add_middleware(
        body_limit.BodyLimitMiddleware,
        limit=100,
        path_limits={'/big': 1000},
    )
    return app, reads


def _chunks(count: int) -> collections.abc.Iterator[bytes]:
    for _ in range(count):
        yield b'x' * 40


class BodyLimitMiddlewareTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app, self.reads = _make_app()
        self.client = testclient.TestClient(self.app)

    def assert_too_large(self, response: httpx.Response, limit: int) -> None:
        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            response.json(),
            {
                'detail': {
                    'error': 'payload_too_large',
                    'message': (
                        f'The request body is larger than {limit} bytes'
                    ),
                }
            },
        )

    def test_under_limit_passes(self) -> None:
        response = self.client.post('/echo', content=b'x' * 100)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'size': 100})

    def test_content_length_over_limit_refused_before_app(self) -> None:
        response = self.client.post('/echo', content=b'x' * 101)
        self.assert_too_large(response, 100)
        self.assertEqual(self.reads, [])

    def test_chunked_body_over_limit_refused(self) -> None:
        response = self.client.post('/echo', content=_chunks(3))
        self.assertEqual(
            response.request.headers.get('transfer-encoding'), 'chunked'
        )
        self.assertNotIn('content-length', response.request.headers)
        self.assert_too_large(response, 100)

    def test_chunked_body_under_limit_passes(self) -> None:
        response = self.client.post('/echo', content=_chunks(2))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'size': 80})

    def test_path_limit_allows_larger_body(self) -> None:
        response = self.client.post('/big/', content=b'x' * 1000)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'size': 1000})

    def test_path_limit_still_enforced(self) -> None:
        response = self.client.post('/big/', content=b'x' * 1001)
        self.assert_too_large(response, 1000)
