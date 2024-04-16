from __future__ import annotations

import copy
import unittest.mock
import uuid

import yarl
from tornado import httputil, web

from imbi import cors


class OriginTests(unittest.TestCase):
    def test_defaults(self):
        origins = cors.Origins()
        self.assertTrue(origins.allow_any)
        self.assertIn(f'https://{uuid.uuid4()}.example.com', origins)

    def test_adding_origin_disables_allow_any(self):
        origins = cors.Origins()
        self.assertTrue(origins.allow_any)

        origins.add('https://example.com/')
        self.assertFalse(origins.allow_any)

    def test_adding_relative_origin(self):
        origins = cors.Origins()
        with self.assertRaises(ValueError):
            origins.add('/foo')


class ConfigTests(unittest.TestCase):
    def test_default_configuration(self):
        cfg = cors.CORSConfig()
        self.assertTrue(cfg.allow_credentials)
        self.assertSetEqual(set(), cfg.allowed_methods)
        self.assertIn('https://example.com', cfg.allowed_origins)
        self.assertIn('Cache-Control', cfg.exposed_headers)
        self.assertIn('Date', cfg.exposed_headers)
        self.assertIn('Last-Modified', cfg.exposed_headers)
        self.assertIn('Link', cfg.exposed_headers)

    def test_that_allow_credentials_can_be_set(self):
        cfg = cors.CORSConfig(allow_credentials=False)
        self.assertFalse(cfg.allow_credentials)

    def test_that_allow_any_origin_can_be_set(self):
        cfg = cors.CORSConfig(allow_any_origin=False)
        self.assertNotIn('https://example.com', cfg.allowed_origins)

    def test_that_allow_methods_can_be_set(self):
        cfg = cors.CORSConfig(allow_methods={'POST'})
        self.assertSetEqual({'POST'}, cfg.allowed_methods)

    def test_updating(self):
        cfg = cors.CORSConfig(allow_any_origin=True,
                              allow_credentials=True,
                              allow_methods={'POST'})

        cfg.update(allow_any_origin=False, allow_credentials=False)
        self.assertFalse(cfg.allowed_origins.allow_any)
        self.assertFalse(cfg.allow_credentials)
        self.assertSetEqual({'POST'}, cfg.allowed_methods)

        # no-op is allowed
        cfg.update()
        self.assertFalse(cfg.allowed_origins.allow_any)
        self.assertFalse(cfg.allow_credentials)
        self.assertSetEqual({'POST'}, cfg.allowed_methods)

        # allow_methods appends
        cfg.update(allow_methods={'DELETE'})
        self.assertFalse(cfg.allowed_origins.allow_any)
        self.assertFalse(cfg.allow_credentials)
        self.assertSetEqual({'DELETE', 'POST'}, cfg.allowed_methods)

        # allow_origins appends
        cfg.update(allow_origins={'https://example.net'})
        self.assertSetEqual({yarl.URL('https://example.net')},
                            cfg.allowed_origins._origins)

        # exposed_headers appends
        starting = cfg.exposed_headers.copy()
        cfg.update(exposed_headers={'ETag'})
        self.assertSetEqual(starting.union({'ETag'}), cfg.exposed_headers)

        # max_age overwrites
        cfg.update(max_age=0)
        self.assertEqual(0, cfg.max_age)

    def test_copying(self):
        source = cors.CORSConfig(allow_methods={'DELETE', 'GET'})
        source.allowed_origins.add('https://example.com')

        clone = copy.copy(source)
        self.assertEqual(source.allow_credentials, clone.allow_credentials)
        self.assertSetEqual(source.allowed_methods, clone.allowed_methods)


class RequestProcessingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.request = httputil.HTTPServerRequest(
            headers=httputil.HTTPHeaders({
                'Origin': 'https://example.com',
            }),
            connection=unittest.mock.Mock(),
            uri='/')
        self.response_headers = httputil.HTTPHeaders()
        self.handler = web.RequestHandler(web.Application(), self.request)
        self.handler.set_header = self.response_headers.__setitem__
        self.handler.add_header = self.response_headers.add


