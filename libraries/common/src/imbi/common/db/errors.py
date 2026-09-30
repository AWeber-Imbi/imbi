"""Map constraint violations (SQLSTATE) to HTTP responses.

One mapping for every app (implementation plan D18, recipe step 4):

=========  ========================  ======
SQLSTATE   psycopg error             Status
=========  ========================  ======
``23001``  ``RestrictViolation``     409
``23503``  ``ForeignKeyViolation``   409
``23505``  ``UniqueViolation``       409
``23514``  ``CheckViolation``        422
=========  ========================  ======

A CHECK constraint and a domain (``slug``, ``jsonb_object``) both raise
23514. :func:`add_exception_handlers` registers a fallback handler for
these errors. The handler returns the standard error body,
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

RESTRICT_VIOLATION = '23001'
FOREIGN_KEY_VIOLATION = '23503'
UNIQUE_VIOLATION = '23505'
CHECK_VIOLATION = '23514'

STATUS: dict[str, int] = {
    RESTRICT_VIOLATION: 409,
    FOREIGN_KEY_VIOLATION: 409,
    UNIQUE_VIOLATION: 409,
    CHECK_VIOLATION: 422,
}

_DETAIL: dict[str, str] = {
    RESTRICT_VIOLATION: 'Other resources refer to this resource',
    FOREIGN_KEY_VIOLATION: 'The request conflicts with a related resource',
    UNIQUE_VIOLATION: 'The resource already exists',
    CHECK_VIOLATION: 'The request has a value that is not permitted',
}

_ERRORS: tuple[type[psycopg.errors.IntegrityError], ...] = (
    errors.RestrictViolation,
    errors.ForeignKeyViolation,
    errors.UniqueViolation,
    errors.CheckViolation,
)


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
    23001, *foreign_key* for 23503, *unique* for 23505, and *check* for
    23514. A violation with no message here goes to the fallback
    handler.

    .. code-block:: python

        with errors.violation_details(
            unique=f'Tag with slug {slug!r} already exists'
        ):
            async with db.transaction(org_id, principal_id) as tx:
                ...

    """
    details = {
        RESTRICT_VIOLATION: restrict,
        FOREIGN_KEY_VIOLATION: foreign_key,
        UNIQUE_VIOLATION: unique,
        CHECK_VIOLATION: check,
    }
    try:
        yield
    except _ERRORS as exc:
        detail = details[exc.sqlstate or '']
        if detail is None:
            raise
        _log(exc)
        raise fastapi.HTTPException(
            status_code=STATUS[exc.sqlstate or ''], detail=detail
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
    sqlstate = error.sqlstate or ''
    _log(error)
    return responses.JSONResponse(
        status_code=STATUS[sqlstate], content={'detail': _DETAIL[sqlstate]}
    )


def add_exception_handlers(app: fastapi.FastAPI) -> None:
    """Register the fallback handler for each mapped SQLSTATE."""
    for cls in _ERRORS:
        app.add_exception_handler(cls, _handle_violation)
