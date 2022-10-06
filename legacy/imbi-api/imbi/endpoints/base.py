"""
Base Request Handlers

"""
import asyncio
import datetime
import logging
import typing
import uuid
from email import utils

import jsonpatch
import problemdetails
import sprockets_postgres as postgres
from openapi_core.deserializing.exceptions import DeserializeError
from openapi_core.schema.media_types.exceptions import InvalidContentType
from openapi_core.templating.paths.exceptions import \
    OperationNotFound, PathNotFound
from openapi_core.unmarshalling.schemas.exceptions import ValidateError
from openapi_core.validation.exceptions import InvalidSecurity
from sprockets.http import mixins
from sprockets.mixins import mediatype
from tornado import httputil, web

from imbi import cors, errors, session, user, version

LOGGER = logging.getLogger(__name__)


def require_permission(permission):
    """Decorator function for requiring a permission string for an endpoint

    :param str permission: The permission string to require
    :raises: problemdetails.Problem

    """
    def _require_permission(f):
        def wrapped(self, *args, **kwargs):
            """Inner-wrapping of the decorator that performs the logic"""
            if not self._current_user or \
                    not self._current_user.has_permission(permission):
                if self._respond_with_html:
                    return self.render(
                        'index.html',
                        javascript_url=self.application.settings.get(
                            'javascript_url'))
                raise errors.Forbidden('%r does not have the "%s" permission',
                                       self._current_user, permission)
            return f(self, *args, **kwargs)
        return wrapped
    return _require_permission


