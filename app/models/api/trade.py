"""Pydantic DTOs for the ``/trades`` router."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.api.audit import AuditLogOut
from app.models.trade import Trade


class TradeOut(BaseModel):
    """Serialisable view of a ``Trade`` row."""

    id: int | None
    signal_id: int | None
    symbol: str
    strategy: str | None
    side: str
    qty: int
    entry_price: float
    exit_price: float | None
    stop_loss: float
    target: float | None
    pnl: float | None
    status: str
    mode: str
    broker_order_id: str | None
    opened_at: datetime | None
    closed_at: datetime | None
    entry_context: dict[str, Any]
    trade_reason: str | None

    @classmethod
    def from_row(cls, t: Trade) -> TradeOut:
        """Build a DTO from a detached ``Trade`` ORM row."""
        return cls(
            id=t.id,
            signal_id=t.signal_id,
            symbol=t.symbol,
            strategy=t.strategy,
            side=t.side,
            qty=t.qty,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            stop_loss=t.stop_loss,
            target=t.target,
            pnl=t.pnl,
            status=t.status,
            mode=t.mode,
            broker_order_id=t.broker_order_id,
            opened_at=t.opened_at,
            closed_at=t.closed_at,
            entry_context=t.entry_context or {},
            trade_reason=getattr(t, "trade_reason", None),
        )


class TradeListOut(BaseModel):
    """List envelope: count + trades."""

    count: int
    trades: list[TradeOut]


class TradeLifecycleOut(BaseModel):
    """Full lifecycle of a single trade: details + ordered audit trail."""

    trade: TradeOut
    audit_trail: list[AuditLogOut]
