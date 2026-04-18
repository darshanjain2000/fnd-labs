from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.agents.execution_agent import ExecutionAgent
from app.api.deps import get_broker, set_mock_quote
from app.db import SessionLocal
from app.services.broker.base import Broker, OrderRequest
from app.strategies.base import Signal

router = APIRouter(prefix="/trade", tags=["trade"])


class ManualTrade(BaseModel):
    symbol: str
    side: str  # BUY / SELL
    qty: int
    order_type: str = "MARKET"
    price: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    tag: str | None = "manual"
    mock_quote: float | None = None


@router.post("/manual")
def place_manual(req: ManualTrade, broker: Broker = Depends(get_broker)) -> dict:
    if req.mock_quote is not None:
        set_mock_quote(req.symbol, req.mock_quote)

    entry_price = req.mock_quote or req.price or 0.0
    stop_loss = req.stop_loss or round(entry_price * 0.98, 2)
    target = req.target or round(entry_price * 1.04, 2)

    # Build a Signal stub so ExecutionAgent can persist the Trade row.
    sig = Signal(
        symbol=req.symbol,
        strategy="manual",
        side=req.side,
        entry=entry_price,
        stop_loss=stop_loss,
        target=target,
        confidence=1.0,
    )

    agent = ExecutionAgent(broker, session_factory=SessionLocal)
    result = agent.execute(sig, qty=req.qty, signal_row_id=None)
    return result.__dict__
