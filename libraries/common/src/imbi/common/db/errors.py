"""Map constraint violations (SQLSTATE) to HTTP responses.

One mapping for every app (implementation plan D18, recipe step 4):

=========  ========================  ======================  ======
SQLSTATE   psycopg error             Cause                   Status
=========  ========================  ======================  ======
``23001``  ``RestrictViolation``     RESTRICT delete         409
``23503``  ``ForeignKeyViolation``   other rows refer to it  409
``23503``  ``ForeignKeyViolation``   missing referenced row  422
``23505``  ``UniqueViolation``       duplicate key           409
``23514``  ``CheckViolation``        CHECK or domain         422
=========  ========================  ======================  ======

23503 has two sides. On the parent side, a delete or a key change is
blocked by rows that refer to the row: 409. On the child side, an
insert or an update refers to a row that does not exist: 422. The
server gives no field for the side, only the text of
``diag.message_primary``: ``insert or update on table ...`` for the
child side and ``update or delete on table ...`` for the parent side.
That text is English only while the server's ``lc_messages`` is
English. With other text, the violation is taken as the parent side.

:func:`add_exception_handlers` registers a fallback handler for these
errors. The handler returns the standard error body,
``{"detail": "..."}``, with a general message. An endpoint that must
keep a specific message wraps its transaction in
:func:`violation_details`.

"""

import contextlib
import logging
import typing
from collections import abc

import fastapi
import psycopg
from fastapi import responses
from psycopg import errors

LOGGER = logging.getLogger(__name__)

_CHILD_SIDE_PREFIX = 'insert or update on table '

_REFERENCED = 'Other resources refer to this resource'

#: The HTTP status and the fallback ``detail`` of each cause.
RULES: dict[str, tuple[int, str]] = {
    'restrict': (409, _REFERENCED),
    'referenced': (409, _REFERENCED),
    'missing_reference': (
        422,
        'The request refers to a resource that does not exist',
    ),
    'unique': (409, 'The resource already exists'),
    'check': (422, 'The request has a value that is not permitted'),
}

_ERRORS: tuple[type[psycopg.errors.IntegrityError], ...] = (
    errors.RestrictViolation,
    errors.ForeignKeyViolation,
    errors.UniqueViolation,
    errors.CheckViolation,
)


def cause(exc: psycopg.Error) -> str:
    """Return the :data:`RULES` key of a mapped violation."""
    if isinstance(exc, errors.RestrictViolation):
        return 'restrict'
    if isinstance(exc, errors.ForeignKeyViolation):
        message = exc.diag.message_primary or ''
        if message.startswith(_CHILD_SIDE_PREFIX):
            return 'missing_reference'
        return 'referenced'
    if isinstance(exc, errors.UniqueViolation):
        return 'unique'
    return 'check'


@contextlib.contextmanager
def violation_details(
    *,
    restrict: str | None = None,
    foreign_key: str | None = None,
    unique: str | None = None,
    check: str | None = None,
) -> abc.Generator[None]:
    """Raise ``HTTPException`` with an endpoint's own message.

    Each argument is the ``detail`` for one SQLSTATE: *restrict* for
    23001, *foreign_key* for 23503 (both sides), *unique* for 23505, and
    *check* for 23514. The status is the status of :data:`RULES`. A
    violation with no message here goes to the fallback handler.

    .. code-block:: python

        with errors.violation_details(
            unique=f'Tag with slug {slug!r} already exists'
        ):
            async with db.transaction(org_id, principal_id) as tx:
                ...

    """
    details = {
        'restrict': restrict,
        'referenced': foreign_key,
        'missing_reference': foreign_key,
        'unique': unique,
        'check': check,
    }
    try:
        yield
    except _ERRORS as exc:
        key = cause(exc)
        detail = details[key]
        if detail is None:
            raise
        _log(exc)
        raise fastapi.HTTPException(
            status_code=RULES[key][0], detail=detail
        ) from exc


def _log(exc: psycopg.Error) -> None:
    LOGGER.info(
        'Constraint violation %s on %s (%s): %s',
        exc.sqlstate,
        exc.diag.table_name,
        exc.diag.constraint_name,
        exc.diag.message_primary,
    )


async def _handle_violation(
    _request: fastapi.Request, exc: Exception
) -> responses.JSONResponse:
    # Registered only for the classes in _ERRORS.
    error = typing.cast('psycopg.Error', exc)
    _log(error)
    status, detail = RULES[cause(error)]
    return responses.JSONResponse(
        status_code=status, content={'detail': detail}
    )


def add_exception_handlers(app: fastapi.FastAPI) -> None:
    """Register the fallback handler for each mapped SQLSTATE."""
    for cls in _ERRORS:
        app.add_exception_handler(cls, _handle_violation)
