from __future__ import annotations

import copy
import logging

import yarl
from tornado import web

LOGGER = logging.getLogger(__name__)


class Unspecified:
    """Sentinel value for optional parameters"""
    pass


class Origins:
    """Collection of CORS origins

    This acts like a set of URLs with a special property to
    enable any URL to match without being present.  This is
    used to determine whether CORS should be enabled for
    requests from a specific Origin.

    By default, any origin is acceptable.  If the application
    adds a specific origin value, then the "any" flag is
    disabled since that is usually what is desired.  The "add"
    operation enforces that only absolute URLs are acceptable
    as origins -- this explicitly means that ``null`` is not
    valid as an acceptable origin. (:rfc:`6454`).

    """
    def __init__(self, *, allow_any: bool = True):
        self.allow_any: bool = allow_any
        self._origins: set[yarl.URL] = set()

    def add(self, item: str) -> None:
        """Add a new URL to the set of origins

        If `item` is not an absolute URL, then a :exc:`ValueError`
        will be raised.

        """
        url = yarl.URL(item)
        if not url.is_absolute():
            raise ValueError(f'{item!r} is not a valid URL')

        self.allow_any = False
        self._origins.add(url)

    def __str__(self) -> str:
        return '<{} allow_any:{} origins:{}>'.format(
            self.__class__.__name__,
            self.allow_any,
            ','.join(str(s) for s in self._origins))

    def __copy__(self) -> Origins:
        return self.__deepcopy__()

    def __deepcopy__(self, *args, **kwargs) -> Origins:
        clone = self.__class__(allow_any=self.allow_any)
        clone._origins.update(self._origins)
        return clone

    def __contains__(self, item: str) -> bool:
        if self.allow_any:
            return True
        return yarl.URL(item) in self._origins


class CORSConfig:
    """Application-level CORS configuration defaults

    :param allow_any_origin: should "any" origin be allowed
        to participate in resource sharing?
    :param allow_credentials: should requests including
        an Authorization header or Cookies be sent to the server?
        Also, should responses with Set-Cookie be returned?
    :param exposed_headers: the list of response headers that
        should be exposed to the JS layer
    :param max_age: the maximum number of seconds that the JS
        layer may cache the CORS response

    """

    def __init__(
            self,
            *,
            allow_any_origin: bool = True,
            allow_credentials: bool = True,
            allow_methods: set[str] | None = None,
            exposed_headers: set[str] | None = None,
            max_age: int = 5,
    ):
        # allow_credentials is True by default to ensure that any
        # cookies we set will be returned to the JS client
        self.allow_credentials = allow_credentials

        self.allowed_methods: set[str] = set()
        if allow_methods:
            self.allowed_methods.update(allow_methods)

        self.allowed_origins = Origins(allow_any=allow_any_origin)

        self.exposed_headers: set[str] = {'Cache-Control', 'Date',
                                          'Last-Modified', 'Link'}
        if exposed_headers:
            self.exposed_headers.update(exposed_headers)

        self.max_age = max_age

    def __str__(self) -> str:
        return (('<{} allow_credentials:{} max_age:{} allowed_methods:{!r}'
                 ' exposed_headers:{!r} origins:{}>').format(
            self.__class__.__name__,
            self.allow_credentials,
            self.max_age,
            self.allowed_methods,
            self.exposed_headers,
            self.allowed_origins,
        ))

    def __copy__(self) -> CORSConfig:
        clone = CORSConfig(
            allow_credentials=self.allow_credentials,
            allow_methods=self.allowed_methods,
            exposed_headers=self.exposed_headers,
            max_age=self.max_age)
        clone.allowed_origins = copy.deepcopy(self.allowed_origins)
        return clone

    def __deepcopy__(self, *args, **kwargs) -> CORSConfig:
        return self.__copy__()

    def update(self, *,
               allow_any_origin: bool | Unspecified = Unspecified(),
               allow_credentials: bool | Unspecified = Unspecified(),
               allow_methods: set[str] | Unspecified = Unspecified(),
               allow_origins: set[str] | Unspecified = Unspecified(),
               exposed_headers: set[str] | Unspecified = Unspecified(),
               max_age: int | Unspecified = Unspecified(),
               ) -> None:
        """Update selected attributes"""
        if not isinstance(allow_any_origin, Unspecified):
            self.allowed_origins.allow_any = allow_any_origin
        if not isinstance(allow_credentials, Unspecified):
            self.allow_credentials = allow_credentials
        if not isinstance(allow_methods, Unspecified):
            self.allowed_methods.update(allow_methods)
        if not isinstance(allow_origins, Unspecified):
            for origin in allow_origins:
                self.allowed_origins.add(origin)
        if not isinstance(exposed_headers, Unspecified):
            self.exposed_headers.update(exposed_headers)
        if not isinstance(max_age, Unspecified):
            self.max_age = max_age


