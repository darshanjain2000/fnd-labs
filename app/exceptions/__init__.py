"""Domain exception hierarchy used across services, controllers, and routes.

Every exception here subclasses ``DomainException`` and carries a
``CustomExceptionCodes`` value. The global FastAPI exception handler in
``app.main`` translates these into ``ApiResponse`` envelopes automatically.
"""
from __future__ import annotations

from app.exceptions.base import DomainException
from app.exceptions.domain import (
    BrokerOrderException,
    DataNotFoundException,
    InvalidRequestException,
    ProcessingFailedException,
    RiskGateRejectedException,
    SignalNotFoundException,
    SpendCapExceededException,
    TradeNotFoundException,
)

__all__ = [
    "DomainException",
    "DataNotFoundException",
    "TradeNotFoundException",
    "SignalNotFoundException",
    "InvalidRequestException",
    "BrokerOrderException",
    "SpendCapExceededException",
    "ProcessingFailedException",
    "RiskGateRejectedException",
]
