"""Tests for market calendar open-day and holiday behavior."""

from __future__ import annotations

from datetime import date, datetime, time

from app.core.market_calendar import (
    IST,
    is_market_day,
    is_market_open,
    minutes_to_close,
    next_market_open,
)


def test_is_market_day_false_on_weekend() -> None:
    """Weekend must be treated as non-trading day."""
    assert is_market_day(date(2026, 5, 16)) is False  # Saturday


def test_is_market_day_false_on_nse_holiday() -> None:
    """Configured NSE holiday must be treated as non-trading day."""
    assert is_market_day(date(2026, 1, 26)) is False


def test_is_market_open_false_on_holiday_even_in_hours() -> None:
    """Market must remain closed on holiday despite in-session clock time."""
    at = datetime(2026, 1, 26, 10, 0, tzinfo=IST)
    assert is_market_open(at) is False


def test_next_market_open_skips_holiday() -> None:
    """Next open should skip holiday and return next valid market day."""
    # Jan 25, 2026 is Sunday; Jan 26 is Republic Day holiday.
    at = datetime(2026, 1, 25, 10, 0, tzinfo=IST)
    nxt = next_market_open(at)
    assert nxt.date() == date(2026, 1, 27)
    assert nxt.hour == 9 and nxt.minute == 15


def test_is_market_open_respects_custom_market_window() -> None:
    """Custom market window should be respected for open/close checks."""
    at = datetime(2026, 4, 20, 9, 30, tzinfo=IST)
    assert is_market_open(at, market_open=time(9, 0), market_close=time(10, 0)) is True
    assert (
        is_market_open(at, market_open=time(10, 0), market_close=time(11, 0)) is False
    )


def test_minutes_to_close_uses_custom_close_time() -> None:
    """Minutes-to-close should use the supplied close time when provided."""
    at = datetime(2026, 4, 20, 15, 0, tzinfo=IST)
    assert minutes_to_close(at, market_close=time(15, 30)) == 30
    assert minutes_to_close(at, market_close=time(15, 0)) == 0
