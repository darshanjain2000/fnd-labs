"""Pydantic DTOs for broker order results."""

from __future__ import annotations

from pydantic import BaseModel

from app.services.broker.base import OrderResult


class OrderResultOut(BaseModel):
    """Serialisable view of a broker ``OrderResult``."""

    order_id: str
    status: str
    avg_price: float
    filled_qty: int
    message: str = ""

    @classmethod
    def from_result(cls, r: OrderResult) -> OrderResultOut:
        """Build a DTO from an ``OrderResult`` dataclass."""
        return cls(
            order_id=r.order_id,
            status=r.status,
            avg_price=r.avg_price,
            filled_qty=r.filled_qty,
            message=r.message,
        )
