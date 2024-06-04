"""
Base Request Handlers

"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import dataclasses
import datetime
import logging
import operator
import uuid
from email import utils

import jsonpatch
import problemdetails
import pydantic
import sprockets.mixins.mediatype.content
import sprockets_postgres as postgres
import typing_extensions as typing
import umsgpack
import yarl
from ietfparse import datastructures
from openapi_core.deserializing.exceptions import DeserializeError
from openapi_core.schema.media_types.exceptions import InvalidContentType
from openapi_core.templating.paths.exceptions import \
    OperationNotFound, PathNotFound
from openapi_core.unmarshalling.schemas.exceptions import ValidateError
from openapi_core.validation.exceptions import InvalidSecurity
from sprockets.http import mixins
from tornado import httputil, web

from imbi import common, cors, errors, session, user, version

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
                raise errors.Forbidden(
                    '%s(%s) does not have the "%s" permission',
                    self._current_user.username, self._current_user.user_type,
                    permission)
            return f(self, *args, **kwargs)

        return wrapped

    return _require_permission


class RequestHandler(cors.CORSMixin, postgres.RequestHandlerMixin,
                     mixins.ErrorLogger, problemdetails.ErrorWriter,
                     sprockets.mixins.mediatype.content.ContentMixin,
                     web.RequestHandler):
    """Base RequestHandler class used for recipients and subscribers."""

    APPLICATION_JSON = 'application/json'
    TEXT_HTML = 'text/html'
    NAME = 'Base'
    ITEM_NAME = ''

    def __init__(self, application, request: httputil.HTTPServerRequest,
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
            self.application.stats.incr, {
                'key': 'http_requests',
                'endpoint': self.NAME,
                'method': self.request.method,
                'status': self.get_status()
            })

        self.application.loop.add_callback(
            self.application.stats.add_duration, {
                'key': 'http_request_duration',
                'endpoint': self.NAME,
                'method': self.request.method,
                'status': self.get_status()
            }, self.request.request_time())

    def compute_etag(self) -> None:
        """Override Tornado's built-in ETag generation"""
        return None

    async def get_current_user(self) -> typing.Optional['user.User']:
        """Used by the system to manage authentication behaviors"""
        if self.session and self.session.user:
            await self.session.user.fetch_last_seen_at()
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

    def on_postgres_timing(self, metric_name: str, duration: float) -> None:
        """Invoked by sprockets-postgres after each query"""
        self.application.loop.add_callback(
            self.application.stats.add_duration, {
                'key': 'postgres_query_duration',
                'query': metric_name,
                'endpoint': self.NAME
            }, duration)

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
                status_code=status_code,
                **kwargs)
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
            raise errors.BadRequest('Failed to deserialize body: %s',
                                    err,
                                    detail=str(err))
        except InvalidSecurity as err:
            raise errors.InternalServerError(
                'Invalid OpenAPI spec security: %s',
                err,
                title='OpenAPI Security Error')
        except OperationNotFound as err:
            raise errors.MethodNotAllowed(err.method.upper())
        except InvalidContentType as err:
            raise errors.UnsupportedMediaType(err.mimetype)
        except PathNotFound as err:
            raise errors.InternalServerError('OpenAPI Spec Error: %s',
                                             err,
                                             title='OpenAPI Spec Error',
                                             detail=str(err))
        except ValidateError as err:
            raise errors.BadRequest(
                'Request failed to validate: %s',
                err,
                detail='The request did not validate',
                errors=[str(e).split('\n')[0] for e in err.schema_errors])


