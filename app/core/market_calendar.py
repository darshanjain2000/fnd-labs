"""NSE market calendar helpers (minimal; Phase 1 will add holiday list)."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def now_ist() -> datetime:
    return datetime.now(tz=IST)


def is_market_open(at: datetime | None = None) -> bool:
    at = at or now_ist()
    if at.weekday() >= 5:
        return False
    return MARKET_OPEN <= at.time() <= MARKET_CLOSE


def minutes_to_close(at: datetime | None = None) -> int:
    at = at or now_ist()
    close_dt = at.replace(hour=MARKET_CLOSE.hour, minute=MARKET_CLOSE.minute, second=0, microsecond=0)
    delta = (close_dt - at).total_seconds() / 60
    return max(0, int(delta))