class RequestHandler(cors.CORSMixin,
                     postgres.RequestHandlerMixin,
                     mixins.ErrorLogger,
                     problemdetails.ErrorWriter,
                     mediatype.ContentMixin,
                     web.RequestHandler):
    """Base RequestHandler class used for recipients and subscribers."""

    APPLICATION_JSON = 'application/json'
    TEXT_HTML = 'text/html'
    NAME = 'Base'
    ITEM_NAME = ''

    def __init__(self,
                 application,
                 request: httputil.HTTPServerRequest,
                 **kwargs):
        super().__init__(application, request, **kwargs)
        self.logger = logging.getLogger(f'imbi.endpoints.{self.NAME}')
        self.session: typing.Optional[session.Session] = None
        self._current_user: typing.Optional[user.User] = None
        self._links = {}

    async def prepare(self) -> None:
        """Prepare the request handler for the request. If the application
        is not ready return a ``503`` error.

        Checks for a session cookie and if present, loads the session into
        the current user and authenticates it. If authentication fails,
        the current user and cookie is cleared.

        """
        if not self.application.ready_to_serve:
            return self.send_error(503, reason='Application not ready')
        self.session = session.Session(self)
        await self.session.initialize()
        self._current_user = await self.get_current_user()
        future = super().prepare()
        if asyncio.isfuture(future) or asyncio.iscoroutine(future):
            await future

    def on_finish(self) -> None:
        """Invoked after a request has completed"""
        super().on_finish()
        self.application.loop.add_callback(
            self.application.stats.incr,
            {
                'key': 'http_requests',
                'endpoint': self.NAME,
                'method': self.request.method,
                'status': self.get_status()
            })

        self.application.loop.add_callback(
            self.application.stats.add_duration,
            {
                'key': 'http_request_duration',
                'endpoint': self.NAME,
                'method': self.request.method,
                'status': self.get_status()
            },
            self.request.request_time())

    def compute_etag(self) -> None:
        """Override Tornado's built-in ETag generation"""
        return None

    async def get_current_user(self) -> typing.Optional['user.User']:
        """Used by the system to manage authentication behaviors"""
        if self.session and self.session.user:
            return self.session.user
        token = self.request.headers.get('Private-Token', None)
        if token:
            current_user = user.User(self.application, token=token)
            if await current_user.authenticate():
                return current_user

    def get_template_namespace(self) -> dict:
        """Returns a dictionary to be used as the default template namespace.

        The results of this method will be combined with additional defaults
        in the :mod:`tornado.template` module and keyword arguments to
        :meth:`~tornado.web.RequestHandler.render`
        or :meth:`~tornado.web.RequestHandler.render_string`.

        """
        namespace = super(RequestHandler, self).get_template_namespace()
        namespace.update({'version': version})
        return namespace

    def on_postgres_timing(self,
                           metric_name: str,
                           duration: float) -> None:
        """Invoked by sprockets-postgres after each query"""
        self.application.loop.add_callback(
            self.application.stats.add_duration,
            {
                'key': 'postgres_query_duration',
                'query': metric_name,
                'endpoint': self.NAME
            },
            duration)

    def send_response(self, value: typing.Union[dict, list]) -> None:
        """Send the response to the client"""
        if 'self' not in self._links:
            self._add_self_link(self.request.path)
            self._add_link_header()
        if hasattr(self, 'TTL') and \
                not self.request.headers.get('Pragma') == 'no-cache':
            self._add_response_caching_headers(self.TTL)
        super().send_response(value)

    def set_default_headers(self) -> None:
        """Override the default headers, setting the Server response header"""
        super().set_default_headers()
        self.set_header('Server', self.settings['server_header'])

    def write_error(self, status_code, **kwargs):
        if self._respond_with_html:
            return self.render(
                'error.html',
                javascript_url=self.application.settings.get('javascript_url'),
                status_code=status_code, **kwargs)
        super().write_error(status_code, **kwargs)

    def _add_last_modified_header(self, value: datetime.datetime) -> None:
        """Add a RFC-822 formatted timestamp for the Last-Modified HTTP
        response header.

        """
        if not value:
            return
        self.set_header('Last-Modified', self._rfc822_date(value))

    def _add_link_header(self) -> None:
        """Takes the accumulated links and creates a link header value"""
        links = []
        for rel, path in self._links.items():
            links.append('<{}://{}{}>; rel="{}"'.format(
                self.request.protocol, self.request.host, path, rel))
        if links:
            self.add_header('Link', ','.join(links))

    def _add_self_link(self, path: str) -> None:
        """Adds the self Link response header"""
        self._links['self'] = path

    def _add_response_caching_headers(self, ttl: int) -> None:
        """Adds the cache response headers for the object being returned."""
        self.add_header('Cache-Control', 'public, max-age={}'.format(ttl))

    @property
    def _respond_with_html(self) -> bool:
        """Returns True if the current response should respond with HTML"""
        return self.get_response_content_type().startswith(self.TEXT_HTML)

    @staticmethod
    def _rfc822_date(value: datetime.datetime) -> str:
        """Return an RFC-822 formatted timestamp for the given value"""
        return utils.format_datetime(value)


class AuthenticatedRequestHandler(RequestHandler):
    """RequestHandler base class for authenticated requests"""

    async def prepare(self) -> None:
        await super().prepare()

        # Don't require authorization for pre-flight requests
        if self.cors.is_preflight:
            return

        if not self._current_user:
            if self._respond_with_html:
                return await self.render(
                    'index.html',
                    javascript_url=self.application.settings.get(
                        'javascript_url'))
            self.set_status(401)
            await self.finish()
            raise web.Finish()


