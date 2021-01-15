"""
Core Application
================

"""
import asyncio
import datetime
import logging
import re
import typing

import aioredis
import sprockets_postgres
from sprockets import http
from sprockets.http import app
from sprockets.mixins.mediatype import content
from tornado import httputil, ioloop, web

from imbi import endpoints, openapi, permissions, stats, transcoders
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
        self.loop: typing.Optional[ioloop.IOLoop] = None
        self.on_start_callbacks.append(self.on_start)
        self.openapi_validator = openapi.request_validator(self.settings)
        self.session_redis: typing.Optional[aioredis.Redis] = None
        self.started_at = datetime.datetime.now(datetime.timezone.utc)
        self.started_at_str = self.started_at.isoformat()
        self.startup_complete: typing.Optional[asyncio.Event] = None
        self.stats: typing.Optional[stats.Stats] = None

        content.set_default_content_type(self, 'application/json')
        content.add_transcoder(self, transcoders.JSONTranscoder())
        content.add_transcoder(self, transcoders.MsgPackTranscoder())

    def decrypt_value(self, key: str, value: str) -> bytes:
        """Decrypt a value that is encrypted using Tornado's secure cookie
        signing methods.

        :param key: The name of the field containing the value
        :param value: The value to decrypt
        :rtype: str

        """
        return web.decode_signed_value(
            self.settings['cookie_secret'], key, value)

    def encrypt_value(self, key: str, value: str) -> str:
        """Encrypt a value using the code used to create Tornado's secure
        cookies, using the common cookie secret.

        :param key: The name of the field containing the value
        :param value: The value to encrypt
        :rtype: str

        """
        return web.create_signed_value(
            self.settings['cookie_secret'], key, value).decode('utf-8')

    @staticmethod
    def is_encrypted_value(value: str) -> bool:
        """Checks to see if the value matches the format for a signed value using
        Tornado's signing methods.

        :param str value: The value to check
        :rtype: bool

        """
        if value is None or not isinstance(value, str):
            return False
        return SIGNED_VALUE_PATTERN.match(value) is not None

    def log_request(self, handler: web.RequestHandler) -> None:
        """Writes a completed HTTP request to the logs"""
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
        if status_code > 500:
            self._request_logger.error(
                REQUEST_LOG_FORMAT, status_code, handler._request_summary(),
                request_time, handler.request.headers.get('User-Agent'))

    async def on_start(self,
                       _app: http.app.Application,
                       _loop: ioloop.IOLoop) -> None:

        """Invoked on startup of the application"""
        self.startup_complete = asyncio.Event()
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
                    self.settings['session_redis_url'],
                    maxsize=self.settings['session_pool_size']))
        except (OSError, ConnectionRefusedError) as error:
            LOGGER.info('Error connecting to Stats redis: %r', error)
            self.stop(self.loop)
            return
        else:
            self.stats = stats.Stats(pool)

        await self._postgres_connected.wait()

        self.startup_complete.set()
        self._ready_to_serve = True
        LOGGER.info('Application startup complete, ready to serve requests')

    def validate_request(self, request: httputil.HTTPServerRequest) -> None:
        """Validate the inbound request, raising any number of OpenAPI
        exceptions on error.

        """
        self.openapi_validator.validate(request).raise_for_errors()

    @property
    def ready_to_serve(self) -> bool:
        """Indicates if the service is available to respond to HTTP requests"""
        return self._ready_to_serve
