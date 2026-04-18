from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_broker, set_mock_quote
from services.broker.base import Broker, OrderRequest

router = APIRouter(prefix="/trade", tags=["trade"])


class ManualTrade(BaseModel):
    symbol: str
    side: str  # BUY / SELL
    qty: int
    order_type: str = "MARKET"
    price: float | None = None
    tag: str | None = "manual"
    mock_quote: float | None = None


@router.post("/manual")
def place_manual(req: ManualTrade, broker: Broker = Depends(get_broker)) -> dict:
    if req.mock_quote is not None:
        set_mock_quote(req.symbol, req.mock_quote)
    result = broker.place_order(
        OrderRequest(
            symbol=req.symbol,
            side=req.side,  # type: ignore[arg-type]
            qty=req.qty,
            order_type=req.order_type,  # type: ignore[arg-type]
            price=req.price,
            tag=req.tag,
        )
    )
    return result.__dict__