class ValidatingRequestHandler(AuthenticatedRequestHandler):
    """Validates the request against the OpenAPI spec"""
    async def prepare(self) -> None:
        await super().prepare()

        # Don't validate preflight OPTIONS requests... otherwise,
        # we need to include the OPTIONS stanza in every OpenAPI
        # path spec
        if self.cors.is_preflight:
            return

        try:
            self.application.validate_request(self.request)
        except DeserializeError as err:
            raise errors.BadRequest('Failed to deserialize body: %s', err,
                                    detail=str(err))
        except InvalidSecurity as err:
            raise errors.InternalServerError(
                'Invalid OpenAPI spec security: %s', err,
                title='OpenAPI Security Error')
        except OperationNotFound as err:
            raise errors.MethodNotAllowed(err.method.upper())
        except InvalidContentType as err:
            raise errors.UnsupportedMediaType(err.mimetype)
        except PathNotFound as err:
            raise errors.InternalServerError('OpenAPI Spec Error: %s', err,
                                             title='OpenAPI Spec Error',
                                             detail=str(err))
        except ValidateError as err:
            raise errors.BadRequest('Request failed to validate: %s', err,
                                    detail='The request did not validate',
                                    errors=[str(e).split('\n')[0]
                                            for e in err.schema_errors])