class CRUDRequestHandler(ValidatingRequestHandler):
    """CRUD request handler to reduce large amounts of duplicated code"""

    NAME = 'default'
    DEFAULTS = {}
    ID_KEY: typing.Union[str, list] = 'id'
    IS_COLLECTION = False
    FIELDS = None
    ITEM_NAME = None  # Used to create link headers for POST requests
    TTL = 300

    OMIT_FIELDS: typing.Optional[list] = None  # currently unused
    """Set this to omit specific fields from a record response.

    Set this to `None` for the previous behavior of omitting
    the `created_at` and `last_modified_at` fields.

    Set this to the empty list to pass *all* fields in the
    response.

    Set this to a list of names to explicitly exclude specific
    fields in the response.

    """

    DELETE_SQL: typing.Optional[str] = None
    GET_SQL: typing.Optional[str] = None
    PATCH_SQL: typing.Optional[str] = None
    POST_SQL: typing.Optional[str] = None

    def initialize(self) -> None:
        super().initialize()
        if self.__class__.OMIT_FIELDS is None and self.OMIT_FIELDS is None:
            # implement backwards compatible behavior
            self.OMIT_FIELDS = ['created_at', 'last_modified_at']

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

        if self.request.method != 'GET' or not self.IS_COLLECTION:
            self._add_last_modified_header(
                value.get('last_modified_at', value.get('created_at')))
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

        for name in self.OMIT_FIELDS:
            value.pop(name, None)

        super().send_response(value)

    async def _delete(self, kwargs):
        result = await self.postgres_execute(self.DELETE_SQL,
                                             self._get_query_kwargs(kwargs),
                                             'delete-{}'.format(self.NAME))
        if not result.row_count:
            raise errors.ItemNotFound(instance=self.request.uri)
        self.set_status(204, reason='Item Deleted')

    async def _get(self, kwargs):
        result = await self.postgres_execute(self.GET_SQL,
                                             self._get_query_kwargs(kwargs),
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

        result = await self.postgres_execute(self.GET_SQL,
                                             self._get_query_kwargs(kwargs),
                                             'get-{}'.format(self.NAME))
        if not result.row_count:
            raise errors.ItemNotFound(instance=self.request.uri)

        original = dict(result.row)
        for key in {
                'created_at', 'created_by', 'last_modified_at',
                'last_modified_by'
        }:
            if key in original:
                del original[key]

        for key, value in original.items():
            if isinstance(value, uuid.UUID):
                original[key] = str(value)

        # Apply the patch to the current value
        patch = jsonpatch.JsonPatch(patch_value)
        updated = patch.apply(original)

        # Bail early if there are no changes
        if not {
                k: original[k]
                for k in original if k in updated and original[k] != updated[k]
        }:
            self._add_self_link(self.request.path)
            self._add_link_header()
            return self.set_status(304)

        # Let the endpoint have a say as to the validity
        if not self._check_validity(updated):
            self.logger.debug('Invalid representation generated %r', updated)
            raise errors.BadRequest('Invalid instance generated by update')

        if isinstance(self.ID_KEY, list):
            for key in self.ID_KEY:
                updated['current_{}'.format(key)] = kwargs[key]
        else:
            updated['current_{}'.format(self.ID_KEY)] = kwargs[self.ID_KEY]
        updated['username'] = self._current_user.username

        result = await self.postgres_execute(self.PATCH_SQL, updated,
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
        result = await self.postgres_execute(self.POST_SQL, values,
                                             'post-{}'.format(self.NAME))
        if not result.row_count:
            raise errors.DatabaseError('No rows returned from POST_SQL',
                                       title='Failed to create record')

            # Return the record as if it were a GET
        await self._get(self._get_query_kwargs(result.row))
        return result.row

    @staticmethod
    def _check_validity(instance: dict[str, typing.Any]) -> bool:
        """Override this method to check if an instance after patching"""
        return True


class CollectionRequestHandler(CRUDRequestHandler):
    DEFAULTS = {}
    ID_KEY: typing.Union[str, list] = 'id'
    IS_COLLECTION: True
    FIELDS = None
    ITEM_NAME = None  # Used to create link headers for POST requests
    COLLECTION_SQL = """SELECT * FROM pg_tables WHERE schemaname = 'v1';"""
    TTL = 300

    async def get(self, *args, **kwargs):
        result = await self.postgres_execute(self.COLLECTION_SQL,
                                             kwargs,
                                             metric_name='get-{}'.format(
                                                 self.NAME))
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


@dataclasses.dataclass
class TimeBasedPaginationToken:
    """Opaque token used in "next" links by the PaginatedRequestMixin"""

    start: datetime.datetime
    limit: int
    earliest: datetime.datetime

    def with_start(self, start: datetime.datetime) -> TimeBasedPaginationToken:
        """Create a new token with a different start value"""
        return TimeBasedPaginationToken(start=start,
                                        limit=self.limit,
                                        earliest=self.earliest)

    @classmethod
    def from_header(cls, header_val: str) -> TimeBasedPaginationToken:
        """Create a token from an opaque header value"""
        raw_token = common.urlsafe_padded_b64decode(header_val)
        data = umsgpack.unpackb(raw_token)
        return TimeBasedPaginationToken(
            earliest=datetime.datetime.fromisoformat(data['earliest']),
            limit=data['limit'],
            start=(datetime.datetime.fromisoformat(data['start']) -
                   datetime.timedelta.resolution))

    def to_header(self) -> str:
        """Generate an opaque header value from this token"""
        return base64.urlsafe_b64encode(
            umsgpack.packb({
                'earliest': self.earliest.isoformat(),
                'limit': self.limit,
                'start': self.start.isoformat(),
            })).decode('ascii').rstrip('=')


TimeBasedPaginationQueryMethod = typing.Callable[
    [dict[str, typing.Any]],
    typing.Coroutine[None, None, list[tuple[datetime.datetime, typing.Any]]]]
"""Type signature of the function called by PaginatedRequestHandler

This is something that looks like:

  async def retrieve_data(
      params: dict[str, typing.Any]) -> list[tuple[datetime.datetime, dict]]:
    ...

"""


class TimeBasedPaginationMixin(web.RequestHandler):
    """Mix this in to repeatedly retrieve query results ordered by time

    Call the `fetch_items` method to call a specified query method
    repeatedly until "token.limit" items have been retrieved.  The
    query method is called with a well-known set of parameters and
    returns a list of ("when", "data") tuples.  The query parameters
    are passed as a dictionary that contains at least the following
    keys:

    * ``earlier``   the earliest (oldest) record to query for
    * ``later``     the most recent record to query for
    * ``remaining`` the maximum number of records to return

    The query function should build a query similar that contains
    ``... some_column BETWEEN %(earlier)s AND %(later)s ...`` as
    well as ``... LIMIT %(remaining)s``.  The parameters dictionary
    contains any additional parameters that are passed into the
    ``fetch_items`` call.

    Call the `pagination_token_from_request` method to retrieve the
    pagination token from the current request if one exists.  If
    the token does not exist, then the concrete implementation needs
    to generate one to pass into `fetch_items`.

    """

    logger: logging.Logger

    async def fetch_items(self, token: TimeBasedPaginationToken,
                          query: TimeBasedPaginationQueryMethod,
                          time_step: datetime.timedelta,
                          **initial_params) -> list[dict]:
        """Call this to iterate over a query function and collect the result

        :param token: controls the pagination process
        :param query: coroutine function to call to retrieve data
        :param time_step: amount of time to "step" for each iteration.
            This controls how much data the "query" function is asked
            to retrieve.
        :param initial_params: additional parameters to include when
            calling `query`
        :returns: list of calling `query` until `token.limit` items
            are retrieved

        """
        buckets = []
        params = initial_params.copy()
        params.update({
            'earlier': token.start - time_step,
            'later': token.start,
            'remaining': token.limit,
        })
        while params['remaining'] > 0 and params['later'] >= token.earliest:
            buckets.extend(await query(params))
            buckets.sort(key=operator.itemgetter(0), reverse=True)
            params.update({
                'earlier': params['earlier'] - time_step,
                'later': params['earlier'],
                'remaining': token.limit - len(buckets),
            })

        buckets = buckets[:token.limit]
        if buckets and buckets[-1][0] > token.earliest:
            target = yarl.URL(self.request.uri).with_query(
                token=token.with_start(buckets[-1][0]).to_header())
            header = datastructures.LinkHeader(str(target), [('rel', 'next')])
            self.add_header('Link', str(header))

        return [entry for _, entry in buckets]

    def get_pagination_token_from_request(
            self) -> TimeBasedPaginationToken | None:
        """Retrieve the pagination token from the request"""
        token = self.get_query_argument('token', '')
        if token:
            try:
                return TimeBasedPaginationToken.from_header(token)
            except ValueError as error:
                self.logger.warning('ignoring malformed token %r: %s', token,
                                    error)


class PaginationToken:
    """Opaque pagination token for use with PaginatedCollectionHandler

    Pagination tokens are passed as the `token` query parameter
    and are read from the request by the `from_request` class method.
    The only field that is in the default token is `limit` which
    defaults to 100.

    Be aware that the body of the token is used as parameters to
    the pagination query in the handler. This interplay between
    the two classes is what should form the basis of your token.

    Create a new subclass that contains additional content to
    store in the token. There are a few rules that need to be
    followed:

    1. the keyword parameter names in `__init__` are required
       to match the keys in the dict returned from `as_dict`
    2. the `limit` parameter cannot be removed
    3. all parameters to the initializer must have default
       values unless they are path parameters to the handler
    4. path parameter names must have corresponding initializer
       parameter names

    The easiest way to do this is to set the values that you
    want for the first page as the defaults for the initializer
    keyword params and add matching path parameter names. If the
    token is not present in the request, the default token is
    created by calling the initializer without only the path
    parameters.

    Then implement the `with_first` method to merge attributes
    from the value parameter into `self.as_dict()` by passing
    overrides.

    .. code-block::

       class MyToken(PaginationToken):
          def __init__(self, *, name: str = '', project_id: int | str,
                       **kwargs: object) -> None:
             super().__init__(name=name, project_id=project_id, **kwargs)
          def with_first(self, value: dict[str, object]) -> typing.Self:
             kwargs = self.as_dict(name=value['name'])
             return MyToken(**kwargs)

    """
    def __init__(self, *, limit: int = 100, **other_props: object):
        self._data: dict[str, object] = {'limit': limit}
        self._data.update(other_props)

    @classmethod
    def from_request(cls, req: httputil.HTTPServerRequest,
                     **path_args: str) -> typing.Self:
        """Generate a token for a request

        If there is no token in the request, then a new token
        is created by calling the initializer without parameters.
        Otherwise, the content of the token is decoded and passed
        as keyword parameters to create the token instance.
        """
        encoded_token = req.query_arguments.get('token')
        if encoded_token:
            try:
                raw_token = common.urlsafe_padded_b64decode(
                    encoded_token[0].decode())
                data = umsgpack.unpackb(raw_token)
            except (AttributeError, ValueError):
                pass
            else:
                # Should we verify that path_args are present
                # in the decoded token?  What happens if someone
                # uses a token on a different URL?
                return cls(**data)

        token = cls(**path_args)
        with contextlib.suppress(IndexError, KeyError):
            token._data['limit'] = int(req.query_arguments['limit'][0])
        return token

    def as_dict(self, **overrides: object) -> dict[str, object]:
        """The properties of the token as a dictionary

        This is used to encode the token into a query string
        value. The `overrides` parameter is a convenience for
        implementing the `with_first` method.
        """
        data = self._data.copy()
        data.update(overrides)
        return data

    def with_first(self, _value: dict[str, object]) -> typing.Self:
        """Return a new token that uses `value` as the search target"""
        raise NotImplementedError

    @property
    def limit(self) -> int:
        return typing.cast(int, self._data['limit'])

    def __str__(self) -> str:
        data = umsgpack.packb(self.as_dict())
        return base64.urlsafe_b64encode(data).decode().rstrip('=')


class PaginatedCollectionHandler(CollectionRequestHandler):
    """Implements a paginated `get` method

    The `get` method uses a combination of the token returned
    from `get_pagination_token_from_request` and the COLLECTION_SQL
    query to retrieve and return pages of the collection.

    Note that the dict form of the token is passed as the parameters
    to the COLLECTION_SQL query.

    """
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.ID_KEY is None:
            self._extract_keys = lambda itm: None
        elif isinstance(self.ID_KEY, str):
            self._extract_keys = lambda itm: (itm[self.ID_KEY], )
        else:
            self._extract_keys = lambda itm: tuple(itm[k] for k in self.ID_KEY)

    def get_pagination_token_from_request(
            self, **path_params: str) -> PaginationToken:
        """Return a pagination token of the appropriate type

        The keyword parameters will match the named patterns
        from the URL match. These correspond with the keyword
        parameters passed to the `get` method.
        """
        raise NotImplementedError()

    async def get(self, **kwargs: str) -> None:
        token = self.get_pagination_token_from_request(**kwargs)
        params = token.as_dict()
        params['limit'] += 1
        rsp = await self.postgres_execute(self.COLLECTION_SQL, params)
        items = rsp.rows
        url = yarl.URL(self.request.uri)
        if len(items) > token.limit:
            items = items[:token.limit]
            target = url.with_query(token=str(token.with_first(items[-1])))
            self.add_header('Link', common.build_link_header(target, 'next'))
        target = url.with_query(limit=token.limit)
        self.add_header('Link', common.build_link_header(target, 'first'))

        if self.ITEM_NAME is not None:
            for item in items:
                item.setdefault(
                    'link',
                    self.reverse_url(self.ITEM_NAME,
                                     *self._extract_keys(item)),
                )

        self.send_response(items)


ModelType = typing.TypeVar('ModelType', bound=pydantic.BaseModel)


class PydanticHandlerMixin(RequestHandler):
    def parse_request_body_as(self,
                              model_cls: typing.Type[ModelType]) -> ModelType:
        try:
            return model_cls.model_validate(self.get_request_body())
        except pydantic.ValidationError as error:
            raise errors.ApplicationError(
                422,
                'invalid-request-body',
                'Failed to validate request body: %s',
                error,
                validation_errors=error.errors())
