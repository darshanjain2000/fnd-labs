"""End-of-day report endpoints."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time as dtime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.api import ApiResponse, ReportBucket, ReportOut, ReportSummary, TradeOut
from app.models.trade import Signal, Trade

IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(prefix="/report", tags=["report"])


def _ist_day_window(target: date) -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) covering the IST calendar day ``target``."""
    start_ist = datetime.combine(target, dtime(0, 0), tzinfo=IST)
    end_ist = datetime.combine(target, dtime(23, 59, 59), tzinfo=IST)
    return (
        start_ist.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
        end_ist.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
    )


@router.get("/today", response_model=ApiResponse[ReportOut])
def report_today(session: Session = Depends(get_session)) -> ApiResponse[ReportOut]:
    """End-of-day summary for today's IST calendar date."""
    return ApiResponse[ReportOut].ok(_report_for(datetime.now(IST).date(), session))


@router.get("/day/{day_iso}", response_model=ApiResponse[ReportOut])
def report_day(day_iso: str, session: Session = Depends(get_session)) -> ApiResponse[ReportOut]:
    """End-of-day summary for a specific IST calendar day (``YYYY-MM-DD``)."""
    target = date.fromisoformat(day_iso)
    return ApiResponse[ReportOut].ok(_report_for(target, session))


def _report_for(target: date, session: Session) -> ReportOut:
    """Aggregate trade/signal metrics for ``target`` (IST day) into a report DTO."""
    start_utc, end_utc = _ist_day_window(target)

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

    per_symbol: dict[str, dict[str, float]] = defaultdict(lambda: {"trades": 0, "pnl": 0.0})
    per_strategy: dict[str, dict[str, float]] = defaultdict(lambda: {"trades": 0, "pnl": 0.0})
    for t in closed:
        per_symbol[t.symbol]["trades"] += 1
        per_symbol[t.symbol]["pnl"] = round(per_symbol[t.symbol]["pnl"] + (t.pnl or 0), 2)
        key = t.strategy or "unknown"
        per_strategy[key]["trades"] += 1
        per_strategy[key]["pnl"] = round(per_strategy[key]["pnl"] + (t.pnl or 0), 2)

    summary = ReportSummary(
        signals_generated=signals_count,
        trades_taken=len(trades),
        trades_closed=len(closed),
        trades_still_open=len(open_trades),
        wins=len(wins),
        losses=len(losses),
        win_rate_pct=round(100 * len(wins) / len(closed), 2) if closed else 0.0,
        total_pnl=total_pnl,
        best_trade_pnl=max((t.pnl or 0) for t in closed) if closed else 0.0,
        worst_trade_pnl=min((t.pnl or 0) for t in closed) if closed else 0.0,
    )

    return ReportOut(
        date_ist=target.isoformat(),
        summary=summary,
        per_symbol={
            sym: ReportBucket(trades=int(buckets["trades"]), pnl=float(buckets["pnl"]))
            for sym, buckets in per_symbol.items()
        },
        per_strategy={
            strat: ReportBucket(trades=int(buckets["trades"]), pnl=float(buckets["pnl"]))
            for strat, buckets in per_strategy.items()
        },
        trades=[TradeOut.from_row(t) for t in trades],
    )
