"""Concrete domain exceptions raised by services, controllers, and DAL."""

from __future__ import annotations

from app.enums.exception_codes import CustomExceptionCodes
from app.exceptions.base import DomainException


class DataNotFoundException(DomainException):
    """Generic 'row not found' — used when a more specific subclass doesn't fit."""

    error_code = CustomExceptionCodes.DataNotFound


class TradeNotFoundException(DomainException):
    """Raised when a Trade row lookup returns no rows."""

    error_code = CustomExceptionCodes.TradeNotFound


class SignalNotFoundException(DomainException):
    """Raised when a Signal row lookup returns no rows."""

    error_code = CustomExceptionCodes.SignalNotFound


class InvalidRequestException(DomainException):
    """Raised when request validation fails at the controller/service boundary."""

    error_code = CustomExceptionCodes.InvalidRequest


class BrokerOrderException(DomainException):
    """Raised when a broker rejects an order or returns an unexpected response."""

    error_code = CustomExceptionCodes.BrokerError


class SpendCapExceededException(DomainException):
    """Raised when the daily LLM spend cap has been hit.

    Replaces the legacy ``SpendCapExceeded(RuntimeError)`` in ``llm_client``.
    The old name is still re-exported from ``app.services.llm_client`` for
    back-compat, but new code should catch this class directly.
    """

    error_code = CustomExceptionCodes.SpendCapExceeded


class ProcessingFailedException(DomainException):
    """Generic 'something went wrong' for unexpected internal errors."""

    error_code = CustomExceptionCodes.ProcessingFailed


class RiskGateRejectedException(DomainException):
    """Raised when the RiskEngine rejects a signal (kill switch, gate failure, etc.)."""

    error_code = CustomExceptionCodes.RiskGateRejected
