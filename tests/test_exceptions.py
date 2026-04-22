"""Tests for the ``app.exceptions`` domain hierarchy + ``CustomExceptionCodes``."""
from __future__ import annotations

import pytest

from app.enums.exception_codes import CustomExceptionCodes
from app.exceptions import (
    BrokerOrderException,
    DataNotFoundException,
    DomainException,
    InvalidRequestException,
    ProcessingFailedException,
    RiskGateRejectedException,
    SignalNotFoundException,
    SpendCapExceededException,
    TradeNotFoundException,
)


def test_exception_codes_are_unique_and_in_6xx_range() -> None:
    """Every code must be unique and sit in the 600–699 range."""
    values = [c.value for c in CustomExceptionCodes]
    assert len(values) == len(set(values)), "duplicate exception codes"
    assert all(600 <= v < 700 for v in values), f"codes outside 6xx: {values}"


@pytest.mark.parametrize(
    ("exc_cls", "expected_code"),
    [
        (DataNotFoundException, CustomExceptionCodes.DataNotFound),
        (TradeNotFoundException, CustomExceptionCodes.TradeNotFound),
        (SignalNotFoundException, CustomExceptionCodes.SignalNotFound),
        (InvalidRequestException, CustomExceptionCodes.InvalidRequest),
        (BrokerOrderException, CustomExceptionCodes.BrokerError),
        (SpendCapExceededException, CustomExceptionCodes.SpendCapExceeded),
        (ProcessingFailedException, CustomExceptionCodes.ProcessingFailed),
        (RiskGateRejectedException, CustomExceptionCodes.RiskGateRejected),
    ],
)
def test_each_domain_exception_maps_to_its_code(exc_cls, expected_code) -> None:
    """Every concrete domain exception carries the right ``error_code``."""
    exc = exc_cls("boom")
    assert isinstance(exc, DomainException)
    assert exc.error_code == expected_code
    assert str(exc) == "boom"


def test_domain_exception_is_raisable_and_catchable() -> None:
    """``raise`` / ``except`` works via the base class."""
    with pytest.raises(DomainException) as info:
        raise TradeNotFoundException("trade 42 not found")
    assert info.value.error_code == CustomExceptionCodes.TradeNotFound


def test_legacy_spend_cap_alias_is_same_class() -> None:
    """The old ``SpendCapExceeded`` name must still work as an alias."""
    from app.services.llm_client import SpendCapExceeded

    assert SpendCapExceeded is SpendCapExceededException
