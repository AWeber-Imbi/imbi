"""Nicer application errors.

This module contains specializations of :class:`problemdetails.Problem`
that provide a customizable ``type`` member along with some useful
functionality for specific error cases.

"""
import typing

import problemdetails
import tornado.httputil
import tornado.web
import yarl


ERROR_URL = yarl.URL('https://localhost/')


def set_canonical_server(server_name: str) -> None:
    """Call this to override the ``type`` URL in errors."""
    global ERROR_URL
    ERROR_URL = yarl.URL.build(scheme='https', host=server_name)


class ApplicationError(problemdetails.Problem):
    """Generic error with some niceties added.

    The ``log_message`` parameter is required to ensure that we
    have log output when we are returning an error.  There is
    additional code to handle incongruent log format and args
    so that we avoid *most* log format failure exceptions.

    The ``reason`` attribute is always set.  It will use the
    ``title`` parameter or the appropriate HTTP reason.

    The ``type`` property is set to the current ``ERROR_URL``
    with the supplied `fragment` appended.

    The ``detail`` property is set to the formatted log
    message.

    """

    # work around some typing weirdness in problemdetails...
    document: typing.Dict[str, typing.Any]
    log_message: str
    reason: str

    def __init__(self, status_code: int, fragment: str,
                 log_message: str, *log_args, **kwargs):
        # NB -- tornado.web.HTTPError DOES NOT set the reason for us :/
        kwargs['reason'] = kwargs.get(
            'reason',
            kwargs.get(
                'title',
                tornado.httputil.responses.get(status_code,
                                               'Unknown Status Code')).title())
        kwargs.setdefault('type', str(ERROR_URL.with_fragment(fragment)))

        # tornado provides partial protection against log message format
        # edge cases but does not insulate against having unnecessary args
        log_args = () if '%' not in log_message else log_args

        super().__init__(status_code, log_message, *log_args, **kwargs)
        self.document.setdefault('title', self.reason)
        self.document.setdefault('detail', self.log_message % log_args)


class BadRequest(ApplicationError):
    def __init__(self, log_message, *log_args, **kwargs):
        super().__init__(400, 'bad-request', log_message, *log_args, **kwargs)


class Forbidden(ApplicationError):
    def __init__(self, log_message, *log_args, **kwargs):
        super().__init__(403, 'forbidden', log_message, *log_args, **kwargs)


class ItemNotFound(ApplicationError):
    def __init__(self, log_message=None, *log_args, **kwargs):
        kwargs.setdefault('title', 'Item not found')
        super().__init__(
            404, 'not-found',
            'Item not found' if log_message is None else log_message,
            *log_args, **kwargs)


class MethodNotAllowed(ApplicationError):
    def __init__(self, requested_method: str, **kwargs):
        super().__init__(405, 'method-not-allowed',
                         '%s is not a supported HTTP method',
                         requested_method.upper(), **kwargs)


class UnsupportedMediaType(ApplicationError):
    def __init__(self, media_type: str, **kwargs):
        super().__init__(
            415, 'unsupported-media-type', '%s is not a supported media type',
            media_type, **kwargs)


class InternalServerError(ApplicationError):
    def __init__(self, log_message, *log_args, **kwargs):
        super().__init__(500, 'server-error', log_message, *log_args, **kwargs)


class DatabaseError(InternalServerError):
    def __init__(self, log_message=None, *log_args,
                 error: typing.Optional[Exception] = None, **kwargs):
        kwargs.setdefault('title', 'Database Error')
        if log_message is None:
            if error is not None:
                log_message = 'Database failure: %s'
                log_args = (error, )
            else:
                log_message = 'Database failure'
                log_args = ()
        super().__init__(log_message, *log_args, **kwargs)


class IntegrationNotFound(InternalServerError):
    def __init__(self, integration_name: str):
        super().__init__('integration lookup failed for %s', integration_name,
                         title='Integration Missing')
