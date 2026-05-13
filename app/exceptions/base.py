"""Base class for all project-specific domain exceptions."""

from __future__ import annotations

from app.enums.exception_codes import CustomExceptionCodes


class DomainException(Exception):
    """Base class for all project-specific domain exceptions.

    Subclasses set ``error_code`` (a ``CustomExceptionCodes`` value). The
    global FastAPI exception handler reads ``error_code`` and ``str(exc)``
    to populate ``ApiResponse.statusCode`` and ``ApiResponse.error``.

    Attributes:
        error_code: Project-specific numeric code (6xx range) identifying
            the exception class. Subclasses override this as a class attr.
    """

    error_code: CustomExceptionCodes = CustomExceptionCodes.ProcessingFailed

    def __init__(self, message: str = "") -> None:
        """Initialise with a human-readable message.

        Args:
            message: Free-form message. Stored as the exception args[0] so
                ``str(exc)`` returns it verbatim.
        """
        super().__init__(message)
