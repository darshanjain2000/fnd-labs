"""Generic ``ApiResponse[T]`` envelope used by every API handler."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

from app.enums.exception_codes import CustomExceptionCodes
from app.exceptions.base import DomainException

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Uniform response envelope for all HTTP endpoints.

    The frontend always sees the same shape: a ``statusCode`` (either an
    HTTP status or a ``CustomExceptionCodes`` value), an optional ``message``
    and ``result`` on success, and an ``error`` string on failure.

    Attributes:
        statusCode: HTTP status for success paths (200/201/...) or a
            ``CustomExceptionCodes`` value (6xx) for domain errors.
        message: Human-readable message. Set on success where useful.
        result: Typed payload on success. ``None`` on error paths.
        error: Human-readable error message. ``None`` on success paths.
    """

    statusCode: int
    message: str | None = None
    result: T | None = None
    error: str | None = None

    @classmethod
    def ok(
        cls, result: T, *, message: str | None = None, status_code: int = 200
    ) -> ApiResponse[T]:
        """Build a success envelope.

        Args:
            result: Typed payload to embed in ``result``.
            message: Optional human-readable message.
            status_code: HTTP status code; defaults to 200.

        Returns:
            ``ApiResponse`` with ``error`` unset.
        """
        return cls(statusCode=status_code, message=message, result=result, error=None)

    @classmethod
    def from_exception(cls, exc: DomainException) -> ApiResponse[T]:
        """Build an error envelope from a ``DomainException``.

        Args:
            exc: A raised domain exception. Its ``error_code`` becomes
                ``statusCode`` and ``str(exc)`` becomes ``error``.

        Returns:
            ``ApiResponse`` with ``result`` unset.
        """
        code: CustomExceptionCodes = exc.error_code
        return cls(
            statusCode=int(code),
            message=None,
            result=None,
            error=str(exc) or exc.__class__.__name__,
        )