class CORSProcessor:
    """CORS Request processor

    An instance of this is created for each request using the
    default configuration as the `config` parameter along with
    optional overrides.  It is instantiated with each handler
    instance, then :meth:`process_request` is called inside
    :meth:`tornado.web.RequestHandler.prepare`.  "Processing"
    the request results in setting the response headers based
    on the CORS protocol.

    The separation between ``process_request`` and ``set_headers``
    is necessary since the request handler logic resets the header
    set when an exception occurs.  The ``CORSMixin`` accounts for
    this by calling :meth:`set_headers` in ``set_default_headers``
    which is called after the request handler resets the headers.
    However, it is also called during instance initialization which
    the mixin also accounts for.  You should rarely need to call
    `set_headers` directly.

    """
    def __init__(self, config: CORSConfig, **overrides) -> None:
        self.config = copy.deepcopy(config)
        self.config.update(**overrides)
        self.requested_origin: str | None = None
        self.is_preflight = None

    @property
    def ok(self) -> bool:
        """Is the request Origin acceptable?"""
        return self.requested_origin is not None

    def process_request(self, handler: web.RequestHandler) -> None:
        """Determine the CORS result for a request

        This is the main logic for CORS handling and should be
        called from your request handler's ``prepare`` method.

        """
        request = handler.request
        if request.method == 'OPTIONS':
            try:
                request.headers['Access-Control-Request-Method']
                origin = request.headers['Origin']
            except KeyError as error:
                LOGGER.debug('not a CORS request, missing required header %s',
                             error.args[0])
            else:
                self.is_preflight = True
                origin = origin.strip()
                if origin in self.config.allowed_origins:
                    self.requested_origin = origin
                else:
                    LOGGER.debug('CORS preflight origin %r not allowed',
                                 origin)
        else:
            self.is_preflight = False
            origin = request.headers.get('origin', '').strip()
            if origin in self.config.allowed_origins:
                self.requested_origin = origin

        self.set_headers(handler)

    def set_headers(self, handler: web.RequestHandler) -> None:
        """Set the appropriate CORS response headers

        **You probably do not need to invoke this method directly!**

        The response header set is determined by a call to
        :meth:`process_request`.  If it has not been called, then
        only the ``Access-Control-Allow-Origin`` header will be set
        if we are configured to allow any origin.

        """
        if self.is_preflight and self.ok:
            def add_headers(name, values):
                for value in values:
                    handler.add_header(name, value)

            add_headers('Access-Control-Allow-Methods',
                        self.config.allowed_methods)
            add_headers('Access-Control-Allow-Headers',
                        handler.request.headers.get_list(
                            'Access-Control-Request-Headers'))
            add_headers('Access-Control-Expose-Headers',
                        self.config.exposed_headers)
            handler.set_header('Access-Control-Max-Age',
                               str(self.config.max_age))

        if self.requested_origin:
            best_origin = self.requested_origin
            if self.config.allow_credentials:
                handler.set_header('Access-Control-Allow-Credentials', 'true')
            elif self.config.allowed_origins.allow_any:
                best_origin = '*'
            handler.set_header('Access-Control-Allow-Origin', best_origin)
        elif self.config.allowed_origins.allow_any:
            handler.set_header('Access-Control-Allow-Origin', '*')

        handler.add_header('Vary', 'Origin')


class CORSMixin(web.RequestHandler):
    """Mix this in to enable CORS pre-flight and request processing

    This mix-in uses the application level CORS configuration to
    determine how a specific response (or future request) is made
    accessible to a JavaScript client. See the [fetch specification]
    for the gory details.

    [fetch specification]: https://fetch.spec.whatwg.org/#http-cors-protocol

    """

    cors_overrides = {}
    """Add specific overrides for CORSProcessor here"""

    def __init__(self, application, request, **kwargs):
        super().__init__(application, request, **kwargs)
        cors_config = getattr(application, 'cors_config', CORSConfig())
        self.cors = CORSProcessor(cors_config, **self.cors_overrides)

        # This little snippet is responsible for determining which
        # methods are actually implemented and building the
        # "allowed methods" default if it is not configured
        if not self.cors.config.allowed_methods:
            defined_methods = set()
            for method_name in self.SUPPORTED_METHODS:
                method = getattr(self, method_name.lower())
                if method and method.__name__ == method_name.lower():
                    defined_methods.add(method_name)
            defined_methods.discard('OPTIONS')
            self.cors.config.update(allow_methods=defined_methods)

    async def prepare(self):
        maybe_coro = super().prepare()
        if maybe_coro:  # pragma: no cover
            await maybe_coro
        self.cors.process_request(self)

    def options(self) -> None:
        self.set_status(204)

    def set_default_headers(self) -> None:
        super().set_default_headers()
        if hasattr(self, 'cors'):
            self.cors.set_headers(self)
