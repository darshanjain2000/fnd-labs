"""Pydantic DTOs for the ``/signals`` router."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.trade import Signal as SignalRow


class SignalOut(BaseModel):
    """Serialisable view of a ``Signal`` row (strategy output + AI verdict)."""

    id: int | None
    symbol: str
    strategy: str
    side: str
    confidence: float
    context: dict[str, Any]
    ai_approved: bool | None
    ai_reasoning: str | None
    created_at: datetime | None

    @classmethod
    def from_row(cls, r: SignalRow) -> SignalOut:
        """Build a DTO from a detached ``Signal`` ORM row."""
        return cls(
            id=r.id,
            symbol=r.symbol,
            strategy=r.strategy,
            side=r.side,
            confidence=r.confidence,
            context=r.context or {},
            ai_approved=r.ai_approved,
            ai_reasoning=r.ai_reasoning,
            created_at=r.created_at,
        )


class SignalListOut(BaseModel):
    """List envelope: count + signals."""

    count: int
    signals: list[SignalOut]
