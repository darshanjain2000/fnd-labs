"""NSE market calendar helpers with holiday-aware open-day checks."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

# NSE trading holidays (cash market) for currently supported years.
# Keep this list updated each year from NSE circulars.
NSE_HOLIDAYS: set[date] = {
    # 2026
    date(2026, 1, 26),  # Republic Day
    date(2026, 2, 18),  # Maha Shivaratri
    date(2026, 3, 6),  # Holi
    date(2026, 3, 27),  # Id-Ul-Fitr (Ramzan Eid)
    date(2026, 4, 3),  # Mahavir Jayanti
    date(2026, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),  # Maharashtra Day
    date(2026, 8, 15),  # Independence Day
    date(2026, 8, 27),  # Ganesh Chaturthi
    date(2026, 10, 2),  # Gandhi Jayanti / Dussehra
    date(2026, 10, 20),  # Diwali Laxmi Pujan (Muhurat day is session-specific)
    date(2026, 11, 5),  # Diwali Balipratipada
    date(2026, 11, 15),  # Gurunanak Jayanti
    date(2026, 12, 25),  # Christmas
}


def now_ist() -> datetime:
    """Return current timestamp in IST timezone."""
    return datetime.now(tz=IST)


def parse_hhmm(value: str) -> time:
    """Parse ``HH:MM`` into a time object.

    Args:
        value: Time string in 24-hour ``HH:MM`` format.

    Returns:
        Parsed ``datetime.time``.
    """
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def is_market_day(day: date, holidays: set[date] | None = None) -> bool:
    """Return True when NSE cash market is open on this date.

    Args:
        day: IST calendar date.

    Returns:
        False for weekends and configured NSE holidays.
    """
    holiday_set = NSE_HOLIDAYS if holidays is None else holidays
    if day.weekday() >= 5:
        return False
    return day not in holiday_set


def is_market_open(
    at: datetime | None = None,
    *,
    market_open: time = MARKET_OPEN,
    market_close: time = MARKET_CLOSE,
    holidays: set[date] | None = None,
) -> bool:
    """Return True if market is open at the given IST timestamp.

    Args:
        at: Reference datetime in IST. Uses current IST when omitted.
        market_open: Daily market open time.
        market_close: Daily market close time.
        holidays: Optional holiday override set for tests/custom calendars.

    Returns:
        True when day is tradable and time is inside the configured window.
    """
    at = at or now_ist()
    if not is_market_day(at.date(), holidays=holidays):
        return False
    return market_open <= at.time() <= market_close


def minutes_to_close(
    at: datetime | None = None, *, market_close: time = MARKET_CLOSE
) -> int:
    """Return minutes remaining to market close; 0 when already closed."""
    at = at or now_ist()
    close_dt = at.replace(
        hour=market_close.hour,
        minute=market_close.minute,
        second=0,
        microsecond=0,
    )
    delta = (close_dt - at).total_seconds() / 60
    return max(0, int(delta))


def next_market_open(
    at: datetime | None = None,
    *,
    market_open: time = MARKET_OPEN,
    holidays: set[date] | None = None,
) -> datetime:
    """Return the next NSE market open datetime in IST.

    Args:
        at: Reference IST timestamp. Uses current IST when omitted.

    Returns:
        Next trading session open timestamp in IST.
    """
    at = at or now_ist()
    candidate = at.replace(
        hour=market_open.hour, minute=market_open.minute, second=0, microsecond=0
    )
    if candidate <= at:
        candidate += timedelta(days=1)
    while not is_market_day(candidate.date(), holidays=holidays):
        candidate += timedelta(days=1)
    return candidate
