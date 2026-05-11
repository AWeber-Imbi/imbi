"""Unit tests for the access_log middleware."""

import logging
import typing
import unittest
from collections import abc

from imbi_common import access_log


class _RecordingApp:
    """ASGI app that records calls and replies with a configurable status."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.scopes: list[abc.MutableMapping[str, typing.Any]] = []

    async def __call__(
        self,
        scope: abc.MutableMapping[str, typing.Any],
        receive: abc.Callable[[], abc.Awaitable[typing.Any]],
        send: abc.Callable[
            [abc.MutableMapping[str, typing.Any]], abc.Awaitable[None]
        ],
    ) -> None:
        self.scopes.append(scope)
        if scope['type'] != 'http':
            return
        await send(
            {
                'type': 'http.response.start',
                'status': self.status,
                'headers': [],
            }
        )
        await send({'type': 'http.response.body', 'body': b''})


def _http_scope(
    path: str = '/foo',
    method: str = 'GET',
    query: bytes = b'',
) -> dict[str, typing.Any]:
    return {
        'type': 'http',
        'http_version': '1.1',
        'method': method,
        'path': path,
        'query_string': query,
        'client': ('10.0.0.1', 51234),
    }


async def _noop_receive() -> typing.Any:  # pragma: no cover - never awaited
    raise AssertionError('receive should not be called')


async def _noop_send(
    _message: abc.MutableMapping[str, typing.Any],
) -> None:
    return None


class AccessLogMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_logs_normal_request(self) -> None:
        app = _RecordingApp(status=200)
        middleware = access_log.AccessLogMiddleware(app)
        with self.assertLogs('imbi_common.access', level=logging.INFO) as cm:
            await middleware(_http_scope(), _noop_receive, _noop_send)
        self.assertEqual(len(cm.records), 1)
        self.assertIn('"GET /foo HTTP/1.1" 200', cm.records[0].getMessage())
        self.assertIn('10.0.0.1:51234', cm.records[0].getMessage())

    async def test_quiet_path_success_is_silenced(self) -> None:
        app = _RecordingApp(status=200)
        middleware = access_log.AccessLogMiddleware(
            app, quiet_paths={'/status'}
        )
        logger = logging.getLogger('imbi_common.access')
        with self.assertNoLogs(logger=logger, level=logging.INFO):
            await middleware(
                _http_scope(path='/status'), _noop_receive, _noop_send
            )

    async def test_quiet_path_failure_is_logged(self) -> None:
        app = _RecordingApp(status=404)
        middleware = access_log.AccessLogMiddleware(
            app, quiet_paths={'/status'}
        )
        with self.assertLogs('imbi_common.access', level=logging.INFO) as cm:
            await middleware(
                _http_scope(path='/status'), _noop_receive, _noop_send
            )
        self.assertEqual(len(cm.records), 1)
        self.assertIn('"GET /status HTTP/1.1" 404', cm.records[0].getMessage())

    async def test_quiet_path_5xx_is_logged(self) -> None:
        app = _RecordingApp(status=500)
        middleware = access_log.AccessLogMiddleware(
            app, quiet_paths={'/status'}
        )
        with self.assertLogs('imbi_common.access', level=logging.INFO) as cm:
            await middleware(
                _http_scope(path='/status'), _noop_receive, _noop_send
            )
        self.assertEqual(len(cm.records), 1)
        self.assertIn('"GET /status HTTP/1.1" 500', cm.records[0].getMessage())

    async def test_query_string_included(self) -> None:
        app = _RecordingApp(status=200)
        middleware = access_log.AccessLogMiddleware(app)
        with self.assertLogs('imbi_common.access', level=logging.INFO) as cm:
            await middleware(
                _http_scope(path='/foo', query=b'a=1&b=2'),
                _noop_receive,
                _noop_send,
            )
        self.assertIn('/foo?a=1&b=2', cm.records[0].getMessage())

    async def test_non_http_scope_passes_through_without_logging(
        self,
    ) -> None:
        app = _RecordingApp()
        middleware = access_log.AccessLogMiddleware(app)
        logger = logging.getLogger('imbi_common.access')
        scope = {'type': 'lifespan'}
        with self.assertNoLogs(logger=logger, level=logging.INFO):
            await middleware(scope, _noop_receive, _noop_send)
        self.assertEqual(app.scopes, [scope])

    async def test_exception_logs_default_500(self) -> None:
        class BoomApp:
            async def __call__(
                self,
                _scope: abc.MutableMapping[str, typing.Any],
                _receive: abc.Callable[[], abc.Awaitable[typing.Any]],
                _send: abc.Callable[
                    [abc.MutableMapping[str, typing.Any]],
                    abc.Awaitable[None],
                ],
            ) -> None:
                raise RuntimeError('boom')

        middleware = access_log.AccessLogMiddleware(BoomApp())
        with self.assertLogs('imbi_common.access', level=logging.INFO) as cm:
            with self.assertRaises(RuntimeError):
                await middleware(_http_scope(), _noop_receive, _noop_send)
        self.assertIn('500', cm.records[0].getMessage())

    async def test_custom_quiet_status_codes(self) -> None:
        app = _RecordingApp(status=301)
        middleware = access_log.AccessLogMiddleware(
            app,
            quiet_paths={'/redirect'},
            quiet_status_codes=range(200, 400),
        )
        logger = logging.getLogger('imbi_common.access')
        with self.assertNoLogs(logger=logger, level=logging.INFO):
            await middleware(
                _http_scope(path='/redirect'),
                _noop_receive,
                _noop_send,
            )

    async def test_custom_logger(self) -> None:
        app = _RecordingApp(status=200)
        custom = logging.getLogger('imbi_common.access.custom_test')
        middleware = access_log.AccessLogMiddleware(app, logger=custom)
        with self.assertLogs(custom, level=logging.INFO) as cm:
            await middleware(_http_scope(), _noop_receive, _noop_send)
        self.assertEqual(cm.records[0].name, custom.name)


if __name__ == '__main__':
    unittest.main()
