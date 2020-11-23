"""
Core Application
================

"""
import ast
import inspect
import logging
import os
import sys
import typing
from distutils import util
from os import path

import aioredis
import sprockets_postgres as postgres
from sprockets import http
from sprockets.http import app
from sprockets.mixins import correlation
from sprockets.mixins.mediatype import content, transcoders
from tornado import ioloop, web

from imbi import (
    __version__,
    common,
    endpoints,
    html,
    pkgfiles,
    stats
)
from imbi.endpoints import default

LOGGER = logging.getLogger(__name__)

DEFAULT_SESSION_POOL_SIZE = 10
REQUEST_LOG_FORMAT = '%d %s %.2fms %s'


def make_application(**settings) -> app.Application:
    """Create the web application instance after building the settings

    :param dict settings: kwarg settings passed in for the application

    """
    _set_default_settings(settings)
    if settings['environment'] in ('development', 'testing'):
        os.environ.pop('SENTRY_DSN', None)
        settings.setdefault('debug', True)

    urls = [
        web.url(r'/static/(.*)', web.StaticFileHandler,
                {'path': settings['static_path']})
    ]
    urls += endpoints.URLS

    settings['permissions'] = _get_permissions(urls)

    application = Application(
        urls,
        log_function=correlation.mixins.correlation_id_logger, **settings)

    # Content handling setup
    content.install(application, 'application/json', 'utf-8')
    content.add_transcoder(application, transcoders.JSONTranscoder())
    content.add_transcoder(
        application, transcoders.JSONTranscoder('application/json-patch+json'))
    content.add_transcoder(application, transcoders.MsgPackTranscoder())
    content.add_transcoder(application, html.HTMLTranscoder())

    # Instrument which libraries to include in sentry reports
    """
    sentry.install(
        app,
        include_paths=[
            'aiopg',
            'aioredis',
            'arrow',
            'imbi',
            'jsonpatch',
            'jsonschema',
            'sprockets.http',
            'sprockets.handlers.status',
            'sprockets.mixins.correlation',
            'sprockets.mixins.mediatype',
            'sprockets.mixins.metrics',
            'sprockets_postgres'],
        release=__version__,
        tags={'environment': settings['environment']})
    """
    return application


def _get_permissions(routes: list) -> set:
    """Return a set of distinct permissions for all of the endpoints that
     are registered in the system.

     :param routes: Routes that will be passed in to app creation

     """
    permissions, processed = set({}), set({})

    def find_decorators(node):
        """Find the decorators on a node and if the decorator name matches
        the expected value (require_permission), add it to the permission set.

        :param ast.Node node: The node to check

        """
        for n in node.decorator_list:
            if isinstance(n, ast.Call):
                name = n.func.attr if isinstance(n.func, ast.Attribute) \
                    else n.func.id
            else:
                name = n.attr if isinstance(n, ast.Attribute) else n.id
            if name == 'require_permission':
                [permissions.add(a.s) for a in n.args]

    # Iterate across all endpoints
    for endpoint in routes:
        for cls in inspect.getmro(endpoint.target):
            if cls in processed:
                continue
            processed.add(cls)
            node_iter = ast.NodeVisitor()
            node_iter.visit_FunctionDef = find_decorators
            node_iter.visit_AsyncFunctionDef = find_decorators
            try:
                node_iter.visit(ast.parse(inspect.getsource(cls)))
            except TypeError:
                pass
    return permissions


def _maybe_disable_request_logging() -> None:
    """Adjust logging levels, turning off access logging in production."""
    for name in {'imbi', 'tornado'}:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
    if os.environ.get('DEBUG') == '1':
        for name in {'imbi'}:
            logging.getLogger(name).setLevel(logging.DEBUG)