class PreflightProcessingTests(RequestProcessingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.cors_processor = cors.CORSProcessor(
            cors.CORSConfig(allow_methods={'POST'}))
        self.request.method = 'OPTIONS'
        self.request.headers['Access-Control-Request-Method'] = 'POST'

    def assert_preflight_failure(self):
        self.assertFalse(self.cors_processor.ok)
        self.assertIn('Origin', self.response_headers.get_list('Vary'))
        self.assertNotIn('Access-Control-Allow-Credentials',
                         self.response_headers)

    def test_correct_cors_preflight(self):
        self.cors_processor.process_request(self.handler)
        self.assertTrue(self.cors_processor.ok)
        self.assertEqual(
            self.request.headers['Origin'],
            self.response_headers.get('Access-Control-Allow-Origin'))
        self.assertEqual(
            'POST', self.response_headers.get('Access-Control-Allow-Methods'))
        self.assertNotIn('Access-Control-Allow-Headers', self.response_headers)
        self.assertEqual(str(self.cors_processor.config.max_age),
                         self.response_headers.get('Access-Control-Max-Age'))
        self.assertIn('Origin', self.response_headers.get_list('Vary'))

    def test_correct_cors_preflight_with_request_headers(self):
        self.request.headers.add('Access-Control-Request-Headers',
                                 'Cache-Control')
        self.cors_processor.process_request(self.handler)
        self.assertTrue(self.cors_processor.ok)
        self.assertIn(
            'Cache-Control',
            self.response_headers.get_list('Access-Control-Allow-Headers'))

    def test_correct_cors_preflight_with_exposed_headers(self):
        self.cors_processor.config.exposed_headers.add('Link')
        self.cors_processor.process_request(self.handler)
        self.assertTrue(self.cors_processor.ok)
        self.assertIn(
            'Link',
            self.response_headers.get_list('Access-Control-Expose-Headers'))

    def test_preflight_without_ac_request_method(self):
        del self.request.headers['Access-Control-Request-Method']
        self.cors_processor.process_request(self.handler)
        self.assert_preflight_failure()
        self.assertEqual('*',
                         self.response_headers['Access-Control-Allow-Origin'])

    def test_preflight_without_origin(self):
        del self.request.headers['Origin']
        self.cors_processor.process_request(self.handler)
        self.assert_preflight_failure()
        self.assertEqual('*',
                         self.response_headers['Access-Control-Allow-Origin'])

    def test_preflight_with_explicit_allowed_origin(self):
        self.cors_processor.config.allowed_origins.allow_any = False
        self.cors_processor.config.allowed_origins.add(
            self.request.headers['Origin'])
        self.cors_processor.process_request(self.handler)
        self.assertTrue(self.cors_processor.ok)
        self.assertEqual(self.request.headers['Origin'],
                         self.response_headers['Access-Control-Allow-Origin'])

    def test_preflight_without_explicit_allowed_origin(self):
        self.cors_processor.config.allowed_origins.allow_any = False
        self.request.headers['Origin'] = 'https://example.net'
        self.cors_processor.process_request(self.handler)
        self.assert_preflight_failure()
        self.assertNotIn('Access-Control-Allow-Origin', self.response_headers)


class RequestProcessingTests(RequestProcessingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.request.method = 'DELETE'

    def process_request(self, **overrides):
        self.response_headers.clear()
        cors_processor = cors.CORSProcessor(
            cors.CORSConfig(allow_methods={'DELETE'}), **overrides)
        cors_processor.process_request(self.handler)

    def test_allowed_request(self):
        self.process_request()
        self.assertEqual(self.request.headers['Origin'],
                         self.response_headers['Access-Control-Allow-Origin'])
        self.assertEqual(
            'true', self.response_headers['Access-Control-Allow-Credentials'])

    def test_request_with_unallowed_method(self):
        # NB -- CORS does not require that the request method matches
        #       the preflight Access-Control-Request-Method    o_O
        self.request.method = 'POST'
        self.process_request()
        self.assertEqual(self.request.headers['Origin'],
                         self.response_headers['Access-Control-Allow-Origin'])
        self.assertEqual(
            'true', self.response_headers['Access-Control-Allow-Credentials'])

    def test_request_without_origin(self):
        del self.request.headers['Origin']
        self.process_request()
        self.assertEqual('*',
                         self.response_headers['Access-Control-Allow-Origin'])
        self.assertNotIn('Access-Control-Allow-Credentials',
                         self.response_headers)

        self.process_request(allow_any_origin=False)
        self.assertNotIn('Access-Control-Allow-Origin', self.response_headers)
        self.assertNotIn('Access-Control-Allow-Credentials',
                         self.response_headers)

    def test_that_allowed_origin_is_widened_without_credentials(self):
        self.process_request(allow_any_origin=True, allow_credentials=False)
        self.assertEqual('*',
                         self.response_headers['Access-Control-Allow-Origin'])

        self.process_request(allow_credentials=False,
                             allow_origins={self.request.headers['Origin']})
        self.assertEqual(self.request.headers['Origin'],
                         self.response_headers['Access-Control-Allow-Origin'])


class MixinTests(unittest.IsolatedAsyncioTestCase):
    class Handler(cors.CORSMixin):
        def delete(self) -> None:
            self.set_status(204)

    def setUp(self) -> None:
        super().setUp()
        self.origin = 'https://example.com'
        self.application = web.Application()

    async def run_handler(self,
                          method: str,
                          *,
                          headers: None | dict = None,
                          **cors_overrides) -> httputil.HTTPHeaders:
        self.Handler.cors_overrides.clear()
        self.Handler.cors_overrides.update(cors_overrides)

        request = httputil.HTTPServerRequest(method=method,
                                             headers=httputil.HTTPHeaders(
                                                 {'Origin': self.origin}),
                                             connection=unittest.mock.Mock(),
                                             uri='/')
        if headers:
            for name, value in headers.items():
                request.headers[name] = value

        handler = self.Handler(self.application, request)
        response_headers = httputil.HTTPHeaders()
        handler.set_header = response_headers.__setitem__
        handler.add_header = response_headers.add
        await handler._execute([])

        return response_headers

    async def test_preflight_request_without_configuration(self):
        response_headers = await self.run_handler(
            'OPTIONS', headers={'Access-Control-Request-Method': 'DELETE'})
        self.assertEqual(self.origin,
                         response_headers['Access-Control-Allow-Origin'])
        self.assertCountEqual(
            ['DELETE'],
            response_headers.get_list('Access-Control-Allow-Methods'))

    async def test_preflight_request_with_methods_defined(self):
        response_headers = await self.run_handler(
            'OPTIONS',
            headers={'Access-Control-Request-Method': 'GET'},
            allow_methods={'GET'})
        self.assertEqual(self.origin,
                         response_headers['Access-Control-Allow-Origin'])
        self.assertCountEqual(
            ['GET'], response_headers.get_list('Access-Control-Allow-Methods'))

    async def test_preflight_request_with_application_config(self):
        self.application.cors_config = cors.CORSConfig(allow_any_origin=False,
                                                       allow_credentials=True,
                                                       max_age=300)
        self.application.cors_config.allowed_origins.add(self.origin)
        response_headers = await self.run_handler(
            'OPTIONS', headers={'Access-Control-Request-Method': 'DELETE'})
        self.assertEqual(self.origin,
                         response_headers['Access-Control-Allow-Origin'])
        self.assertCountEqual(
            ['DELETE'],
            response_headers.get_list('Access-Control-Allow-Methods'))
        self.assertEqual(str(self.application.cors_config.max_age),
                         response_headers['Access-Control-Max-Age'])

    async def test_non_preflight_response_headers(self):
        response_headers = await self.run_handler('DELETE')
        self.assertIn('Origin', response_headers.get('Vary'))
        self.assertEqual(self.origin,
                         response_headers['Access-Control-Allow-Origin'])

    async def test_cors_headers_on_request_failure(self):
        with unittest.mock.patch.object(
                self.Handler, 'delete',
                new_callable=unittest.mock.MagicMock) as delete:
            delete.__name__ = 'delete'
            delete.side_effect = RuntimeError('injected failure')
            response_headers = await self.run_handler('DELETE')

        self.assertIn('Origin', response_headers.get('Vary'))
        self.assertEqual(self.origin,
                         response_headers['Access-Control-Allow-Origin'])