class CRUDRequestHandler(ValidatingRequestHandler):
    """CRUD request handler to reduce large amounts of duplicated code"""

    NAME = 'default'
    DEFAULTS = {}
    ID_KEY: typing.Union[str, list] = 'id'
    IS_COLLECTION = False
    FIELDS = None
    ITEM_NAME = None  # Used to create link headers for POST requests
    TTL = 300

    DELETE_SQL: typing.Optional[str] = None
    GET_SQL: typing.Optional[str] = None
    PATCH_SQL: typing.Optional[str] = None
    POST_SQL: typing.Optional[str] = None

    async def delete(self, *args, **kwargs):
        if self.DELETE_SQL is None:
            self.logger.debug('DELETE_SQL not defined')
            raise errors.MethodNotAllowed('DELETE')
        await self._delete(kwargs)

    async def get(self, *args, **kwargs):
        if self.GET_SQL is None:
            self.logger.debug('GET_SQL not defined')
            raise errors.MethodNotAllowed('GET')
        if self._respond_with_html:
            return self.render(
                'index.html',
                javascript_url=self.application.settings.get('javascript_url'))
        await self._get(kwargs)

    async def patch(self, *args, **kwargs):
        if self.PATCH_SQL is None:
            self.logger.debug('PATCH_SQL not defined')
            raise errors.MethodNotAllowed('PATCH')
        await self._patch(kwargs)

    async def post(self, *args, **kwargs):
        if self.POST_SQL is None:
            self.logger.debug('POST_SQL not defined')
            raise errors.MethodNotAllowed('POST')
        await self._post(kwargs)

    def send_response(self, value: typing.Union[dict, list]) -> None:
        """Send the response to the client"""
        if isinstance(value, list):
            return super().send_response(value)

        if not (self.request.method == 'GET' and self.IS_COLLECTION):
            self._add_last_modified_header(
                value.get('last_modified_at', value.get('created_at')))
            for key in {'created_at', 'last_modified_at'}:
                if key in value:
                    del value[key]
            if self.ID_KEY:
                if isinstance(self.ID_KEY, list):
                    args = [str(value[k]) for k in self.ID_KEY]
                else:
                    args = [str(value[self.ID_KEY])]

                try:
                    self._add_self_link(
                        self.reverse_url(self.ITEM_NAME or self.NAME, *args))
                except (AssertionError, KeyError):
                    self.logger.debug('Failed to reverse URL for %s %r',
                                      self.NAME, args)
            self._add_link_header()
        super().send_response(value)

    async def _delete(self, kwargs):
        result = await self.postgres_execute(
            self.DELETE_SQL, self._get_query_kwargs(kwargs),
            'delete-{}'.format(self.NAME))
        if not result.row_count:
            raise errors.ItemNotFound(instance=self.request.uri)
        self.set_status(204, reason='Item Deleted')

    async def _get(self, kwargs):
        result = await self.postgres_execute(
            self.GET_SQL, self._get_query_kwargs(kwargs),
            'get-{}'.format(self.NAME))
        if not result.row_count or not result.row:
            raise errors.ItemNotFound(instance=self.request.uri)
        for key, value in result.row.items():
            if isinstance(value, uuid.UUID):
                result.row[key] = str(value)
        self.send_response(result.row)

    def _get_query_kwargs(self, kwargs) -> dict:
        if isinstance(self.ID_KEY, list):
            return {k: kwargs[k] for k in self.ID_KEY}
        return {self.ID_KEY: kwargs[self.ID_KEY]}

    async def _patch(self, kwargs):
        patch_value = self.get_request_body()

        result = await self.postgres_execute(
            self.GET_SQL, self._get_query_kwargs(kwargs),
            'get-{}'.format(self.NAME))
        if not result.row_count:
            raise errors.ItemNotFound(instance=self.request.uri)

        original = dict(result.row)
        for key in {'created_at', 'created_by',
                    'last_modified_at', 'last_modified_by'}:
            if key in original:
                del original[key]

        for key, value in original.items():
            if isinstance(value, uuid.UUID):
                original[key] = str(value)

        # Apply the patch to the current value
        patch = jsonpatch.JsonPatch(patch_value)
        updated = patch.apply(original)

        # Bail early if there are no changes
        if not {k: original[k] for k in original
                if k in updated and original[k] != updated[k]}:
            self._add_self_link(self.request.path)
            self._add_link_header()
            return self.set_status(304)

        if isinstance(self.ID_KEY, list):
            for key in self.ID_KEY:
                updated['current_{}'.format(key)] = kwargs[key]
        else:
            updated['current_{}'.format(self.ID_KEY)] = kwargs[self.ID_KEY]
        updated['username'] = self._current_user.username

        result = await self.postgres_execute(
            self.PATCH_SQL, updated,
            'patch-{}'.format(self.NAME))
        if not result.row_count:
            raise errors.DatabaseError('No rows returned from PATCH_SQL',
                                       title='Failed to update record')

        # Send the new record as a response
        await self._get(self._get_query_kwargs(updated))

    async def _post(self, kwargs) -> dict:
        values = self.get_request_body()

        # Handle compound keys for child object CRUD
        if isinstance(self.ID_KEY, list):
            for key in self.ID_KEY:
                if key not in values and key in kwargs:
                    values[key] = kwargs[key]
        elif self.ID_KEY not in values and self.ID_KEY in kwargs:
            values[self.ID_KEY] = kwargs[self.ID_KEY]

        # Set defaults of None for all fields in insert
        for name in self.FIELDS:
            if name not in values:
                values[name] = self.DEFAULTS.get(name)

        values['username'] = self._current_user.username
        result = await self.postgres_execute(
            self.POST_SQL, values, 'post-{}'.format(self.NAME))
        if not result.row_count:
            raise errors.DatabaseError('No rows returned from POST_SQL',
                                       title='Failed to create record')

            # Return the record as if it were a GET
        await self._get(self._get_query_kwargs(result.row))
        return result.row


class CollectionRequestHandler(CRUDRequestHandler):

    DEFAULTS = {}
    ID_KEY: typing.Union[str, list] = 'id'
    IS_COLLECTION: True
    FIELDS = None
    ITEM_NAME = None  # Used to create link headers for POST requests
    COLLECTION_SQL = """SELECT * FROM pg_tables WHERE schemaname = 'v1';"""
    TTL = 300

    async def get(self, *args, **kwargs):
        result = await self.postgres_execute(
            self.COLLECTION_SQL, kwargs,
            metric_name='get-{}'.format(self.NAME))
        self.send_response(result.rows)


class AdminCRUDRequestHandler(CRUDRequestHandler):

    @require_permission('admin')
    async def delete(self, *args, **kwargs):
        await super().delete(*args, **kwargs)

    @require_permission('admin')
    async def get(self, *args, **kwargs):
        await super().get(*args, **kwargs)

    @require_permission('admin')
    async def patch(self, *args, **kwargs):
        await super().patch(*args, **kwargs)

    @require_permission('admin')
    async def post(self, *args, **kwargs):
        await super().post(*args, **kwargs)
