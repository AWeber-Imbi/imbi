"""
Custom exceptions for Imbi.

RFC 7807 Problem Details for HTTP APIs error responses.
"""

from fastapi import status
from fastapi.responses import JSONResponse


class ProblemDetailException(Exception):
    """Base exception for RFC 7807 Problem Details responses."""

    def __init__(
        self,
        status_code: int,
        title: str,
        detail: str,
        type_url: str | None = None,
    ):
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.type_url = (
            type_url
            or f"https://imbi.example.com/errors/{title.lower().replace(' ', '-')}"
        )
        super().__init__(detail)

    def to_response(self) -> JSONResponse:
        """Convert to JSONResponse with RFC 7807 format."""
        return JSONResponse(
            status_code=self.status_code,
            content={
                "type": self.type_url,
                "title": self.title,
                "status": self.status_code,
                "detail": self.detail,
            },
        )


class Unauthorized(ProblemDetailException):
    """401 Unauthorized error."""

    def __init__(self, detail: str = "Authentication required"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Unauthorized",
            detail=detail,
            type_url="https://imbi.example.com/errors/unauthorized",
        )


class Forbidden(ProblemDetailException):
    """403 Forbidden error."""

    def __init__(self, detail: str = "Forbidden"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Forbidden",
            detail=detail,
            type_url="https://imbi.example.com/errors/forbidden",
        )


class NotFound(ProblemDetailException):
    """404 Not Found error."""

    def __init__(self, detail: str = "Not found"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=detail,
            type_url="https://imbi.example.com/errors/not-found",
        )


class Conflict(ProblemDetailException):
    """409 Conflict error."""

    def __init__(self, detail: str = "Conflict"):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail=detail,
            type_url="https://imbi.example.com/errors/conflict",
        )
