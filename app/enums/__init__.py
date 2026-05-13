"""Project-wide enum definitions.

Centralising IntEnum/StrEnum types here keeps magic numbers and strings out
of business logic. See ``app.enums.exception_codes`` for the canonical list
of error codes returned in ``ApiResponse.statusCode``.
"""

from __future__ import annotations

from app.enums.exception_codes import CustomExceptionCodes
from app.enums.regime import Regime

__all__ = ["CustomExceptionCodes", "Regime"]
