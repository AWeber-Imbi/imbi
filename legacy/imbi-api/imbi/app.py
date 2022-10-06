"""
Core Application
================

"""
import asyncio
import datetime
import json
import logging
import os
import re
import typing

import aioredis
import sprockets_postgres
try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None
import umsgpack
from sprockets import http
from sprockets.http import app
from sprockets.mixins.mediatype import content
from tornado import httputil, ioloop, web
try:
    from sentry_sdk.integrations import logging as sentry_logging
    from sentry_sdk.integrations import tornado as sentry_tornado
except ImportError:
    sentry_logging, sentry_tornado = None, None

from imbi import (cors, endpoints, errors, keychain, openapi,
                  permissions, stats, transcoders, version)
from imbi.clients import opensearch
from imbi.endpoints import default

LOGGER = logging.getLogger(__name__)

DEFAULT_SESSION_POOL_SIZE = 10
REQUEST_LOG_FORMAT = '%d %s %.2fms %s'
SIGNED_VALUE_PATTERN = re.compile(r'^(?:[1-9][0-9]*)\|(?:.*)$')


class Application(sprockets_postgres.ApplicationMixin, app.Application):

    def __init__(self, **settings):
        LOGGER.info('imbi v%s starting', settings['version'])
        settings['default_handler_class'] = default.RequestHandler
        settings['permissions'] = permissions.PERMISSIONS
        super(Application, self).__init__(endpoints.URLS, **settings)
        self._ready_to_serve = False
        self._request_logger = logging.getLogger('imbi')
        self.keychain = keychain.Keychain(self.settings['encryption_key'])
        self.loop: typing.Optional[ioloop.IOLoop] = None
        self.on_start_callbacks.append(self.on_start)
        self.on_shutdown_callbacks.append(self.on_shutdown)
        self.openapi_validator = openapi.request_validator(self.settings)
        self.opensearch: typing.Optional[opensearch.OpenSearch] = None
        self.session_redis: typing.Optional[aioredis.Redis] = None
        self.started_at = datetime.datetime.now(datetime.timezone.utc)
        self.started_at_str = self.started_at.isoformat()
        self.startup_complete: typing.Optional[asyncio.Event] = None
        self.stats: typing.Optional[stats.Stats] = None

        content.set_default_content_type(self, 'application/json')
        content.add_transcoder(self, transcoders.FormTranscoder())
        content.add_transcoder(self, transcoders.JSONTranscoder())
        content.add_transcoder(self, transcoders.MsgPackTranscoder())
        content.add_text_content_type(
            self, 'application/json-patch+json', 'utf-8',
            json.dumps, json.loads)
        content.add_binary_content_type(
            self, 'application/json-patch+msgpack',
            umsgpack.packb, umsgpack.unpackb)

        errors.set_canonical_server(self.settings['canonical_server_name'])

        if self.settings.get('cors'):
            kwargs = {
                name: self.settings['cors'][name]
                for name in {'allow_any_origin', 'allow_credentials',
                             'allow_methods', 'exposed_headers',
                             'max_age'}
                if name in self.settings['cors']
            }
            self.cors_config = cors.CORSConfig(**kwargs)
        else:
            self.cors_config = cors.CORSConfig()
        for allowed_origin in self.settings.get('cors', {}).get('origins', []):
            self.cors_config.allowed_origins.add(allowed_origin)

    def hash_password(self, password: str) -> str:
        """Generate a HMAC-SHA512 hash of `password`."""
        hashed_bytes = self.keychain.hash(password)
        return '{}:{}'.format(self.keychain.algorithm.name, hashed_bytes.hex())

    def decrypt_value(self, value: str) -> str:
        """Decrypt a value that is encrypted using `encrypt_value`."""
        plaintext_bytes = self.keychain.decrypt(bytes.fromhex(value))
        return plaintext_bytes.decode('utf-8')

    def encrypt_value(self, value: str) -> str:
        """Encrypt a value."""
        cipher_bytes = self.keychain.encrypt(value.encode('utf-8'))
        return cipher_bytes.hex()

    def log_request(self, handler: web.RequestHandler) -> None:
        """Writes a completed HTTP request to the logs"""
        if handler.request.path == '/status':
            return
        request_time = 1000.0 * handler.request.request_time()
        status_code = handler.get_status()
        if status_code < 400:
            self._request_logger.info(
                REQUEST_LOG_FORMAT, status_code, handler._request_summary(),
                request_time, handler.request.headers.get('User-Agent'))
        if 400 <= status_code < 500:
            self._request_logger.warning(
                REQUEST_LOG_FORMAT, status_code, handler._request_summary(),
                request_time, handler.request.headers.get('User-Agent'))
        if status_code >= 500:
            self._request_logger.error(
                REQUEST_LOG_FORMAT, status_code, handler._request_summary(),
                request_time, handler.request.headers.get('User-Agent'))

    async def on_start(self,
                       _app: http.app.Application,
                       _loop: ioloop.IOLoop) -> None:

        """Invoked on startup of the application"""
        self.startup_complete = asyncio.Event()
        if sentry_sdk and self.settings.get('sentry_backend_dsn'):
            sentry_sdk.init(
                debug=self.settings['debug'],
                dsn=self.settings['sentry_backend_dsn'],
                environment=os.environ.get('environment', 'production'),
                integrations=[
                    sentry_tornado.TornadoIntegration(),
                    sentry_logging.LoggingIntegration(
                        event_level=logging.CRITICAL)
                    ],
                release=version)

        self.loop = ioloop.IOLoop.current()
        try:
            self.session_redis = aioredis.Redis(
                await aioredis.create_pool(
                    self.settings['session_redis_url'],
                    maxsize=self.settings['session_pool_size']))
        except (OSError, ConnectionRefusedError) as error:
            LOGGER.info('Error connecting to Session redis: %r', error)
            self.stop(self.loop)
            return

        try:
            pool = aioredis.Redis(
                await aioredis.create_pool(
                    self.settings['stats_redis_url'],
                    maxsize=self.settings['stats_pool_size']))
        except (OSError, ConnectionRefusedError) as error:
            LOGGER.info('Error connecting to Stats redis: %r', error)
            self.stop(self.loop)
            return
        else:
            self.stats = stats.Stats(pool)

        await self._postgres_connected.wait()

        self.opensearch = opensearch.OpenSearch(self.settings['opensearch'])
        if not await self.opensearch.initialize():
            self.stop(self.loop)
            return

        self.startup_complete.set()
        self._ready_to_serve = True
        LOGGER.info('Application startup complete')

    async def on_shutdown(self, *_args, **_kwargs) -> None:
        await self.opensearch.stop()

    def validate_request(self, request: httputil.HTTPServerRequest) -> None:
        """Validate the inbound request, raising any number of OpenAPI
        exceptions on error.

        """
        self.openapi_validator.validate(request).raise_for_errors()

    @property
    def ready_to_serve(self) -> bool:
        """Indicates if the service is available to respond to HTTP requests"""
        return self._ready_to_serve
