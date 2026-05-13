"""Manual order placement endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.controllers.execution_controller import ExecutionController
from app.models.api import ApiResponse, OrderResultOut
from app.routers.deps import get_execution_controller, set_mock_quote
from app.strategies.base import Signal

router = APIRouter(prefix="/trade", tags=["trade"])


class ManualTrade(BaseModel):
    """Request body for ``POST /trade/manual``."""

    symbol: str
    side: str  # BUY / SELL
    qty: int
    order_type: str = "MARKET"
    price: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    tag: str | None = "manual"
    mock_quote: float | None = None


@router.post("/manual", response_model=ApiResponse[OrderResultOut])
def place_manual(
    req: ManualTrade,
    execution: ExecutionController = Depends(get_execution_controller),
) -> ApiResponse[OrderResultOut]:
    """Place a manual order through the active broker.

    Builds a synthetic ``Signal`` (``strategy="manual"``) so the execution
    service can persist a Trade row alongside the broker call. Falls back
    to ``±2%`` / ``±4%`` bounds when ``stop_loss`` / ``target`` are not
    supplied.
    """
    if req.mock_quote is not None:
        set_mock_quote(req.symbol, req.mock_quote)

    entry_price = req.mock_quote or req.price or 0.0
    stop_loss = req.stop_loss or round(entry_price * 0.98, 2)
    target = req.target or round(entry_price * 1.04, 2)

    sig = Signal(
        symbol=req.symbol,
        strategy="manual",
        side=req.side,
        entry=entry_price,
        stop_loss=stop_loss,
        target=target,
        confidence=1.0,
    )

    result = execution.execute(sig, qty=req.qty, signal_row_id=None)
    return ApiResponse[OrderResultOut].ok(OrderResultOut.from_result(result))
