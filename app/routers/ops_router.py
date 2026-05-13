"""Operations endpoints for deployment readiness checks."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.models.api import ApiResponse

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/paper-ready", response_model=ApiResponse[dict])
def paper_ready() -> ApiResponse[dict]:
    """Return a deployment readiness check for paper-trade mode.

    This endpoint validates the minimum safe settings for a paper-first run
    (local or AWS): no live mode, scheduler auto-start, AI disabled, and a
    non-empty watchlist.

    Returns:
        ApiResponse with ``ready`` flag and a detailed checks dictionary.
    """
    s = get_settings()
    checks: dict[str, bool] = {
        "mode_is_paper": s.mode == "paper",
        "broker_is_paper": s.broker == "paper",
        "paper_trade_flag": bool(s.paper_trade),
        "auto_run_enabled": bool(s.auto_run_enabled),
        "ai_disabled": not bool(s.openrouter_enabled),
        "watchlist_non_empty": len(s.watchlist_pairs()) > 0,
        "run_interval_positive": s.run_interval_sec > 0,
        "market_times_set": bool(
            s.market_open and s.market_close and s.square_off_time
        ),
    }
    ready = all(checks.values())
    return ApiResponse[dict].ok(
        {
            "ready": ready,
            "checks": checks,
            "watchlist": [f"{sym}:{exch}" for sym, exch in s.watchlist_pairs()],
            "notes": (
                "Paper deployment settings look safe"
                if ready
                else "One or more paper-mode safety checks failed"
            ),
        }
    )
