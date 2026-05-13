"""Numeric error codes returned in ``ApiResponse.statusCode``.

The 6xx range is reserved for project-specific domain errors so callers can
distinguish them from standard HTTP status codes. Every domain exception in
``app.exceptions`` maps to exactly one code here.
"""

from __future__ import annotations

from enum import IntEnum


class CustomExceptionCodes(IntEnum):
    """Project-specific error codes for the ``ApiResponse`` envelope.

    Codes use the 6xx range to avoid clashes with HTTP status codes. New
    members should be added at the end so historical callers keep working.
    """

    DataNotFound = 601
    InvalidRequest = 602
    TradeNotFound = 603
    SignalNotFound = 604
    SpendCapExceeded = 605
    ProcessingFailed = 606
    BrokerError = 607
    RiskGateRejected = 608
