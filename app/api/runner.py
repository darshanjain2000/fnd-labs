"""Runner control (start/stop/status) + EOD Report API."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time as dtime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.trade import AuditLog, Signal, Trade
from app.services.scheduler import get_scheduler

IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(prefix="/runner", tags=["runner"])
report_router = APIRouter(prefix="/report", tags=["report"])


class StartResponse(BaseModel):
    started: bool
    already_running: bool


@router.post("/start", response_model=StartResponse)
def start_runner() -> StartResponse:
    sched = get_scheduler()
    started = sched.start()
    return StartResponse(started=started, already_running=not started)


@router.post("/stop")
async def stop_runner() -> dict:
    sched = get_scheduler()
    await sched.stop()
    return {"stopped": True, "status": _status_dict(sched)}


@router.get("/status")
def runner_status() -> dict:
    return _status_dict(get_scheduler())


def _status_dict(sched) -> dict:
    s = sched.status
    return {
        "running": s.running,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "last_tick_at": s.last_tick_at.isoformat() if s.last_tick_at else None,
        "ticks": s.ticks,
        "signals_seen": s.signals_seen,
        "trades_opened": s.trades_opened,
        "trades_auto_closed": s.trades_auto_closed,
        "last_error": s.last_error,
        "watchlist": s.watchlist,
    }


# -------- EOD Report ---------------------------------------------------------
def _ist_day_window(target: date) -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) for the given IST calendar day."""
    start_ist = datetime.combine(target, dtime(0, 0), tzinfo=IST)
    end_ist = datetime.combine(target, dtime(23, 59, 59), tzinfo=IST)
    # DB stores UTC-naive datetimes (datetime.utcnow)
    return (
        start_ist.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
        end_ist.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
    )


@report_router.get("/today")
def report_today(session: Session = Depends(get_session)) -> dict:
    """End-of-day summary: trades count, wins/losses, total P&L, breakdowns."""
    return _report_for(datetime.now(IST).date(), session)


@report_router.get("/day/{day_iso}")
def report_day(day_iso: str, session: Session = Depends(get_session)) -> dict:
    """Summary for a specific IST calendar day (YYYY-MM-DD)."""
    target = date.fromisoformat(day_iso)
    return _report_for(target, session)


def _report_for(target: date, session: Session) -> dict:
    start_utc, end_utc = _ist_day_window(target)

    # All trades whose entry OR exit fell within the IST day
    trades: list[Trade] = (
        session.query(Trade)
        .filter(Trade.opened_at >= start_utc, Trade.opened_at <= end_utc)
        .order_by(desc(Trade.opened_at))
        .all()
    )

    signals_count = (
        session.query(Signal)
        .filter(Signal.created_at >= start_utc, Signal.created_at <= end_utc)
        .count()
    )

    closed = [t for t in trades if t.status == "CLOSED"]
    open_trades = [t for t in trades if t.status == "OPEN"]
    wins = [t for t in closed if (t.pnl or 0) > 0]
    losses = [t for t in closed if (t.pnl or 0) < 0]
    total_pnl = round(sum((t.pnl or 0) for t in closed), 2)

    per_symbol: dict[str, dict] = defaultdict(lambda: {"trades": 0, "pnl": 0.0})
    per_strategy: dict[str, dict] = defaultdict(lambda: {"trades": 0, "pnl": 0.0})
    for t in closed:
        per_symbol[t.symbol]["trades"] += 1
        per_symbol[t.symbol]["pnl"] = round(per_symbol[t.symbol]["pnl"] + (t.pnl or 0), 2)
        key = t.strategy or "unknown"
        per_strategy[key]["trades"] += 1
        per_strategy[key]["pnl"] = round(per_strategy[key]["pnl"] + (t.pnl or 0), 2)

    return {
        "date_ist": target.isoformat(),
        "summary": {
            "signals_generated": signals_count,
            "trades_taken": len(trades),
            "trades_closed": len(closed),
            "trades_still_open": len(open_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(100 * len(wins) / len(closed), 2) if closed else 0.0,
            "total_pnl": total_pnl,
            "best_trade_pnl": max((t.pnl or 0) for t in closed) if closed else 0.0,
            "worst_trade_pnl": min((t.pnl or 0) for t in closed) if closed else 0.0,
        },
        "per_symbol": dict(per_symbol),
        "per_strategy": dict(per_strategy),
        "trades": [
            {
                "id": t.id,
                "symbol": t.symbol,
                "strategy": t.strategy,
                "side": t.side,
                "qty": t.qty,
                "entry": t.entry_price,
                "exit": t.exit_price,
                "sl": t.stop_loss,
                "target": t.target,
                "pnl": t.pnl,
                "status": t.status,
                "opened_at": t.opened_at.isoformat() if t.opened_at else None,
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            }
            for t in trades
        ],
    }
