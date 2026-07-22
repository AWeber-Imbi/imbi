"""Unit tests for the access_log middleware."""

import logging
import typing
import unittest
from collections import abc
from unittest import mock

from imbi.common import access_log, otel
from imbi.common.auth import core


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
    headers: abc.Iterable[tuple[bytes, bytes]] = (),
) -> dict[str, typing.Any]:
    return {
        'type': 'http',
        'http_version': '1.1',
        'method': method,
        'path': path,
        'query_string': query,
        'client': ('10.0.0.1', 51234),
        'headers': list(headers),
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
        with self.assertLogs('imbi.common.access', level=logging.INFO) as cm:
            await middleware(_http_scope(), _noop_receive, _noop_send)
        self.assertEqual(len(cm.records), 1)
        self.assertIn('"GET /foo HTTP/1.1" 200', cm.records[0].getMessage())
        self.assertIn('10.0.0.1:51234', cm.records[0].getMessage())

    async def test_quiet_path_success_is_silenced(self) -> None:
        app = _RecordingApp(status=200)
        middleware = access_log.AccessLogMiddleware(
            app, quiet_paths={'/status'}
        )
        logger = logging.getLogger('imbi.common.access')
        with self.assertNoLogs(logger=logger, level=logging.INFO):
            await middleware(
                _http_scope(path='/status'), _noop_receive, _noop_send
            )

    async def test_quiet_path_failure_is_logged(self) -> None:
        app = _RecordingApp(status=404)
        middleware = access_log.AccessLogMiddleware(
            app, quiet_paths={'/status'}
        )
        with self.assertLogs('imbi.common.access', level=logging.INFO) as cm:
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
        with self.assertLogs('imbi.common.access', level=logging.INFO) as cm:
            await middleware(
                _http_scope(path='/status'), _noop_receive, _noop_send
            )
        self.assertEqual(len(cm.records), 1)
        self.assertIn('"GET /status HTTP/1.1" 500', cm.records[0].getMessage())

    async def test_query_string_included(self) -> None:
        app = _RecordingApp(status=200)
        middleware = access_log.AccessLogMiddleware(app)
        with self.assertLogs('imbi.common.access', level=logging.INFO) as cm:
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
        logger = logging.getLogger('imbi.common.access')
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
        with self.assertLogs('imbi.common.access', level=logging.INFO) as cm:
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
        logger = logging.getLogger('imbi.common.access')
        with self.assertNoLogs(logger=logger, level=logging.INFO):
            await middleware(
                _http_scope(path='/redirect'),
                _noop_receive,
                _noop_send,
            )

    async def test_access_log_context_appended(self) -> None:
        class ContextApp:
            async def __call__(
                self,
                scope: abc.MutableMapping[str, typing.Any],
                _receive: abc.Callable[[], abc.Awaitable[typing.Any]],
                send: abc.Callable[
                    [abc.MutableMapping[str, typing.Any]],
                    abc.Awaitable[None],
                ],
            ) -> None:
                scope.setdefault('state', {})['imbi_common_access_log'] = {
                    'event_type': 'whatever',
                    'selected': False,
                }
                await send(
                    {
                        'type': 'http.response.start',
                        'status': 200,
                        'headers': [],
                    }
                )
                await send({'type': 'http.response.body', 'body': b''})

        middleware = access_log.AccessLogMiddleware(ContextApp())
        scope = _http_scope()
        scope['state'] = {}
        with self.assertLogs('imbi.common.access', level=logging.INFO) as cm:
            await middleware(scope, _noop_receive, _noop_send)
        self.assertIn(
            ' 200 (event_type:whatever selected:False)',
            cm.records[0].getMessage(),
        )

    async def test_empty_access_log_context_omits_suffix(self) -> None:
        class ContextApp:
            async def __call__(
                self,
                scope: abc.MutableMapping[str, typing.Any],
                _receive: abc.Callable[[], abc.Awaitable[typing.Any]],
                send: abc.Callable[
                    [abc.MutableMapping[str, typing.Any]],
                    abc.Awaitable[None],
                ],
            ) -> None:
                scope.setdefault('state', {})['imbi_common_access_log'] = {}
                await send(
                    {
                        'type': 'http.response.start',
                        'status': 200,
                        'headers': [],
                    }
                )
                await send({'type': 'http.response.body', 'body': b''})

        middleware = access_log.AccessLogMiddleware(ContextApp())
        scope = _http_scope()
        scope['state'] = {}
        with self.assertLogs('imbi.common.access', level=logging.INFO) as cm:
            await middleware(scope, _noop_receive, _noop_send)
        message = cm.records[0].getMessage()
        self.assertTrue(message.endswith('200'), message)

    async def test_missing_state_omits_suffix(self) -> None:
        """Pure-ASGI scopes without ``state`` should still log cleanly."""
        app = _RecordingApp(status=200)
        middleware = access_log.AccessLogMiddleware(app)
        with self.assertLogs('imbi.common.access', level=logging.INFO) as cm:
            await middleware(_http_scope(), _noop_receive, _noop_send)
        message = cm.records[0].getMessage()
        self.assertTrue(message.endswith('200'), message)

    async def test_non_mapping_state_omits_suffix(self) -> None:
        """A ``state`` value that isn't a mapping must not raise."""
        app = _RecordingApp(status=200)
        middleware = access_log.AccessLogMiddleware(app)
        scope = _http_scope()
        scope['state'] = 'unexpected'
        with self.assertLogs('imbi.common.access', level=logging.INFO) as cm:
            await middleware(scope, _noop_receive, _noop_send)
        message = cm.records[0].getMessage()
        self.assertTrue(message.endswith('200'), message)

    async def test_non_mapping_access_log_value_omits_suffix(self) -> None:
        """A non-mapping ``imbi_common_access_log`` must not raise."""
        app = _RecordingApp(status=200)
        middleware = access_log.AccessLogMiddleware(app)
        scope = _http_scope()
        scope['state'] = {'imbi_common_access_log': ['not', 'a', 'mapping']}
        with self.assertLogs('imbi.common.access', level=logging.INFO) as cm:
            await middleware(scope, _noop_receive, _noop_send)
        message = cm.records[0].getMessage()
        self.assertTrue(message.endswith('200'), message)

    async def test_access_log_context_escapes_control_characters(
        self,
    ) -> None:
        """Newlines in context values must be escaped to prevent forging."""
        app = _RecordingApp(status=200)
        middleware = access_log.AccessLogMiddleware(app)
        scope = _http_scope()
        scope['state'] = {
            'imbi_common_access_log': {
                'note': 'line1\nline2',
                'cr\rkey': 'value\r',
            }
        }
        with self.assertLogs('imbi.common.access', level=logging.INFO) as cm:
            await middleware(scope, _noop_receive, _noop_send)
        message = cm.records[0].getMessage()
        self.assertNotIn('\n', message)
        self.assertNotIn('\r', message)
        self.assertIn(r'note:line1\nline2', message)
        self.assertIn(r'cr\rkey:value\r', message)

    async def test_trace_id_prepended_to_suffix(self) -> None:
        app = _RecordingApp(status=200)
        middleware = access_log.AccessLogMiddleware(app)
        with mock.patch.object(otel, 'current_trace_id') as get_id:
            get_id.return_value = 'cafebabedeadbeefcafebabedeadbeef'
            with self.assertLogs(
                'imbi.common.access', level=logging.INFO
            ) as cm:
                await middleware(_http_scope(), _noop_receive, _noop_send)
        self.assertIn(
            ' 200 (trace_id:cafebabedeadbeefcafebabedeadbeef)',
            cm.records[0].getMessage(),
        )

    async def test_trace_id_merges_with_handler_context(self) -> None:
        class ContextApp:
            async def __call__(
                self,
                scope: abc.MutableMapping[str, typing.Any],
                _receive: abc.Callable[[], abc.Awaitable[typing.Any]],
                send: abc.Callable[
                    [abc.MutableMapping[str, typing.Any]],
                    abc.Awaitable[None],
                ],
            ) -> None:
                scope.setdefault('state', {})['imbi_common_access_log'] = {
                    'event_type': 'whatever',
                }
                await send(
                    {
                        'type': 'http.response.start',
                        'status': 200,
                        'headers': [],
                    }
                )
                await send({'type': 'http.response.body', 'body': b''})

        middleware = access_log.AccessLogMiddleware(ContextApp())
        scope = _http_scope()
        scope['state'] = {}
        with mock.patch.object(otel, 'current_trace_id') as get_id:
            get_id.return_value = 'cafebabedeadbeefcafebabedeadbeef'
            with self.assertLogs(
                'imbi.common.access', level=logging.INFO
            ) as cm:
                await middleware(scope, _noop_receive, _noop_send)
        self.assertIn(
            ' 200 (trace_id:cafebabedeadbeefcafebabedeadbeef '
            'event_type:whatever)',
            cm.records[0].getMessage(),
        )

    async def test_trace_id_omitted_when_no_active_span(self) -> None:
        app = _RecordingApp(status=200)
        middleware = access_log.AccessLogMiddleware(app)
        with mock.patch.object(otel, 'current_trace_id') as get_id:
            get_id.return_value = None
            with self.assertLogs(
                'imbi.common.access', level=logging.INFO
            ) as cm:
                await middleware(_http_scope(), _noop_receive, _noop_send)
        message = cm.records[0].getMessage()
        self.assertNotIn('trace_id:', message)
        self.assertTrue(message.endswith('200'), message)

    async def test_include_trace_context_false_suppresses_lookup(
        self,
    ) -> None:
        app = _RecordingApp(status=200)
        middleware = access_log.AccessLogMiddleware(
            app, include_trace_context=False
        )
        with mock.patch.object(otel, 'current_trace_id') as get_id:
            get_id.return_value = 'cafebabedeadbeefcafebabedeadbeef'
            with self.assertLogs(
                'imbi.common.access', level=logging.INFO
            ) as cm:
                await middleware(_http_scope(), _noop_receive, _noop_send)
        message = cm.records[0].getMessage()
        self.assertNotIn('trace_id:', message)
        get_id.assert_not_called()

    async def test_custom_logger(self) -> None:
        app = _RecordingApp(status=200)
        custom = logging.getLogger('imbi.common.access.custom_test')
        middleware = access_log.AccessLogMiddleware(app, logger=custom)
        with self.assertLogs(custom, level=logging.INFO) as cm:
            await middleware(_http_scope(), _noop_receive, _noop_send)
        self.assertEqual(cm.records[0].name, custom.name)


class PrincipalLoggingTests(unittest.IsolatedAsyncioTestCase):
    """Verify the NCSA authuser slot is populated from request auth."""

    def setUp(self) -> None:
        access_log.clear_api_key_principals()
        self.addCleanup(access_log.clear_api_key_principals)

    async def _emit(
        self,
        headers: abc.Iterable[tuple[bytes, bytes]] = (),
        *,
        include_principal: bool = True,
    ) -> str:
        app = _RecordingApp(status=200)
        middleware = access_log.AccessLogMiddleware(
            app, include_principal=include_principal
        )
        with self.assertLogs('imbi.common.access', level=logging.INFO) as cm:
            await middleware(
                _http_scope(headers=headers), _noop_receive, _noop_send
            )
        return cm.records[0].getMessage()

    async def test_no_authorization_header_logs_dash(self) -> None:
        message = await self._emit()
        self.assertIn('10.0.0.1:51234 - - "GET /foo HTTP/1.1" 200', message)

    async def test_jwt_logs_local_part_of_email(self) -> None:
        token = core.create_access_token(subject='gavinr@aweber.com')
        message = await self._emit(
            headers=[(b'authorization', f'Bearer {token}'.encode())],
        )
        self.assertIn(
            '10.0.0.1:51234 - gavinr "GET /foo HTTP/1.1" 200', message
        )

    async def test_jwt_subject_without_at_sign_logs_full_subject(
        self,
    ) -> None:
        token = core.create_access_token(subject='svc-deploy-bot')
        message = await self._emit(
            headers=[(b'authorization', f'Bearer {token}'.encode())],
        )
        self.assertIn(' - svc-deploy-bot "GET ', message)

    async def test_api_key_logs_key_id_only(self) -> None:
        message = await self._emit(
            headers=[(b'authorization', b'Bearer ik_abc123_sekretsecret')],
        )
        self.assertIn(' - ik_abc123 "GET ', message)

    async def test_malformed_api_key_logs_dash(self) -> None:
        # ``ik_`` prefix without an id segment.
        message = await self._emit(
            headers=[(b'authorization', b'Bearer ik__nokey')],
        )
        self.assertIn(' - - "GET ', message)
        # ``ik_<id>`` with no secret segment at all.
        message = await self._emit(
            headers=[(b'authorization', b'Bearer ik_abc123')],
        )
        self.assertIn(' - - "GET ', message)
        # ``ik_<id>_`` with an empty secret segment.
        message = await self._emit(
            headers=[(b'authorization', b'Bearer ik_abc123_')],
        )
        self.assertIn(' - - "GET ', message)

    async def test_invalid_jwt_logs_dash(self) -> None:
        message = await self._emit(
            headers=[(b'authorization', b'Bearer not.a.jwt')],
        )
        self.assertIn(' - - "GET ', message)

    async def test_mixed_case_bearer_scheme_is_accepted(self) -> None:
        token = core.create_access_token(subject='daves@aweber.com')
        message = await self._emit(
            headers=[(b'Authorization', f'BEARER {token}'.encode())],
        )
        self.assertIn(' - daves "GET ', message)

    async def test_non_bearer_scheme_logs_dash(self) -> None:
        message = await self._emit(
            headers=[(b'authorization', b'Basic dXNlcjpwYXNz')],
        )
        self.assertIn(' - - "GET ', message)

    async def test_empty_bearer_token_logs_dash(self) -> None:
        message = await self._emit(
            headers=[(b'authorization', b'Bearer   ')],
        )
        self.assertIn(' - - "GET ', message)

    async def test_include_principal_false_skips_extraction(self) -> None:
        token = core.create_access_token(subject='gavinr@aweber.com')
        message = await self._emit(
            headers=[(b'authorization', f'Bearer {token}'.encode())],
            include_principal=False,
        )
        self.assertIn(' - - "GET ', message)

    async def test_api_key_remembered_owner_logs_label(self) -> None:
        access_log.remember_api_key_principal('ik_abc123', 'gavinr@aweber.com')
        message = await self._emit(
            headers=[(b'authorization', b'Bearer ik_abc123_sekretsecret')],
        )
        self.assertIn(' - gavinr@aweber.com "GET ', message)

    async def test_api_key_uncached_falls_back_to_key_id(self) -> None:
        access_log.remember_api_key_principal('ik_other', 'someone@x.com')
        message = await self._emit(
            headers=[(b'authorization', b'Bearer ik_abc123_sekretsecret')],
        )
        self.assertIn(' - ik_abc123 "GET ', message)

    async def test_remember_ignores_empty_values(self) -> None:
        access_log.remember_api_key_principal('', 'someone@x.com')
        access_log.remember_api_key_principal('ik_abc123', '')
        message = await self._emit(
            headers=[(b'authorization', b'Bearer ik_abc123_sekretsecret')],
        )
        self.assertIn(' - ik_abc123 "GET ', message)

    async def test_api_key_owner_label_is_escaped(self) -> None:
        access_log.remember_api_key_principal(
            'ik_abc123', 'evil\r\nINJECTED 200'
        )
        message = await self._emit(
            headers=[(b'authorization', b'Bearer ik_abc123_sekretsecret')],
        )
        self.assertNotIn('\r', message)
        self.assertNotIn('\n', message)
        self.assertIn(r' - evil\r\nINJECTED 200 "GET ', message)

    async def test_api_key_owner_cache_evicts_lru(self) -> None:
        with mock.patch.object(access_log, '_API_KEY_PRINCIPAL_CACHE_MAX', 1):
            access_log.remember_api_key_principal('ik_abc123', 'first@x.com')
            # Pushing a second entry past the cap evicts the oldest.
            access_log.remember_api_key_principal('ik_zzz', 'second@x.com')
        message = await self._emit(
            headers=[(b'authorization', b'Bearer ik_abc123_sekretsecret')],
        )
        self.assertIn(' - ik_abc123 "GET ', message)


if __name__ == '__main__':
    unittest.main()
