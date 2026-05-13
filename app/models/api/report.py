"""Pydantic DTOs for the ``/report`` router."""

from __future__ import annotations

from pydantic import BaseModel

from app.models.api.trade import TradeOut


class ReportSummary(BaseModel):
    """Aggregate metrics for an IST trading day."""

    signals_generated: int
    trades_taken: int
    trades_closed: int
    trades_still_open: int
    wins: int
    losses: int
    win_rate_pct: float
    total_pnl: float
    best_trade_pnl: float
    worst_trade_pnl: float


class ReportBucket(BaseModel):
    """Per-symbol or per-strategy rollup."""

    trades: int
    pnl: float


class ReportOut(BaseModel):
    """End-of-day report envelope."""

    date_ist: str
    summary: ReportSummary
    per_symbol: dict[str, ReportBucket]
    per_strategy: dict[str, ReportBucket]
    trades: list[TradeOut]
