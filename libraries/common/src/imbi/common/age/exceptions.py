"""Exception wrappers for Apache AGE / psycopg errors.

Provides exception types that mirror the Neo4j driver exceptions
previously used throughout the codebase, allowing endpoint code to
change only the import path.
"""


class ConstraintError(Exception):
    """Raised when a unique constraint is violated.

    Wraps ``psycopg.errors.UniqueViolation`` so that calling code
    can catch a domain-specific exception without importing psycopg
    directly.
    """

    def __init__(self, message: str = 'Unique constraint violated') -> None:
        super().__init__(message)


class ClientError(Exception):
    """Raised for general AGE / database client errors."""

    def __init__(
        self, message: str = 'Database client error', code: str | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