def _set_default_settings(settings: dict) -> None:
    """Update the settings, setting default values that will not override
    any previous configuration.

    """
    settings.setdefault('compress_response', False)
    settings.setdefault('cookie_secret',  os.environ.get(
        'COOKIE_SECRET', common.DEFAULT_COOKIE_SECRET))
    settings.setdefault(
        'default_handler_class', default.RequestHandler)
    settings.setdefault(
        'environment', os.environ.get('ENVIRONMENT', 'development'))
    settings.setdefault(
        'debug', util.strtobool(os.environ.get('DEBUG', 'FALSE')))
    settings.setdefault(
        'gitlab_url',
        os.environ.get('GITLAB_URL', 'https://gitlab.com'))
    settings.setdefault('gitlab_token', os.environ.get('GITLAB_TOKEN'))
    settings.setdefault(
        'session_redis_url',
        os.environ.get('SESSION_REDIS_URL', 'redis://localhost:6379/0'))
    settings.setdefault(
        'stats_redis_url',
        os.environ.get('STATS_REDIS_URL', 'redis://localhost:6379/1'))
    settings.setdefault('service', os.environ.get('SERVICE', 'imbi'))
    settings.setdefault(
        'static_path',
        path.join(path.dirname(sys.modules['imbi'].__file__), 'static'))
    settings.setdefault(
        'template_loader',
        pkgfiles.TemplateLoader(debug=settings.get('debug', False)))
    settings.setdefault('template_path', 'templates')
    settings.setdefault('version', __version__)
    settings.setdefault('xheaders', True)
    settings.setdefault('xsrf_cookies', False)


class Application(postgres.ApplicationMixin,
                  app.Application):
    """Extend tornado.web.Application to create our various client objects and
    to implement the ready_to_serve logic.

    """
    def __init__(self, *args, **kwargs):
        super(Application, self).__init__(*args, **kwargs)
        self._access_log = logging.LoggerAdapter(
            logging.getLogger('tornado.access'),
            {'correlation-id': ''})
        self._ready = False
        self.loop: typing.Optional[ioloop.IOLoop] = None
        self.session_redis: typing.Optional[aioredis.Redis] = None
        self.stats: typing.Optional[stats.Stats] = None
        self.on_start_callbacks.append(self.on_start)

    @property
    def environment(self) -> str:
        """Return the operational environment as a string"""
        return self.settings['environment']

    def log_request(self, handler):
        """Writes a completed HTTP request to the logs.
        By default writes to the python root logger.

        """
        status_code = handler.get_status()
        if status_code < 400:
            log_method = self._access_log.info
        elif status_code < 500:
            log_method = self._access_log.warning
        else:
            log_method = self._access_log.error
        request_time = 1000.0 * handler.request.request_time()
        correlation_id = getattr(handler, 'correlation_id', None)
        if correlation_id is None:
            correlation_id = handler.request.headers.get(
                'Correlation-ID', None)
        self._access_log.extra['correlation-id'] = correlation_id
        log_method(REQUEST_LOG_FORMAT, status_code,
                   handler._request_summary(), request_time,
                   handler.request.headers.get('User-Agent'))

    async def on_start(self,
                       _app: http.app.Application,
                       loop: ioloop.IOLoop) -> None:
        """Invoked on startup of the application"""
        self.loop = loop
        try:
            self.session_redis = aioredis.Redis(
                await aioredis.create_pool(
                    self.settings['session_redis_url'],
                    maxsize=int(os.environ.get(
                        'SESSION_POOL_SIZE', DEFAULT_SESSION_POOL_SIZE))))
        except (OSError, ConnectionRefusedError) as error:
            LOGGER.info('Error connecting to Session redis: %r', error)
            self.stop(loop)
            return

        try:
            self.stats = await stats.create(self.settings['stats_redis_url'])
        except (OSError, ConnectionRefusedError) as error:
            LOGGER.info('Error connecting to Stats redis: %r', error)
            self.stop(loop)
            return
        self._ready = True
        LOGGER.debug('Application ready')

    @property
    def ready_to_serve(self) -> bool:
        """Indicates if the service is available to respond to HTTP requests"""
        return self._ready


def run():  # pragma: no cover
    """Run the service"""
    number_of_procs = os.environ.get('NUMBER_OF_PROCS')
    if number_of_procs:
        http.run(make_application, {'number_of_procs': int(number_of_procs)})
    else:
        http.run(make_application)
